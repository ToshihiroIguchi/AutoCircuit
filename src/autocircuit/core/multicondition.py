"""Multi-condition joint fitting: level 1 (shared topology) and level 2 (parametric laws).

``CLAUDE.md`` names this the one instrument that can actually *break* an equivalence class:
``R1-p(R2,C1)`` and ``p(R1,C1-R2)`` fit any single spectrum identically (``docs/HANDOFF.md``
section 3), but if ``R1`` and ``R2`` each follow their own Arrhenius law with a different
activation energy, the exact algebraic map between the two forms turns one sum of exponentials
into two, and only one form stays Arrhenius. A series of spectra taken at different
temperatures can see that; one spectrum never can. See ``docs/IMPACT_PLAN.md`` section 3 for
the design this module implements and the gates (A1-A5) that measure it.

Two levels, both operating on a :class:`~autocircuit.core.spectrum.SpectrumSet`:

* **Level 1** (:func:`discover_set`): one topology, fitted *independently* to every condition.
  This does not break any degeneracy -- fitting each spectrum alone and intersecting the results
  would find the same candidates -- but it pools evidence for the *topology*: a block whose
  share of the response is too small to recover from one spectrum can still show up once a
  second condition where it carries more weight is fitted alongside it. Ranking uses the summed
  weighted sum of squares across conditions and a parameter count of ``k * n_conditions``, which
  is what makes this a strictly additive extension of single-spectrum discovery -- each
  condition's own :func:`~autocircuit.core.fit.fit` is otherwise untouched.
* **Level 2** (:func:`fit_joint`, :func:`select_level2`): each parameter *class* -- resistive,
  reactive, or everything else -- is assigned one status: ``shared`` (one value for every
  condition), ``free`` (one per condition, i.e. level 1's own assumption), or ``lawful`` (a
  two-parameter Arrhenius law, ``x(T) = x_ref * exp(Ea * (1/(kB*T) - 1/(kB*T_ref)))``, one
  instance per lawful circuit parameter, anchored at the first condition's own temperature --
  see :class:`LawFit` for why it is centred there rather than extrapolated to ``T -> inf``.
  :func:`select_level2` tries every assignment over the classes a topology actually has and
  keeps the one with the lowest BIC.

**Why this reuses the single-spectrum statistics machinery rather than inventing a second one.**
Level 1's residual decomposes exactly into independent per-condition blocks -- a free parameter
in one condition never appears in another condition's residual -- so its per-parameter standard
errors are just each condition's own :func:`~autocircuit.core.fit.fit` result; only the pooled
information criteria (:func:`~autocircuit.core.stats.information_criteria`) need combining.
Level 2 genuinely couples conditions (a shared or lawful parameter appears in every condition's
residual at once), so it needs one real joint least-squares problem -- but once that residual
vector and its Jacobian exist, :func:`~autocircuit.core.stats.compute_statistics` computes
every information criterion, standard error and correlation exactly as it does for a single
spectrum. In particular ``Ea`` is a first-class search variable in the joint parameterisation
(not a quantity derived from other fitted values), so its standard error comes directly out of
that covariance -- no separate propagation step is needed.

**What this module does not do**, stated so it is not silently assumed elsewhere: it does not
run the exhaustive stage's growth or genetic-search fallback (:func:`discover_set` is
exhaustive-only, matching this project's default up-to-five-element regime), it does not widen
the pool from the spectrum's own shape the way ``--pool auto`` does for a single spectrum
(:mod:`autocircuit.core.descriptors` is not consulted here), and ``lawful`` status is only
defined for ``condition_kind="temperature_K"`` -- the polynomial-in-bias law
``docs/IMPACT_PLAN.md`` section 3.2 describes for ``bias_V`` is not implemented, because no
gate in that plan exercises it. None of this is hidden inside a default: every one of these is
either an explicit argument or a ``ValueError`` naming the omission.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from itertools import product
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares

from .circuit import Circuit, CircuitError
from .discover import (
    DEFAULT_DEGENERACY_BUDGET,
    EQUIVALENCE_RTOL,
    PARSIMONY_CHI2_FACTOR,
    enumerate_candidates,
)
from .elements import DEFAULT_POOL, BoundsContext, ParamSpec
from .fit import PUBLISH_LOCAL, FitContext, FitResult, LocalBudget, fit, screen
from .noise import resolve_weights
from .spectrum import ConditionKind, Spectrum, SpectrumSet
from .stats import (
    DEFAULT_CRITERION,
    Criterion,
    Statistics,
    compute_statistics,
    information_criteria,
    unresolved_mask,
)
from .weighting import Weighting

Float = NDArray[np.float64]
Complex = NDArray[np.complex128]

#: How much of a parameter's topology this joint fit lets a single condition or a law explain.
ParameterStatus = Literal["shared", "free", "lawful"]

#: Which physical role a parameter plays, read off its unit (:attr:`ParamSpec.unit`).
#: ``CLAUDE.md``'s own description ("all R-type parameters take one status, all C/L-type
#: another, CPE exponents a third") is generalised here to the full element vocabulary rather
#: than special-cased to CPE: anything that is not in ohms, farads or henries -- a CPE
#: exponent, a Warburg coefficient, a Havriliak-Negami shape parameter -- shares the third
#: bucket, because there is no principled way to split it further without more elements than
#: any gated topology here actually has.
ParamClass = Literal["resistive", "reactive", "other"]

#: Boltzmann constant in eV/K, so activation energies come out in the unit the field reports
#: them in rather than joules.
BOLTZMANN_EV_PER_K = 8.617333262e-5

#: Search bounds for a lawful parameter's activation energy, in eV. Wide enough to cover every
#: solid-state activation energy this project's own documents discuss (typically 0.1-2 eV)
#: with room either side; not a hard physical limit, just the optimizer's box.
EA_BOUNDS_EV: tuple[float, float] = (-3.0, 3.0)

#: Default weighting for multi-condition calls. Unlike single-spectrum discovery -- where
#: ``weighting="auto"`` stays opt-in because of the recommendation flips measured in
#: ``docs/IMPACT_PLAN.md`` section 2's gate N2 -- pooling chi-squared across conditions is not
#: meaningful unless each spectrum's noise is on a common footing first (``docs/IMPACT_PLAN.md``
#: section 0: "B goes before A"). There is no single-condition N2-style regression risk here
#: because there is no existing multi-condition default to regress from.
DEFAULT_SET_WEIGHTING: Weighting = "auto"


def _param_class(spec: ParamSpec) -> ParamClass:
    if spec.unit == "ohm":
        return "resistive"
    if spec.unit in ("F", "H"):
        return "reactive"
    return "other"


def _present_classes(circuit: Circuit) -> tuple[ParamClass, ...]:
    """Which parameter classes a circuit actually has, in a fixed, deterministic order."""
    present = {_param_class(spec) for spec in circuit.param_specs()}
    return tuple(c for c in ("resistive", "reactive", "other") if c in present)


@dataclass(frozen=True)
class LawFit:
    """One lawful parameter's fitted Arrhenius law.

    ``x(T) = x_ref * exp(Ea * (1/(kB*T) - 1/(kB*T_ref)))``, so ``x_ref`` is the fitted value at
    ``T_ref`` -- the *first* condition in the set, not the ``T -> inf`` prefactor the textbook
    form ``x0 * exp(Ea/(kB*T))`` would centre on. That textbook form was tried first and
    rejected: for an activation energy of a few tenths of an eV, ``x0`` sits many orders of
    magnitude below any value ever observed (``exp(Ea/(kB*300 K))`` alone is ~1e5 at 0.3 eV and
    ~1e13 at 0.8 eV), which pushed it below the element's own hard physical bound and made the
    true value structurally unreachable regardless of the optimizer's starting point --
    measured directly: a joint fit that reached ``chi2_reduced ~ 1.28`` under ``"free"`` status
    reached ``~1244`` under the ``x0``-centred ``"lawful"`` status on the same data. Anchoring
    at an observed condition instead keeps ``x_ref`` inside the same physical bounds ``"shared"``
    and ``"free"`` already use, because it *is* one of the values those statuses would report.
    """

    param_name: str
    t_ref: float
    x_ref: float
    x_ref_stderr: float
    ea_ev: float
    ea_stderr: float


@dataclass(frozen=True)
class ConditionFit:
    """One condition's slice of a joint fit: its own parameter values and modelled response."""

    condition: float
    spectrum: Spectrum
    values: Float
    z_model: Complex


@dataclass(frozen=True)
class JointFitResult:
    """A circuit fitted jointly across a :class:`SpectrumSet` under one status assignment."""

    circuit: Circuit
    status: dict[ParamClass, ParameterStatus]
    conditions: tuple[float, ...]
    condition_kind: ConditionKind
    per_condition: tuple[ConditionFit, ...]
    statistics: Statistics
    laws: dict[str, LawFit]
    """Fitted law for each parameter with status ``"lawful"``, keyed by ``circuit.param_names``."""
    relative_error: float
    """Pooled RMS ``|dZ_model - dZ_data| / |Z_data|`` across every condition."""
    success: bool

    def score(self, criterion: Criterion = DEFAULT_CRITERION) -> float:
        return self.statistics.criterion_value(criterion)


class _VarSpec:
    """Where one circuit parameter's search variable(s) live in the joint ``x`` vector."""

    __slots__ = ("kind", "param_index", "slot")

    def __init__(self, kind: ParameterStatus, param_index: int, slot: tuple[int, ...]) -> None:
        self.kind = kind
        self.param_index = param_index
        self.slot = slot


class _JointProblem:
    """Residual machinery for one (circuit, SpectrumSet, status assignment) combination."""

    def __init__(
        self,
        circuit: Circuit,
        spectrum_set: SpectrumSet,
        status: dict[ParamClass, ParameterStatus],
        weighting: Weighting,
    ) -> None:
        self.circuit = circuit
        self.spectrum_set = spectrum_set
        n_conditions = spectrum_set.n_conditions
        specs = circuit.param_specs()
        classes = [_param_class(spec) for spec in specs]
        missing = {cls for cls in classes if cls not in status}
        if missing:
            raise ValueError(f"status assignment missing parameter class(es): {missing}")
        self.t_ref = math.nan
        if "lawful" in status.values():
            if spectrum_set.condition_kind != "temperature_K":
                raise ValueError('status "lawful" requires condition_kind="temperature_K"')
            if n_conditions < 2:
                raise ValueError('status "lawful" requires at least two conditions')
            # Temperatures in Kelvin are always > 0, so this can never be a division by zero --
            # unlike the condition value itself, which is unconstrained for other condition
            # kinds and is why t_ref is left unset (NaN) whenever no parameter is lawful.
            self.t_ref = float(spectrum_set.conditions[0])

        pooled_omega = np.concatenate([sp.omega for sp in spectrum_set.spectra])
        pooled_z = np.concatenate([sp.z for sp in spectrum_set.spectra])
        ctx = BoundsContext.from_data(pooled_omega, pooled_z)
        lo_all, hi_all = circuit.bounds(ctx)

        self.w_re = []
        self.w_im = []
        for sp in spectrum_set.spectra:
            w_re, w_im = resolve_weights(sp, weighting)
            self.w_re.append(w_re)
            self.w_im.append(w_im)

        names: list[str] = []
        log_mask: list[bool] = []
        lower: list[float] = []
        upper: list[float] = []
        layout: list[_VarSpec] = []
        cursor = 0

        def _push(value_name: str, log_scale: bool, lo: float, hi: float) -> int:
            nonlocal cursor
            idx = cursor
            cursor += 1
            names.append(value_name)
            log_mask.append(log_scale)
            lower.append(math.log10(max(lo, 1e-300)) if log_scale else lo)
            upper.append(math.log10(max(hi, 1e-299)) if log_scale else hi)
            return idx

        for i, name in enumerate(circuit.param_names):
            spec = specs[i]
            st = status[classes[i]]
            lo, hi = float(lo_all[i]), float(hi_all[i])
            if st == "shared":
                idx = _push(name, spec.log_scale, lo, hi)
                layout.append(_VarSpec(st, i, (idx,)))
            elif st == "free":
                idxs = tuple(
                    _push(f"{name}@{cond:g}", spec.log_scale, lo, hi)
                    for cond in spectrum_set.conditions
                )
                layout.append(_VarSpec(st, i, idxs))
            elif st == "lawful":
                i0 = _push(f"{name}.x_ref", spec.log_scale, lo, hi)
                i1 = _push(f"{name}.Ea_eV", False, *EA_BOUNDS_EV)
                layout.append(_VarSpec(st, i, (i0, i1)))
            else:
                raise ValueError(f"unknown parameter status {st!r}")

        self.status = dict(status)
        self.layout = layout
        self.names = tuple(names)
        self.log_mask = np.array(log_mask, dtype=bool)
        self.lower_x = np.array(lower, dtype=np.float64)
        self.upper_x = np.array(upper, dtype=np.float64)
        self.n_x = cursor
        self.n_conditions = n_conditions

    def to_condition_values(self, x: Float) -> list[Float]:
        """Natural-unit parameter vectors, one per condition, in ``circuit.param_names`` order."""
        out = [np.empty(len(self.circuit.param_names)) for _ in range(self.n_conditions)]
        conditions = self.spectrum_set.conditions
        for var in self.layout:
            if var.kind == "shared":
                (idx,) = var.slot
                value = 10.0 ** x[idx] if self.log_mask[idx] else x[idx]
                for values in out:
                    values[var.param_index] = value
            elif var.kind == "free":
                for j, idx in enumerate(var.slot):
                    out[j][var.param_index] = 10.0 ** x[idx] if self.log_mask[idx] else x[idx]
            else:  # lawful
                i0, i1 = var.slot
                x_ref = 10.0 ** x[i0] if self.log_mask[i0] else x[i0]
                ea = x[i1]
                inv_kt_ref = 1.0 / (BOLTZMANN_EV_PER_K * self.t_ref)
                for j, condition in enumerate(conditions):
                    inv_kt = 1.0 / (BOLTZMANN_EV_PER_K * condition)
                    out[j][var.param_index] = x_ref * math.exp(ea * (inv_kt - inv_kt_ref))
        return out

    def natural_values(self, x: Float) -> Float:
        """One natural-unit number per joint slot, for :func:`compute_statistics`."""
        out = np.empty(self.n_x, dtype=np.float64)
        for var in self.layout:
            if var.kind == "lawful":
                i0, i1 = var.slot
                out[i0] = 10.0 ** x[i0] if self.log_mask[i0] else x[i0]
                out[i1] = x[i1]
            else:
                for idx in var.slot:
                    out[idx] = 10.0 ** x[idx] if self.log_mask[idx] else x[idx]
        return out

    def residuals(self, x: Float) -> Float:
        condition_values = self.to_condition_values(x)
        parts: list[Float] = []
        for j, sp in enumerate(self.spectrum_set.spectra):
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                z = self.circuit.impedance(sp.omega, condition_values[j])
            if not np.all(np.isfinite(z)):
                z = np.where(np.isfinite(z), z, 0.0)
            parts.append((z.real - sp.z.real) * self.w_re[j])
            parts.append((z.imag - sp.z.imag) * self.w_im[j])
        res = np.concatenate(parts)
        return np.where(np.isfinite(res), res, 1e6)


def _initial_guess(
    problem: _JointProblem, weighting: Weighting, seed: int, restarts: int
) -> tuple[Float, list[FitResult]]:
    """Seed the joint search from independent per-condition fits.

    Each status is a function of those independent optima alone: the median for ``shared``, the
    value itself for ``free``, and an ordinary least-squares regression of ``ln(value)`` against
    ``1/(kB*T) - 1/(kB*T_ref)`` for ``lawful`` (the same Arrhenius law, linearised and centred
    the same way :class:`LawFit` is -- see its docstring for why centring at an observed
    condition rather than extrapolating to ``T -> inf`` is not optional here). Starting there
    rather than from a fresh global search is deliberate: the basin for this topology is already
    found by the time :func:`fit_joint` is called (level 1 discovery or a caller who already
    knows the topology), so what is left is coupling the conditions together under the status
    assignment, which is a local problem.
    """
    circuit = problem.circuit
    per_condition_fits = [
        fit(
            circuit,
            sp,
            weighting=weighting,
            seed=seed,
            restarts=restarts,
            context=FitContext.build(sp, weighting, None),
        )
        for sp in problem.spectrum_set.spectra
    ]

    x_init = np.empty(problem.n_x, dtype=np.float64)
    conditions = np.array(problem.spectrum_set.conditions, dtype=np.float64)
    inv_kt_ref = 1.0 / (BOLTZMANN_EV_PER_K * problem.t_ref)
    for var in problem.layout:
        values_here = [fr.values[var.param_index] for fr in per_condition_fits]
        if var.kind == "shared":
            (idx,) = var.slot
            v = float(np.median(values_here))
            x_init[idx] = math.log10(max(v, 1e-300)) if problem.log_mask[idx] else v
        elif var.kind == "free":
            for j, idx in enumerate(var.slot):
                v = float(values_here[j])
                x_init[idx] = math.log10(max(v, 1e-300)) if problem.log_mask[idx] else v
        else:  # lawful
            i0, i1 = var.slot
            ln_v = np.log(np.clip(values_here, 1e-300, None))
            centred_inv_kt = 1.0 / (BOLTZMANN_EV_PER_K * conditions) - inv_kt_ref
            slope, intercept = np.polyfit(centred_inv_kt, ln_v, 1)
            ea = float(np.clip(slope, *EA_BOUNDS_EV))
            x_ref_val = float(math.exp(intercept))
            x_init[i0] = math.log10(max(x_ref_val, 1e-300)) if problem.log_mask[i0] else x_ref_val
            x_init[i1] = ea
    return np.clip(x_init, problem.lower_x, problem.upper_x), per_condition_fits


def fit_joint(
    circuit: Circuit | str,
    spectrum_set: SpectrumSet,
    status: dict[ParamClass, ParameterStatus],
    *,
    weighting: Weighting = DEFAULT_SET_WEIGHTING,
    seed: int = 0,
    restarts: int = 5,
    local: LocalBudget = PUBLISH_LOCAL,
) -> JointFitResult:
    """Fit ``circuit`` to every spectrum in ``spectrum_set`` at once, under one status assignment.

    ``status`` maps each :data:`ParamClass` the circuit actually has to a :data:`ParameterStatus`
    (``"shared"``, ``"free"`` or ``"lawful"``); a class the circuit does not have may be omitted.
    Level 1 is the special case where every class is ``"free"`` -- see :func:`discover_set`,
    which computes that case directly from independent per-condition fits rather than through
    this joint optimizer, since a fully-free residual has no cross-condition coupling to solve
    for. This function exists for the cases that do couple conditions: ``"shared"`` and
    ``"lawful"``.
    """
    if isinstance(circuit, str):
        circuit = Circuit.parse(circuit)
    problem = _JointProblem(circuit, spectrum_set, status, weighting)
    x_init, _ = _initial_guess(problem, weighting, seed, restarts)

    solution = least_squares(
        problem.residuals,
        x_init,
        bounds=(problem.lower_x, problem.upper_x),
        method="trf",
        xtol=local.xtol,
        ftol=local.ftol,
        gtol=local.gtol,
        max_nfev=local.max_nfev,
    )
    x = np.asarray(solution.x, dtype=np.float64)
    residuals = np.asarray(solution.fun, dtype=np.float64)
    natural_values = problem.natural_values(x)

    statistics = compute_statistics(
        residuals=residuals,
        jac_x=np.asarray(solution.jac, dtype=np.float64),
        values=natural_values,
        log_mask=problem.log_mask,
        param_names=problem.names,
        lower_x=problem.lower_x,
        upper_x=problem.upper_x,
        x=x,
    )

    condition_values = problem.to_condition_values(x)
    per_condition: list[ConditionFit] = []
    sq_rel_errors: list[Float] = []
    for j, sp in enumerate(spectrum_set.spectra):
        z_model = circuit.impedance(sp.omega, condition_values[j])
        per_condition.append(
            ConditionFit(
                condition=spectrum_set.conditions[j],
                spectrum=sp,
                values=condition_values[j],
                z_model=z_model,
            )
        )
        sq_rel_errors.append((np.abs(z_model - sp.z) / np.abs(sp.z)) ** 2)
    relative_error = float(np.sqrt(np.mean(np.concatenate(sq_rel_errors))))

    laws: dict[str, LawFit] = {}
    for var in problem.layout:
        if var.kind != "lawful":
            continue
        name = circuit.param_names[var.param_index]
        i0, i1 = var.slot
        laws[name] = LawFit(
            param_name=name,
            t_ref=problem.t_ref,
            x_ref=float(natural_values[i0]),
            x_ref_stderr=float(statistics.stderr[i0]),
            ea_ev=float(natural_values[i1]),
            ea_stderr=float(statistics.stderr[i1]),
        )

    return JointFitResult(
        circuit=circuit,
        status=dict(status),
        conditions=spectrum_set.conditions,
        condition_kind=spectrum_set.condition_kind,
        per_condition=tuple(per_condition),
        statistics=statistics,
        laws=laws,
        relative_error=relative_error,
        success=bool(solution.success),
    )


def select_level2(
    circuit: Circuit | str,
    spectrum_set: SpectrumSet,
    *,
    weighting: Weighting = DEFAULT_SET_WEIGHTING,
    seed: int = 0,
    restarts: int = 5,
    criterion: Criterion = DEFAULT_CRITERION,
) -> JointFitResult:
    """Try every status assignment over ``circuit``'s parameter classes and keep the lowest-BIC.

    The lattice is per parameter *class*, not per parameter, which is what keeps it small: a
    circuit with all three classes present has ``3**3 = 27`` assignments to fit, not one per
    parameter. ``criterion`` chooses which score breaks the tie; it defaults to
    :data:`~autocircuit.core.stats.DEFAULT_CRITERION` (BIC) because this is exactly the
    model-selection question BIC is for -- does the extra flexibility of ``"free"`` over
    ``"shared"``, or of ``"lawful"`` over ``"free"``, earn its parameters back.
    """
    if isinstance(circuit, str):
        circuit = Circuit.parse(circuit)
    classes = _present_classes(circuit)
    best: JointFitResult | None = None
    statuses: tuple[ParameterStatus, ...] = ("shared", "free", "lawful")
    for combo in product(statuses, repeat=len(classes)):
        status: dict[ParamClass, ParameterStatus] = dict(zip(classes, combo, strict=True))
        try:
            candidate = fit_joint(
                circuit, spectrum_set, status, weighting=weighting, seed=seed, restarts=restarts
            )
        except (CircuitError, ValueError, np.linalg.LinAlgError):
            continue
        if not math.isfinite(candidate.score(criterion)):
            continue
        if best is None or candidate.score(criterion) < best.score(criterion):
            best = candidate
    if best is None:
        raise CircuitError(
            f"no parameter-status assignment could be fitted for {circuit.to_string()}"
        )
    return best


@dataclass(frozen=True)
class SetCandidate:
    """One topology, fitted independently to every condition (level 1)."""

    circuit: Circuit
    per_condition: tuple[FitResult, ...]
    ssr_total: float
    n_data_total: int
    n_params_total: int
    criteria: dict[str, float]

    @property
    def complexity(self) -> float:
        return self.circuit.complexity

    @property
    def chi2_reduced(self) -> float:
        dof = max(self.n_data_total - self.n_params_total, 1)
        return self.ssr_total / dof

    @property
    def n_unresolved(self) -> int:
        """Parameters unresolved in *any* condition's own independent fit, summed."""
        return sum(
            int(np.count_nonzero(unresolved_mask(fr.values, fr.statistics.stderr)))
            for fr in self.per_condition
        )

    def score(self, criterion: Criterion = DEFAULT_CRITERION) -> float:
        key = "aic" if criterion == "ftest" else criterion
        try:
            return self.criteria[key]
        except KeyError:
            raise ValueError(f"unknown model-selection criterion {criterion!r}") from None


def _refit_topology_set(
    text: str,
    spectrum_set: SpectrumSet,
    contexts: list[FitContext],
    weighting: Weighting,
    seed: int,
    restarts: int,
) -> SetCandidate:
    circuit = Circuit.parse(text)
    per_condition = tuple(
        fit(circuit, sp, weighting=weighting, seed=seed, restarts=restarts, context=ctx)
        for sp, ctx in zip(spectrum_set.spectra, contexts, strict=True)
    )
    ssr_total = float(sum(fr.statistics.ssr for fr in per_condition))
    n_data_total = sum(fr.statistics.n_data for fr in per_condition)
    n_params_total = per_condition[0].statistics.n_params * len(per_condition)
    criteria = information_criteria(ssr_total, n_data_total, n_params_total)
    return SetCandidate(circuit, per_condition, ssr_total, n_data_total, n_params_total, criteria)


def _same_response_set(a: SetCandidate, b: SetCandidate) -> bool:
    if len(a.per_condition) != len(b.per_condition):
        return False
    for fa, fb in zip(a.per_condition, b.per_condition, strict=True):
        za, zb = fa.z_model, fb.z_model
        if za.shape != zb.shape:
            return False
        magnitude = np.abs(zb)
        if not np.all(magnitude > 0.0):
            return False
        if np.max(np.abs(za - zb) / magnitude) > EQUIVALENCE_RTOL:
            return False
    return True


def _pareto_front_set(candidates: list[SetCandidate], criterion: Criterion) -> list[SetCandidate]:
    scores = {id(c): c.score(criterion) for c in candidates}
    front: list[SetCandidate] = []
    for candidate in candidates:
        mine = scores[id(candidate)]
        dominated = any(
            other is not candidate
            and other.complexity <= candidate.complexity
            and scores[id(other)] <= mine
            and (other.complexity < candidate.complexity or scores[id(other)] < mine)
            for other in candidates
        )
        if not dominated:
            front.append(candidate)
    return sorted(front, key=lambda c: (c.complexity, scores[id(c)]))


@dataclass
class SetDiscoveryResult:
    """Outcome of a level 1 (shared topology, independent parameters) search."""

    candidates: list[SetCandidate]
    """Every distinct topology evaluated, best first under :attr:`criterion`."""
    pareto: list[SetCandidate]
    n_evaluated: int
    elapsed_s: float
    pool: tuple[str, ...]
    complete_up_to: int | None
    conditions: tuple[float, ...]
    condition_kind: ConditionKind
    criterion: Criterion = DEFAULT_CRITERION

    @property
    def best(self) -> SetCandidate | None:
        return self.candidates[0] if self.candidates else None

    def _well_fitting(self) -> list[SetCandidate]:
        if not self.candidates:
            return []
        threshold = min(c.chi2_reduced for c in self.candidates) * PARSIMONY_CHI2_FACTOR
        return [c for c in self.pareto if c.chi2_reduced <= threshold]

    @property
    def recommended(self) -> SetCandidate | None:
        """The simplest topology that fits as well as any, with every parameter resolved.

        Mirrors :attr:`autocircuit.core.discover.DiscoveryResult.recommended` exactly -- same
        :data:`~autocircuit.core.discover.PARSIMONY_CHI2_FACTOR` band, same
        ``(complexity, aicc)`` tie-break -- because this is the identical rule applied to a
        pooled chi-squared instead of a single spectrum's, not a second convention.
        """
        if not self.candidates:
            return None
        well_fitting = self._well_fitting()
        viable = [c for c in well_fitting if c.n_unresolved == 0] or well_fitting
        if not viable:
            return self.best
        return min(viable, key=lambda c: (c.complexity, c.criteria["aicc"]))

    def equivalents_of(self, candidate: SetCandidate) -> list[SetCandidate]:
        return [
            other
            for other in self.candidates
            if other is not candidate and _same_response_set(other, candidate)
        ]


def discover_set(
    spectrum_set: SpectrumSet,
    *,
    pool: tuple[str, ...] | None = None,
    exhaustive_limit: int = 5,
    exhaustive_min: int = 1,
    max_candidates: int = 20_000,
    feasibility_filter: bool = True,
    feasibility_budget: int = DEFAULT_DEGENERACY_BUDGET,
    weighting: Weighting = DEFAULT_SET_WEIGHTING,
    criterion: Criterion = DEFAULT_CRITERION,
    seed: int = 0,
    screen_popsize: int = 8,
    screen_maxiter: int = 40,
    refit_top_k: int = 10,
    final_restarts: int = 5,
) -> SetDiscoveryResult:
    """Level 1 topology search: one topology, every parameter free per condition.

    Exhaustive-only -- reuses :func:`~autocircuit.core.discover.enumerate_candidates` for the
    candidate list and its feasibility filter (checked against the first condition's spectrum;
    every condition is assumed to share the same measurement window, which is what
    ``docs/IMPACT_PLAN.md`` section 3's data model assumes throughout). There is no genetic
    fallback and no growth stage here: both are single-spectrum machinery in
    :mod:`autocircuit.core.discover` that this function does not extend, which is why
    ``exhaustive_limit`` defaults to the same five-element regime the single-spectrum default
    covers without either.

    Ranking sums each condition's own :func:`~autocircuit.core.fit.screen` cost (tier 1) or
    :func:`~autocircuit.core.fit.fit` result (tier 2) and scores the pool with a parameter count
    of ``k * n_conditions``, via :func:`~autocircuit.core.stats.information_criteria`. Because a
    level 1 residual has no cross-condition coupling, this is exact, not an approximation: the
    joint least-squares problem :func:`fit_joint` solves for level 2 would find precisely the
    same per-condition optima here.
    """
    started = time.perf_counter()
    pool_codes = tuple(pool) if pool is not None else DEFAULT_POOL
    plan = enumerate_candidates(
        spectrum_set.spectra[0],
        pool=pool_codes,
        skeleton=None,
        limit=exhaustive_limit,
        floor=exhaustive_min,
        max_candidates=max_candidates,
        feasibility_filter=feasibility_filter,
        feasibility_budget=feasibility_budget,
    )
    texts = list(plan.texts)
    contexts = [FitContext.build(sp, weighting, None) for sp in spectrum_set.spectra]

    scored: list[tuple[float, str]] = []
    for text in texts:
        try:
            circuit = Circuit.parse(text)
            cost = sum(
                screen(
                    circuit,
                    sp,
                    weighting=weighting,
                    seed=seed,
                    popsize=screen_popsize,
                    maxiter=screen_maxiter,
                    context=ctx,
                )
                for sp, ctx in zip(spectrum_set.spectra, contexts, strict=True)
            )
        except (ValueError, CircuitError, np.linalg.LinAlgError):
            cost = math.inf
        scored.append((cost, text))
    complete_up_to = plan.coverage(len(scored))

    shortlist = sorted(scored, key=lambda item: item[0])[:refit_top_k]
    candidates: list[SetCandidate] = []
    for cost, text in shortlist:
        if not math.isfinite(cost):
            continue
        try:
            candidate = _refit_topology_set(
                text, spectrum_set, contexts, weighting, seed, final_restarts
            )
        except (ValueError, CircuitError, np.linalg.LinAlgError):
            continue
        if math.isfinite(candidate.score(criterion)):
            candidates.append(candidate)
    candidates.sort(key=lambda c: c.score(criterion))

    pareto = _pareto_front_set(candidates, criterion)
    return SetDiscoveryResult(
        candidates=candidates,
        pareto=pareto,
        n_evaluated=len([c for c in scored if math.isfinite(c[0])]),
        elapsed_s=time.perf_counter() - started,
        pool=pool_codes,
        complete_up_to=complete_up_to,
        conditions=spectrum_set.conditions,
        condition_kind=spectrum_set.condition_kind,
        criterion=criterion,
    )
