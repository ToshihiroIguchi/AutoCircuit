"""Fit statistics: uncertainty propagation, information criteria and identifiability checks."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple

import numpy as np
from numpy.typing import NDArray

from .wire import decode_array, decode_float, encode_array, encode_float

Float = NDArray[np.float64]

#: Correlation magnitude above which two parameters are reported as inseparable.
CORRELATION_WARNING = 0.99
#: Distance (relative to the bound span) inside which a parameter counts as stuck at a bound.
BOUND_TOLERANCE = 1e-4
#: Singular values below this fraction of the largest one are treated as null directions.
RANK_RCOND = 1e-10

#: Which rule decides between models. Six scores and one test; see :func:`criterion_value`.
type Criterion = Literal["aic", "aicc", "bic", "caic", "hqc", "waic", "ftest"]

#: Every criterion a caller may name, in the order a menu should offer them.
CRITERIA: tuple[Criterion, ...] = ("aic", "aicc", "bic", "caic", "hqc", "waic", "ftest")

#: The default, everywhere. AICc was the default until 2026-08-16.
DEFAULT_CRITERION: Criterion = "aic"

#: How each one is written in a report or a menu.
CRITERION_LABELS: dict[Criterion, str] = {
    "aic": "AIC",
    "aicc": "AICc",
    "bic": "BIC",
    "caic": "CAIC",
    "hqc": "HQC",
    "waic": "WAIC",
    "ftest": "F-test",
}

#: One line each, for a tooltip or a ``--help`` string.
CRITERION_NOTES: dict[Criterion, str] = {
    "aic": "Akaike information criterion; penalty 2 per parameter.",
    "aicc": "AIC with the small-sample correction; use it when the point count is small.",
    "bic": "Bayesian information criterion; penalty log(n) per parameter, so it prefers "
    "simpler models than AIC on any real spectrum.",
    "caic": "Bozdogan's consistent AIC; BIC's penalty plus one per parameter.",
    "hqc": "Hannan-Quinn; penalty 2*log(log n), between AIC and BIC.",
    "waic": "Widely applicable information criterion, under a Laplace approximation of the "
    "posterior (see compute_statistics): its penalty counts the parameters the data "
    "actually resolves rather than the parameters the model declares.",
    "ftest": "Not a score but a test between two models: it ranks by AIC and then steps up "
    "the Pareto front only where the extra parameters are significant. It assumes the "
    "simpler model is nested in the larger one, which topologies generally are not.",
}

#: Criteria that give one number per model. ``ftest`` is the one that does not.
SCORE_CRITERIA: tuple[Criterion, ...] = tuple(c for c in CRITERIA if c != "ftest")

#: The score an F-test run ranks and draws its Pareto front by, since a test provides no axis.
FTEST_RANKING: Criterion = "aic"

#: Significance level of the sequential F-test.
FTEST_ALPHA = 0.05


class FTest(NamedTuple):
    """One extra-sum-of-squares comparison of a simpler model against a larger one."""

    f: float
    p: float
    df1: int
    """Parameters the larger model adds."""
    df2: int
    """Residual degrees of freedom of the larger model."""

    @property
    def significant(self) -> bool:
        return self.p < FTEST_ALPHA


def f_test(
    ssr_simple: float, k_simple: int, ssr_complex: float, k_complex: int, n_data: int
) -> FTest | None:
    """Does the larger model's extra sum of squares earn its extra parameters?

    ``F = ((SSR1 - SSR2)/(k2 - k1)) / (SSR2/(n - k2))`` against ``F(k2 - k1, n - k2)``, which is
    the standard extra-sum-of-squares test. **It assumes model 1 is nested inside model 2**, and
    two topologies on a Pareto front generally are not: ``R1-p(R2,C1)`` is not a special case of
    ``C1-R1-L1``. Whoever reports this has to say so; see
    :meth:`~autocircuit.core.discover.DiscoveryResult.summary`.

    Returns None when the comparison is not defined at all -- the larger model has no more
    parameters, there are no residual degrees of freedom left, or a sum of squares is not
    finite and positive. A larger model that fits *worse* is not an error and comes back with
    ``f = 0`` and ``p = 1``.

    The p-value comes from the regularised incomplete beta function rather than from
    ``scipy.stats``: ``P(F > f) = I_{d2/(d2 + d1 f)}(d2/2, d1/2)``. ``scipy.special`` is already
    imported by :mod:`autocircuit.core.elements`, and ``scipy.stats`` is a second heavy import
    on a page whose start-up cost is measured in seconds (docs/METRICS_AND_UX_PLAN.md section 1).

    That import happens *here* rather than at module scope, which is the one thing in this file
    that is about the browser rather than about statistics: this module also carries the
    criteria menu, which the web front end asks for before scipy has finished loading
    (``docs/STARTUP_AND_EDITING_PLAN.md`` section 3.2). Everything else here is numpy.
    """
    from scipy.special import betainc

    df1 = k_complex - k_simple
    df2 = n_data - k_complex
    if df1 <= 0 or df2 <= 0:
        return None
    if not (math.isfinite(ssr_simple) and math.isfinite(ssr_complex)) or ssr_complex <= 0.0:
        return None
    gain = ssr_simple - ssr_complex
    if gain <= 0.0:
        return FTest(0.0, 1.0, df1, df2)
    f_value = (gain / df1) / (ssr_complex / df2)
    p = float(betainc(df2 / 2.0, df1 / 2.0, df2 / (df2 + df1 * f_value)))
    return FTest(float(f_value), p, df1, df2)


@dataclass(frozen=True)
class Statistics:
    """Uncertainty and model-selection statistics for one fit."""

    n_data: int
    """Number of real residuals (twice the number of frequency points)."""
    n_params: int
    ssr: float
    """Weighted sum of squared residuals."""
    chi2_reduced: float
    stderr: Float
    """Standard error of each parameter, in the parameter's own units."""
    correlation: Float
    aic: float
    aicc: float
    bic: float
    caic: float = math.nan
    """Bozdogan's consistent AIC: ``deviance + k*(log n + 1)``."""
    hqc: float = math.nan
    """Hannan-Quinn: ``deviance + 2k*log(log n)``."""
    waic: float = math.nan
    """Widely applicable IC, under the Laplace approximation :func:`compute_statistics` makes."""
    p_waic: float = math.nan
    """WAIC's effective parameter count: how many parameters the data actually resolves.

    Reported beside :attr:`waic` because the difference between them and AIC's nominal ``2k`` is
    the only reason to ask for WAIC here. In the well-behaved limit it equals :attr:`rank`.
    """
    rank: int = 0
    """Numerical rank of the Jacobian; less than ``n_params`` means structural degeneracy."""
    warnings: tuple[str, ...] = field(default=())

    @property
    def dof(self) -> int:
        return self.n_data - self.n_params

    def criterion_value(self, criterion: Criterion) -> float:
        """This fit's score under ``criterion``, smaller being better.

        ``ftest`` is not a score -- it compares two models -- so it answers with the criterion
        an F-test run ranks by (:data:`FTEST_RANKING`). Anything that has to *choose* between
        models under ``ftest`` must call :func:`f_test` instead of reading this.
        """
        name = FTEST_RANKING if criterion == "ftest" else criterion
        try:
            return float(getattr(self, name))
        except AttributeError:  # pragma: no cover - guarded by the Criterion type
            raise ValueError(f"unknown model-selection criterion {criterion!r}") from None

    def to_wire(self) -> dict[str, Any]:
        """Every field, JSON-safe and lossless (see :mod:`autocircuit.core.wire`).

        The correlation matrix and the standard errors are the reason this exists rather than
        a reuse of ``FitResult.to_dict``: they are what says a model is unidentifiable, and
        a transport that drops them delivers a fit that looks better than it is.
        """
        return {
            "n_data": self.n_data,
            "n_params": self.n_params,
            "ssr": encode_float(self.ssr),
            "chi2_reduced": encode_float(self.chi2_reduced),
            "stderr": encode_array(self.stderr),
            "correlation": encode_array(self.correlation),
            "aic": encode_float(self.aic),
            "aicc": encode_float(self.aicc),
            "bic": encode_float(self.bic),
            "caic": encode_float(self.caic),
            "hqc": encode_float(self.hqc),
            "waic": encode_float(self.waic),
            "p_waic": encode_float(self.p_waic),
            "rank": self.rank,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> Statistics:
        """Inverse of :meth:`to_wire`."""
        return cls(
            n_data=int(payload["n_data"]),
            n_params=int(payload["n_params"]),
            ssr=decode_float(payload["ssr"]),
            chi2_reduced=decode_float(payload["chi2_reduced"]),
            stderr=decode_array(payload["stderr"]),
            correlation=decode_array(payload["correlation"]),
            aic=decode_float(payload["aic"]),
            aicc=decode_float(payload["aicc"]),
            bic=decode_float(payload["bic"]),
            caic=decode_float(payload["caic"]),
            hqc=decode_float(payload["hqc"]),
            waic=decode_float(payload["waic"]),
            p_waic=decode_float(payload["p_waic"]),
            rank=int(payload["rank"]),
            warnings=tuple(payload["warnings"]),
        )


def compute_statistics(
    residuals: Float,
    jac_x: Float,
    values: Float,
    log_mask: NDArray[np.bool_],
    param_names: tuple[str, ...],
    lower_x: Float | None = None,
    upper_x: Float | None = None,
    x: Float | None = None,
) -> Statistics:
    """Derive standard errors, correlations and information criteria from a converged fit.

    The covariance is computed in the *search* space (log10 for scale parameters) and only
    then mapped to parameter units. Doing it the other way round is numerically hopeless:
    a circuit whose parameters span 1e-10 F and 1e5 ohm gives a parameter-space Gauss-Newton
    Hessian with a condition number around 1e20, and its pseudo-inverse collapses to almost
    rank one, which shows up as a spurious +/-1.0 correlation between every pair. The mapping
    ``p = 10**x`` is diagonal with a positive derivative, so correlations are identical in
    both spaces and only the standard errors need rescaling by ``dp/dx = p * ln 10``.

    Args:
        residuals: Weighted residual vector (length ``2 * n_points``).
        jac_x: Residual Jacobian with respect to the search variables.
        values: Fitted parameter values in natural units.
        log_mask: Which parameters were searched in log10 space.
        param_names: Names used in the warning messages.
        lower_x, upper_x, x: Search bounds and solution, used to flag parameters at a bound.
    """
    n_data = int(residuals.size)
    n_params = int(values.size)
    ssr = float(np.dot(residuals, residuals))
    dof = max(n_data - n_params, 1)
    chi2_reduced = ssr / dof

    cov_x, rank, leverage = _covariance(jac_x, chi2_reduced)

    variance_x = np.clip(np.diag(cov_x), 0.0, np.inf)
    stderr_x = np.sqrt(variance_x)

    # Correlation is invariant under the diagonal, positive transform p = 10**x.
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = np.outer(stderr_x, stderr_x)
        correlation = np.where(denom > 0.0, cov_x / denom, 0.0)
    np.fill_diagonal(correlation, 1.0)
    correlation = np.clip(np.nan_to_num(correlation), -1.0, 1.0)

    # dp/dx = p * ln(10) for log-scale parameters, 1 otherwise.
    scale = np.ones_like(values)
    scale[log_mask] = np.abs(values[log_mask]) * math.log(10.0)
    stderr = stderr_x * scale

    criteria = information_criteria(ssr, n_data, n_params, residuals, leverage)

    warnings = _collect_warnings(
        correlation, stderr, values, param_names, rank, lower_x, upper_x, x
    )

    return Statistics(
        n_data=n_data,
        n_params=n_params,
        ssr=ssr,
        chi2_reduced=chi2_reduced,
        stderr=stderr,
        correlation=correlation,
        rank=rank,
        warnings=warnings,
        aic=criteria["aic"],
        aicc=criteria["aicc"],
        bic=criteria["bic"],
        caic=criteria["caic"],
        hqc=criteria["hqc"],
        waic=criteria["waic"],
        p_waic=criteria["p_waic"],
    )


def information_criteria(
    ssr: float,
    n_data: int,
    n_params: int,
    residuals: Float | None = None,
    leverage: Float | None = None,
) -> dict[str, float]:
    """Every model-selection score this project offers, from one fit's residuals.

    All of them are written on the deviance scale the project has always used::

        deviance = n * log(SSR / n)

    which is ``-2*logL`` for a Gaussian likelihood with the variance profiled out, less the
    constant ``n*log(2*pi) + n``. Dropping a constant is safe because every use is a
    *difference* between two models fitted to the same data -- and it is what makes AIC here
    comparable with the number ``fit --json`` has always printed.

    ``residuals`` and ``leverage`` are only needed for WAIC; without them it is NaN, which is
    the honest answer for a screening pass that never computed a Jacobian
    (:func:`autocircuit.core.discover._screening_score`).
    """
    k = n_params
    deviance = n_data * math.log(ssr / n_data) if ssr > 0.0 else -math.inf
    aic = deviance + 2.0 * k
    aicc = aic + 2.0 * k * (k + 1) / (n_data - k - 1) if n_data - k - 1 > 0 else math.inf
    log_n = math.log(n_data) if n_data > 0 else -math.inf
    waic, p_waic = _waic(ssr, n_data, residuals, leverage)
    return {
        "aic": aic,
        "aicc": aicc,
        "bic": deviance + k * log_n,
        "caic": deviance + k * (log_n + 1.0),
        # log(log n) is negative below n = e, where 2k*log(log n) would *reward* parameters.
        # Two residuals is not a spectrum, but a criterion that inverts its own penalty on a
        # degenerate input should say so rather than return a number.
        "hqc": (
            deviance + 2.0 * k * math.log(log_n) if log_n > 0.0 else math.nan
        ),
        "waic": waic,
        "p_waic": p_waic,
    }


def _waic(
    ssr: float, n_data: int, residuals: Float | None, leverage: Float | None
) -> tuple[float, float]:
    """WAIC and its effective parameter count, under a Laplace approximation.

    **WAIC is defined over a posterior and this is a least-squares fitter**, so something has to
    be assumed. Two things are, and they are named here rather than hidden in a number:

    * the posterior is the Laplace approximation at the fitted point -- the covariance
      :func:`_covariance` already computes, in the log search space for the reason
      docs/HANDOFF.md section 3 gives;
    * the residual is linearised through the same Jacobian that covariance comes from.

    Under those two every integral WAIC needs is Gaussian and closes in one line. With
    ``sigma2 = SSR/n`` and the leverage ``h`` (the hat-matrix diagonal, so the predictive
    variance at point i is ``sigma2 * h_i``)::

        lppd   = sum_i [ -log(2*pi*sigma2)/2 - log(1 + h_i)/2 - a_i^2/(2*sigma2*(1 + h_i)) ]
        p_waic = sum_i [ h_i^2/2 + a_i^2*h_i/sigma2 ]

    and ``waic = -2*lppd + 2*p_waic``, less the same constant every other criterion drops.

    In the small-leverage limit this is ``deviance + 2*rank``: WAIC's *effective* parameter
    count where AIC has the nominal one, which is the whole reason to offer it here -- on a
    circuit the data cannot resolve the two disagree by exactly what is unresolved. What it
    cannot see is posterior non-Gaussianity, which for a fifteen-decade log-parameterised fit
    is not nothing. It is an approximation, and it is reported as one.
    """
    if residuals is None or leverage is None:
        return math.nan, math.nan
    if not math.isfinite(ssr) or ssr <= 0.0 or n_data <= 0:
        # An exact fit: AIC, AICc and BIC are all -inf here too (see tests/test_wire.py).
        return (-math.inf if ssr == 0.0 else math.nan), math.nan
    h = np.asarray(leverage, dtype=np.float64)
    if not np.all(np.isfinite(h)):
        return math.nan, math.nan
    h = np.clip(h, 0.0, np.inf)
    sigma2 = ssr / n_data
    a2 = np.asarray(residuals, dtype=np.float64) ** 2
    pointwise = (
        -0.5 * math.log(2.0 * math.pi * sigma2)
        - 0.5 * np.log1p(h)
        - a2 / (2.0 * sigma2 * (1.0 + h))
    )
    lppd = float(np.sum(pointwise))
    p_waic = float(np.sum(0.5 * h**2 + a2 * h / sigma2))
    waic = -2.0 * lppd + 2.0 * p_waic - n_data * math.log(2.0 * math.pi) - n_data
    return waic, p_waic


def _covariance(jac_x: Float, chi2_reduced: float) -> tuple[Float, int, Float]:
    """Pseudo-inverse of the Gauss-Newton Hessian via SVD, the rank, and the leverage.

    The leverage is the hat-matrix diagonal, ``diag(U U^T)`` over the singular directions that
    were kept. It costs one more line here because the SVD has already been done, and it is what
    :func:`_waic` needs; computing it anywhere else would mean a second decomposition of the
    same Jacobian.
    """
    jac = np.nan_to_num(np.asarray(jac_x, dtype=np.float64))
    n = jac.shape[1]
    failed = np.full(jac.shape[0], np.nan)
    try:
        u, singular, vt = np.linalg.svd(jac, full_matrices=False)
    except np.linalg.LinAlgError:
        return np.full((n, n), np.nan), 0, failed
    if singular.size == 0 or singular[0] == 0.0:
        return np.full((n, n), np.inf), 0, failed
    keep = singular > singular[0] * RANK_RCOND
    rank = int(np.count_nonzero(keep))
    inv_sq = np.zeros_like(singular)
    inv_sq[keep] = 1.0 / singular[keep] ** 2
    cov = (vt.T * inv_sq) @ vt
    leverage = np.sum(u[:, keep] ** 2, axis=1)
    return cov * chi2_reduced, rank, leverage


def _collect_warnings(
    correlation: Float,
    stderr: Float,
    values: Float,
    param_names: tuple[str, ...],
    rank: int,
    lower_x: Float | None,
    upper_x: Float | None,
    x: Float | None,
) -> tuple[str, ...]:
    warnings: list[str] = []
    k = len(param_names)

    if rank < k:
        warnings.append(
            f"the Jacobian has rank {rank} for {k} parameters: the model is over-parameterised "
            "for this data and at least one parameter combination is unconstrained"
        )

    for i in range(k):
        for j in range(i + 1, k):
            if abs(correlation[i, j]) >= CORRELATION_WARNING:
                warnings.append(
                    f"{param_names[i]} and {param_names[j]} are {correlation[i, j]:+.4f} "
                    "correlated: they are not independently identifiable from this data"
                )

    for i in range(k):
        if math.isfinite(stderr[i]) and values[i] != 0 and stderr[i] / abs(values[i]) > 1.0:
            warnings.append(
                f"{param_names[i]} has a standard error larger than its value "
                f"({stderr[i]:.3g} vs {values[i]:.3g}): the parameter is poorly constrained"
            )

    if lower_x is not None and upper_x is not None and x is not None:
        span = np.where(upper_x > lower_x, upper_x - lower_x, 1.0)
        at_lower = (x - lower_x) / span < BOUND_TOLERANCE
        at_upper = (upper_x - x) / span < BOUND_TOLERANCE
        for i in range(k):
            if at_lower[i] or at_upper[i]:
                which = "lower" if at_lower[i] else "upper"
                warnings.append(
                    f"{param_names[i]} converged onto its {which} search bound "
                    f"({values[i]:.4g}): the element may be redundant or the data may not "
                    "constrain it"
                )
    return tuple(warnings)
