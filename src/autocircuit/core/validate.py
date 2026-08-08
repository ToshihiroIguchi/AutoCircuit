"""Linear Kramers-Kronig (Lin-KK) data validation.

Before fitting any equivalent circuit it is worth asking a different question: *is this data
even measurable by a linear, causal, stable, time-invariant system?* The Kramers-Kronig
relations answer that, and the linear KK test of Boukamp (J. Electrochem. Soc. 142, 1885,
1995) with the model-order criterion of Schoenleber, Klotz and Ivers-Tiffee (Electrochim.
Acta 131, 20, 2014) is the practical way to run it.

The idea: fit the data with a series of ``M`` Voigt (parallel RC) elements whose time
constants are *fixed* on a logarithmic grid, plus a series resistance and optionally a series
inductance and capacitance. Every such element is KK-compliant by construction, and because
the time constants are fixed the resistances follow from ordinary *linear* least squares --
no initial values, no local minima. If a KK-compliant model with enough elements still cannot
follow the data, the data itself violates the KK relations: drift, non-stationarity or a
non-linear response.

A drifting spectrum will happily fit an equivalent circuit and give confident, wrong numbers,
so this test is run automatically as a pre-flight check before fitting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .fit import Weighting, weight_vectors
from .spectrum import Spectrum

Float = NDArray[np.float64]
Complex = NDArray[np.complex128]

#: Default stopping value for Schoenleber's mu criterion (0.85 is the value in the paper).
DEFAULT_MU_CRITERION = 0.85
#: Residuals below this (relative to |Z|) pass regardless of their shape.
DEFAULT_RESIDUAL_LIMIT = 0.01
#: Runs-test z-score below which residuals are called systematic rather than random.
RUNS_Z_LIMIT = -3.0


@dataclass(frozen=True)
class KKResult:
    """Outcome of a Lin-KK test."""

    n_elements: int
    """Number of Voigt elements used."""
    mu: float
    """Schoenleber's over-fitting indicator; the model order is raised until mu drops below
    the criterion."""
    tau: Float
    resistances: Float
    r_ohm: float
    inductance: float
    capacitance: float
    z_fit: Complex
    residual_real: Float
    """(Re Z - Re Z_fit) / |Z|, per frequency point."""
    residual_imag: Float
    max_residual: float
    rms_residual: float
    runs_z: float
    """How random the residual sign pattern is. Around 0 for noise; strongly negative when
    the residuals form smooth systematic trends, which is what a KK violation looks like."""
    systematic: bool
    passed: bool
    residual_limit: float

    def summary(self, spectrum: Spectrum) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        lines = [
            f"Lin-KK validation : {verdict}",
            f"  Voigt elements  : {self.n_elements} (mu = {self.mu:.3f})",
            f"  Max residual    : {self.max_residual:.4%}  (limit {self.residual_limit:.2%})",
            f"  RMS residual    : {self.rms_residual:.4%}",
            f"  Residual pattern: {'systematic' if self.systematic else 'random'}"
            f" (runs z = {self.runs_z:+.2f})",
        ]
        if not self.passed:
            combined = np.abs(self.residual_real) + np.abs(self.residual_imag)
            worst = int(np.argmax(combined))
            lines += [
                f"  Worst point     : {spectrum.f[worst]:.6g} Hz",
                "",
                "  The data is not consistent with a linear, causal, stationary system.",
                "  Typical causes: drift during the sweep, a non-linear excitation amplitude,",
                "  temperature change, or a bad contact. Fitting a circuit to this data will",
                "  produce confident but meaningless parameters.",
            ]
        return "\n".join(lines)


def _design_matrix(
    omega: Float, tau: Float, add_inductance: bool, add_capacitance: bool
) -> Complex:
    """Columns of the KK-compliant linear model, evaluated at each angular frequency."""
    columns: list[Complex] = [np.ones_like(omega, dtype=np.complex128)]
    if add_inductance:
        columns.append(np.asarray(1j * omega, dtype=np.complex128))
    if add_capacitance:
        columns.append(np.asarray(1.0 / (1j * omega), dtype=np.complex128))
    for t in tau:
        columns.append(np.asarray(1.0 / (1.0 + 1j * omega * t), dtype=np.complex128))
    return np.stack(columns, axis=1)


def _solve(
    omega: Float,
    z: Complex,
    tau: Float,
    w_re: Float,
    w_im: Float,
    add_inductance: bool,
    add_capacitance: bool,
) -> tuple[Float, Complex]:
    """Weighted linear least squares for the Voigt resistances and the series terms.

    The columns are normalised before the solve. Without it the system is hopeless: the
    series-capacitance column scales as 1/omega and the series-inductance column as omega, so
    across the eight decades of a typical sweep they differ by sixteen orders of magnitude
    and ``lstsq`` truncates the solution into nonsense. Scaling each column to unit norm
    (Jacobi preconditioning) leaves the solution unchanged but makes it computable.
    """
    design = _design_matrix(omega, tau, add_inductance, add_capacitance)
    a = np.vstack([design.real * w_re[:, None], design.imag * w_im[:, None]])
    b = np.concatenate([z.real * w_re, z.imag * w_im])

    norms = np.linalg.norm(a, axis=0)
    norms[norms == 0.0] = 1.0
    scaled, *_ = np.linalg.lstsq(a / norms, b, rcond=None)
    coefficients = scaled / norms

    z_fit = design @ coefficients.astype(np.complex128)
    return coefficients, z_fit


def lin_kk(
    spectrum: Spectrum,
    *,
    mu_criterion: float = DEFAULT_MU_CRITERION,
    max_elements: int | None = None,
    add_inductance: bool = True,
    add_capacitance: bool = True,
    weighting: Weighting = "modulus",
    residual_limit: float = DEFAULT_RESIDUAL_LIMIT,
) -> KKResult:
    """Run the Lin-KK test on a spectrum.

    Args:
        spectrum: Data to validate.
        mu_criterion: Model order is increased until ``mu`` falls below this value. Lower
            values allow more Voigt elements and therefore a more flexible KK model.
        max_elements: Hard cap on the number of Voigt elements.
        add_inductance: Include a series inductance, needed for data that turns inductive
            at high frequency (most real components do).
        add_capacitance: Include a series capacitance, needed for blocking / capacitive data.
        weighting: Weighting used in the linear least squares; see
            :func:`autocircuit.core.fit.weight_vectors`.
        residual_limit: Residual magnitude (relative to |Z|) that passes unconditionally.

    Returns:
        A :class:`KKResult`. ``passed`` is False when the data cannot be represented by a
        KK-compliant model, which means the measurement, not the model, is the problem.
    """
    omega = spectrum.omega
    z = spectrum.z
    w_re, w_im = weight_vectors(z, weighting)

    n_series = 1 + int(add_inductance) + int(add_capacitance)
    hard_cap = max(2 * len(spectrum) - n_series - 1, 3)
    default_cap = min(hard_cap, max(len(spectrum), 3))
    cap = int(min(max_elements if max_elements is not None else default_cap, hard_cap))

    scan: list[tuple[int, float, float, Float, Complex]] = []
    for m in _candidate_orders(cap):
        tau = np.logspace(np.log10(1.0 / omega.max()), np.log10(1.0 / omega.min()), m)
        coefficients, z_fit = _solve(omega, z, tau, w_re, w_im, add_inductance, add_capacitance)
        mu = _mu(coefficients[n_series:])
        max_res = float(np.max(np.abs(z - z_fit) / np.abs(z)))
        scan.append((m, mu, max_res, coefficients, z_fit))

    m, mu, _, coefficients, z_fit = _select_order(scan, mu_criterion)
    tau = np.logspace(np.log10(1.0 / omega.max()), np.log10(1.0 / omega.min()), m)

    index = 0
    r_ohm = float(coefficients[index])
    index += 1
    inductance = float(coefficients[index]) if add_inductance else 0.0
    index += int(add_inductance)
    inverse_c = float(coefficients[index]) if add_capacitance else 0.0
    capacitance = 1.0 / inverse_c if inverse_c != 0.0 else math.inf
    index += int(add_capacitance)
    resistances = coefficients[index:]

    magnitude = np.abs(z)
    residual_real = (z.real - z_fit.real) / magnitude
    residual_imag = (z.imag - z_fit.imag) / magnitude
    stacked = np.concatenate([residual_real, residual_imag])
    max_residual = float(np.max(np.abs(stacked)))
    rms_residual = float(np.sqrt(np.mean(stacked**2)))

    runs_z = min(_runs_z(residual_real), _runs_z(residual_imag))
    systematic = bool(runs_z < RUNS_Z_LIMIT)
    passed = bool(max_residual <= residual_limit or not systematic)

    return KKResult(
        n_elements=m,
        mu=mu,
        tau=tau,
        resistances=resistances,
        r_ohm=r_ohm,
        inductance=inductance,
        capacitance=capacitance,
        z_fit=z_fit,
        residual_real=residual_real,
        residual_imag=residual_imag,
        max_residual=max_residual,
        rms_residual=rms_residual,
        runs_z=runs_z,
        systematic=systematic,
        passed=passed,
        residual_limit=residual_limit,
    )


#: Upper limit on how many model orders the scan evaluates. Each order costs a dense least
#: squares solve, so a spectrum with hundreds of points must not be scanned one order at a
#: time; a geometric ladder resolves small orders finely and large ones coarsely, which is
#: exactly where the resolution is needed.
MAX_SCAN_STEPS = 40


def _candidate_orders(cap: int) -> list[int]:
    """Model orders to try, densely at the low end and geometrically spaced above it."""
    if cap <= 3:
        return [3]
    if cap - 2 <= MAX_SCAN_STEPS:
        return list(range(3, cap + 1))
    ladder = np.unique(np.round(np.geomspace(3, cap, MAX_SCAN_STEPS)).astype(int))
    return [int(m) for m in ladder]


def _select_order(
    scan: list[tuple[int, float, float, Float, Complex]], mu_criterion: float
) -> tuple[int, float, float, Float, Complex]:
    """Pick the model order: the first sufficiently flexible fit that is not over-fitting.

    Schoenleber's rule is to raise M until mu drops below the criterion. Taken literally that
    is fragile, because mu can dip early on a model that is still far too stiff to follow the
    data. So candidates are additionally required to fit about as well as the best order seen
    anywhere in the scan, which rejects those early dips.
    """
    best_residual = min(entry[2] for entry in scan)
    tolerance = max(best_residual * 2.0, 1e-9)
    for entry in scan:
        if entry[1] <= mu_criterion and entry[2] <= tolerance:
            return entry
    return min(scan, key=lambda entry: entry[2])


def _mu(resistances: Float) -> float:
    """Schoenleber's over-fitting indicator.

    ``mu = 1 - sum|R_k<0| / sum|R_k>=0|``. An under-parameterised model has all-positive
    resistances and mu near 1; as elements are added the fit starts using negative
    resistances to chase noise and mu falls. Stopping at a threshold picks the largest model
    order that is still fitting signal rather than noise.
    """
    negative = float(np.sum(np.abs(resistances[resistances < 0])))
    positive = float(np.sum(np.abs(resistances[resistances >= 0])))
    if positive == 0.0:
        return 0.0
    return float(np.clip(1.0 - negative / positive, 0.0, 1.0))


def _runs_z(residual: Float) -> float:
    """Wald-Wolfowitz runs test on the residual signs.

    Random measurement noise changes sign about half the time from one frequency to the next.
    A Kramers-Kronig violation is smooth in frequency, so its residuals keep the same sign
    over long stretches and the number of sign changes collapses. This distinguishes "the
    residuals are large because the data is noisy" (fine) from "the residuals are large
    because the data is not physically consistent" (not fine) without needing to know the
    noise level in advance.
    """
    signs = np.sign(residual)
    signs = signs[signs != 0.0]
    n = signs.size
    if n < 8:
        return 0.0
    changes = int(np.count_nonzero(np.diff(signs) != 0))
    expected = (n - 1) / 2.0
    std = math.sqrt(n - 1) / 2.0
    return float((changes - expected) / std) if std > 0 else 0.0
