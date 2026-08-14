"""Fit statistics: uncertainty propagation, information criteria and identifiability checks."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

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
    rank: int = 0
    """Numerical rank of the Jacobian; less than ``n_params`` means structural degeneracy."""
    warnings: tuple[str, ...] = field(default=())

    @property
    def dof(self) -> int:
        return self.n_data - self.n_params

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

    cov_x, rank = _covariance(jac_x, chi2_reduced)

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

    k = n_params
    log_likelihood_term = n_data * math.log(ssr / n_data) if ssr > 0.0 else -math.inf
    aic = log_likelihood_term + 2.0 * k
    aicc = aic + 2.0 * k * (k + 1) / (n_data - k - 1) if n_data - k - 1 > 0 else math.inf
    bic = log_likelihood_term + k * math.log(n_data)

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
        aic=aic,
        aicc=aicc,
        bic=bic,
        rank=rank,
        warnings=warnings,
    )


def _covariance(jac_x: Float, chi2_reduced: float) -> tuple[Float, int]:
    """Pseudo-inverse of the Gauss-Newton Hessian via SVD, plus the numerical rank."""
    jac = np.nan_to_num(np.asarray(jac_x, dtype=np.float64))
    n = jac.shape[1]
    try:
        _, singular, vt = np.linalg.svd(jac, full_matrices=False)
    except np.linalg.LinAlgError:
        return np.full((n, n), np.nan), 0
    if singular.size == 0 or singular[0] == 0.0:
        return np.full((n, n), np.inf), 0
    keep = singular > singular[0] * RANK_RCOND
    rank = int(np.count_nonzero(keep))
    inv_sq = np.zeros_like(singular)
    inv_sq[keep] = 1.0 / singular[keep] ** 2
    cov = (vt.T * inv_sq) @ vt
    return cov * chi2_reduced, rank


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
