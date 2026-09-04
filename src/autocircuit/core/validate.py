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
no initial values, no local minima. A KK-compliant model that follows the data closely but
*systematically* is the test's evidence that the data violates the KK relations: drift,
non-stationarity or a non-linear response.

A drifting spectrum will happily fit an equivalent circuit and give confident, wrong numbers,
so this test is run automatically as a pre-flight check before fitting.

**The failure to be careful about is the model's own.** A Voigt series plus the three series
terms has only real poles, so a complex *pole* of Z -- an anti-resonance, which is what a
parallel resonance is -- is unreachable at any order. [measured] On a Butterworth-Van Dyke
resonator, data that is KK-compliant by construction because it is the exact response of a
passive circuit, the residual sits at 96.8% of |Z| from M = 3 all the way to M = 317. That is
not a verdict about the data, and this module must not report it as one.

Note the limits of that sentence, both of which are measured rather than reasoned:

*A series resonance is fine.* A series R-L-C has Z = R + jwL + 1/(jwC), which is literally the
three series terms of this basis, and it passes with a 0.98% residual. It is the pole, not the
resonance, that the basis cannot reach.

*And a residual magnitude alone does not catch it.* :data:`MODEL_FAILURE_RMS` works when the
basis misses completely. A moderately damped anti-resonance is half-reached: [measured] the same
resonator at mechanical Q = 2, 3, 5, 10 and 15 gives residuals of 1.3%, 2.6%, 4.6%, 17.6% and
24.5% -- under the threshold -- while the residual pattern stays firmly systematic (runs z from
-5.7 to -17.3). Those read as a plain failure blaming the measurement until the *resonance
probe* asks a second question of them; see :data:`PROBE_COLUMN_FRACTION` and
``docs/KK_RESONANCE_PLAN.md``, whose section 2 records why the probe is a probe rather than a
replacement basis. What remains true either way is that **this test cannot validate a
resonator**: "inconclusive" is the honest answer, not a workaround for one.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from .noise import resolve_weights
from .spectrum import Spectrum
from .weighting import Weighting
from .wire import encode_array, encode_complex_array, encode_float

Float = NDArray[np.float64]
Complex = NDArray[np.complex128]

#: Version of :meth:`KKResult.to_wire`; see :data:`autocircuit.core.fit.WIRE_VERSION`.
#:
#: 2 (2026-08-22) added ``verdict``, so that the browser's badge stops compressing a three-way
#: outcome into pass/fail.
#: 3 (2026-08-22) added the resonance probe's residual and runs z.
WIRE_VERSION = 3

#: What the test concluded. ``"fail"`` is a statement about the data; ``"inconclusive"`` is a
#: statement about the model, and says nothing either way about the measurement.
Verdict = Literal["pass", "fail", "inconclusive"]

#: Default stopping value for Schoenleber's mu criterion (0.85 is the value in the paper).
DEFAULT_MU_CRITERION = 0.85
#: Residuals below this (relative to |Z|) pass regardless of their shape.
DEFAULT_RESIDUAL_LIMIT = 0.01
#: Runs-test z-score below which residuals are called systematic rather than random.
RUNS_Z_LIMIT = -3.0
#: RMS residual (relative to |Z|) above which the *model*, not the data, is judged to have
#: failed -- the Voigt series never followed the curve, so nothing about the data's causality
#: has been tested and none may be claimed.
#:
#: [measured] The two situations are an order of magnitude apart, in both directions. A genuine
#: KK violation (a Randles cell whose charge-transfer resistance drifts 40% across the sweep)
#: still gets tracked: best RMS residual 1.8%, improving 11.5x as the model order grows, and
#: the verdict comes from the residual *pattern*. A resonance the basis cannot express gets
#: best RMS 48.7%, improving 1.2x -- adding elements buys nothing because the shape is not
#: reachable. 25% sits clear of both.
#:
#: Extra evidence, gathered when this became a user-visible state. Genuine violations stay far
#: below it across two orders of magnitude of drift -- 40%, 100%, 300% and 1000% multiplicative
#: drift give 2.5%, 4.1%, 8.0% and 15.0% RMS -- so the drift family never reaches this line.
#:
#: **Do not read this flag on its own; read :attr:`KKResult.verdict`.** Noise raises the residual
#: without being a KK violation at all: [measured] KK-compliant Randles data at 30% and 50% noise
#: gives 28.1% and 43.7% RMS and is over this line, while passing correctly on the runs test. A
#: consumer that asked this question before asking whether the spectrum passed would report
#: healthy noisy data as untested.
MODEL_FAILURE_RMS = 0.25

#: Quality factors of the probe's resonant bank; see :func:`_resonant_columns` and
#: ``docs/KK_RESONANCE_PLAN.md``. Four values spanning two decades of damping, because a pole
#: pair off the grid is approximated by its neighbours and the grid only has to be dense
#: enough, not exact.
PROBE_Q_GRID: tuple[float, ...] = (3.0, 10.0, 30.0, 100.0)

#: How many columns the probe's bank may add, as a fraction of the 2N real equations a spectrum
#: of N points provides. **This is the number that keeps the probe from destroying the test.**
#: [measured] An uncounted bank of 200 columns fits a 61-point spectrum drifting 1000% -- a
#: gross KK violation -- to 0.00% residual with random residual signs, because 122 equations
#: cannot constrain 223 unknowns. Budgeted here, the same drift stays firmly systematic at every
#: point density tried. Do not raise this without re-running gate K2.
PROBE_COLUMN_FRACTION = 0.15


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
    probe_rms: float = math.nan
    """RMS residual of the resonance probe, or NaN when the probe did not run.

    The probe refits at the same order with a bank of fixed resonances added, and is only ever
    reached from a failure whose residual is small enough to be worth a second question. See
    ``docs/KK_RESONANCE_PLAN.md``.
    """
    probe_runs_z: float = math.nan
    """Runs-test z of the probe's residual, or NaN when the probe did not run.

    This, not the residual magnitude, is what decides: [measured] requiring the probe to beat
    the plain residual threefold as well dropped a Q = 2 resonator whose plain residual is
    already 1.3%, while adding nothing -- the drift family is separated by the runs test alone,
    at runs z from -5.0 to -15.3.
    """

    @property
    def model_failed(self) -> bool:
        """True when the KK model never followed the data; see :data:`MODEL_FAILURE_RMS`.

        A raw magnitude question, and rarely the one a caller wants. Use :attr:`verdict`.
        """
        return self.rms_residual >= MODEL_FAILURE_RMS

    @property
    def resonance_suspected(self) -> bool:
        """The probe ran and removed the systematic residual, so the basis was the problem."""
        if math.isnan(self.probe_runs_z):
            return False
        return self.probe_runs_z >= RUNS_Z_LIMIT and self.probe_rms < MODEL_FAILURE_RMS

    @property
    def verdict(self) -> Verdict:
        """The three-way outcome, and the single place the order of those questions is decided.

        ``passed`` is asked *first*, which is not an arbitrary ordering: noise inflates the
        residual without being a KK violation, so KK-compliant data at 30% noise is over
        :data:`MODEL_FAILURE_RMS` and must still read as a pass. Asking the magnitude question
        first would report it as untested. Every consumer -- the summary below, the CLI's exit
        code, the browser's badge -- goes through here rather than re-deriving it.
        """
        if self.passed:
            return "pass"
        if self.model_failed or self.resonance_suspected:
            return "inconclusive"
        return "fail"

    def summary(self, spectrum: Spectrum) -> str:
        headline = {"pass": "PASS", "fail": "FAIL", "inconclusive": "NO VERDICT"}[self.verdict]
        lines = [
            f"Lin-KK validation : {headline}",
            f"  Voigt elements  : {self.n_elements} (mu = {self.mu:.3f})",
            f"  Max residual    : {self.max_residual:.4%}  (limit {self.residual_limit:.2%})",
            f"  RMS residual    : {self.rms_residual:.4%}",
            f"  Residual pattern: {'systematic' if self.systematic else 'random'}"
            f" (runs z = {self.runs_z:+.2f})",
        ]
        if not self.passed:
            combined = np.abs(self.residual_real) + np.abs(self.residual_imag)
            worst = int(np.argmax(combined))
            lines.append(f"  Worst point     : {spectrum.f[worst]:.6g} Hz")
            lines.append("")
            if self.resonance_suspected:
                lines += [
                    "  A KK-compliant model that also carries resonances fits this data with",
                    "  random residuals, and the Lin-KK basis cannot express an anti-resonance",
                    "  because it has only real poles. The failure above is therefore about",
                    "  the basis, not about the measurement, and no verdict on the data is",
                    "  available. A resonator is the usual reason; the probe's own residual is",
                    f"  {self.probe_rms:.4%} with runs z = {self.probe_runs_z:+.2f}.",
                ]
            elif self.verdict == "inconclusive":
                # The residual is the size of the data, so the model reproduced essentially
                # none of it and has tested nothing. Saying which of the two causes it is
                # would be a guess, so both are named and neither is asserted.
                lines += [
                    "  The KK model could not follow this data at all, so the test has not",
                    "  been applied -- this is not a verdict on the measurement. Two things",
                    "  look like this. Either the response is outside what a Voigt series can",
                    "  express -- an anti-resonance is the usual case, because this basis has",
                    "  only real poles -- or the data is too corrupted for any model to track.",
                    "  Check whether the spectrum turns inductive over a band and back before",
                    "  reading this as bad data.",
                ]
            else:
                lines += [
                    "  The data is not consistent with a linear, causal, stationary system.",
                    "  Typical causes: drift during the sweep, a non-linear excitation",
                    "  amplitude, temperature change, or a bad contact. Fitting a circuit to",
                    "  this data will produce confident but meaningless parameters.",
                ]
        return "\n".join(lines)

    def to_wire(self, spectrum: Spectrum) -> dict[str, Any]:
        """JSON-safe form of this verdict, for a browser thread that has to display it.

        There is no ``from_wire``: the far side of this boundary is JavaScript, which plots the
        residuals and prints the verdict rather than rebuilding a :class:`KKResult`. The
        rendered :meth:`summary` travels with the numbers on purpose -- the explanation of what
        a failed KK test means is science, so the UI shows the text the CLI shows rather than
        writing its own account of it.
        """
        return {
            "version": WIRE_VERSION,
            "n_elements": self.n_elements,
            "mu": encode_float(self.mu),
            "tau": encode_array(self.tau),
            "resistances": encode_array(self.resistances),
            "r_ohm": encode_float(self.r_ohm),
            "inductance": encode_float(self.inductance),
            "capacitance": encode_float(self.capacitance),
            "z_fit": encode_complex_array(self.z_fit),
            "residual_real": encode_array(self.residual_real),
            "residual_imag": encode_array(self.residual_imag),
            "max_residual": encode_float(self.max_residual),
            "rms_residual": encode_float(self.rms_residual),
            "runs_z": encode_float(self.runs_z),
            "probe_rms": encode_float(self.probe_rms),
            "probe_runs_z": encode_float(self.probe_runs_z),
            "systematic": self.systematic,
            "passed": self.passed,
            "verdict": self.verdict,
            "residual_limit": encode_float(self.residual_limit),
            "summary": self.summary(spectrum),
        }


def _resonant_columns(omega: Float, w0: float, q: float) -> list[Complex]:
    """The two numerator functions over one fixed conjugate pole pair.

    A parallel R-L-C block is ``Z = A / (1 + jQ(w/w0 - w0/w))``, which in pole form is
    ``A (w0/Q) s / (s^2 + (w0/Q) s + w0^2)``: a pole pair at real part ``-w0/(2Q)``, in the left
    half plane for any Q > 0. Fixing ``w0`` and ``Q`` on a grid is what keeps the amplitude
    linear -- the same trick the fixed tau grid plays for the relaxations -- and it also means
    the sign of the amplitude cannot move the poles, so a negative one is no less causal than
    the negative ``R_k`` a Voigt series already produces.

    Both columns are Hermitian in omega, so real coefficients keep the model a real-valued
    time-domain response. The second (low-pass) column is what lets a *fixed* pole pair carry
    any residue, rather than only the band-pass one.
    """
    denominator = (w0**2 - omega**2) + 1j * omega * w0 / q
    return [
        np.asarray((w0 / q) * (1j * omega) / denominator, dtype=np.complex128),
        np.asarray((w0**2) / denominator, dtype=np.complex128),
    ]


def _probe_grid(omega: Float, n_points: int) -> list[tuple[float, float]]:
    """Resonance grid for the probe: log-spaced frequencies against :data:`PROBE_Q_GRID`.

    Sized by :data:`PROBE_COLUMN_FRACTION` of the data rather than by anything about the
    spectrum's shape, so the probe cannot buy flexibility from the question it is being asked.
    """
    budget = int(PROBE_COLUMN_FRACTION * 2 * n_points)
    pairs = max(1, budget // (2 * len(PROBE_Q_GRID)))
    frequencies = np.logspace(np.log10(omega.min()), np.log10(omega.max()), pairs)
    return [(float(w0), float(q)) for q in PROBE_Q_GRID for w0 in frequencies]


def _design_matrix(
    omega: Float,
    tau: Float,
    add_inductance: bool,
    add_capacitance: bool,
    resonances: Sequence[tuple[float, float]] = (),
) -> Complex:
    """Columns of the KK-compliant linear model, evaluated at each angular frequency."""
    columns: list[Complex] = [np.ones_like(omega, dtype=np.complex128)]
    if add_inductance:
        columns.append(np.asarray(1j * omega, dtype=np.complex128))
    if add_capacitance:
        columns.append(np.asarray(1.0 / (1j * omega), dtype=np.complex128))
    for t in tau:
        columns.append(np.asarray(1.0 / (1.0 + 1j * omega * t), dtype=np.complex128))
    for w0, q in resonances:
        columns.extend(_resonant_columns(omega, w0, q))
    return np.stack(columns, axis=1)


def _solve(
    omega: Float,
    z: Complex,
    tau: Float,
    w_re: Float,
    w_im: Float,
    add_inductance: bool,
    add_capacitance: bool,
    resonances: Sequence[tuple[float, float]] = (),
) -> tuple[Float, Complex]:
    """Weighted linear least squares for the Voigt resistances and the series terms.

    The columns are normalised before the solve. Without it the system is hopeless: the
    series-capacitance column scales as 1/omega and the series-inductance column as omega, so
    across the eight decades of a typical sweep they differ by sixteen orders of magnitude
    and ``lstsq`` truncates the solution into nonsense. Scaling each column to unit norm
    (Jacobi preconditioning) leaves the solution unchanged but makes it computable.
    """
    design = _design_matrix(omega, tau, add_inductance, add_capacitance, resonances)
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
    resonance_probe: bool = True,
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
            :func:`autocircuit.core.weighting.weight_vectors`.
        residual_limit: Residual magnitude (relative to |Z|) that passes unconditionally.
        resonance_probe: On a *failing* spectrum whose residual is small enough to be worth a
            second question, refit with a bank of fixed resonances added and check whether the
            systematic residual was the basis's fault. It can only ever turn a failure into
            ``"inconclusive"``; nothing that passes is touched. Off, the verdict is the
            two-question one this module had before ``docs/KK_RESONANCE_PLAN.md``.

    Returns:
        A :class:`KKResult`. ``passed`` is False when a KK-compliant model tracks the data
        but leaves a systematic residual, which means the measurement is the problem -- and
        also when the model never tracked the data at all, which means nothing has been
        tested. :attr:`KKResult.model_failed` separates the two, and the summary says which.
    """
    omega = spectrum.omega
    z = spectrum.z
    w_re, w_im = resolve_weights(spectrum, weighting)

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

    # Only from a failure, and only from one the model did follow: above MODEL_FAILURE_RMS the
    # verdict is already "inconclusive" and a second solve would answer a question nobody asked.
    probe_rms = math.nan
    probe_runs_z = math.nan
    if resonance_probe and not passed and rms_residual < MODEL_FAILURE_RMS:
        _, z_probe = _solve(
            omega,
            z,
            tau,
            w_re,
            w_im,
            add_inductance,
            add_capacitance,
            _probe_grid(omega, len(spectrum)),
        )
        probe_re = (z.real - z_probe.real) / magnitude
        probe_im = (z.imag - z_probe.imag) / magnitude
        probe_rms = float(np.sqrt(np.mean(np.concatenate([probe_re, probe_im]) ** 2)))
        probe_runs_z = min(_runs_z(probe_re), _runs_z(probe_im))

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
        probe_rms=probe_rms,
        probe_runs_z=probe_runs_z,
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
