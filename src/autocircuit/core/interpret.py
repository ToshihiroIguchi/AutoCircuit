"""Reading a fitted circuit as internal structure, in the only terms the input supports.

The pipeline up to here ends at a topology and parameter values with units. This module is the
step after: turning those into the quantities somebody actually wanted -- how many relaxations
there are, how fast each one is, how much of the polarisation it carries, what the ESR and the
self-resonance are.

**Everything here is geometry-free, and that is a decision rather than a limitation to be
lifted later.** ``Z(f)`` fixes a capacitance; it cannot fix a permittivity, because the two
differ by ``A/d``, a factor the spectrum does not contain. So no permittivity, no conductivity,
no diffusion coefficient and no layer thickness appears below. What *does* survive is larger
than it first looks -- note ``D/L**2``, which comes straight out of a finite-length Warburg's
own time constant: the ratio is measurable where the coefficient is not.

The organising idea is the split every quantity here carries as :attr:`Quantity.invariant`.

An exact reparameterisation -- ``R1-p(R2,C1)`` and ``p(R1,C1-R2)`` fit the same data to 1.2e-15
(``docs/HANDOFF.md`` section 3) -- is two names for one ``Z``. So:

* anything computed **from Z** is the same for every member of the equivalence class: terminal
  resistances, the self-resonant frequency, tan delta, and the poles and zeros of ``Z(s)``.
* anything computed **from a block of the tree** is not. "The R times the C of this parallel
  pair" depends on which member the search happened to report, and two members disagree.

The consequence worth stating, because it is the one that gets guessed wrong: *characteristic
time constants themselves are invariant*, since identical ``Z`` means identical poles. What is
form-dependent is the habit of reading them off as ``R*C`` of a block. When the circuit is
R/L/C only, :func:`modes_of` therefore gives time constants that every member of the class
agrees on; when a CPE or a Warburg makes ``Z`` non-rational there are no poles in the ordinary
sense, and the form-independent answer is the DRT, which is computed from the data and never
from the circuit (:mod:`autocircuit.core.drt`).

Uncertainties are propagated by the delta method in **log parameter space**, which is where the
covariance was computed in the first place (``docs/HANDOFF.md`` section 3). For a pure power
product such as ``tau = R*C`` that is exact; for anything else it is the usual first-order
approximation; for the poles it is not attempted at all, because root ordering is not a smooth
function of the parameters.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from numpy.typing import NDArray

from .circuit import Circuit, ElementNode, Node, Parallel, Series
from .spectrum import Spectrum

if TYPE_CHECKING:  # importing fit at runtime would pull scipy in for callers that never fit
    from .fit import FitResult

Float = NDArray[np.float64]
Complex = NDArray[np.complex128]

#: Points per decade used when the model is resampled to find a crossing or a minimum.
GRID_PER_DECADE = 200

#: Relative step used for the log-space finite differences behind every standard error.
DELTA_STEP = 1e-4

#: How far past the measured band a DC or infinite-frequency limit is chased, in decades.
LIMIT_DECADES = 6

#: Relative agreement between the last two decades required before a limit is called converged.
LIMIT_RTOL = 1e-3

#: Poles and zeros closer together than this (relative) are treated as a cancelling pair.
CANCEL_RTOL = 1e-6

#: A limit below this fraction of the *smallest* measured ``|Z|`` is reported as exactly zero.
#: The reference is the smallest and not the largest for a reason: a capacitor's ESR can be
#: 0.01 ohm against a 5000 ohm spectrum, so a threshold taken from the top of the range would
#: erase a real number. What this catches is the other case -- a network that is a short at one
#: end comes back as 5e-13 ohm, and printing that with a standard error beside it dresses a
#: rounding artefact up as a measurement.
NEGLIGIBLE_FRACTION = 1e-6

#: How capacitive the response must be before an apparent capacitance or a loss tangent is
#: reported at that frequency: ``-Im Z`` must exceed ``Re Z``, i.e. the phase must be past -45
#: degrees. Without this both quantities are still *defined* where the part is resistive and
#: both are meaningless there -- a plain R-p(R,C) reads 15.9 F and tan delta 11 at 1 Hz, which
#: is arithmetic rather than a measurement of a capacitor.
CAPACITIVE_PHASE_RATIO = 1.0

#: Effective-capacitance convention used for an R-CPE block. Named because it is a choice.
CPE_CAPACITANCE_NOTE = (
    "Hsu-Mansfeld form, which assumes a distribution of time constants; the Brug form assumes"
    " a surface distribution instead and gives a different number. The spectrum does not say"
    " which applies"
)


# -- Result types --------------------------------------------------------------------------


@dataclass(frozen=True)
class Quantity:
    """One derived number, with the two things a reader needs in order to judge it.

    ``invariant`` is the important field. True means every topology in this result's
    equivalence class gives the same value, so the number is a property of the measurement.
    False means the number describes *the form that was reported*, and a different member of
    the class -- fitting the data exactly as well -- would give a different one.
    """

    name: str
    value: float
    unit: str
    invariant: bool
    stderr: float | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "invariant": self.invariant,
        }
        if self.stderr is not None:
            out["stderr"] = self.stderr
        if self.note is not None:
            out["note"] = self.note
        return out


@dataclass(frozen=True)
class Mode:
    """A pole or zero of ``Z(s)`` -- invariant across the equivalence class.

    A real root is reported as a time constant; a complex pair as a resonant frequency and a
    quality factor, with only one member of the conjugate pair appearing.
    """

    kind: Literal["pole", "zero"]
    tau: float | None = None
    f0: float | None = None
    q: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "tau_s": self.tau, "f0_hz": self.f0, "q": self.q}


@dataclass(frozen=True)
class Relaxation:
    """One ``p(R,C)`` or ``p(R,CPE)`` block of the reported tree -- **form-dependent**."""

    label: str
    resistance: float
    capacitance: float
    tau: float
    f_peak: float
    share: float
    cpe_n: float | None = None
    tau_stderr: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "resistance_ohm": self.resistance,
            "capacitance_f": self.capacitance,
            "tau_s": self.tau,
            "f_peak_hz": self.f_peak,
            "share": self.share,
            "cpe_n": self.cpe_n,
            "tau_stderr_s": self.tau_stderr,
        }


@dataclass(frozen=True)
class Interpretation:
    """What a fitted circuit says is inside the part, split by what survives the class."""

    circuit: str
    quantities: tuple[Quantity, ...] = ()
    modes: tuple[Mode, ...] = ()
    modes_available: bool = False
    relaxations: tuple[Relaxation, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def invariant(self) -> tuple[Quantity, ...]:
        """Quantities every member of the equivalence class agrees on."""
        return tuple(q for q in self.quantities if q.invariant)

    @property
    def form_dependent(self) -> tuple[Quantity, ...]:
        """Quantities that describe the reported form rather than the measurement."""
        return tuple(q for q in self.quantities if not q.invariant)

    def get(self, name: str) -> Quantity | None:
        for q in self.quantities:
            if q.name == name:
                return q
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "circuit": self.circuit,
            "quantities": [q.to_dict() for q in self.quantities],
            "modes": [m.to_dict() for m in self.modes],
            "modes_available": self.modes_available,
            "relaxations": [r.to_dict() for r in self.relaxations],
            "notes": list(self.notes),
        }

    def summary(self) -> str:
        lines = [f"Interpretation of {self.circuit}", ""]
        lines.append("From the spectrum (the same for every equivalent topology):")
        if self.invariant:
            lines.extend(_format_quantity(q) for q in self.invariant)
        else:
            lines.append("  (nothing the measured band determines)")
        if self.modes_available:
            lines.append("")
            lines.append("Characteristic times of Z(s) (also equivalence-class invariant):")
            if self.modes:
                lines.extend(_format_mode(m) for m in self.modes)
            else:
                lines.append("  (none)")
        if self.relaxations or self.form_dependent:
            lines.append("")
            lines.append("From this particular circuit form -- another member of the same")
            lines.append("equivalence class would put different numbers here:")
            for r in self.relaxations:
                pm = "" if r.tau_stderr is None else f" +/- {r.tau_stderr:.3g}"
                cpe = "" if r.cpe_n is None else f", n = {r.cpe_n:.3f}"
                lines.append(
                    f"  {r.label}: tau = {r.tau:.4g}{pm} s (f = {r.f_peak:.4g} Hz), "
                    f"R = {r.resistance:.4g} ohm, C = {r.capacitance:.4g} F{cpe}, "
                    f"{r.share:.1%} of the polarisation"
                )
            lines.extend(_format_quantity(q) for q in self.form_dependent)
        if self.notes:
            lines.append("")
            lines.extend(f"! {note}" for note in self.notes)
        return "\n".join(lines)


def _format_quantity(q: Quantity) -> str:
    pm = "" if q.stderr is None else f" +/- {q.stderr:.3g}"
    unit = "" if q.unit == "-" else f" {q.unit}"
    note = "" if q.note is None else f"   [{q.note}]"
    return f"  {q.name} = {q.value:.6g}{pm}{unit}{note}"


def _format_mode(m: Mode) -> str:
    if m.tau is not None:
        return f"  {m.kind}: tau = {m.tau:.4g} s (f = {1.0 / (2 * math.pi * m.tau):.4g} Hz)"
    assert m.f0 is not None and m.q is not None
    return f"  {m.kind}: resonance at {m.f0:.4g} Hz, Q = {m.q:.3g}"


# -- Poles and zeros of Z(s) ----------------------------------------------------------------
#
# Built as an exact rational function of ``s`` rather than estimated from samples, so the roots
# are the circuit's own and not an artefact of the grid. Only R, L and C give a rational Z; a
# CPE or a Warburg carries a fractional power of ``s`` and has no poles in this sense, which is
# reported as such rather than approximated.

RATIONAL_CODES = frozenset({"R", "C", "L"})


def _poly_add(a: Float, b: Float) -> Float:
    out = np.zeros(max(a.size, b.size), dtype=np.float64)
    out[: a.size] += a
    out[: b.size] += b
    return out


def _poly_mul(a: Float, b: Float) -> Float:
    return np.convolve(a, b)


def _poly_trim(a: Float) -> Float:
    """Drop leading (highest-degree) coefficients that are numerically zero."""
    if a.size == 0:
        return a
    scale = float(np.max(np.abs(a)))
    if scale == 0.0:
        return np.zeros(1, dtype=np.float64)
    keep = a.size
    while keep > 1 and abs(a[keep - 1]) <= 1e-14 * scale:
        keep -= 1
    return a[:keep]


def _normalise(num: Float, den: Float) -> tuple[Float, Float]:
    """Scale numerator and denominator together, which leaves Z and both root sets alone."""
    scale = max(float(np.max(np.abs(num))), float(np.max(np.abs(den))))
    if scale == 0.0 or not math.isfinite(scale):
        return num, den
    return num / scale, den / scale


def _rational(
    node: Node, params: dict[str, Float], w_ref: float, z_ref: float
) -> tuple[Float, Float]:
    """Z(s)/z_ref as a ratio of polynomials in ``s/w_ref``, lowest degree first."""
    if isinstance(node, ElementNode):
        value = float(params[node.label][0])
        if node.code == "R":
            return np.array([value / z_ref]), np.array([1.0])
        if node.code == "L":
            return np.array([0.0, w_ref * value / z_ref]), np.array([1.0])
        if node.code == "C":
            return np.array([1.0]), np.array([0.0, w_ref * value * z_ref])
        raise ValueError(f"{node.code} is not a rational element")

    parts = [_rational(child, params, w_ref, z_ref) for child in node.children]
    num, den = parts[0]
    for other_num, other_den in parts[1:]:
        if isinstance(node, Series):
            num, den = (
                _poly_add(_poly_mul(num, other_den), _poly_mul(other_num, den)),
                _poly_mul(den, other_den),
            )
        else:
            num, den = (
                _poly_mul(num, other_num),
                _poly_add(_poly_mul(num, other_den), _poly_mul(other_num, den)),
            )
        num, den = _normalise(num, den)
    return num, den


def _roots(poly: Float) -> NDArray[np.complex128]:
    trimmed = _poly_trim(poly)
    if trimmed.size <= 1:
        return np.array([], dtype=np.complex128)
    return np.asarray(np.roots(trimmed[::-1]), dtype=np.complex128)


def _cancel(
    zeros: NDArray[np.complex128], poles: NDArray[np.complex128]
) -> tuple[NDArray[np.complex128], NDArray[np.complex128]]:
    """Remove pole-zero pairs that coincide, which is how a redundant element shows up."""
    keep_zero = [True] * zeros.size
    keep_pole = [True] * poles.size
    for i, z in enumerate(zeros):
        for j, p in enumerate(poles):
            if not keep_pole[j]:
                continue
            scale = max(abs(z), abs(p))
            if scale == 0.0 or abs(z - p) <= CANCEL_RTOL * scale:
                keep_zero[i] = False
                keep_pole[j] = False
                break
    return zeros[np.array(keep_zero, dtype=bool)], poles[np.array(keep_pole, dtype=bool)]


def _modes_from_roots(
    roots: NDArray[np.complex128], kind: Literal["pole", "zero"], w_ref: float
) -> tuple[list[Mode], bool]:
    """Turn scaled roots into time constants and resonances; also report any non-decaying one."""
    out: list[Mode] = []
    unstable = False
    for scaled in roots:
        s = complex(scaled) * w_ref
        if abs(s) == 0.0:
            continue
        if abs(s.imag) <= 1e-9 * abs(s):
            if s.real >= 0.0:
                unstable = True
                continue
            out.append(Mode(kind=kind, tau=-1.0 / s.real))
            continue
        if s.imag < 0.0:
            continue  # one member of each conjugate pair
        if s.real >= 0.0:
            unstable = True
            continue
        omega0 = abs(s)
        out.append(Mode(kind=kind, f0=omega0 / (2 * math.pi), q=omega0 / (2 * abs(s.real))))
    out.sort(key=lambda m: m.tau if m.tau is not None else 1.0 / (m.f0 or math.inf))
    return out, unstable


def modes_of(
    circuit: Circuit, values: Float, *, w_ref: float = 1.0, z_ref: float = 1.0
) -> tuple[tuple[Mode, ...], bool, bool]:
    """Poles and zeros of ``Z(s)``: ``(modes, available, unstable)``.

    ``available`` is False when the circuit contains an element that makes ``Z`` non-rational,
    which is a statement about the model rather than a failure -- see the module docstring.
    """
    if any(leaf.code not in RATIONAL_CODES for leaf in circuit.leaves):
        return (), False, False
    params = {
        leaf.label: np.asarray(values[sl], dtype=np.float64)
        for leaf, sl in zip(circuit.leaves, circuit.slices().values(), strict=True)
    }
    num, den = _rational(circuit.root, params, w_ref, z_ref)
    zeros, poles = _cancel(_roots(num), _roots(den))
    pole_modes, unstable_p = _modes_from_roots(poles, "pole", w_ref)
    zero_modes, unstable_z = _modes_from_roots(zeros, "zero", w_ref)
    return tuple(pole_modes + zero_modes), True, unstable_p or unstable_z


# -- Quantities read off Z ------------------------------------------------------------------


def _omega_grid(spectrum: Spectrum) -> Float:
    """Resampled **angular** frequencies spanning the measured band.

    Angular, because that is what every ``impedance()`` in this package takes; the Hz that come
    out of a file are converted once, here and in the callers, and never travel further.
    """
    lo, hi = 2 * math.pi * float(spectrum.f[0]), 2 * math.pi * float(spectrum.f[-1])
    decades = max(math.log10(hi / lo), 1e-6)
    n = max(int(decades * GRID_PER_DECADE), 32)
    return np.logspace(math.log10(lo), math.log10(hi), n)


def _srf(circuit: Circuit, values: Float, omega_grid: Float) -> float | None:
    """Lowest frequency in band where Im Z crosses zero from capacitive to inductive, in Hz."""
    z = circuit.impedance(omega_grid, values)
    im = np.asarray(z.imag, dtype=np.float64)
    if not np.all(np.isfinite(im)):
        return None
    sign = np.sign(im)
    crossings = np.nonzero((sign[:-1] < 0) & (sign[1:] >= 0))[0]
    if crossings.size == 0:
        return None
    i = int(crossings[0])
    y0, y1 = im[i], im[i + 1]
    x0, x1 = math.log10(omega_grid[i]), math.log10(omega_grid[i + 1])
    t = 0.0 if y1 == y0 else -y0 / (y1 - y0)
    return float(10.0 ** (x0 + t * (x1 - x0)) / (2 * math.pi))


def _at(circuit: Circuit, values: Float, omega: float) -> complex:
    return complex(circuit.impedance(np.array([omega]), values)[0])


def _z_min(circuit: Circuit, values: Float, omega_grid: Float) -> float | None:
    mag = np.abs(circuit.impedance(omega_grid, values))
    if not np.all(np.isfinite(mag)):
        return None
    return float(np.min(mag))


def _limit(
    circuit: Circuit, values: Float, edge: float, scale: float, floor: float, low: bool
) -> float | None:
    """Re Z extrapolated past the band, or None when it does not converge to a finite real."""
    decades = np.arange(1, LIMIT_DECADES + 1, dtype=np.float64)
    omegas = 2 * math.pi * edge * (10.0 ** (-decades if low else decades))
    z = circuit.impedance(omegas, values)
    if not np.all(np.isfinite(z)):
        return None
    tail = z[-2:]
    if abs(tail[-1] - tail[-2]) > LIMIT_RTOL * scale:
        return None
    if abs(tail[-1].imag) > LIMIT_RTOL * scale:
        return None
    limit = float(tail[-1].real)
    return 0.0 if abs(limit) < NEGLIGIBLE_FRACTION * floor else limit


# -- Uncertainty ----------------------------------------------------------------------------


def log_covariance(values: Float, stderr: Float | None, correlation: Float | None) -> Float | None:
    """Covariance of ``ln(parameter)``, rebuilt from what a fit reports.

    The fitter computes its covariance in log space and maps it out to parameter units
    (``docs/HANDOFF.md`` section 3); this maps it back, which is the space every derived
    quantity here is a smooth function of.
    """
    if stderr is None or correlation is None:
        return None
    n = values.size
    if stderr.shape != (n,) or correlation.shape != (n, n):
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.asarray(stderr, dtype=np.float64) / np.abs(values)
    if not np.all(np.isfinite(rel)):
        return None
    return np.asarray(correlation, dtype=np.float64) * np.outer(rel, rel)


def _propagate(
    fn: Callable[[Float], float | None], values: Float, cov_ln: Float | None
) -> float | None:
    """Delta method in log parameter space; exact for a power product, first-order otherwise."""
    if cov_ln is None:
        return None
    base = fn(values)
    if base is None or not math.isfinite(base) or base == 0.0:
        return None
    grad = np.zeros(values.size, dtype=np.float64)
    for i in range(values.size):
        if values[i] == 0.0:
            return None
        step = abs(values[i]) * DELTA_STEP
        up, down = values.copy(), values.copy()
        up[i] += step
        down[i] -= step
        f_up, f_down = fn(up), fn(down)
        if f_up is None or f_down is None:
            return None
        if not (math.isfinite(f_up) and math.isfinite(f_down)):
            return None
        grad[i] = ((f_up - f_down) / (2 * step)) * (values[i] / base)
    var = float(grad @ cov_ln @ grad)
    if not math.isfinite(var) or var < 0.0:
        return None
    return abs(base) * math.sqrt(var)


# -- Blocks of the reported tree ------------------------------------------------------------


def _blocks(node: Node) -> list[tuple[ElementNode, ElementNode]]:
    """Every ``p(R,C)`` or ``p(R,CPE)`` pair in the tree, as (resistor, capacitive element).

    Deliberately strict: a parallel node with a third child, or with two resistors, is not a
    relaxation block and is not reported as one. A block this misses simply does not appear,
    which is the safe direction -- the invariant quantities do not depend on any of this.
    """
    out: list[tuple[ElementNode, ElementNode]] = []
    if isinstance(node, ElementNode):
        return out
    if isinstance(node, Parallel) and len(node.children) == 2:
        first, second = node.children
        if isinstance(first, ElementNode) and isinstance(second, ElementNode):
            codes = {first.code, second.code}
            if "R" in codes and (codes & {"C", "CPE"}):
                resistor = first if first.code == "R" else second
                capacitive = second if first.code == "R" else first
                out.append((resistor, capacitive))
    for child in node.children:
        out.extend(_blocks(child))
    return out


def _block_tau(r: float, capacitive_values: Float, code: str) -> tuple[float, float, float | None]:
    """Return ``(tau, effective capacitance, n)`` for one block."""
    if code == "C":
        c = float(capacitive_values[0])
        return r * c, c, None
    q, n = float(capacitive_values[0]), float(capacitive_values[1])
    tau = (r * q) ** (1.0 / n)
    c_eff = (q * r ** (1.0 - n)) ** (1.0 / n)
    return tau, c_eff, n


# -- The entry points -----------------------------------------------------------------------


def interpret_values(
    circuit: Circuit,
    values: Float,
    spectrum: Spectrum,
    *,
    stderr: Float | None = None,
    correlation: Float | None = None,
    drt_peaks: int | None = None,
) -> Interpretation:
    """Read a circuit and its fitted values as internal structure.

    Takes the pieces rather than a :class:`~autocircuit.core.fit.FitResult` so that the
    equivalence-class invariance of the result can be tested on two circuits built by hand --
    which is gate I1, and which would otherwise need two global fits to run.

    ``drt_peaks`` is the number of relaxations the model-free DRT found, if the caller has run
    one. It is used for a cross-check and for nothing else: this module never lets the DRT
    change a number, exactly as the search never lets it change a candidate
    (``docs/DISCOVERY_V2_PLAN.md`` section 3.4).
    """
    values = np.asarray(values, dtype=np.float64)
    if values.shape != (circuit.n_params,):
        raise ValueError(f"expected {circuit.n_params} values, got {values.size}")

    omega_grid = _omega_grid(spectrum)
    scale = float(np.max(np.abs(spectrum.z)))
    floor = float(np.min(np.abs(spectrum.z)))
    f_min, f_max = float(spectrum.f[0]), float(spectrum.f[-1])
    f_geo = math.sqrt(f_min * f_max)
    w_min, w_max, w_geo = 2 * math.pi * f_min, 2 * math.pi * f_max, 2 * math.pi * f_geo
    w_ref = w_geo
    z_ref = float(np.exp(np.mean(np.log(np.abs(spectrum.z)))))
    cov_ln = log_covariance(values, stderr, correlation)

    quantities: list[Quantity] = []
    notes: list[str] = []

    def add(
        name: str,
        fn: Callable[[Float], float | None],
        unit: str,
        *,
        invariant: bool = True,
        note: str | None = None,
    ) -> None:
        value = fn(values)
        if value is None or not math.isfinite(value):
            return
        quantities.append(
            Quantity(
                name=name,
                value=value,
                unit=unit,
                invariant=invariant,
                stderr=_propagate(fn, values, cov_ln),
                note=note,
            )
        )

    # Terminal behaviour: everything below is a function of Z alone, so every member of the
    # equivalence class produces it identically. That is what `invariant=True` asserts.
    def srf(v: Float) -> float | None:
        return _srf(circuit, v, omega_grid)

    def esr_at_srf(v: Float) -> float | None:
        f = _srf(circuit, v, omega_grid)
        return None if f is None else _at(circuit, v, 2 * math.pi * f).real

    def z_min(v: Float) -> float | None:
        return _z_min(circuit, v, omega_grid)

    def r_dc(v: Float) -> float | None:
        return _limit(circuit, v, f_min, scale, floor, low=True)

    def r_inf(v: Float) -> float | None:
        return _limit(circuit, v, f_max, scale, floor, low=False)

    def r_polarisation(v: Float) -> float | None:
        low, high = r_dc(v), r_inf(v)
        return None if low is None or high is None else low - high

    def _capacitive(z: complex) -> bool:
        return (
            math.isfinite(z.real)
            and math.isfinite(z.imag)
            and z.imag < 0.0
            and -z.imag > CAPACITIVE_PHASE_RATIO * z.real
        )

    def capacitance_at_f_min(v: Float) -> float | None:
        z = _at(circuit, v, w_min)
        if not _capacitive(z):
            return None
        return -1.0 / (w_min * z.imag)

    def _inductive(z: complex) -> bool:
        return (
            math.isfinite(z.real)
            and math.isfinite(z.imag)
            and z.imag > 0.0
            and z.imag > CAPACITIVE_PHASE_RATIO * z.real
        )

    def inductance_at_f_max(v: Float) -> float | None:
        z = _at(circuit, v, w_max)
        if not _inductive(z):
            return None
        return z.imag / w_max

    def tan_delta(v: Float) -> float | None:
        z = _at(circuit, v, w_geo)
        if not _capacitive(z):
            return None
        return z.real / -z.imag

    def q_factor(v: Float) -> float | None:
        t = tan_delta(v)
        return None if t is None or t == 0.0 else 1.0 / t

    extrapolated = "extrapolated past the measured band"
    add("self_resonant_frequency", srf, "Hz")
    add("esr_at_resonance", esr_at_srf, "ohm")
    add("z_min", z_min, "ohm", note="minimum |Z| inside the measured band")
    add("r_dc", r_dc, "ohm", note=extrapolated)
    add("r_inf", r_inf, "ohm", note=extrapolated)
    add("r_polarisation", r_polarisation, "ohm", note="r_dc - r_inf, " + extrapolated)
    add(
        "capacitance_at_f_min",
        capacitance_at_f_min,
        "F",
        note=f"apparent series capacitance at {f_min:.4g} Hz",
    )
    add(
        "inductance_at_f_max",
        inductance_at_f_max,
        "H",
        note=f"apparent series inductance (ESL) at {f_max:.4g} Hz",
    )
    add("tan_delta", tan_delta, "-", note=f"at {f_geo:.4g} Hz")
    add("q_factor", q_factor, "-", note=f"at {f_geo:.4g} Hz")

    modes, modes_available, unstable = modes_of(circuit, values, w_ref=w_ref, z_ref=z_ref)
    if not modes_available:
        notes.append(
            "Z is not a rational function here -- a CPE or a Warburg carries a fractional power"
            " of s -- so it has no poles, and no form-independent time constant can be read off"
            " the circuit. The DRT is the form-independent answer, because it is computed from"
            " the data (core/drt.py)."
        )
    if unstable:
        notes.append(
            "A root of Z(s) does not decay: the fitted values are not those of a passive"
            " network. Treat the model as a curve fit rather than as a circuit."
        )

    # Everything below describes the reported form. Another member of the same equivalence
    # class fits the data exactly as well and puts different numbers here.
    slices = circuit.slices()
    blocks = _blocks(circuit.root)
    resistances = [float(values[slices[r.label]][0]) for r, _ in blocks]
    total_r = sum(resistances)
    relaxations: list[Relaxation] = []
    for (resistor, capacitive), r_value in zip(blocks, resistances, strict=True):
        cap_slice = slices[capacitive.label]
        tau, c_eff, n = _block_tau(r_value, values[cap_slice], capacitive.code)
        if not math.isfinite(tau) or tau <= 0.0:
            continue

        def block_tau(
            v: Float,
            _r: slice = slices[resistor.label],
            _c: slice = cap_slice,
            _code: str = capacitive.code,
        ) -> float | None:
            out, _, _ = _block_tau(float(v[_r][0]), v[_c], _code)
            return out if math.isfinite(out) else None

        relaxations.append(
            Relaxation(
                label=f"{resistor.label}|{capacitive.label}",
                resistance=r_value,
                capacitance=c_eff,
                tau=tau,
                f_peak=1.0 / (2 * math.pi * tau),
                share=r_value / total_r if total_r > 0.0 else math.nan,
                cpe_n=n,
                tau_stderr=_propagate(block_tau, values, cov_ln),
            )
        )
    if any(r.cpe_n is not None for r in relaxations):
        notes.append("Effective capacitance of an R-CPE block: " + CPE_CAPACITANCE_NOTE + ".")
    if relaxations:
        notes.append(
            "Polarisation shares are fractions of the sum over these blocks, not of r_dc -"
            " r_inf, so they are shares of what this form resolves."
        )

    # Diffusion: a finite-length Warburg carries its own time constant, and tau = L^2 / D, so
    # the ratio D/L^2 comes out even though neither D nor L does. That is the geometry rule
    # working in the direction that gives something rather than takes it away.
    for leaf in circuit.leaves:
        if leaf.code not in {"Ws", "Wo"}:
            continue
        tau_slice = slices[leaf.label]

        def d_over_l2(v: Float, _s: slice = tau_slice) -> float | None:
            tau = float(v[_s][1])
            return None if tau <= 0.0 else 1.0 / tau

        add(
            f"{leaf.label}.D_over_L2",
            d_over_l2,
            "1/s",
            invariant=False,
            note="diffusion coefficient over squared length; neither factor alone is measurable",
        )

    if len(relaxations) == 2:
        caps = sorted(r.capacitance for r in relaxations)
        if caps[0] > 0.0:
            quantities.append(
                Quantity(
                    name="capacitance_ratio",
                    value=caps[1] / caps[0],
                    unit="-",
                    invariant=False,
                    note=(
                        "larger over smaller. Under a brick-layer reading this is the"
                        " grain-boundary thickness over the grain size, but only if both regions"
                        " share a permittivity, and calling the smaller capacitance the grain is"
                        " a convention rather than a measurement"
                    ),
                )
            )

    if drt_peaks is not None:
        if drt_peaks == len(relaxations):
            notes.append(
                f"The model-free DRT also counts {drt_peaks} relaxation(s), so the block"
                " decomposition and the data agree on how many there are."
            )
        else:
            notes.append(
                f"The model-free DRT counts {drt_peaks} relaxation(s) where this circuit form"
                f" has {len(relaxations)}. One of the two is wrong about how many processes the"
                " data resolves, and the disagreement is the finding."
            )

    return Interpretation(
        circuit=circuit.to_string(),
        quantities=tuple(quantities),
        modes=modes,
        modes_available=modes_available,
        relaxations=tuple(relaxations),
        notes=tuple(notes),
    )


def interpret(
    result: FitResult, spectrum: Spectrum, *, drt_peaks: int | None = None
) -> Interpretation:
    """Read a fitted result as internal structure; see :func:`interpret_values`."""
    return interpret_values(
        result.circuit,
        result.values,
        spectrum,
        stderr=result.statistics.stderr,
        correlation=result.statistics.correlation,
        drt_peaks=drt_peaks,
    )


@dataclass(frozen=True)
class ClassSpread:
    """One quantity as the *whole equivalence class* answers it.

    ``spread`` is ``max|v - median| / |median|`` over the members that report the quantity. For
    an invariant quantity it is a measurement of how well the claim holds on real fits rather
    than an assertion that it does; for a form-dependent one it is the size of the disagreement
    the reader is being warned about.
    """

    name: str
    unit: str
    invariant: bool
    values: tuple[float, ...]
    spread: float
    reported_by: int
    """How many members produce this quantity at all. Below the class size is itself a finding:
    a quantity one member has and another does not cannot be a property of the measurement."""


@dataclass(frozen=True)
class ClassInterpretation:
    """One candidate read as internal structure, and what its equivalence class does to that.

    Discovery does not return *a* circuit. It returns a Pareto front and, within it, classes of
    topologies that produce the same response -- and `CLAUDE.md` says the reason the `interpret`
    objective exists at all is that under it those classes *are* the question: whether a
    resistance is a grain boundary or an electrode interface is exactly a difference of form,
    and the spectrum does not contain the answer.

    So a discovery report may not simply interpret its recommendation and stop. This reads the
    recommendation, reads every other member of its class, and **measures** which numbers the
    class agrees on. The invariant/form-dependent split is then not a label the reader has to
    trust: the spread beside each number is what the class actually did.
    """

    reading: Interpretation
    members: tuple[str, ...]
    spreads: tuple[ClassSpread, ...]
    relaxation_counts: tuple[int, ...] = ()
    """How many relaxation blocks each member shows, in ``members`` order.

    The bluntest form-dependent quantity there is, and the one gate I1's second half is built
    on: ``R1-p(R2,C1)`` presents one relaxation and its exact equivalent ``p(R1,C1-R2)``
    presents none, on identical data with identical Z. When these counts differ, "how many
    processes does this part have" is a question the reported *form* answered and the
    measurement did not -- which is the single most misleading thing a non-expert can take from
    a discovery report, so the summary says it in those words.
    """

    @property
    def worst_invariant(self) -> ClassSpread | None:
        """The invariant quantity the class agreed on least well. None if there are none."""
        invariant = [s for s in self.spreads if s.invariant and math.isfinite(s.spread)]
        return max(invariant, key=lambda s: s.spread) if invariant else None

    @property
    def disagreeing(self) -> tuple[ClassSpread, ...]:
        """Form-dependent quantities the class does not agree on, worst first."""
        out = [s for s in self.spreads if not s.invariant and s.spread > 0.0]
        return tuple(sorted(out, key=lambda s: -s.spread))

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.reading.to_dict(),
            "class_members": list(self.members),
            "class_relaxation_counts": list(self.relaxation_counts),
            "class_spread": [
                {
                    "name": s.name,
                    "unit": s.unit,
                    "invariant": s.invariant,
                    "values": list(s.values),
                    "spread": s.spread,
                    "reported_by": s.reported_by,
                }
                for s in self.spreads
            ],
        }

    def summary(self) -> str:
        lines = [self.reading.summary()]
        if len(self.members) < 2:
            lines.append("")
            lines.append(
                "No other topology in this report reproduces the same response, so nothing "
                "here can be checked against a second form."
            )
            return "\n".join(lines)
        lines.append("")
        lines.append(
            f"Checked against the {len(self.members) - 1} other topolog"
            f"{'y' if len(self.members) == 2 else 'ies'} the data cannot tell this one apart "
            "from:"
        )
        for member in self.members[1:]:
            lines.append(f"  {member}")
        worst = self.worst_invariant
        if worst is not None:
            lines.append(
                f"  the quantities above marked as the measurement's agree across all of them "
                f"to {worst.spread:.2%} (worst: {worst.name})"
            )
        partial = [s for s in self.spreads if s.reported_by < len(self.members)]
        if partial:
            lines.append(
                "  reported by only some of them, so not a property of the measurement: "
                + ", ".join(s.name for s in partial)
            )
        counts = set(self.relaxation_counts)
        if len(counts) > 1:
            lines.append(
                "  they do not agree on how many relaxations this part shows: "
                + ", ".join(
                    f"{circuit} says {n}"
                    for circuit, n in zip(self.members, self.relaxation_counts, strict=True)
                )
                + " -- that count is a property of the form, not of the measurement"
            )
        if self.disagreeing:
            worst_form = self.disagreeing[0]
            lines.append(
                f"  the form-dependent quantities differ between them by up to "
                f"{worst_form.spread:.0%} ({worst_form.name}) -- choosing between those "
                "topologies is physical knowledge you have, not something this fit measured"
            )
        return "\n".join(lines)


def interpret_class(
    results: Sequence[FitResult], spectrum: Spectrum, *, drt_peaks: int | None = None
) -> ClassInterpretation:
    """Interpret ``results[0]``, and measure what the rest of its equivalence class says.

    ``results`` is one equivalence class, the topology to report first. The caller decides what
    a class is -- :meth:`~autocircuit.core.discover.DiscoveryResult.equivalence_classes` does it
    by comparing responses -- because that decision belongs with the search and not here.
    """
    if not results:
        raise ValueError("interpret_class needs at least one fitted result")
    readings = [
        interpret_values(
            r.circuit,
            r.values,
            spectrum,
            stderr=r.statistics.stderr,
            correlation=r.statistics.correlation,
            drt_peaks=drt_peaks if r is results[0] else None,
        )
        for r in results
    ]
    by_name: dict[str, list[Quantity]] = {}
    for reading in readings:
        for q in reading.quantities:
            by_name.setdefault(q.name, []).append(q)

    spreads: list[ClassSpread] = []
    for name, quantities in by_name.items():
        values = tuple(q.value for q in quantities)
        finite = [v for v in values if math.isfinite(v)]
        median = float(np.median(finite)) if finite else math.nan
        deviation = max(abs(v - median) for v in finite) if finite else math.nan
        if finite and len(finite) == len(values) and deviation == 0.0:
            # Exact agreement, whatever the median is. Without this branch a quantity every
            # member reports as the same zero -- r_inf of a network that is a short at the top
            # of the band -- comes out as an *infinite* spread, because the relative measure
            # divides by that zero. Perfect agreement reported as total disagreement is the
            # wrong way round, and it also made the whole payload undeliverable to the browser,
            # whose wire is strict JSON (docs/OBJECTIVE_PLAN.md section 4.5).
            spread = 0.0
        elif not finite or median == 0.0 or len(finite) < len(values):
            spread = math.inf if len(values) > 1 else 0.0
        else:
            spread = deviation / abs(median)
        spreads.append(
            ClassSpread(
                name=name,
                unit=quantities[0].unit,
                invariant=quantities[0].invariant,
                values=values,
                spread=spread,
                reported_by=len(quantities),
            )
        )
    spreads.sort(key=lambda s: (not s.invariant, s.name))
    return ClassInterpretation(
        reading=readings[0],
        members=tuple(r.circuit.to_string() for r in results),
        spreads=tuple(spreads),
        relaxation_counts=tuple(len(reading.relaxations) for reading in readings),
    )
