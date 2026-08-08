"""Analytic-value and structural tests for every element in ``autocircuit.core.elements``.

Every expectation below is derived independently of the implementation (hand algebra or a
known textbook asymptote), never by re-calling the formula under test.
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.testing import assert_allclose

from autocircuit.core.circuit import Circuit
from autocircuit.core.elements import (
    REGISTRY,
    BoundsContext,
    Capacitor,
    ColeCole,
    ConstantPhaseElement,
    Gerischer,
    HavriliakNegami,
    Inductor,
    Resistor,
    SkinFractional,
    SkinRoundWire,
    Warburg,
    WarburgOpen,
    WarburgShort,
)

Float = np.ndarray


def _omega(f_hz: Float | list[float]) -> Float:
    return 2.0 * np.pi * np.asarray(f_hz, dtype=np.float64)


# =============================================================================================
# R, C, L
# =============================================================================================


def test_resistor_is_real_and_frequency_independent() -> None:
    r = Resistor()
    omega = _omega(np.logspace(0, 8, 20))
    z = r.impedance(omega, np.array([57.0]))
    assert_allclose(z.real, 57.0, atol=1e-12)
    assert_allclose(z.imag, 0.0, atol=1e-12)


def test_capacitor_magnitude_and_phase() -> None:
    c = Capacitor()
    capacitance = 4.7e-6
    omega = _omega(np.logspace(1, 6, 25))
    z = c.impedance(omega, np.array([capacitance]))
    expected_mag = 1.0 / (omega * capacitance)
    assert_allclose(np.abs(z), expected_mag, rtol=1e-12)
    assert_allclose(np.angle(z, deg=True), -90.0, atol=1e-9)


def test_inductor_magnitude_and_phase() -> None:
    inductor = Inductor()
    inductance = 2.2e-3
    omega = _omega(np.logspace(1, 6, 25))
    z = inductor.impedance(omega, np.array([inductance]))
    expected_mag = omega * inductance
    assert_allclose(np.abs(z), expected_mag, rtol=1e-12)
    assert_allclose(np.angle(z, deg=True), 90.0, atol=1e-9)


# =============================================================================================
# CPE
# =============================================================================================


def test_cpe_phase_is_minus_n_times_90_degrees_at_every_frequency() -> None:
    cpe = ConstantPhaseElement()
    q, n = 3.3e-5, 0.62
    omega = _omega(np.logspace(-1, 8, 30))
    z = cpe.impedance(omega, np.array([q, n]))
    assert_allclose(np.angle(z, deg=True), -n * 90.0, atol=1e-9)


def test_cpe_n1_reproduces_capacitor_with_c_equal_q() -> None:
    q = 8.2e-6
    omega = _omega(np.logspace(0, 7, 20))
    z_cpe = ConstantPhaseElement().impedance(omega, np.array([q, 1.0]))
    z_cap = Capacitor().impedance(omega, np.array([q]))
    assert_allclose(z_cpe, z_cap, rtol=1e-10)


def test_cpe_n0_reproduces_resistor_with_r_equal_1_over_q() -> None:
    q = 4.0e-3
    omega = _omega(np.logspace(0, 7, 20))
    z_cpe = ConstantPhaseElement().impedance(omega, np.array([q, 0.0]))
    z_res = Resistor().impedance(omega, np.array([1.0 / q]))
    assert_allclose(z_cpe, z_res, rtol=1e-10)


# =============================================================================================
# W (semi-infinite Warburg)
# =============================================================================================


def test_warburg_phase_is_minus_45_degrees_and_magnitude_scales_as_inverse_sqrt_omega() -> None:
    w = Warburg()
    a = 120.0
    omega = _omega(np.logspace(-1, 7, 25))
    z = w.impedance(omega, np.array([a]))
    assert_allclose(np.angle(z, deg=True), -45.0, atol=1e-9)
    assert_allclose(np.abs(z), a / np.sqrt(omega), rtol=1e-12)


# =============================================================================================
# Ws (finite-length, short / transmissive Warburg)
# =============================================================================================


def test_warburg_short_low_frequency_limit_is_real_resistance() -> None:
    # tanh(x)/x -> 1 as x -> 0, so Z -> R with a vanishing capacitive correction.
    ws = WarburgShort()
    r, tau = 50.0, 2e-3
    omega = np.array([1e-8 / tau])  # omega*tau tiny
    z = ws.impedance(omega, np.array([r, tau]))
    assert_allclose(z.real, r, rtol=1e-6)
    assert abs(z.imag) < r * 1e-4


def test_warburg_short_high_frequency_limit_is_45_degree_warburg_line() -> None:
    # tanh(x) -> 1 for large Re(x), so Z -> R/sqrt(j*omega*tau): the same 45 degree line as W.
    ws = WarburgShort()
    r, tau = 50.0, 2e-3
    omega = np.array([1e8 / tau])  # omega*tau huge
    z = ws.impedance(omega, np.array([r, tau]))
    assert_allclose(np.angle(z, deg=True), -45.0, atol=1e-6)
    assert_allclose(np.abs(z), r / np.sqrt(omega * tau), rtol=1e-6)


# =============================================================================================
# Wo (finite-length, open / reflective Warburg)
# =============================================================================================


def test_warburg_open_low_frequency_limit_matches_capacitive_expansion() -> None:
    # Taylor expansion of coth(x)/x around x=0 gives 1/x^2 + 1/3 (independently derived: with
    # tanh(x) ~= x - x^3/3, tanh(x)*x ~= x^2*(1 - x^2/3), so 1/(tanh(x)*x) ~= 1/x^2 + 1/3).
    # x^2 = j*omega*tau, so Z -> R/(j*omega*tau) + R/3.
    wo = WarburgOpen()
    r, tau = 50.0, 2e-3
    omega = np.array([1e-6 / tau])
    z = wo.impedance(omega, np.array([r, tau]))
    expected = r / (1j * omega * tau) + r / 3.0
    assert_allclose(z.real, r / 3.0, rtol=1e-6)
    assert_allclose(z.imag, expected.imag, rtol=1e-6)
    assert z.imag < 0.0  # capacitive divergence as omega -> 0


def test_warburg_open_high_frequency_limit_is_45_degree_warburg_line() -> None:
    # coth(x) -> 1 for large Re(x), so Z -> R/sqrt(j*omega*tau), same as Ws.
    wo = WarburgOpen()
    r, tau = 50.0, 2e-3
    omega = np.array([1e8 / tau])
    z = wo.impedance(omega, np.array([r, tau]))
    assert_allclose(np.angle(z, deg=True), -45.0, atol=1e-6)
    assert_allclose(np.abs(z), r / np.sqrt(omega * tau), rtol=1e-6)


# =============================================================================================
# G (Gerischer)
# =============================================================================================


def test_gerischer_dc_value_is_r() -> None:
    g = Gerischer()
    r, tau = 75.0, 1e-3
    z = g.impedance(np.array([0.0]), np.array([r, tau]))
    assert_allclose(z, complex(r, 0.0), rtol=0, atol=1e-12)


def test_gerischer_high_frequency_phase_tends_to_minus_45_degrees() -> None:
    # 1 + j*omega*tau -> j*omega*tau for omega*tau >> 1, so Z -> R/sqrt(j*omega*tau).
    g = Gerischer()
    r, tau = 75.0, 1e-3
    omega = np.array([1e8 / tau])
    z = g.impedance(omega, np.array([r, tau]))
    assert_allclose(np.angle(z, deg=True), -45.0, atol=1e-4)


# =============================================================================================
# CC (Cole-Cole) and HN (Havriliak-Negami)
# =============================================================================================


def test_cole_cole_alpha_1_equals_parallel_rc_block() -> None:
    # Z_CC = R / (1 + j*omega*tau) with alpha=1, which is exactly the parallel R-C impedance
    # R / (1 + j*omega*R*C) when C = tau / R.
    r, tau = 120.0, 5e-4
    c = tau / r
    omega = _omega(np.logspace(0, 8, 15))

    z_cc = ColeCole().impedance(omega, np.array([r, tau, 1.0]))

    circuit = Circuit.parse("p(R1,C1)")
    z_parallel = circuit.impedance(omega, np.array([r, c]))

    assert_allclose(z_cc, z_parallel, rtol=1e-10)


def test_havriliak_negami_beta_1_equals_cole_cole() -> None:
    r, tau, alpha = 90.0, 3e-4, 0.73
    omega = _omega(np.logspace(0, 8, 15))
    z_cc = ColeCole().impedance(omega, np.array([r, tau, alpha]))
    z_hn = HavriliakNegami().impedance(omega, np.array([r, tau, alpha, 1.0]))
    assert_allclose(z_hn, z_cc, rtol=1e-10)


# =============================================================================================
# SKINF (phenomenological skin effect)
# =============================================================================================


def test_skinf_phase_is_n_times_90_degrees_and_magnitude_scales_as_omega_to_the_n() -> None:
    skinf = SkinFractional()
    a, n = 2.5e-4, 0.5
    omega = _omega(np.logspace(-1, 8, 25))
    z = skinf.impedance(omega, np.array([a, n]))
    assert_allclose(np.angle(z, deg=True), n * 90.0, atol=1e-9)
    assert_allclose(np.abs(z), a * omega**n, rtol=1e-12)


# =============================================================================================
# SKINW (exact round-wire skin effect)
# =============================================================================================


def test_skinw_dc_limit_matches_internal_inductance_expansion() -> None:
    # Independent derivation from the small-argument Bessel series:
    #   J0(q) ~= 1 - q^2/4,  J1(q) ~= (q/2)(1 - q^2/8)
    #   => J0(q)/J1(q) ~= (2/q)(1 - q^2/8)
    #   => Z = Rdc*(q/2)*J0(q)/J1(q) ~= Rdc*(1 - q^2/8)
    # with q^2 = -j*omega*tau_s, giving Z -> Rdc + j*omega*Rdc*tau_s/8.
    skinw = SkinRoundWire()
    r_dc, tau_s = 10.0, 1e-3
    omega = np.array([1e-4 / tau_s])  # omega*tau_s tiny => |q| << 300, exact Bessel branch used
    z = skinw.impedance(omega, np.array([r_dc, tau_s]))
    expected = r_dc + 1j * omega * r_dc * tau_s / 8.0
    assert_allclose(z.real, r_dc, rtol=1e-8)
    assert_allclose(z.imag, expected.imag, rtol=1e-6)


def test_skinw_high_frequency_phase_and_sqrt_scaling() -> None:
    # Classical high-frequency skin-effect asymptote (round wire): the AC resistance and the
    # internal reactance become equal, both proportional to sqrt(omega); i.e. a 45 degree
    # phase and magnitude growing as sqrt(omega).
    # 45 degrees is a limit, not a value reached at any finite frequency: the correction to
    # the Bessel ratio falls off as 0.5/|q|, so the phase approaches 45 degrees from below.
    skinw = SkinRoundWire()
    r_dc, tau_s = 10.0, 1e-3
    q_values = np.array([2e3, 2e4, 2e5, 2e6])
    omegas = (q_values**2) / tau_s
    z = skinw.impedance(omegas, np.array([r_dc, tau_s]))

    deviation = 45.0 - np.angle(z, deg=True)
    assert np.all(deviation > 0.0), "phase should approach 45 degrees from below"
    # Each tenfold increase in |q| must shrink the deviation about tenfold.
    assert_allclose(deviation[:-1] / deviation[1:], 10.0, rtol=0.05)
    assert deviation[-1] < 1e-4

    # |Z| grows as sqrt(omega) in the same limit, again approached at the 1/|q| rate.
    ratio = np.abs(z[1:]) / np.abs(z[:-1])
    error = np.abs(ratio - np.sqrt(omegas[1:] / omegas[:-1])) / 10.0
    assert_allclose(error[:-1] / error[1:], 10.0, rtol=0.05)
    assert error[-1] < 1e-5


@pytest.mark.parametrize("q_switch", [300.0, SkinRoundWire._ASYMPTOTIC_Q])
def test_skinw_is_continuous_across_the_asymptotic_switch(q_switch: float) -> None:
    """The exact Bessel branch and the asymptotic branch must join without a step.

    Regression test. An earlier implementation switched at |q| = 300 using only the leading
    asymptotic term ``J0/J1 -> j``, which left a 0.17% jump: the Hankel series converges as
    1/|q|, not exponentially, so the leading term alone is off by ~0.5/|q| at the switch.
    The fix carries the expansion to ``j + 1/(2q) - 3j/(8q^2)`` and moves the switch to
    |q| = 1e5, where it agrees with the Bessel evaluation to machine precision. Both the old
    and the current switch point are checked, so neither can regress.
    """
    skinw = SkinRoundWire()
    r_dc, tau_s = 10.0, 1e-3
    omega_switch = (q_switch**2) / tau_s
    deltas = np.linspace(-0.005, 0.005, 4001)
    omegas = omega_switch * (1.0 + deltas)
    z = skinw.impedance(omegas, np.array([r_dc, tau_s]))
    relative_step = np.abs(np.diff(z)) / np.abs(z[:-1])
    # A smooth function on a grid this dense shows relative steps of the same tiny order
    # everywhere; a genuine discontinuity blows one of them far above its neighbours.
    assert np.max(relative_step) < 1e-4


def test_skinw_asymptotic_branch_matches_the_bessel_branch() -> None:
    """Directly compare the two branches where both are computable."""
    from scipy import special

    magnitudes = np.array([1e5, 1e6, 1e7])
    q = magnitudes * np.exp(-1j * np.pi / 4)
    exact = special.jve(0, q) / special.jve(1, q)
    u = 1.0 / q
    asymptotic = 1j + 0.5 * u - 0.375j * u * u
    assert_allclose(asymptotic, exact, rtol=1e-13)


# =============================================================================================
# Batched evaluation == per-candidate evaluation, for every element in the registry
# =============================================================================================

#: (low, high, log-uniform?) sampling range for each parameter, in ``element.params`` order.
#: Ranges stay comfortably inside each parameter's hard limits so the comparison never touches
#: a numerically delicate edge case (e.g. exponents right at 0 or 1).
_PARAM_SAMPLE_RANGES: dict[str, list[tuple[float, float, bool]]] = {
    "R": [(1.0, 1e4, True)],
    "C": [(1e-9, 1e-3, True)],
    "L": [(1e-9, 1e-3, True)],
    "CPE": [(1e-8, 1e-2, True), (0.1, 0.95, False)],
    "W": [(1.0, 1e4, True)],
    "Ws": [(1.0, 1e4, True), (1e-6, 1.0, True)],
    "Wo": [(1.0, 1e4, True), (1e-6, 1.0, True)],
    "G": [(1.0, 1e4, True), (1e-6, 1.0, True)],
    "CC": [(1.0, 1e4, True), (1e-6, 1.0, True), (0.1, 0.95, False)],
    "HN": [(1.0, 1e4, True), (1e-6, 1.0, True), (0.1, 0.95, False), (0.1, 0.95, False)],
    "SKINF": [(1e-6, 1e2, True), (0.1, 0.9, False)],
    "SKINW": [(1.0, 1e4, True), (1e-9, 1e-1, True)],
}


def _sample_candidates(code: str, rng: np.random.Generator, n: int = 6) -> Float:
    """Random candidate parameter block, shape ``(n_params, n)``."""
    rows = []
    for lo, hi, log_scale in _PARAM_SAMPLE_RANGES[code]:
        if log_scale:
            rows.append(10.0 ** rng.uniform(np.log10(lo), np.log10(hi), n))
        else:
            rows.append(rng.uniform(lo, hi, n))
    return np.array(rows)


@pytest.mark.parametrize("code", sorted(REGISTRY))
def test_batched_evaluation_matches_per_candidate_evaluation(code: str) -> None:
    element = REGISTRY[code]
    rng = np.random.default_rng(20240501)
    n_candidates = 6
    values = _sample_candidates(code, rng, n_candidates)
    omega = _omega(np.logspace(0, 7, 30))

    batched = element.impedance(omega[np.newaxis, :], values[:, :, np.newaxis])
    assert batched.shape == (n_candidates, omega.size)

    for k in range(n_candidates):
        single = element.impedance(omega, values[:, k])
        assert_allclose(batched[k], single, rtol=1e-12)


# =============================================================================================
# BoundsContext.from_data / Element.bounds()
# =============================================================================================


def test_bounds_from_data_contain_the_true_capacitance() -> None:
    capacitance = 1e-6
    f = np.logspace(2, 9, 50)  # 100 Hz .. 1 GHz
    omega = 2.0 * np.pi * f
    z = 1.0 / (1j * omega * capacitance)
    ctx = BoundsContext.from_data(omega, z)
    lo, hi = Capacitor().bounds(ctx)[0]
    assert lo < capacitance < hi


def test_bounds_from_data_contain_the_true_resistance() -> None:
    resistance = 100.0
    f = np.logspace(2, 9, 50)
    omega = 2.0 * np.pi * f
    z = np.full_like(omega, resistance, dtype=np.complex128)
    ctx = BoundsContext.from_data(omega, z)
    lo, hi = Resistor().bounds(ctx)[0]
    assert lo < resistance < hi


def test_bounds_from_data_contain_the_true_inductance() -> None:
    inductance = 1e-3
    f = np.logspace(3, 8, 50)
    omega = 2.0 * np.pi * f
    z = 1j * omega * inductance
    ctx = BoundsContext.from_data(omega, z)
    lo, hi = Inductor().bounds(ctx)[0]
    assert lo < inductance < hi


@pytest.mark.parametrize("code", sorted(REGISTRY))
def test_bounds_are_ordered_and_respect_hard_limits(code: str) -> None:
    element = REGISTRY[code]
    # A generic, wide data scale: 0.1 Hz .. 10 MHz, |Z| from 10 mOhm to 1 MOhm.
    ctx = BoundsContext(
        omega_min=2.0 * np.pi * 0.1,
        omega_max=2.0 * np.pi * 1.0e7,
        z_min=1e-2,
        z_max=1e6,
    )
    bounds = element.bounds(ctx)
    assert len(bounds) == element.n_params
    for (lo, hi), spec in zip(bounds, element.params, strict=True):
        assert lo < hi
        assert lo >= spec.hard_lo
        assert hi <= spec.hard_hi
