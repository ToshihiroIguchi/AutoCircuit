"""Circuit element library.

Every element is a stateless singleton describing a two-terminal impedance as a function of
angular frequency and a flat vector of parameter values. Elements also carry the metadata the
fitting engine needs to work *without user-supplied initial values*: units, log-scale flags,
hard physical limits, and a rule for deriving search bounds from the measured data itself.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from scipy import special

Complex = NDArray[np.complex128]
Float = NDArray[np.float64]

# Absolute sanity limits. They exist only to keep the optimizer inside a physically meaningful
# region; the effective search range is always the (much tighter) data-derived bound.
_R_LIMITS = (1e-9, 1e15)
_C_LIMITS = (1e-18, 1e2)
_L_LIMITS = (1e-15, 1e3)
_TAU_LIMITS = (1e-15, 1e9)
_EXP_LIMITS = (0.02, 1.0)


@dataclass(frozen=True)
class ParamSpec:
    """Description of a single fittable parameter."""

    name: str
    unit: str
    log_scale: bool
    hard_lo: float
    hard_hi: float

    def clip(self, lo: float, hi: float) -> tuple[float, float]:
        """Clamp a proposed search interval to the parameter's hard limits."""
        lo = max(lo, self.hard_lo)
        hi = min(hi, self.hard_hi)
        if not lo < hi:
            lo, hi = self.hard_lo, self.hard_hi
        return lo, hi


@dataclass(frozen=True)
class BoundsContext:
    """Scale information extracted from the data, used to derive parameter search bounds."""

    omega_min: float
    omega_max: float
    z_min: float
    z_max: float
    margin_decades: float = 3.0

    @classmethod
    def from_data(cls, omega: Float, z: Complex, margin_decades: float = 3.0) -> BoundsContext:
        mag = np.abs(z)
        mag = mag[mag > 0.0]
        if mag.size == 0:
            raise ValueError("cannot derive bounds from an all-zero spectrum")
        return cls(
            omega_min=float(np.min(omega)),
            omega_max=float(np.max(omega)),
            z_min=float(np.min(mag)),
            z_max=float(np.max(mag)),
            margin_decades=margin_decades,
        )

    def widen(self, lo: float, hi: float, extra_decades: float = 0.0) -> tuple[float, float]:
        """Expand an interval symmetrically in log space by the configured safety margin."""
        if lo > hi:
            lo, hi = hi, lo
        factor = 10.0 ** (self.margin_decades + extra_decades)
        return lo / factor, hi * factor

    # -- Scale estimates for the common parameter kinds -----------------------------------
    def resistance(self) -> tuple[float, float]:
        return self.widen(self.z_min, self.z_max)

    def capacitance(self) -> tuple[float, float]:
        # |Z| = 1 / (omega * C)
        return self.widen(
            1.0 / (self.omega_max * self.z_max), 1.0 / (self.omega_min * self.z_min)
        )

    def inductance(self) -> tuple[float, float]:
        # |Z| = omega * L
        return self.widen(self.z_min / self.omega_max, self.z_max / self.omega_min)

    def tau(self) -> tuple[float, float]:
        # A relaxation is only observable if 1/tau falls in (or near) the measured band.
        return self.widen(1.0 / self.omega_max, 1.0 / self.omega_min)


class Element(ABC):
    """Base class for two-terminal circuit elements."""

    code: ClassVar[str]
    name: ClassVar[str]
    params: ClassVar[tuple[ParamSpec, ...]]
    #: Structural cost used by the topology search; elements that can absorb a lot of
    #: unexplained behaviour (CPE, HN) are deliberately expensive.
    complexity: ClassVar[float] = 1.0
    #: How this element is realised in a SPICE netlist.
    #: ``primitive`` - a native R/C/L device;
    #: ``rc`` - a passive RC ladder (capacitive fractional elements);
    #: ``rl`` - a passive RL ladder (inductive / skin-effect elements).
    spice_form: ClassVar[str] = "rc"
    #: Leading log-log slope of |Z| as omega -> 0 and as omega -> infinity: the exponent m in
    #: |Z| ~ omega^m. Given as an interval because elements with a free exponent (CPE, CC, HN,
    #: SKINF) sweep a range of slopes as that exponent moves over its hard limits. The
    #: structural feasibility filter in :mod:`autocircuit.core.enumerate` combines these along
    #: the topology tree and compares the result with the measured endpoint slopes, which
    #: rules out whole families of candidates before a single fit is attempted.
    dc_exponent: ClassVar[tuple[float, float]] = (0.0, 0.0)
    hf_exponent: ClassVar[tuple[float, float]] = (0.0, 0.0)

    @property
    def n_params(self) -> int:
        return len(self.params)

    @abstractmethod
    def impedance(self, omega: Float, values: Float) -> Complex:
        """Return Z(omega) in ohms for this element's parameter values.

        Implementations must be *broadcast-safe*. The fitter evaluates a whole population of
        candidate parameter sets at once by passing ``omega`` with shape ``(1, n_freq)`` and
        each ``values[i]`` with shape ``(n_candidates, 1)``, which turns one generation of the
        global optimizer into a single vectorised call instead of hundreds of Python-level
        ones. In practice this means: use array arithmetic on ``values[i]`` directly, never
        ``float(values[i])``, and never assume ``omega.shape`` is the output shape.
        """

    @abstractmethod
    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        """Return per-parameter search intervals derived from the data scale."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.code}>"


def _exponent_bounds(spec: ParamSpec) -> tuple[float, float]:
    return spec.hard_lo, spec.hard_hi


#: Real part beyond which tanh is 1 to within double precision. numpy evaluates complex tanh
#: through exponentials, so without this clamp a finite-length Warburg element overflows the
#: moment the optimizer tries a large time constant -- and the optimizer always does.
_TANH_SATURATION = 30.0


def _tanh(x: Complex) -> Complex:
    """Complex tanh that saturates instead of overflowing."""
    return np.tanh(np.clip(x.real, -_TANH_SATURATION, _TANH_SATURATION) + 1j * x.imag)


class Resistor(Element):
    code = "R"
    name = "Resistor"
    params = (ParamSpec("R", "ohm", True, *_R_LIMITS),)
    complexity = 1.0
    spice_form = "primitive"
    dc_exponent = (0.0, 0.0)
    hf_exponent = (0.0, 0.0)

    def impedance(self, omega: Float, values: Float) -> Complex:
        return (values[0] + 0j) * np.ones_like(omega, dtype=np.complex128)

    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        return [self.params[0].clip(*ctx.resistance())]


class Capacitor(Element):
    code = "C"
    name = "Capacitor"
    params = (ParamSpec("C", "F", True, *_C_LIMITS),)
    complexity = 1.0
    spice_form = "primitive"
    dc_exponent = (-1.0, -1.0)
    hf_exponent = (-1.0, -1.0)

    def impedance(self, omega: Float, values: Float) -> Complex:
        return 1.0 / (1j * omega * values[0])

    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        return [self.params[0].clip(*ctx.capacitance())]


class Inductor(Element):
    code = "L"
    name = "Inductor"
    params = (ParamSpec("L", "H", True, *_L_LIMITS),)
    complexity = 1.0
    spice_form = "primitive"
    dc_exponent = (1.0, 1.0)
    hf_exponent = (1.0, 1.0)

    def impedance(self, omega: Float, values: Float) -> Complex:
        return 1j * omega * values[0]

    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        return [self.params[0].clip(*ctx.inductance())]


class ConstantPhaseElement(Element):
    """Z = 1 / (Q * (j*omega)^n).  n = 1 is a capacitor, n = 0 a resistor, n = 0.5 a Warburg."""

    code = "CPE"
    name = "Constant phase element"
    params = (
        ParamSpec("Q", "S*s^n", True, 1e-18, 1e6),
        ParamSpec("n", "-", False, *_EXP_LIMITS),
    )
    complexity = 2.5
    # |Z| ~ omega^-n with n over its hard limits, at both ends.
    dc_exponent = (-_EXP_LIMITS[1], -_EXP_LIMITS[0])
    hf_exponent = (-_EXP_LIMITS[1], -_EXP_LIMITS[0])

    def impedance(self, omega: Float, values: Float) -> Complex:
        return 1.0 / (values[0] * (1j * omega) ** values[1])

    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        # Q spans between the resistive limit (n->0, Q ~ 1/|Z|) and the capacitive limit
        # (n->1, Q ~ 1/(omega|Z|)); take the union of both so no exponent is excluded.
        cap_lo, cap_hi = ctx.capacitance()
        res_lo, res_hi = 1.0 / ctx.z_max, 1.0 / ctx.z_min
        lo, hi = min(cap_lo, res_lo), max(cap_hi, res_hi)
        return [self.params[0].clip(lo, hi), _exponent_bounds(self.params[1])]


class Warburg(Element):
    """Semi-infinite Warburg diffusion, Z = A / sqrt(j*omega) (45 degree constant phase)."""

    code = "W"
    name = "Warburg (semi-infinite)"
    params = (ParamSpec("A", "ohm*s^-0.5", True, 1e-9, 1e15),)
    complexity = 1.5
    dc_exponent = (-0.5, -0.5)
    hf_exponent = (-0.5, -0.5)

    def impedance(self, omega: Float, values: Float) -> Complex:
        return values[0] / np.sqrt(1j * omega)

    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        lo = ctx.z_min * math.sqrt(ctx.omega_min)
        hi = ctx.z_max * math.sqrt(ctx.omega_max)
        return [self.params[0].clip(*ctx.widen(lo, hi))]


class WarburgShort(Element):
    """Finite-length transmissive Warburg, Z = R * tanh(sqrt(j*omega*tau)) / sqrt(j*omega*tau)."""

    code = "Ws"
    name = "Warburg (finite-length, short)"
    params = (
        ParamSpec("R", "ohm", True, *_R_LIMITS),
        ParamSpec("tau", "s", True, *_TAU_LIMITS),
    )
    complexity = 2.0
    # tanh(x)/x -> 1 as x -> 0, so Z -> R; at high frequency tanh -> 1 and Z -> R/sqrt(j w t).
    dc_exponent = (0.0, 0.0)
    hf_exponent = (-0.5, -0.5)

    def impedance(self, omega: Float, values: Float) -> Complex:
        x = np.sqrt(1j * omega * values[1])
        return values[0] * _tanh(x) / x

    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        return [self.params[0].clip(*ctx.resistance()), self.params[1].clip(*ctx.tau())]


class WarburgOpen(Element):
    """Finite-length reflective Warburg, Z = R * coth(sqrt(j*omega*tau)) / sqrt(j*omega*tau)."""

    code = "Wo"
    name = "Warburg (finite-length, open)"
    params = (
        ParamSpec("R", "ohm", True, *_R_LIMITS),
        ParamSpec("tau", "s", True, *_TAU_LIMITS),
    )
    complexity = 2.0
    # coth(x)/x ~ 1/x^2 as x -> 0, so Z ~ R/(j w tau): capacitive at DC, 45 degrees at HF.
    dc_exponent = (-1.0, -1.0)
    hf_exponent = (-0.5, -0.5)

    def impedance(self, omega: Float, values: Float) -> Complex:
        x = np.sqrt(1j * omega * values[1])
        return values[0] / (_tanh(x) * x)

    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        return [self.params[0].clip(*ctx.resistance()), self.params[1].clip(*ctx.tau())]


class Gerischer(Element):
    """Gerischer impedance, Z = R / sqrt(1 + j*omega*tau)."""

    code = "G"
    name = "Gerischer"
    params = (
        ParamSpec("R", "ohm", True, *_R_LIMITS),
        ParamSpec("tau", "s", True, *_TAU_LIMITS),
    )
    complexity = 2.0
    dc_exponent = (0.0, 0.0)
    hf_exponent = (-0.5, -0.5)

    def impedance(self, omega: Float, values: Float) -> Complex:
        return values[0] / np.sqrt(1.0 + 1j * omega * values[1])

    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        return [self.params[0].clip(*ctx.resistance()), self.params[1].clip(*ctx.tau())]


class ColeCole(Element):
    """Cole-Cole relaxation, Z = R / (1 + (j*omega*tau)^alpha)."""

    code = "CC"
    name = "Cole-Cole relaxation"
    params = (
        ParamSpec("R", "ohm", True, *_R_LIMITS),
        ParamSpec("tau", "s", True, *_TAU_LIMITS),
        ParamSpec("alpha", "-", False, *_EXP_LIMITS),
    )
    complexity = 3.0
    # Resistive plateau at DC; |Z| ~ omega^-alpha once (j w tau)^alpha dominates.
    dc_exponent = (0.0, 0.0)
    hf_exponent = (-_EXP_LIMITS[1], -_EXP_LIMITS[0])

    def impedance(self, omega: Float, values: Float) -> Complex:
        return values[0] / (1.0 + (1j * omega * values[1]) ** values[2])

    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        return [
            self.params[0].clip(*ctx.resistance()),
            self.params[1].clip(*ctx.tau()),
            _exponent_bounds(self.params[2]),
        ]


class HavriliakNegami(Element):
    """Havriliak-Negami relaxation, Z = R / (1 + (j*omega*tau)^alpha)^beta."""

    code = "HN"
    name = "Havriliak-Negami relaxation"
    params = (
        ParamSpec("R", "ohm", True, *_R_LIMITS),
        ParamSpec("tau", "s", True, *_TAU_LIMITS),
        ParamSpec("alpha", "-", False, *_EXP_LIMITS),
        ParamSpec("beta", "-", False, *_EXP_LIMITS),
    )
    complexity = 4.0
    # High-frequency slope is -alpha*beta, so the extremes are the products of the limits.
    dc_exponent = (0.0, 0.0)
    hf_exponent = (-_EXP_LIMITS[1] * _EXP_LIMITS[1], -_EXP_LIMITS[0] * _EXP_LIMITS[0])

    def impedance(self, omega: Float, values: Float) -> Complex:
        return values[0] / (1.0 + (1j * omega * values[1]) ** values[2]) ** values[3]

    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        return [
            self.params[0].clip(*ctx.resistance()),
            self.params[1].clip(*ctx.tau()),
            _exponent_bounds(self.params[2]),
            _exponent_bounds(self.params[3]),
        ]


class SkinFractional(Element):
    """Phenomenological skin-effect element, Z = A * (j*omega)^n.

    With n = 0.5 this reproduces the textbook skin-effect signature: series resistance rising
    as sqrt(f) with an equal-magnitude inductive part (45 degree phase). Letting n float
    absorbs proximity effect and partial-penetration deviations from the ideal exponent.
    """

    code = "SKINF"
    name = "Skin effect (fractional)"
    params = (
        ParamSpec("A", "ohm*s^n", True, 1e-15, 1e12),
        ParamSpec("n", "-", False, 0.05, 0.95),
    )
    complexity = 2.5
    spice_form = "rl"
    # |Z| ~ omega^n, inductive at both ends over the whole allowed exponent range.
    dc_exponent = (0.05, 0.95)
    hf_exponent = (0.05, 0.95)

    def impedance(self, omega: Float, values: Float) -> Complex:
        return values[0] * (1j * omega) ** values[1]

    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        # |Z| = A * omega^n with n in (0, 1); bound A by the extremes of that family.
        lo = ctx.z_min / max(ctx.omega_max, 1.0)
        hi = ctx.z_max / min(ctx.omega_min, 1.0)
        return [self.params[0].clip(*ctx.widen(lo, hi)), _exponent_bounds(self.params[1])]


class SkinRoundWire(Element):
    """Exact internal impedance of a solid round conductor (Bessel-function solution).

    Z(omega) = R_dc * (q/2) * J0(q) / J1(q),  q = sqrt(-j * omega * tau_s),
    where tau_s = mu * sigma * a^2 is the magnetic diffusion time of a wire of radius ``a``.

    The DC limit is R_dc with internal inductance R_dc * tau_s / 8 (= mu / (8*pi) per unit
    length, the classic result), and the high-frequency limit is the sqrt(f) skin-effect
    asymptote. Unlike the RL-ladder approximations used for time-domain SPICE, this is exact
    at every frequency, which is what a frequency-domain fitter should use. Ladder synthesis
    is applied only when exporting to SPICE.
    """

    code = "SKINW"
    name = "Skin effect (round wire, exact)"
    params = (
        ParamSpec("Rdc", "ohm", True, *_R_LIMITS),
        ParamSpec("tau_s", "s", True, *_TAU_LIMITS),
    )
    complexity = 3.0
    spice_form = "rl"
    # DC limit is the plain R_dc; the high-frequency limit is the sqrt(f) skin asymptote.
    dc_exponent = (0.0, 0.0)
    hf_exponent = (0.5, 0.5)

    #: |q| above which the three-term asymptotic expansion below is used instead of the
    #: Bessel functions. The expansion's leading error is O(|q|^-3), so at 1e5 it agrees with
    #: the exact ratio to ~3e-16 -- the switch introduces no visible step. (An earlier version
    #: switched at |q| = 300 using only the leading term, which left a 0.17% discontinuity:
    #: the asymptotic series converges as 1/|q|, not exponentially.)
    _ASYMPTOTIC_Q = 1e5

    def impedance(self, omega: Float, values: Float) -> Complex:
        r_dc, tau_s = values[0], values[1]
        q = np.sqrt(-1j * omega * tau_s)
        small = np.abs(q) <= self._ASYMPTOTIC_Q

        # Each branch is evaluated on a sanitised argument so that the one being discarded
        # cannot overflow or divide by zero and pollute the result with warnings.
        q_exact = np.where(small, q, self._ASYMPTOTIC_Q)
        # jve is the exponentially scaled Bessel function; the scaling cancels in the ratio
        # and keeps the intermediate values from overflowing for large imaginary arguments.
        ratio_exact = special.jve(0, q_exact) / special.jve(1, q_exact)

        # Hankel asymptotic expansion of J0(q)/J1(q) for Im q -> -inf (which is always the
        # case here, since q = sqrt(-j*omega*tau) has phase -45 degrees):
        #     J0/J1 = j + 1/(2q) - 3j/(8q^2) + O(q^-3)
        u = 1.0 / np.where(small, self._ASYMPTOTIC_Q, q)
        ratio_asymptotic = 1j + 0.5 * u - 0.375j * u * u

        ratio = np.where(small, ratio_exact, ratio_asymptotic)
        return r_dc * 0.5 * q * ratio

    def bounds(self, ctx: BoundsContext) -> list[tuple[float, float]]:
        return [self.params[0].clip(*ctx.resistance()), self.params[1].clip(*ctx.tau())]


#: All elements available to the parser, the fitter and the topology search.
REGISTRY: dict[str, Element] = {
    e.code: e
    for e in (
        Resistor(),
        Capacitor(),
        Inductor(),
        ConstantPhaseElement(),
        Warburg(),
        WarburgShort(),
        WarburgOpen(),
        Gerischer(),
        ColeCole(),
        HavriliakNegami(),
        SkinFractional(),
        SkinRoundWire(),
    )
}

#: Element codes ordered so that a longest-match tokenizer never mistakes "Ws" for "W".
CODES_BY_LENGTH: tuple[str, ...] = tuple(sorted(REGISTRY, key=len, reverse=True))

#: Sensible default pool for the topology search over generic passive components.
DEFAULT_POOL: tuple[str, ...] = ("R", "C", "L", "CPE")

#: Pool tuned for capacitor / inductor characterisation including skin effect.
COMPONENT_POOL: tuple[str, ...] = ("R", "C", "L", "CPE", "SKINF")

#: Pool tuned for electrochemical and dielectric (Maxwell-Wagner) spectra.
ELECTROCHEMICAL_POOL: tuple[str, ...] = ("R", "C", "L", "CPE", "W", "Ws", "Wo", "G")


def get(code: str) -> Element:
    """Look up an element by code, raising a helpful error for unknown codes."""
    try:
        return REGISTRY[code]
    except KeyError:
        raise KeyError(
            f"unknown element code {code!r}; known codes: {', '.join(sorted(REGISTRY))}"
        ) from None
