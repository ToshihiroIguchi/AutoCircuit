"""Complex non-linear least-squares fitting that needs no user-supplied initial values.

The strategy has four parts:

1. **Log-parameter transform.** Every scale-type parameter is searched as ``x = log10(p)``.
   That makes the search space scale-invariant and enforces positivity for free, which is what
   lets a global optimizer work across the 15+ decades a passive-component parameter set spans.
2. **Data-derived bounds.** Each element knows how to turn the measured frequency range and
   impedance magnitude range into a plausible interval for each of its parameters
   (see :mod:`autocircuit.core.elements`). The user never has to supply a starting guess.
3. **Global stage.** Differential evolution over those bounds.
4. **Local polish.** A trust-region least-squares refinement, whose Jacobian also yields the
   parameter covariance matrix.

Restarts with different seeds are used both to escape local minima and, more importantly, to
*detect* when a model is unidentifiable: if independent restarts land on materially different
parameter sets with the same fit quality, the result is reported as non-unique instead of
being presented as an answer.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import OptimizeResult, differential_evolution, least_squares

from .circuit import Circuit
from .elements import BoundsContext
from .spectrum import Spectrum
from .stats import Statistics, compute_statistics

Float = NDArray[np.float64]
Complex = NDArray[np.complex128]

Weighting = Literal["unit", "modulus", "proportional", "sigma"]

#: Cost returned for parameter sets that make the model blow up; large but finite so the
#: global optimizer can still rank two bad candidates against each other.
_PENALTY = 1e30

#: Relative spread across restarts above which parameters are called non-reproducible.
_RESTART_SPREAD_WARNING = 0.05


def weight_vectors(
    z: Complex, weighting: Weighting = "modulus", sigma: Float | None = None
) -> tuple[Float, Float]:
    """Return the (real, imaginary) residual weights for the chosen weighting scheme.

    - ``unit``: ordinary least squares; dominated by the largest-|Z| points.
    - ``modulus``: weight 1/|Z|; equivalent to minimising *relative* error and the right
      default for spectra spanning several decades of magnitude (e.g. capacitors).
    - ``proportional``: weight each component by its own magnitude; the classic CNLS choice
      when the instrument error is proportional to each measured component.
    - ``sigma``: user-supplied per-point standard deviations.
    """
    mag = np.abs(z)
    if weighting == "unit":
        ones = np.ones_like(mag)
        return ones, ones
    if weighting == "modulus":
        floor = np.max(mag) * 1e-12
        w = 1.0 / np.maximum(mag, floor)
        return w, w
    if weighting == "proportional":
        floor = np.max(mag) * 1e-6
        return 1.0 / np.maximum(np.abs(z.real), floor), 1.0 / np.maximum(np.abs(z.imag), floor)
    if weighting == "sigma":
        if sigma is None:
            raise ValueError("weighting='sigma' requires the sigma argument")
        s = np.asarray(sigma, dtype=np.float64)
        if s.shape != mag.shape:
            raise ValueError("sigma must have the same length as the spectrum")
        if np.any(s <= 0):
            raise ValueError("sigma must be strictly positive")
        return 1.0 / s, 1.0 / s
    raise ValueError(f"unknown weighting {weighting!r}")


@dataclass
class FitResult:
    """Outcome of one fit, including everything needed to judge whether to trust it."""

    circuit: Circuit
    values: Float
    """Fitted parameter values in natural units, ordered like ``circuit.param_names``."""
    z_model: Complex
    residuals: Float
    statistics: Statistics
    weighting: Weighting
    success: bool
    message: str
    n_restarts: int
    restart_spread: dict[str, float] = field(default_factory=dict)
    """Relative spread of each parameter across restarts; large values mean non-unique."""
    fixed: dict[str, float] = field(default_factory=dict)
    elapsed_s: float = 0.0

    @property
    def params(self) -> dict[str, float]:
        return self.circuit.values_dict(self.values)

    @property
    def stderr(self) -> dict[str, float]:
        return dict(zip(self.circuit.param_names, self.statistics.stderr, strict=True))

    @property
    def chi2_reduced(self) -> float:
        return self.statistics.chi2_reduced

    @property
    def aicc(self) -> float:
        return self.statistics.aicc

    def relative_error(self, spectrum: Spectrum) -> float:
        """Root-mean-square |Z_model - Z_data| / |Z_data| over the spectrum."""
        rel = np.abs(self.z_model - spectrum.z) / np.abs(spectrum.z)
        return float(np.sqrt(np.mean(rel**2)))

    @property
    def warnings(self) -> tuple[str, ...]:
        extra = [
            f"{name} varies by {spread:.1%} across restarts: the fit is not unique"
            for name, spread in self.restart_spread.items()
            if spread > _RESTART_SPREAD_WARNING
        ]
        return tuple(self.statistics.warnings) + tuple(extra)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable representation, used by the CLI and the web front end."""
        return {
            "circuit": self.circuit.to_string(),
            "canonical": self.circuit.canonical_form(),
            "weighting": self.weighting,
            "success": self.success,
            "message": self.message,
            "parameters": {
                name: {
                    "value": float(value),
                    "stderr": float(err),
                    "unit": spec.unit,
                    "fixed": name in self.fixed,
                }
                for name, value, err, spec in zip(
                    self.circuit.param_names,
                    self.values,
                    self.statistics.stderr,
                    self.circuit.param_specs(),
                    strict=True,
                )
            },
            "statistics": {
                "n_data": self.statistics.n_data,
                "n_params": self.statistics.n_params,
                "ssr": self.statistics.ssr,
                "chi2_reduced": self.statistics.chi2_reduced,
                "aic": self.statistics.aic,
                "aicc": self.statistics.aicc,
                "bic": self.statistics.bic,
            },
            "restart_spread": self.restart_spread,
            "warnings": list(self.warnings),
            "elapsed_s": self.elapsed_s,
        }

    def summary(self, spectrum: Spectrum | None = None) -> str:
        """Human-readable report for the command line."""
        lines = [
            f"Circuit      : {self.circuit.to_string()}",
            f"Weighting    : {self.weighting}",
            f"Status       : {'converged' if self.success else 'FAILED'} ({self.message})",
            "",
            f"{'Parameter':<14}{'Value':>14}{'Std. error':>14}{'Rel.':>9}  Unit",
        ]
        for name, value, err, spec in zip(
            self.circuit.param_names,
            self.values,
            self.statistics.stderr,
            self.circuit.param_specs(),
            strict=True,
        ):
            tag = " (fixed)" if name in self.fixed else ""
            rel = f"{err / abs(value):.1%}" if value != 0 and math.isfinite(err) else "-"
            lines.append(f"{name:<14}{value:>14.6g}{err:>14.3g}{rel:>9}  {spec.unit}{tag}")
        lines += [
            "",
            f"chi^2 (reduced) : {self.statistics.chi2_reduced:.6g}",
            f"AICc            : {self.statistics.aicc:.6g}",
            f"Data points     : {self.statistics.n_data // 2}"
            f"   Free parameters: {self.statistics.n_params}",
        ]
        if spectrum is not None:
            lines.append(f"RMS relative |Z| error : {self.relative_error(spectrum):.4%}")
        if self.warnings:
            lines.append("")
            lines.append("Warnings:")
            lines.extend(f"  - {w}" for w in self.warnings)
        return "\n".join(lines)


class _Problem:
    """Precomputed residual machinery for one (circuit, spectrum, weighting) combination."""

    def __init__(
        self,
        circuit: Circuit,
        spectrum: Spectrum,
        weighting: Weighting,
        sigma: Float | None,
        fixed: dict[str, float],
        bounds: dict[str, tuple[float, float]] | None,
        margin_decades: float,
    ) -> None:
        self.circuit = circuit
        self.spectrum = spectrum
        self.weighting = weighting
        self.omega = spectrum.omega
        self.z_data = spectrum.z
        self.w_re, self.w_im = weight_vectors(spectrum.z, weighting, sigma)

        names = circuit.param_names
        unknown = set(fixed) - set(names)
        if unknown:
            raise ValueError(f"cannot fix unknown parameters: {', '.join(sorted(unknown))}")
        self.fixed = dict(fixed)
        self.free_idx = np.array(
            [i for i, name in enumerate(names) if name not in fixed], dtype=int
        )
        if self.free_idx.size == 0:
            raise ValueError("all parameters are fixed; nothing to fit")

        ctx = BoundsContext.from_data(spectrum.omega, spectrum.z, margin_decades)
        lo_all, hi_all = circuit.bounds(ctx)
        if bounds:
            unknown = set(bounds) - set(names)
            if unknown:
                raise ValueError(f"bounds given for unknown parameters: {', '.join(unknown)}")
            for name, (lo, hi) in bounds.items():
                i = names.index(name)
                lo_all[i], hi_all[i] = lo, hi

        self.template = np.empty(len(names), dtype=np.float64)
        for i, name in enumerate(names):
            self.template[i] = fixed.get(name, math.sqrt(lo_all[i] * hi_all[i]))

        self.log_mask_all = circuit.log_mask()
        self.log_mask = self.log_mask_all[self.free_idx]
        lo, hi = lo_all[self.free_idx], hi_all[self.free_idx]
        self.lower_x = np.where(self.log_mask, np.log10(np.maximum(lo, 1e-300)), lo)
        self.upper_x = np.where(self.log_mask, np.log10(np.maximum(hi, 1e-299)), hi)

    # -- Transforms -----------------------------------------------------------------------
    def to_values(self, x: Float) -> Float:
        """Scatter free search variables into a full parameter vector in natural units."""
        free = np.where(self.log_mask, np.power(10.0, x), x)
        values = self.template.copy()
        values[self.free_idx] = free
        return values

    def to_x(self, values: Float) -> Float:
        free = values[self.free_idx]
        return np.where(self.log_mask, np.log10(np.maximum(free, 1e-300)), free)

    def canonicalize(self, x: Float) -> Float:
        """Put interchangeable branches in a deterministic order (see Circuit).

        Skipped when any parameter is fixed, because swapping two branches would move a
        fixed value onto a different element.
        """
        if self.fixed:
            return x
        values = self.circuit.canonicalize_values(self.to_values(x))
        return np.clip(self.to_x(values), self.lower_x, self.upper_x)

    # -- Objective ------------------------------------------------------------------------
    def model(self, x: Float) -> Complex:
        return self.circuit.impedance(self.omega, self.to_values(x))

    def residuals(self, x: Float) -> Float:
        z = self.model(x)
        if not np.all(np.isfinite(z)):
            z = np.where(np.isfinite(z), z, 0.0)
            bad = True
        else:
            bad = False
        res = np.concatenate(
            [(z.real - self.z_data.real) * self.w_re, (z.imag - self.z_data.imag) * self.w_im]
        )
        if bad:
            res = np.where(np.isfinite(res), res, np.sqrt(_PENALTY / res.size))
        return res

    def cost(self, x: Float) -> float:
        res = self.residuals(x)
        value = float(np.dot(res, res))
        return value if math.isfinite(value) else _PENALTY

    def to_values_batch(self, xs: Float) -> Float:
        """Scatter a population of search vectors into full parameter vectors.

        ``xs`` has shape ``(n_free, n_candidates)``; the result is ``(n_params, n_candidates)``.
        """
        free = np.where(self.log_mask[:, None], np.power(10.0, xs), xs)
        values = np.repeat(self.template[:, None], xs.shape[1], axis=1)
        values[self.free_idx, :] = free
        return values

    def cost_vectorized(self, xs: Float, /) -> Float:
        """Score a whole population in one pass; ``xs`` is ``(n_free, n_candidates)``.

        Evaluating the circuit once for the entire differential-evolution population instead
        of once per individual is the difference between a topology search that explores a
        handful of generations and one that explores hundreds: the work per candidate is a
        few microseconds of array arithmetic, so the Python call overhead dominates unless
        it is amortised across the population.
        """
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            z = self.circuit.impedance(self.omega, self.to_values_batch(xs))
            z = np.where(np.isfinite(z), z, np.nan)
            residual_re = (z.real - self.z_data[None, :].real) * self.w_re[None, :]
            residual_im = (z.imag - self.z_data[None, :].imag) * self.w_im[None, :]
            cost = np.sum(residual_re**2, axis=1) + np.sum(residual_im**2, axis=1)
        return np.where(np.isfinite(cost), cost, _PENALTY)


def fit(
    circuit: Circuit | str,
    spectrum: Spectrum,
    *,
    weighting: Weighting = "modulus",
    sigma: Float | None = None,
    fixed: dict[str, float] | None = None,
    bounds: dict[str, tuple[float, float]] | None = None,
    initial: dict[str, float] | None = None,
    restarts: int = 5,
    seed: int = 0,
    popsize: int = 20,
    maxiter: int = 400,
    tol: float = 1e-8,
    workers: int = 1,
    margin_decades: float = 3.0,
    global_search: bool = True,
    time_limit: float | None = None,
) -> FitResult:
    """Fit ``circuit`` to ``spectrum`` without requiring initial parameter values.

    Args:
        circuit: A :class:`Circuit` or a DSL string such as ``"C1-R1-L1"``.
        spectrum: The measured data.
        weighting: Residual weighting scheme; see :func:`weight_vectors`.
        sigma: Per-point standard deviations, required when ``weighting='sigma'``.
        fixed: Parameters to hold constant, e.g. ``{"L1.L": 5e-10}``.
        bounds: Per-parameter search interval overrides.
        initial: Optional starting guess. Never required; when given with
            ``global_search=False`` it turns the call into a pure local refinement.
        restarts: Independent global searches; also the basis of the uniqueness check.
        seed: Base random seed. Restart *i* uses ``seed + i``, so results are reproducible.
        popsize: Differential-evolution population multiplier.
        maxiter: Differential-evolution generation cap per restart.
        workers: Process count for the global stage; keep at 1 under Pyodide.
        margin_decades: Safety margin added to the data-derived bounds.
        global_search: Set False to skip the global stage (requires ``initial``).
        time_limit: Wall-clock budget in seconds for the global stage, per restart.

    Returns:
        A :class:`FitResult` with parameters, uncertainties and identifiability warnings.
    """
    started = time.perf_counter()
    if isinstance(circuit, str):
        circuit = Circuit.parse(circuit)
    problem = _Problem(
        circuit, spectrum, weighting, sigma, fixed or {}, bounds, margin_decades
    )

    if not global_search and initial is None:
        raise ValueError("global_search=False requires an initial guess")

    x0_user: Float | None = None
    if initial is not None:
        template = problem.template.copy()
        for name, value in initial.items():
            if name not in circuit.param_names:
                raise ValueError(f"initial value given for unknown parameter {name!r}")
            template[circuit.param_names.index(name)] = value
        x0_user = np.clip(problem.to_x(template), problem.lower_x, problem.upper_x)

    solutions: list[tuple[float, Float, OptimizeResult]] = []
    messages: list[str] = []
    n_restarts = max(1, restarts) if global_search else 1

    for attempt in range(n_restarts):
        if global_search:
            x_start = _global_stage(
                problem,
                seed=seed + attempt,
                popsize=popsize,
                maxiter=maxiter,
                tol=tol,
                workers=workers,
                time_limit=time_limit,
                x0=x0_user if attempt == 0 else None,
            )
        else:
            assert x0_user is not None
            x_start = x0_user
        x_start = problem.canonicalize(x_start)
        local = least_squares(
            problem.residuals,
            x_start,
            bounds=(problem.lower_x, problem.upper_x),
            method="trf",
            xtol=1e-14,
            ftol=1e-14,
            gtol=1e-12,
            max_nfev=20000,
        )
        solutions.append((float(np.dot(local.fun, local.fun)), local.x, local))
        messages.append(local.message)

    solutions.sort(key=lambda item: item[0])
    best_cost, best_x, best = solutions[0]

    spread = _restart_spread(problem, [x for _, x, _ in solutions], best_cost)

    values = problem.to_values(best_x)
    z_model = circuit.impedance(spectrum.omega, values)
    residuals = np.asarray(best.fun, dtype=np.float64)

    free_names = tuple(circuit.param_names[i] for i in problem.free_idx)
    stats_free = compute_statistics(
        residuals=residuals,
        jac_x=np.asarray(best.jac, dtype=np.float64),
        values=values[problem.free_idx],
        log_mask=problem.log_mask,
        param_names=free_names,
        lower_x=problem.lower_x,
        upper_x=problem.upper_x,
        x=best_x,
    )
    statistics = _expand_statistics(stats_free, circuit, problem)

    return FitResult(
        circuit=circuit,
        values=values,
        z_model=z_model,
        residuals=residuals,
        statistics=statistics,
        weighting=weighting,
        success=bool(best.success),
        message=messages[0] if len(messages) == 1 else f"best of {n_restarts} restarts",
        n_restarts=n_restarts,
        restart_spread=spread,
        fixed=dict(fixed or {}),
        elapsed_s=time.perf_counter() - started,
    )


def screen(
    circuit: Circuit | str,
    spectrum: Spectrum,
    *,
    weighting: Weighting = "modulus",
    sigma: Float | None = None,
    seed: int = 0,
    popsize: int = 8,
    maxiter: int = 40,
    tol: float = 1e-4,
    margin_decades: float = 3.0,
    abandon_above: float = math.inf,
) -> float:
    """Rank-only fit: return the weighted sum of squared residuals and nothing else.

    Exhaustive discovery fits thousands of topologies just to sort them, and only the best
    few are ever refitted properly and reported. Building a full :class:`FitResult` for the
    rest -- covariance, statistics, restart spread -- is wasted work, so this does the global
    stage once, polishes, and hands back a single number.

    ``abandon_above`` is the early-abandon switch: when the global stage alone already lands
    above that cost, the local polish is skipped and the raw global cost returned. A candidate
    that is two orders of magnitude worse than the best one of its size is not going to be
    rescued by a trust-region step, and skipping it is where most of the screening time is
    saved.

    Raises the same exceptions as :func:`fit`; callers screening many topologies should catch
    ``ValueError``, ``CircuitError`` and ``numpy.linalg.LinAlgError``.
    """
    if isinstance(circuit, str):
        circuit = Circuit.parse(circuit)
    problem = _Problem(circuit, spectrum, weighting, sigma, {}, None, margin_decades)
    x = _global_stage(
        problem,
        seed=seed,
        popsize=popsize,
        maxiter=maxiter,
        tol=tol,
        workers=1,
        time_limit=None,
        x0=None,
    )
    cost = problem.cost(x)
    if not math.isfinite(cost) or cost > abandon_above:
        return cost
    local = least_squares(
        problem.residuals,
        problem.canonicalize(x),
        bounds=(problem.lower_x, problem.upper_x),
        method="trf",
        xtol=1e-12,
        ftol=1e-12,
        gtol=1e-10,
        max_nfev=2000,
    )
    polished = float(np.dot(local.fun, local.fun))
    return polished if math.isfinite(polished) else cost


def _global_stage(
    problem: _Problem,
    *,
    seed: int,
    popsize: int,
    maxiter: int,
    tol: float,
    workers: int,
    time_limit: float | None,
    x0: Float | None,
) -> Float:
    """Run differential evolution over the log-space bounds and return the best point."""
    deadline = None if time_limit is None else time.perf_counter() + time_limit

    def callback(xk: Float, convergence: float = 0.0) -> bool:
        return deadline is not None and time.perf_counter() > deadline

    kwargs: dict[str, Any] = {
        "bounds": list(zip(problem.lower_x, problem.upper_x, strict=True)),
        "seed": seed,
        "popsize": popsize,
        "maxiter": maxiter,
        "tol": tol,
        "mutation": (0.4, 1.0),
        "recombination": 0.9,
        "strategy": "best1bin",
        "init": "sobol",
        "polish": False,
        "callback": callback,
    }
    if x0 is not None:
        kwargs["x0"] = x0
    if workers and workers != 1:
        kwargs["workers"] = workers
        kwargs["updating"] = "deferred"
        result = differential_evolution(problem.cost, **kwargs)
    else:
        kwargs["vectorized"] = True
        kwargs["updating"] = "deferred"
        # scipy-stubs has a single, non-overloaded signature for differential_evolution that
        # always types `func` as scalar-returning; it does not model the `vectorized=True`
        # calling convention (population in, cost array out) that this code relies on, so the
        # declared return type of cost_vectorized genuinely cannot match the stub here.
        result = differential_evolution(problem.cost_vectorized, **kwargs)  # type: ignore[arg-type]
    return np.asarray(result.x, dtype=np.float64)


def _restart_spread(problem: _Problem, xs: list[Float], best_cost: float) -> dict[str, float]:
    """Relative parameter spread across restarts that reached a comparable cost.

    Only restarts within 1% of the best cost are compared: a restart that simply failed to
    converge says nothing about identifiability, whereas two equally good fits with different
    parameters say the model is degenerate.
    """
    if len(xs) < 2:
        return {}
    comparable = [x for x in xs if problem.cost(x) <= best_cost * 1.01 + 1e-300]
    if len(comparable) < 2:
        return {}
    values = np.array(
        [problem.to_values(problem.canonicalize(x))[problem.free_idx] for x in comparable]
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        centre = np.median(np.abs(values), axis=0)
        spread = np.where(centre > 0, (values.max(axis=0) - values.min(axis=0)) / centre, 0.0)
    names = [problem.circuit.param_names[i] for i in problem.free_idx]
    return {name: float(s) for name, s in zip(names, spread, strict=True) if math.isfinite(s)}


def _expand_statistics(stats: Statistics, circuit: Circuit, problem: _Problem) -> Statistics:
    """Re-index free-parameter statistics onto the full parameter list (fixed ones get 0)."""
    n = len(circuit.param_names)
    if problem.free_idx.size == n:
        return stats
    stderr = np.zeros(n)
    stderr[problem.free_idx] = stats.stderr
    correlation = np.eye(n)
    idx = problem.free_idx
    correlation[np.ix_(idx, idx)] = stats.correlation
    return Statistics(
        n_data=stats.n_data,
        n_params=stats.n_params,
        ssr=stats.ssr,
        chi2_reduced=stats.chi2_reduced,
        stderr=stderr,
        correlation=correlation,
        aic=stats.aic,
        aicc=stats.aicc,
        bic=stats.bic,
        warnings=stats.warnings,
    )
