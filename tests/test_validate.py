"""Tests for the Lin-KK Kramers-Kronig validation in autocircuit.core.validate."""

from __future__ import annotations

import numpy as np
import pytest

from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.validate import (
    MODEL_FAILURE_RMS,
    RUNS_Z_LIMIT,
    WIRE_VERSION,
    _runs_z,
    _solve,
    lin_kk,
)
from autocircuit.core.weighting import weight_vectors

# Circuits used to exercise the noise-free / noisy passes below.
_CIRCUITS: list[tuple[str, dict[str, float]]] = [
    ("R1-C1-p(R2,C2)", {"R1.R": 10.0, "C1.C": 1e-7, "R2.R": 500.0, "C2.C": 1e-9}),
    ("R1-L1-C1", {"R1.R": 5.0, "L1.L": 1e-6, "C1.C": 1e-6}),
    (
        "p(R1,C1)-Ws1",
        {"R1.R": 100.0, "C1.C": 2e-7, "Ws1.R": 50.0, "Ws1.tau": 1e-3},
    ),
]


def _simulate(circuit: str, values: dict[str, float], **kwargs: object) -> Spectrum:
    f = log_frequencies(1.0, 1e6, points_per_decade=10)
    return simulate(circuit, f, values, **kwargs)


@pytest.mark.parametrize(("circuit", "values"), _CIRCUITS)
def test_lin_kk_passes_noise_free_synthetic_data(circuit: str, values: dict[str, float]) -> None:
    spectrum = _simulate(circuit, values)
    result = lin_kk(spectrum)
    assert result.passed
    assert result.max_residual < 1e-4


def test_lin_kk_passes_data_with_one_percent_noise_and_reports_random_residuals() -> None:
    circuit, values = _CIRCUITS[0]
    spectrum = _simulate(circuit, values, noise=0.01, seed=1)
    result = lin_kk(spectrum)
    assert result.passed
    assert not result.systematic
    # Random noise keeps the runs z-score comfortably above the systematic-pattern threshold.
    assert result.runs_z > RUNS_Z_LIMIT


def test_lin_kk_fails_on_smooth_multiplicative_drift() -> None:
    circuit, values = _CIRCUITS[0]
    spectrum = _simulate(circuit, values)
    ramp = np.linspace(1.0, 1.3, spectrum.n)
    drifted = Spectrum(spectrum.f, spectrum.z * ramp, dict(spectrum.metadata))

    result = lin_kk(drifted)
    assert not result.passed
    assert result.systematic
    assert result.runs_z < RUNS_Z_LIMIT
    # Well below the threshold, not just barely over it.
    assert result.runs_z < -5.0


def test_drift_is_blamed_on_the_data_because_the_model_did_track_it() -> None:
    """The other side of the resonator test below: here the KK model *does* follow the data.

    That is what makes the systematic residual evidence about the measurement, and it is the
    distinction ``model_failed`` draws. Asserted here so the two messages cannot both be
    reached by the same spectrum.
    """
    circuit, values = _CIRCUITS[0]
    spectrum = _simulate(circuit, values)
    ramp = np.linspace(1.0, 1.4, spectrum.n)
    drifted = Spectrum(spectrum.f, spectrum.z * ramp, dict(spectrum.metadata))

    result = lin_kk(drifted)
    assert not result.passed
    assert not result.model_failed
    assert result.rms_residual < 0.05
    assert "not consistent with a linear, causal, stationary system" in result.summary(drifted)


def test_a_resonance_is_not_reported_as_bad_data() -> None:
    """A Butterworth-Van Dyke resonator is KK-compliant by construction -- it is the exact
    response of a passive circuit -- but a Voigt series has only real poles and cannot express
    a complex pole pair. The test must fail (it could not be applied) without blaming the
    measurement, which is what it did before ``model_failed`` existed.
    """
    f = log_frequencies(1.6e5, 2.6e5, points_per_decade=1500)
    spectrum = simulate(
        "p(C1,R1-L1-C2)", f, {"C1.C": 2e-9, "R1.R": 40.0, "L1.L": 3.2e-3, "C2.C": 2e-10}
    )

    result = lin_kk(spectrum)
    assert not result.passed
    assert result.model_failed
    assert result.rms_residual > MODEL_FAILURE_RMS
    summary = result.summary(spectrum)
    assert "could not follow this data at all" in summary
    assert "not consistent with a linear" not in summary


def test_more_voigt_elements_do_not_rescue_a_resonance() -> None:
    """Why :data:`MODEL_FAILURE_RMS` is keyed on the residual and not on the model order.

    The residual is flat in M because the shape is unreachable, not because the order scan
    stopped early. Solved here at two orders 60x apart rather than through ``lin_kk``, which
    would choose an order for us and so could not show that the choice does not matter.
    """
    f = log_frequencies(1.6e5, 2.6e5, points_per_decade=1500)
    spectrum = simulate(
        "p(C1,R1-L1-C2)", f, {"C1.C": 2e-9, "R1.R": 40.0, "L1.L": 3.2e-3, "C2.C": 2e-10}
    )
    omega, z = spectrum.omega, spectrum.z
    w_re, w_im = weight_vectors(z, "modulus")

    def rms_at(m: int) -> float:
        tau = np.logspace(np.log10(1.0 / omega.max()), np.log10(1.0 / omega.min()), m)
        _, z_fit = _solve(omega, z, tau, w_re, w_im, True, True)
        return float(np.sqrt(np.mean(np.abs(z - z_fit) ** 2 / np.abs(z) ** 2)))

    stiff, generous = rms_at(3), rms_at(200)
    assert generous > MODEL_FAILURE_RMS
    # [measured] 1.24x. Drifting data, which the basis *can* express, improves ~11x over the
    # same range; the bar sits between the two.
    assert stiff / generous < 3.0


def test_lin_kk_series_rlc_is_exactly_representable() -> None:
    # A series R-L-C spectrum is literally in the Lin-KK basis (series R plus series L plus
    # series C), so the residual should be near machine precision. This is a regression test
    # for the column-scaling (Jacobi preconditioning) in validate._solve: without it, the
    # series-L and series-C columns differ by many orders of magnitude across a wide sweep and
    # lstsq truncates the solution, leaving a residual of about 7% instead of ~1e-15.
    f = log_frequencies(1.0, 1e6, points_per_decade=10)
    spectrum = simulate("R1-L1-C1", f, {"R1.R": 5.0, "L1.L": 1e-6, "C1.C": 1e-6})
    result = lin_kk(spectrum)
    assert result.max_residual < 1e-8


def test_noisy_but_valid_data_passes_even_though_its_residual_is_large() -> None:
    """The measured trap behind the order of the two questions in ``verdict``.

    Noise inflates the residual without being a KK violation. At 30% noise this spectrum is
    over ``MODEL_FAILURE_RMS`` while its residual signs are still random, so a consumer that
    asked the residual question first would report healthy data as untested.
    """
    circuit, values = _CIRCUITS[0]
    spectrum = _simulate(circuit, values, noise=0.30, seed=5)

    result = lin_kk(spectrum)
    assert result.model_failed
    assert result.passed
    assert result.verdict == "pass"


def test_drift_stays_a_verdict_about_the_data_at_every_magnitude() -> None:
    """A genuine violation is *tracked*, so it never reaches the inconclusive branch.

    [measured] 40%, 100%, 300% and 1000% drift give 2.5%, 4.1%, 8.0% and 15.0% RMS -- two
    orders of magnitude of drift, and the whole family stays under ``MODEL_FAILURE_RMS``.
    """
    circuit, values = _CIRCUITS[0]
    spectrum = _simulate(circuit, values)
    for drift in (0.4, 1.0, 3.0, 10.0):
        ramp = np.linspace(1.0, 1.0 + drift, spectrum.n)
        drifted = Spectrum(spectrum.f, spectrum.z * ramp, dict(spectrum.metadata))

        result = lin_kk(drifted)
        assert result.verdict == "fail", drift
        assert result.rms_residual < MODEL_FAILURE_RMS, drift


def test_a_series_resonance_is_representable_and_a_parallel_one_is_not() -> None:
    """The distinction is the *pole*, not the resonance, and it is easy to state too broadly.

    A series R-L-C is literally the three series terms of the Lin-KK basis, so it passes. The
    Butterworth-Van Dyke resonator's anti-resonance is a complex pole of Z, and no number of
    real-pole Voigt elements reaches it.
    """
    series = simulate(
        "L1-C1-R1",
        log_frequencies(1e4, 1e6, points_per_decade=300),
        {"L1.L": 1e-3, "C1.C": 1e-9, "R1.R": 20.0},
    )
    assert lin_kk(series).verdict == "pass"

    parallel = simulate(
        "p(C1,R1-L1-C2)",
        log_frequencies(1.6e5, 2.6e5, points_per_decade=1500),
        {"C1.C": 2e-9, "R1.R": 40.0, "L1.L": 3.2e-3, "C2.C": 2e-10},
    )
    assert lin_kk(parallel).verdict == "inconclusive"


def test_the_open_gap_at_moderate_damping_is_recorded_rather_than_claimed_fixed() -> None:
    """`MODEL_FAILURE_RMS` catches an unreachable shape only when the basis misses completely.

    [measured] The same resonator at mechanical Q = 5 leaves a residual of about 4.6% -- well
    under the threshold -- while the residual pattern is firmly systematic. It therefore still
    reports as a plain failure and still blames the measurement. This asserts the *current*
    behaviour so that the limitation is visible in the suite rather than only in prose; closing
    it means giving the basis complex poles, which is a change with its own measurement.
    """
    damped = simulate(
        "p(C1,R1-L1-C2)",
        log_frequencies(1.6e5, 2.6e5, points_per_decade=1500),
        # R = 2*pi*fs*L / Q with Q = 5.
        {"C1.C": 2e-9, "R1.R": 800.0, "L1.L": 3.2e-3, "C2.C": 2e-10},
    )

    result = lin_kk(damped)
    assert result.verdict == "fail"
    assert result.rms_residual < MODEL_FAILURE_RMS
    assert result.systematic


def test_wire_carries_the_verdict() -> None:
    circuit, values = _CIRCUITS[0]
    spectrum = _simulate(circuit, values)
    wire = lin_kk(spectrum).to_wire(spectrum)

    assert wire["version"] == WIRE_VERSION
    assert wire["verdict"] in {"pass", "fail", "inconclusive"}
    # The browser reads `verdict` rather than rebuilding it, so both must travel and agree.
    assert wire["verdict"] == ("pass" if wire["passed"] else wire["verdict"])
    assert isinstance(wire["summary"], str)


def test_runs_z_is_near_zero_for_random_signs() -> None:
    rng = np.random.default_rng(0)
    random_signs = rng.choice([-1.0, 1.0], size=400)
    z = _runs_z(random_signs)
    assert abs(z) < 3.0


def test_runs_z_is_strongly_negative_for_a_constant_sign_sequence() -> None:
    constant_sign = np.ones(200)
    z = _runs_z(constant_sign)
    assert z < RUNS_Z_LIMIT
    assert z < -10.0


def test_runs_z_is_zero_below_the_minimum_sample_size() -> None:
    # The function bails out (returns 0.0) rather than computing a noisy statistic on too few
    # sign changes to be meaningful.
    tiny = np.array([1.0, -1.0, 1.0, -1.0, 1.0])
    assert _runs_z(tiny) == 0.0
