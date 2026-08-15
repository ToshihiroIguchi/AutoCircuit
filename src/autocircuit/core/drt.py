"""Distribution of relaxation times (DRT) -- structure probing, not a rival analysis.

An impedance spectrum made of parallel-RC blocks is a sum of Debye terms::

    Z(w) = R_inf + jwL + 1/(jwC) + SUM_k  gamma_k / (1 + jw tau_k)

Fix the time constants ``tau_k`` on a logarithmic grid and the unknowns enter *linearly*, so
the whole thing is one least-squares solve: no initial values, no local minima, deterministic.
That is the same trick :mod:`autocircuit.core.validate` uses for the Lin-KK test, and the
column-scaling lesson recorded there applies here verbatim.

The difference is what the answer is used for. Lin-KK asks "is this data physically
consistent?" and throws the coefficients away. DRT keeps them and reads the *shape* of
``gamma(tau)``:

* how many distinct relaxations does this sample actually show (how many blocks does the
  ceramic have)?
* is a peak wider than this inversion makes an ideal Debye peak -- which is what a distributed
  process looks like, and a reason to reach for CPE rather than C?
* what are the series R and L?

**This is advice for the report, and nothing more.** [measured] It deliberately does *not*
raise the enumeration floor of :func:`autocircuit.core.discover.discover`: the small element
counts are under 1% of the filtered topology space, so the saving is seconds, while raising
``exhaustive_min`` clears the completeness guarantee that the exhaustive mode exists to make
(``docs/DISCOVERY_V2_PLAN.md`` section 3.4). A DRT that miscounts a broadened peak must not be
able to delete the right answer from a search that still calls itself exhaustive.

Two choices worth knowing about before changing anything here:

* **The unconstrained solution picks the regularisation; the reported solution is
  non-negative.** Generalised cross-validation is derived for a *linear* estimator, and
  non-negative least squares is not one, so lambda is selected on the unconstrained problem
  where GCV actually means something and the final gamma is then recomputed under
  ``gamma >= 0``. Negative relaxation strengths are unphysical, and letting the inversion
  oscillate through zero invents peaks that are not there -- which is the one failure mode
  that matters for a peak *count*.
* **Broadening is measured against this inversion, not against a delta.** A regularised
  inversion smears even a perfect Debye peak, by an amount that depends on lambda, on the grid
  and on where in the window the peak sits. So the reference width for each peak is obtained
  by inverting a synthetic ideal Debye at that same tau through the same machinery. Comparing
  against a textbook zero width would call every peak broadened.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.linalg import solve_triangular
from scipy.optimize import nnls
from scipy.signal import find_peaks

from .enumerate import EndpointBehaviour
from .fit import Weighting, weight_vectors
from .spectrum import Spectrum
from .wire import encode_array, encode_complex_array, encode_float

Float = NDArray[np.float64]
Complex = NDArray[np.complex128]

#: Version of :meth:`DRTResult.to_wire`; see :data:`autocircuit.core.fit.WIRE_VERSION`.
WIRE_VERSION = 1

#: Grid density for the log-tau axis. Ten per decade resolves peaks a decade apart without
#: making the null space any larger than the regulariser can control.
DEFAULT_POINTS_PER_DECADE = 10

#: How far the tau grid runs beyond the measured ``1/omega`` range, in decades at each end.
#: The plan asked for twice the measured range; that was reduced deliberately. Time constants
#: far outside the window are unidentifiable, and the smoothness prior fills the resulting
#: null space with ramps that peak-pick as relaxations the data never showed. One decade is
#: enough to keep a peak sitting on the edge from being clipped.
DEFAULT_EXTENSION_DECADES = 1.0

#: Search grid for the regularisation strength, in units where 1.0 makes the penalty term
#: comparable in norm to the data term (see :func:`_normalised_lambda`). Keeping the grid
#: dimensionless is what lets one range serve spectra measured in milliohms and in megohms.
LAMBDA_GRID = np.logspace(-8.0, 2.0, 41)

#: Relative residual below which data counts as exact, so that wanting no regularisation at
#: all is a statement about the data rather than a symptom of the GCV breakdown described in
#: :func:`_select_lambda`.
EXACT_RESIDUAL = 1e-3

#: A peak must rise this fraction of **its own height** above its surroundings to be counted.
#: [measured] Prominence relative to the *tallest* peak -- the obvious rule, and the first one
#: tried -- fails the use case this module was built for: in the two-block Maxwell-Wagner
#: reference one block carries 1e4 ohm against the other's 5e5, so the smaller relaxation sits
#: at 2% of the tallest peak and any threshold high enough to reject regularisation ripple also
#: rejects the block. Relative prominence separates the two properly instead: a well-separated
#: relaxation returns to near zero on both sides, so its prominence is nearly its whole height
#: however small that height is, while a ripple on the flank of a big peak has prominence far
#: below its own height. Scale-free, and it does not care how uneven the blocks are.
DEFAULT_PROMINENCE = 0.5

#: ...and a detection threshold, because relative prominence alone counts every ripple the
#: inversion leaves behind. A relaxation is real when it moves the impedance by more than the
#: noise does: its weight, against ``|Z|`` at its own characteristic frequency, must exceed
#: this multiple of the RMS residual.
#:
#: [measured] This is the only test found that separates the two cases that matter, because
#: they overlap on every cruder measure. The smaller block of the Maxwell-Wagner reference
#: carries 2.0% of the total polarisation and the spurious ripples on a depressed semicircle
#: carry 0.6-3.0%, so no threshold on weight can tell them apart. In units of the noise they
#: are not close: the real block changes |Z| at its own frequency by 140 times the RMS
#: residual, the ripples by 0.6 times.
#:
#: [measured] The value is 8 because that is where the sweep stops improving. Counting one,
#: two and three Debye relaxations at 1% noise is 10/10 for every threshold from 2 upwards,
#: but two blocks a single decade apart, and two blocks of 50:1 uneven weight, are 9/10 until
#: the threshold reaches 5 and 8 respectively -- the missing seeds are *over*-counts, ripples
#: passing as relaxations. Nothing is lost on the other side: a weak block is still found
#: 10/10 down to a 100:1 weight ratio at every threshold tried. Only past that, where the
#: block moves the impedance by less than the noise does, does detection fall off, and there
#: a "detection" is not one.
DEFAULT_SIGNIFICANCE = 8.0

#: Residual above which the data is not a sum of relaxations at all and the peaks mean nothing.
#: [measured] Good inversions of 1% -noise data measure 2.6-3.4%; the capacitor reference, whose
#: skin-effect term is a distributed *inductive* process that no sum of RC relaxations can
#: carry, measures 64%. The limit sits in the wide gap between those, and what matters is that
#: the failure is reported rather than dressed up as a relaxation count of zero.
REPRESENTATION_LIMIT = 0.10

#: A peak is called broadened when it is this many times wider than this same inversion makes
#: an ideal Debye peak at the same position.
BROADENING_FACTOR = 1.5


@dataclass(frozen=True)
class Peak:
    """One relaxation read off the distribution."""

    tau: float
    """Time constant at the peak, in seconds."""
    f_peak: float
    """The frequency it shows up at, ``1 / (2 pi tau)`` in Hz."""
    weight: float
    """Polarisation resistance under the peak, in ohms."""
    fwhm_decades: float
    """Full width at half maximum, in decades of tau."""
    ideal_fwhm_decades: float
    """What this inversion does to a perfect Debye peak at the same tau."""
    broadened: bool
    """``fwhm_decades`` exceeds ``ideal_fwhm_decades`` by :data:`BROADENING_FACTOR`, which
    suggests a distributed process -- CPE or a Cole-Cole element rather than a plain C."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tau_s": self.tau,
            "f_peak_hz": self.f_peak,
            "weight_ohm": self.weight,
            "fwhm_decades": self.fwhm_decades,
            "ideal_fwhm_decades": self.ideal_fwhm_decades,
            "broadened": self.broadened,
        }


@dataclass(frozen=True)
class DRTResult:
    """A regularised distribution of relaxation times and what can be read from it."""

    omega: Float
    """Angular frequencies of the data, rad/s -- the axis the residuals belong to."""
    tau: Float
    """The fixed log-spaced grid of time constants, seconds."""
    gamma: Float
    """Relaxation strength at each grid point, in ohms. This is a *discrete* distribution --
    the resistance assigned to each grid point, so ``sum(gamma)`` is the total polarisation
    resistance and individual values scale with ``points_per_decade``."""
    peaks: tuple[Peak, ...]
    r_inf: float
    """Series resistance, ohms."""
    inductance: float
    """Series inductance, henries; 0.0 when the term was not included."""
    capacitance: float
    """Series capacitance, farads; ``inf`` when the term was not included."""
    lam: float
    """The regularisation strength actually used, in the dimensionless units of
    :data:`LAMBDA_GRID`."""
    lam_rule: str
    """How it was chosen: ``"gcv"``, ``"l-curve"`` or ``"fixed"``."""
    z_fit: Complex
    residual_real: Float
    """``(Re Z - Re Z_fit) / |Z|``, per frequency point."""
    residual_imag: Float
    max_residual: float
    rms_residual: float

    @property
    def n_relaxations(self) -> int:
        """How many distinct relaxations the spectrum shows.

        Only meaningful when :attr:`well_described` is True.
        """
        return len(self.peaks)

    @property
    def r_polarisation(self) -> float:
        """Total polarisation resistance, the area under the whole distribution."""
        return float(np.sum(self.gamma))

    @property
    def well_described(self) -> bool:
        """Whether a sum of relaxations can represent this spectrum at all.

        DRT models the data as ``R + jwL + 1/(jwC)`` plus *capacitive* RC relaxations. A
        distributed inductive process -- skin effect, say -- is outside that model, and the
        inversion answers anyway: it returns some distribution, with no peaks in it and a
        badly wrong series resistance. The residual is what gives it away.
        """
        return self.max_residual <= REPRESENTATION_LIMIT

    def hints(self) -> list[str]:
        """Plain-English structural advice, for the discovery report.

        Deliberately phrased as suggestions. Everything here is read off a regularised
        inversion of noisy data, and none of it constrains the search.
        """
        if not self.well_described:
            return [
                f"DRT cannot represent this spectrum (residual up to {self.max_residual:.1%}),"
                " so it says nothing about it.",
                "  A sum of RC relaxations cannot carry a distributed inductive process such"
                " as skin effect, nor data that is not relaxation-like at all.",
            ]
        lines = [
            f"DRT shows {self.n_relaxations} relaxation"
            f"{'' if self.n_relaxations == 1 else 's'}"
            f" (total polarisation {self.r_polarisation:.4g} ohm)."
        ]
        for peak in self.peaks:
            shape = "broadened" if peak.broadened else "near-ideal"
            lines.append(
                f"  tau = {peak.tau:.3g} s ({peak.f_peak:.4g} Hz), {peak.weight:.4g} ohm,"
                f" {peak.fwhm_decades:.2f} decades wide -- {shape}"
            )
        if any(peak.broadened for peak in self.peaks):
            lines.append(
                "  A broadened peak is a distributed process: try CPE or Cole-Cole in place"
                " of C for that block."
            )
        for text in self._series_hints():
            lines.append(text)
        return lines

    def _series_hints(self) -> list[str]:
        """The series terms, reported only where they are above the noise.

        The fit always assigns *something* to every column it was given, and a term worth a
        few ohms on a half-megohm spectrum is a rounding error being presented as a component.
        Each term is therefore judged by how much it moves the impedance where it matters most
        -- a series resistance at the smallest |Z|, an inductance at the top of the sweep, a
        capacitance at the bottom -- against the residual the fit already leaves there.
        """
        magnitude = np.abs(self.z_fit)
        if magnitude.size == 0 or self.rms_residual <= 0.0:
            return []
        lines: list[str] = []
        if self.r_inf > self.rms_residual * float(np.min(magnitude)):
            lines.append(f"  Series resistance about {self.r_inf:.4g} ohm.")
        top = float(self.omega[-1])
        if self.inductance * top > self.rms_residual * float(magnitude[-1]):
            lines.append(f"  Series inductance about {self.inductance:.4g} H.")
        bottom = float(self.omega[0])
        if (
            math.isfinite(self.capacitance)
            and 1.0 / (bottom * self.capacitance) > self.rms_residual * float(magnitude[0])
        ):
            lines.append(f"  Series capacitance about {self.capacitance:.4g} F (blocking).")
        return lines

    def summary(self) -> str:
        header = [
            "Distribution of relaxation times",
            f"  Relaxations   : {self.n_relaxations if self.well_described else '-'}",
            f"  Regularisation: {self.lam:.3g} (chosen by {self.lam_rule})",
            f"  Max residual  : {self.max_residual:.4%}",
            f"  RMS residual  : {self.rms_residual:.4%}",
        ]
        return "\n".join([*header, *self.hints()])

    def to_wire(self) -> dict[str, Any]:
        """JSON-safe form of this probe, for a browser thread that has to draw it.

        Not :meth:`to_dict` with a different name. That one is the CLI's ``--json`` file and it
        writes bare floats, one of which is routinely infinite -- ``capacitance`` is ``inf``
        whenever the blocking term was not included, and a payload carrying it cannot be
        serialised with ``allow_nan=False`` and could not be parsed by JavaScript if it were
        (``core/wire.py``). There is no ``from_wire``: the far side plots this and prints
        :meth:`hints`, which travel with the numbers so that the browser shows the sentences the
        command line shows rather than writing its own account of a distribution.
        """
        return {
            "version": WIRE_VERSION,
            "n_relaxations": self.n_relaxations,
            "well_described": self.well_described,
            "r_inf": encode_float(self.r_inf),
            "r_polarisation": encode_float(self.r_polarisation),
            "inductance": encode_float(self.inductance),
            "capacitance": encode_float(self.capacitance),
            "lam": encode_float(self.lam),
            "lam_rule": self.lam_rule,
            "max_residual": encode_float(self.max_residual),
            "rms_residual": encode_float(self.rms_residual),
            "tau": encode_array(self.tau),
            "gamma": encode_array(self.gamma),
            "peaks": [
                {
                    "tau": encode_float(peak.tau),
                    "f_peak": encode_float(peak.f_peak),
                    "weight": encode_float(peak.weight),
                    "fwhm_decades": encode_float(peak.fwhm_decades),
                    "ideal_fwhm_decades": encode_float(peak.ideal_fwhm_decades),
                    "broadened": peak.broadened,
                }
                for peak in self.peaks
            ],
            "z_fit": encode_complex_array(self.z_fit),
            "residual_real": encode_array(self.residual_real),
            "residual_imag": encode_array(self.residual_imag),
            "hints": self.hints(),
            "summary": self.summary(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_relaxations": self.n_relaxations,
            "well_described": self.well_described,
            "r_inf_ohm": self.r_inf,
            "r_polarisation_ohm": self.r_polarisation,
            "inductance_h": self.inductance,
            "capacitance_f": self.capacitance,
            "lambda": self.lam,
            "lambda_rule": self.lam_rule,
            "max_residual": self.max_residual,
            "rms_residual": self.rms_residual,
            "peaks": [peak.to_dict() for peak in self.peaks],
            "tau_s": self.tau.tolist(),
            "gamma_ohm": self.gamma.tolist(),
        }


def drt(
    spectrum: Spectrum,
    *,
    points_per_decade: int = DEFAULT_POINTS_PER_DECADE,
    extension_decades: float = DEFAULT_EXTENSION_DECADES,
    series_inductance: bool | None = None,
    series_capacitance: bool | None = None,
    weighting: Weighting = "modulus",
    lam: float | None = None,
    prominence: float = DEFAULT_PROMINENCE,
    significance: float = DEFAULT_SIGNIFICANCE,
) -> DRTResult:
    """Invert a spectrum into a distribution of relaxation times.

    Args:
        spectrum: The measured data.
        points_per_decade: Density of the log-spaced tau grid.
        extension_decades: How far the grid runs past the measured window at each end.
        series_inductance: Include a ``jwL`` term. ``None`` decides from the high-frequency
            slope of the data, which is what tells you whether there is one.
        series_capacitance: Include a ``1/(jwC)`` term, needed for blocking data. ``None``
            decides from the low-frequency slope.
        weighting: Residual weighting, as in :func:`autocircuit.core.fit.weight_vectors`.
        lam: Fix the regularisation strength instead of selecting it. Dimensionless, in the
            units of :data:`LAMBDA_GRID`.
        prominence: Peak prominence threshold, as a fraction of each peak's own height.
        significance: How far a peak must stand above the noise to be counted, in multiples
            of the RMS residual (see :data:`DEFAULT_SIGNIFICANCE`).

    Returns:
        A :class:`DRTResult`. Its ``peaks`` and ``n_relaxations`` are advisory: they describe
        a regularised inversion of noisy data, and no part of the fitting or discovery
        machinery is allowed to treat them as constraints. Check ``well_described`` first --
        a spectrum the Debye model cannot represent still produces peaks, and they are
        meaningless.
    """
    omega = spectrum.omega
    z = spectrum.z
    w_re, w_im = weight_vectors(z, weighting)

    add_l, add_c = _series_terms(spectrum, series_inductance, series_capacitance)
    tau = _tau_grid(omega, points_per_decade, extension_decades)

    design = _design_matrix(omega, tau, add_l, add_c)
    a, b, scale = _weighted_system(design, z, w_re, w_im)
    penalty = _penalty_matrix(tau.size, a.shape[1], scale)

    if lam is None:
        chosen, rule = _select_lambda(a, b, penalty)
    else:
        chosen, rule = float(lam), "fixed"

    coefficients = _solve_nonnegative(a, b, penalty, chosen, scale)
    z_fit = design @ coefficients.astype(np.complex128)

    n_series = design.shape[1] - tau.size
    gamma = coefficients[n_series:]
    r_inf = float(coefficients[0])
    inductance = float(coefficients[1]) if add_l else 0.0
    inverse_c = float(coefficients[1 + int(add_l)]) if add_c else 0.0
    capacitance = 1.0 / inverse_c if inverse_c > 0.0 else math.inf

    magnitude = np.abs(z)
    residual_real = (z.real - z_fit.real) / magnitude
    residual_imag = (z.imag - z_fit.imag) / magnitude
    stacked = np.concatenate([residual_real, residual_imag])
    rms_residual = float(np.sqrt(np.mean(stacked**2)))

    peaks = _find_peaks(
        tau,
        gamma,
        prominence,
        significance,
        noise=lambda t: rms_residual * _magnitude_at(omega, magnitude, t),
        reference=lambda t: _ideal_fwhm(t, omega, tau, add_l, add_c, chosen, weighting),
    )

    return DRTResult(
        omega=omega,
        tau=tau,
        gamma=gamma,
        peaks=peaks,
        r_inf=r_inf,
        inductance=inductance,
        capacitance=capacitance,
        lam=chosen,
        lam_rule=rule,
        z_fit=z_fit,
        residual_real=residual_real,
        residual_imag=residual_imag,
        max_residual=float(np.max(np.abs(stacked))),
        rms_residual=rms_residual,
    )


def _magnitude_at(omega: Float, magnitude: Float, tau_peak: float) -> float:
    """``|Z|`` at the frequency a relaxation of ``tau_peak`` shows up at.

    Log-log interpolation, clamped at the ends of the measured range -- which is deliberate:
    a peak whose time constant lies outside the window is judged against the nearest frequency
    that was actually measured, since nothing beyond it was.
    """
    if omega.size == 0:
        return 1.0
    return float(
        10.0 ** np.interp(math.log10(1.0 / tau_peak), np.log10(omega), np.log10(magnitude))
    )


# =================================================================================================
# Building the linear system
# =================================================================================================


def _series_terms(
    spectrum: Spectrum, series_inductance: bool | None, series_capacitance: bool | None
) -> tuple[bool, bool]:
    """Decide which series terms the model needs, from the endpoint slopes of the data.

    A free ``jwL`` on data that is not inductive, or a free ``1/(jwC)`` on data that does not
    block, is a column the fit can only use to chase noise -- and in the capacitive case one
    that can quietly absorb a genuine low-frequency relaxation, which is exactly the thing
    being counted. So both are switched on by evidence rather than by default. The same
    endpoint measurement drives the feasibility filter, so the two agree by construction.
    """
    if series_inductance is not None and series_capacitance is not None:
        return series_inductance, series_capacitance
    behaviour = EndpointBehaviour.from_spectrum(spectrum)
    add_l = (
        series_inductance
        if series_inductance is not None
        else not math.isfinite(behaviour.high_slope) or behaviour.high_slope > 0.2
    )
    add_c = (
        series_capacitance
        if series_capacitance is not None
        else math.isfinite(behaviour.low_slope) and behaviour.low_slope < -0.5
    )
    return bool(add_l), bool(add_c)


def _tau_grid(omega: Float, points_per_decade: int, extension_decades: float) -> Float:
    """Log-spaced time constants spanning the measured window plus a margin at each end."""
    lo = math.log10(1.0 / float(omega.max())) - extension_decades
    hi = math.log10(1.0 / float(omega.min())) + extension_decades
    count = max(int(round((hi - lo) * points_per_decade)) + 1, 3)
    return np.logspace(lo, hi, count)


def _design_matrix(omega: Float, tau: Float, add_l: bool, add_c: bool) -> Complex:
    """Columns of the linear DRT model: series terms first, then one Debye term per tau."""
    columns: list[Complex] = [np.ones_like(omega, dtype=np.complex128)]
    if add_l:
        columns.append(np.asarray(1j * omega, dtype=np.complex128))
    if add_c:
        columns.append(np.asarray(1.0 / (1j * omega), dtype=np.complex128))
    columns.extend(1.0 / (1.0 + 1j * omega * t) for t in tau)
    return np.stack(columns, axis=1)


def _weighted_system(
    design: Complex, z: Complex, w_re: Float, w_im: Float
) -> tuple[Float, Float, Float]:
    """Stack real and imaginary parts into one weighted real system, with unit-norm columns.

    Returns ``(a, b, scale)`` where ``a`` has unit-norm columns and the unknowns of ``a`` are
    the physical ones multiplied by ``scale``. Without the scaling the system is hopeless in
    the same way the Lin-KK one was: the ``1/(jwC)`` column runs as ``1/w`` and the ``jwL``
    column as ``w``, so over eight decades they differ by sixteen orders of magnitude and
    ``lstsq`` truncates the answer into nonsense.
    """
    a = np.vstack([design.real * w_re[:, None], design.imag * w_im[:, None]])
    b = np.concatenate([z.real * w_re, z.imag * w_im])
    scale = np.linalg.norm(a, axis=0)
    scale[scale == 0.0] = 1.0
    return a / scale, b, scale


def _penalty_matrix(n_tau: int, n_columns: int, scale: Float) -> Float:
    """Second difference of gamma along log tau, expressed in the scaled unknowns.

    The smoothness prior is on the *physical* gamma, so the operator is divided by the same
    column scaling the design matrix was: ``penalty @ scaled_x`` equals ``D @ physical_x``
    exactly, and the conditioning fix costs nothing in meaning. The series terms are not
    penalised -- a series resistance is not part of the distribution.
    """
    n_series = n_columns - n_tau
    rows = max(n_tau - 2, 0)
    d = np.zeros((rows, n_columns))
    for i in range(rows):
        d[i, n_series + i] = 1.0
        d[i, n_series + i + 1] = -2.0
        d[i, n_series + i + 2] = 1.0
    return d / scale


def _normalised_lambda(a: Float, penalty: Float, lam: float) -> float:
    """Turn a dimensionless lambda into the multiplier the augmented system wants.

    ``lam = 1`` is defined as "penalty block of the same Frobenius norm as the data block",
    which makes one search grid work for spectra of any impedance scale.
    """
    norm_a = float(np.linalg.norm(a))
    norm_d = float(np.linalg.norm(penalty))
    if norm_d == 0.0:
        return 0.0
    return lam * (norm_a / norm_d) ** 2


def _augmented(a: Float, b: Float, penalty: Float, lam: float) -> tuple[Float, Float]:
    """The Tikhonov problem written as one ordinary least-squares problem."""
    multiplier = _normalised_lambda(a, penalty, lam)
    stacked = np.vstack([a, math.sqrt(multiplier) * penalty])
    target = np.concatenate([b, np.zeros(penalty.shape[0])])
    return stacked, target


# =================================================================================================
# Choosing the regularisation strength
# =================================================================================================


def _select_lambda(a: Float, b: Float, penalty: Float) -> tuple[float, str]:
    """Generalized cross-validation over :data:`LAMBDA_GRID`, with an L-curve fallback.

    GCV is the principled choice and it is cheap here, but it has one well-known failure: on
    correlated noise it slides towards lambda = 0, and an unregularised DRT is mostly
    oscillation -- which fragments a single broad relaxation into a row of spikes and makes
    the peak *count* wrong. The fallback rule has to separate that failure from the case where
    lambda = 0 is simply correct.

    [measured] The two are easy to tell apart by how well the model then fits. On noise-free
    synthetic data GCV goes to the bottom of the grid and the fit is exact to 0.03%, with the
    relaxations landing as single grid spikes and the count still right; at 1% noise it settles
    in the interior of the grid on its own. So a bottom-of-grid minimum is believed only when
    the residual there says the data really is that clean. A top-of-grid minimum is never
    believed: that is a criterion that never turned over.

    An earlier version rejected *both* edges, and paid for it by over-smoothing noise-free data
    to a 5.5% residual through the L-curve -- which has no corner to find when there is no
    noise to trade against.
    """
    scores: list[float] = []
    relative: list[float] = []
    rho: list[float] = []
    eta: list[float] = []
    norm_b = float(np.linalg.norm(b)) or 1.0
    for lam in LAMBDA_GRID:
        stacked, target = _augmented(a, b, penalty, float(lam))
        _, residual, smoothness, trace = _linear_solve(stacked, target, a, b, penalty)
        n = b.size
        denominator = n - trace
        scores.append(n * residual**2 / denominator**2 if denominator > 0.0 else math.inf)
        relative.append(residual / norm_b)
        rho.append(math.log10(max(residual, 1e-300)))
        eta.append(math.log10(max(smoothness, 1e-300)))

    best = int(np.argmin(scores))
    believable = (
        math.isfinite(scores[best])
        and best < len(LAMBDA_GRID) - 1
        and (best > 0 or relative[0] <= EXACT_RESIDUAL)
    )
    if believable:
        return float(LAMBDA_GRID[best]), "gcv"
    return float(LAMBDA_GRID[_l_curve_corner(rho, eta)]), "l-curve"


def _linear_solve(
    stacked: Float, target: Float, a: Float, b: Float, penalty: Float
) -> tuple[Float, float, float, float]:
    """Solve one augmented system and report what the selection criteria need.

    Returns ``(x, ||a x - b||, ||penalty x||, trace of the hat matrix)``. The trace comes from
    the QR factor of the augmented matrix -- ``tr H = || a R^-1 ||_F^2`` -- which avoids ever
    forming the normal equations and squaring the condition number.
    """
    q, r = np.linalg.qr(stacked)
    x = solve_triangular(r, q.T @ target, lower=False, check_finite=False)
    residual = float(np.linalg.norm(a @ x - b))
    smoothness = float(np.linalg.norm(penalty @ x))
    projected = solve_triangular(r, a.T, trans="T", lower=False, check_finite=False)
    return x, residual, smoothness, float(np.sum(projected**2))


def _l_curve_corner(rho: list[float], eta: list[float]) -> int:
    """Index of maximum curvature of the (log residual, log smoothness) trade-off curve.

    The corner is where buying a little more smoothness starts costing a lot of fit. Curvature
    is taken from plain finite differences: the grid is uniform in log lambda and only the
    location of the maximum is wanted, so a spline would add machinery without adding an
    answer.
    """
    x = np.asarray(rho)
    y = np.asarray(eta)
    if x.size < 5:
        return x.size // 2
    dx, dy = np.gradient(x), np.gradient(y)
    ddx, ddy = np.gradient(dx), np.gradient(dy)
    denominator = (dx**2 + dy**2) ** 1.5
    with np.errstate(divide="ignore", invalid="ignore"):
        curvature = np.abs(dx * ddy - dy * ddx) / denominator
    curvature[~np.isfinite(curvature)] = 0.0
    # The endpoints of a finite-difference curvature are unreliable, and a corner never sits
    # there anyway -- the curve is straight at both extremes of lambda by construction.
    curvature[:2] = 0.0
    curvature[-2:] = 0.0
    return int(np.argmax(curvature))


def _solve_nonnegative(
    a: Float, b: Float, penalty: Float, lam: float, scale: Float
) -> Float:
    """The reported solution: the same Tikhonov problem, under ``x >= 0``.

    Every coefficient here is a resistance, an inductance or an inverse capacitance, so all of
    them are non-negative in any passive network. Enforcing that is what keeps the inversion
    from oscillating through zero and inventing peaks -- the one failure mode that would make
    a relaxation *count* wrong. If NNLS cannot converge the unconstrained solution is returned
    rather than nothing, clipped at zero.
    """
    stacked, target = _augmented(a, b, penalty, lam)
    try:
        scaled, _ = nnls(stacked, target, maxiter=50 * stacked.shape[1])
    except (RuntimeError, ValueError):
        scaled = np.clip(np.linalg.lstsq(stacked, target, rcond=None)[0], 0.0, None)
    return scaled / scale


# =================================================================================================
# Reading the distribution
# =================================================================================================


def _find_peaks(
    tau: Float,
    gamma: Float,
    prominence: float,
    significance: float,
    noise: Callable[[float], float],
    reference: Callable[[float], float],
) -> tuple[Peak, ...]:
    """Peak picking on the distribution: relative prominence, then detectability.

    See :data:`DEFAULT_PROMINENCE` for why the prominence test is against each peak's own
    height rather than against the tallest peak, and :data:`DEFAULT_SIGNIFICANCE` for why a
    second test against the noise is needed on top of it.
    """
    if gamma.size < 3 or not np.any(gamma > 0.0):
        return ()
    indices, properties = find_peaks(gamma, prominence=0.0)
    log_tau = np.log10(tau)

    peaks: list[Peak] = []
    for position, left, right, rise in zip(
        indices,
        properties["left_bases"],
        properties["right_bases"],
        properties["prominences"],
        strict=True,
    ):
        height = float(gamma[position])
        weight = float(np.sum(gamma[int(left) : int(right) + 1]))
        if height <= 0.0 or rise < prominence * height:
            continue
        if weight < significance * noise(float(tau[position])):
            continue
        width = _fwhm(log_tau, gamma, int(position))
        ideal = reference(float(tau[position]))
        peaks.append(
            Peak(
                tau=float(tau[position]),
                f_peak=1.0 / (2.0 * math.pi * float(tau[position])),
                weight=weight,
                fwhm_decades=width,
                ideal_fwhm_decades=ideal,
                broadened=bool(ideal > 0.0 and width > ideal * BROADENING_FACTOR),
            )
        )
    return tuple(peaks)


def _fwhm(log_tau: Float, gamma: Float, position: int) -> float:
    """Full width at half maximum around one peak, in decades, by linear interpolation."""
    half = gamma[position] / 2.0
    left = _crossing(log_tau, gamma, position, half, step=-1)
    right = _crossing(log_tau, gamma, position, half, step=+1)
    return float(right - left)


def _crossing(log_tau: Float, gamma: Float, position: int, level: float, step: int) -> float:
    """Where the curve drops through ``level`` walking away from ``position``.

    A peak that runs off the end of the grid without ever dropping to half height is reported
    at the grid edge; it is wider than the window can show, which the caller sees as a large
    width rather than as a missing value.
    """
    i = position
    while 0 <= i + step < gamma.size and gamma[i + step] > level:
        i += step
    j = i + step
    if not (0 <= j < gamma.size):
        return float(log_tau[i])
    span = gamma[i] - gamma[j]
    if span <= 0.0:
        return float(log_tau[j])
    fraction = (gamma[i] - level) / span
    return float(log_tau[i] + fraction * (log_tau[j] - log_tau[i]))


def _ideal_fwhm(
    tau_peak: float,
    omega: Float,
    tau: Float,
    add_l: bool,
    add_c: bool,
    lam: float,
    weighting: Weighting,
) -> float:
    """Width this same inversion gives a perfect Debye relaxation at ``tau_peak``.

    Noise-free, unit strength, same frequencies, same grid, same lambda. Anything wider than
    this in the real distribution is broadening the *data* carries, not broadening the method
    added -- which is the only version of the question that has an answer.
    """
    z: Complex = np.asarray(1.0 / (1.0 + 1j * omega * tau_peak), dtype=np.complex128)
    w_re, w_im = weight_vectors(z, weighting)
    design = _design_matrix(omega, tau, add_l, add_c)
    a, b, scale = _weighted_system(design, z, w_re, w_im)
    penalty = _penalty_matrix(tau.size, a.shape[1], scale)
    coefficients = _solve_nonnegative(a, b, penalty, lam, scale)
    gamma = coefficients[design.shape[1] - tau.size :]
    if not np.any(gamma > 0.0):
        return 0.0
    return _fwhm(np.log10(tau), gamma, int(np.argmax(gamma)))
