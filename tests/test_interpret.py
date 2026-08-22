"""Tests for reading a fitted circuit as internal structure (``core/interpret.py``).

Covers, in order:

1. **Gate I1, both halves.** On an exact reparameterisation -- two circuits that are two names
   for one ``Z`` -- every quantity marked ``invariant`` must agree, and the form-dependent ones
   must be allowed to disagree. The second half is not decoration: a label that nothing can
   falsify is not a label, and the way to get I1 to pass trivially is to mark everything
   form-dependent.
2. Analytic values for the three shapes this module has closed forms for: a series R-L-C, a
   two-block Maxwell-Wagner, and an R-CPE block at ``n = 1``, where the CPE *is* a capacitor and
   the Hsu-Mansfeld effective capacitance must reduce to it exactly.
3. What is deliberately absent: limits that diverge, poles of a non-rational ``Z``.
4. Uncertainty propagation, checked against the closed form for a power product.
5. A synthetic-data round trip through the real fitter, which is what the rest of this suite
   requires of every feature that reads a fit.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from autocircuit.core.circuit import Circuit
from autocircuit.core.fit import fit
from autocircuit.core.interpret import interpret, interpret_values
from autocircuit.core.spectrum import Spectrum


def _spectrum(circuit: Circuit, values: list[float], f: np.ndarray) -> Spectrum:
    z = circuit.impedance(2 * np.pi * f, np.array(values, dtype=float))
    return Spectrum(f=f, z=np.asarray(z, dtype=np.complex128))


# -- 1. Gate I1 -----------------------------------------------------------------------------
#
# ``R1-p(R2,C1)`` and ``p(R1,C1-R2)`` are the pair docs/HANDOFF.md section 3 records as fitting
# the same data to 1.2e-15. Here the correspondence is written down exactly rather than fitted,
# so the gate tests the interpretation and not the optimizer:
#
#   R1' = R1 + R2        R2' = R1(R1+R2)/R2        C1' = R2^2 C1 / (R1+R2)^2


def _equivalent_pair() -> tuple[tuple[Circuit, list[float]], tuple[Circuit, list[float]]]:
    r1, r2, c1 = 10.0, 100.0, 1e-6
    a = (Circuit.parse("R1-p(R2,C1)"), [r1, r2, c1])
    b = (
        Circuit.parse("p(R1,C1-R2)"),
        [r1 + r2, r2**2 * c1 / (r1 + r2) ** 2, r1 * (r1 + r2) / r2],
    )
    return a, b


def test_the_pair_really_is_one_impedance() -> None:
    """The premise of gate I1. If this drifts, I1 is testing nothing."""
    (ca, va), (cb, vb) = _equivalent_pair()
    omega = 2 * np.pi * np.logspace(0, 6, 61)
    za = ca.impedance(omega, np.array(va))
    zb = cb.impedance(omega, np.array(vb))
    assert np.max(np.abs(za - zb) / np.abs(za)) < 1e-12


def test_i1_invariant_quantities_survive_an_exact_reparameterisation() -> None:
    (ca, va), (cb, vb) = _equivalent_pair()
    f = np.logspace(0, 6, 61)
    spectrum = _spectrum(ca, va, f)
    a = interpret_values(ca, np.array(va), spectrum)
    b = interpret_values(cb, np.array(vb), spectrum)

    names_a = {q.name for q in a.invariant}
    names_b = {q.name for q in b.invariant}
    assert names_a == names_b
    assert names_a  # the gate is vacuous if nothing is marked invariant
    for name in sorted(names_a):
        qa, qb = a.get(name), b.get(name)
        assert qa is not None and qb is not None
        assert qa.value == pytest.approx(qb.value, rel=1e-9), name

    # Poles and zeros are invariant by the same argument and are checked the same way.
    assert a.modes_available and b.modes_available
    assert [m.kind for m in a.modes] == [m.kind for m in b.modes]
    for ma, mb in zip(a.modes, b.modes, strict=True):
        assert (ma.tau is None) == (mb.tau is None)
        if ma.tau is not None and mb.tau is not None:
            assert ma.tau == pytest.approx(mb.tau, rel=1e-9)


def test_i1_form_dependent_quantities_are_allowed_to_disagree() -> None:
    """The other half: the invariant flag has to be falsifiable to mean anything.

    ``R1-p(R2,C1)`` presents a relaxation block; its exact equivalent ``p(R1,C1-R2)`` presents
    none at all, because a block is a feature of the tree rather than of the impedance. Same
    data, same ``Z``, different answer to "how many relaxations does this circuit show".
    """
    (ca, va), (cb, vb) = _equivalent_pair()
    spectrum = _spectrum(ca, va, np.logspace(0, 6, 61))
    a = interpret_values(ca, np.array(va), spectrum)
    b = interpret_values(cb, np.array(vb), spectrum)
    assert len(a.relaxations) == 1
    assert len(b.relaxations) == 0


# -- 2. Analytic values ---------------------------------------------------------------------


def test_series_rlc_matches_the_closed_form() -> None:
    cap, res, ind = 1e-6, 0.01, 5e-10
    circuit = Circuit.parse("C1-R1-L1")
    values = [cap, res, ind]
    f = np.logspace(3, 9, 121)
    result = interpret_values(circuit, np.array(values), _spectrum(circuit, values, f))

    srf = result.get("self_resonant_frequency")
    esr = result.get("esr_at_resonance")
    assert srf is not None and esr is not None
    assert srf.value == pytest.approx(1.0 / (2 * math.pi * math.sqrt(ind * cap)), rel=1e-5)
    assert esr.value == pytest.approx(res, rel=1e-6)

    # At the lowest frequency the part is a capacitor and nothing else.
    apparent = result.get("capacitance_at_f_min")
    assert apparent is not None
    assert apparent.value == pytest.approx(cap, rel=1e-3)

    # Z has a double zero at the resonance and a single pole at s = 0, which is not a mode.
    resonances = [m for m in result.modes if m.f0 is not None]
    assert len(resonances) == 1
    assert resonances[0].kind == "zero"
    assert resonances[0].f0 == pytest.approx(1.0 / (2 * math.pi * math.sqrt(ind * cap)), rel=1e-9)
    assert resonances[0].q == pytest.approx(math.sqrt(ind / cap) / res, rel=1e-9)


def test_two_block_maxwell_wagner_recovers_every_block_number() -> None:
    r1, c1, r2, c2 = 100.0, 1e-6, 5000.0, 1e-8
    circuit = Circuit.parse("p(R1,C1)-p(R2,C2)")
    values = [r1, c1, r2, c2]
    f = np.logspace(-1, 6, 141)
    result = interpret_values(circuit, np.array(values), _spectrum(circuit, values, f))

    dc = result.get("r_dc")
    assert dc is not None and dc.value == pytest.approx(r1 + r2, rel=1e-6)
    pol = result.get("r_polarisation")
    assert pol is not None and pol.value == pytest.approx(r1 + r2, rel=1e-6)

    taus = sorted(r.tau for r in result.relaxations)
    assert taus == pytest.approx(sorted([r1 * c1, r2 * c2]), rel=1e-9)
    shares = {r.label: r.share for r in result.relaxations}
    assert shares["R1|C1"] == pytest.approx(r1 / (r1 + r2), rel=1e-9)
    assert shares["R2|C2"] == pytest.approx(r2 / (r1 + r2), rel=1e-9)

    ratio = result.get("capacitance_ratio")
    assert ratio is not None and ratio.value == pytest.approx(c1 / c2, rel=1e-9)
    assert ratio.invariant is False

    # Both poles are the block time constants, and they are invariant where the blocks are not.
    poles = sorted(m.tau for m in result.modes if m.kind == "pole" and m.tau is not None)
    assert poles == pytest.approx(sorted([r1 * c1, r2 * c2]), rel=1e-9)


def test_cpe_block_reduces_to_a_capacitor_at_n_equals_one() -> None:
    """The anchor for the Hsu-Mansfeld form: at n = 1 a CPE *is* a capacitor of value Q."""
    r, q = 250.0, 4e-7
    circuit = Circuit.parse("p(R1,CPE1)")
    values = [r, q, 1.0]
    f = np.logspace(-1, 5, 121)
    result = interpret_values(circuit, np.array(values), _spectrum(circuit, values, f))

    assert len(result.relaxations) == 1
    block = result.relaxations[0]
    assert block.capacitance == pytest.approx(q, rel=1e-9)
    assert block.tau == pytest.approx(r * q, rel=1e-9)
    assert block.f_peak == pytest.approx(1.0 / (2 * math.pi * r * q), rel=1e-9)
    assert block.cpe_n == pytest.approx(1.0)
    assert block.share == pytest.approx(1.0)


def test_finite_warburg_gives_the_ratio_and_not_the_coefficient() -> None:
    circuit = Circuit.parse("R1-Ws1")
    values = [10.0, 200.0, 3.0]
    f = np.logspace(-3, 3, 121)
    result = interpret_values(circuit, np.array(values), _spectrum(circuit, values, f))
    ratio = result.get("Ws1.D_over_L2")
    assert ratio is not None
    assert ratio.value == pytest.approx(1.0 / 3.0, rel=1e-9)
    assert ratio.invariant is False
    # The geometry rule: no bare diffusion coefficient and no length anywhere in the report.
    names = {q.name for q in result.quantities}
    assert not any("permittivity" in n or n.endswith(".D") or n.endswith(".L") for n in names)


# -- 3. Deliberate absences -----------------------------------------------------------------


def test_limits_are_absent_when_they_diverge() -> None:
    """A lone capacitor blocks DC and shorts at high frequency, and both are said properly.

    ``r_inf`` is 0 rather than missing, because that limit does converge -- the absence to test
    for is ``r_dc``, where |Z| runs away and no number would be honest.
    """
    circuit = Circuit.parse("C1")
    values = [1e-6]
    f = np.logspace(1, 5, 41)
    result = interpret_values(circuit, np.array(values), _spectrum(circuit, values, f))
    assert result.get("r_dc") is None
    r_inf = result.get("r_inf")
    assert r_inf is not None and r_inf.value == pytest.approx(0.0, abs=1e-9)
    cap = result.get("capacitance_at_f_min")
    assert cap is not None and cap.value == pytest.approx(1e-6, rel=1e-9)


def test_a_non_rational_circuit_reports_no_poles_and_says_why() -> None:
    circuit = Circuit.parse("R1-p(CPE1,R2)")
    values = [10.0, 1e-5, 0.85, 500.0]
    f = np.logspace(-2, 5, 121)
    result = interpret_values(circuit, np.array(values), _spectrum(circuit, values, f))
    assert result.modes_available is False
    assert result.modes == ()
    assert any("not a rational function" in note for note in result.notes)
    assert any("DRT" in note for note in result.notes)


def test_drt_disagreement_is_reported_as_the_finding() -> None:
    circuit = Circuit.parse("p(R1,C1)-p(R2,C2)")
    values = [100.0, 1e-6, 5000.0, 1e-8]
    f = np.logspace(-1, 6, 141)
    spectrum = _spectrum(circuit, values, f)
    agree = interpret_values(circuit, np.array(values), spectrum, drt_peaks=2)
    assert any("agree on how many" in note for note in agree.notes)
    disagree = interpret_values(circuit, np.array(values), spectrum, drt_peaks=3)
    assert any("disagreement is the finding" in note for note in disagree.notes)


# -- 4. Uncertainty -------------------------------------------------------------------------


def test_a_power_product_propagates_exactly() -> None:
    """tau = R*C, so the relative variances add. Nothing here is approximated."""
    circuit = Circuit.parse("p(R1,C1)")
    values = np.array([100.0, 1e-6])
    f = np.logspace(-1, 5, 61)
    spectrum = _spectrum(circuit, list(values), f)
    rel = 0.1
    result = interpret_values(
        circuit,
        values,
        spectrum,
        stderr=rel * values,
        correlation=np.eye(2),
    )
    block = result.relaxations[0]
    assert block.tau_stderr is not None
    assert block.tau_stderr / block.tau == pytest.approx(math.sqrt(2) * rel, rel=1e-6)


def test_no_covariance_means_no_standard_error_rather_than_a_guess() -> None:
    circuit = Circuit.parse("p(R1,C1)")
    values = np.array([100.0, 1e-6])
    spectrum = _spectrum(circuit, list(values), np.logspace(-1, 5, 61))
    result = interpret_values(circuit, values, spectrum)
    assert result.relaxations[0].tau_stderr is None
    assert all(q.stderr is None for q in result.quantities)


def test_to_dict_is_json_safe() -> None:
    circuit = Circuit.parse("p(R1,C1)-p(R2,C2)")
    values = np.array([100.0, 1e-6, 5000.0, 1e-8])
    f = np.logspace(-1, 6, 81)
    result = interpret_values(circuit, values, _spectrum(circuit, list(values), f))
    text = json.dumps(result.to_dict(), allow_nan=False)
    assert json.loads(text)["circuit"] == "p(R1,C1)-p(R2,C2)"


# -- 5. Round trip through the real fitter --------------------------------------------------


def test_round_trip_through_a_fit_recovers_the_time_constants() -> None:
    """Two blocks of comparable polarisation, on purpose.

    At 100 ohm against 5000 the smaller block carries 2% of the polarisation and a 1%-noise fit
    of the *true* topology does not recover it -- R1 comes back as 0.09 ohm and its time
    constant as 3e-15. That is an identifiability limit of the data, not something this module
    can read around, so the round trip is run where the fit can actually deliver.
    """
    truth = Circuit.parse("p(R1,C1)-p(R2,C2)")
    values = [100.0, 1e-6, 500.0, 1e-8]
    f = np.logspace(-1, 6, 71)
    clean = _spectrum(truth, values, f)
    rng = np.random.default_rng(0)
    noisy = Spectrum(
        f=f,
        z=clean.z * (1 + 0.01 * (rng.normal(size=f.size) + 1j * rng.normal(size=f.size))),
    )
    result = fit(truth, noisy, restarts=3, seed=0)
    reading = interpret(result, noisy)

    taus = sorted(r.tau for r in reading.relaxations)
    assert taus == pytest.approx(sorted([100.0 * 1e-6, 500.0 * 1e-8]), rel=0.05)
    assert all(r.tau_stderr is not None for r in reading.relaxations)
    dc = reading.get("r_dc")
    assert dc is not None and dc.value == pytest.approx(600.0, rel=0.05)
    # The poles are the invariant statement of the same two time constants.
    poles = sorted(m.tau for m in reading.modes if m.kind == "pole" and m.tau is not None)
    assert poles == pytest.approx(taus, rel=1e-6)
