"""Tests for the Lin-KK Kramers-Kronig validation in autocircuit.core.validate."""

from __future__ import annotations

import numpy as np
import pytest

from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.validate import RUNS_Z_LIMIT, _runs_z, lin_kk

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
