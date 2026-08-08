"""Tests for the distribution of relaxation times (DRT) module (docs/DISCOVERY_V2_PLAN.md
gate G4) and the ``drt`` CLI subcommand.

Covers, in order:

1. **Gate G4 itself**: ``drt()`` must return the exact ``n_relaxations`` for 1-, 2- and 3-peak
   Debye spectra, 10/10 seeds at 0% and 1% noise, and the recovered peak positions and weights
   must land close to the truth.
2. The two-block Maxwell-Wagner case, the regression test for the peak-significance criterion
   (see ``DEFAULT_SIGNIFICANCE`` in the library).
3. Broadening detection: a depressed semicircle (CPE) is flagged, an ideal Debye peak is not.
4. ``well_described``: a spectrum outside the Debye model (a distributed inductive process)
   is reported as unrepresentable rather than given a bogus peak count.
5. Series-term auto-detection (``_series_terms``) and recovery of the series resistance.
6. Determinism and the public knobs (``lam``, ``points_per_decade``, ``significance``,
   ``prominence``).
7. Helper-level unit tests that pin down the numerics of the linear-algebra building blocks.
8. The ``drt`` CLI subcommand, and the ``discover --no-drt`` flag.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from autocircuit.cli.main import main
from autocircuit.core.drt import (
    _magnitude_at,
    _penalty_matrix,
    _series_terms,
    _solve_nonnegative,
    _tau_grid,
    drt,
)
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum

# =================================================================================================
# 1. Gate G4 -- the acceptance gate
# =================================================================================================


@dataclass(frozen=True)
class _PeakCase:
    """A spectrum built from ``n`` well-separated Debye (parallel R-C) blocks.

    ``true_taus`` and ``true_weights`` are the RC products and block resistances in the order
    the blocks appear in the circuit string, which is also ascending-tau order (each block's
    time constant is a decade or more past the previous one), matching the order ``drt()``
    reports peaks in.
    """

    circuit: str
    params: dict[str, float]
    f_min: float
    f_max: float
    true_taus: tuple[float, ...]
    true_weights: tuple[float, ...]


_GATE_G4_CASES = [
    _PeakCase(
        "R1-p(R2,C1)",
        {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-5},
        1e-1,
        1e6,
        (100.0 * 1e-5,),
        (100.0,),
    ),
    _PeakCase(
        "R1-p(R2,C1)-p(R3,C2)",
        {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-7, "R3.R": 200.0, "C2.C": 1e-4},
        1e-2,
        1e6,
        (100.0 * 1e-7, 200.0 * 1e-4),
        (100.0, 200.0),
    ),
    _PeakCase(
        "R1-p(R2,C1)-p(R3,C2)-p(R4,C3)",
        {
            "R1.R": 10.0,
            "R2.R": 100.0,
            "C1.C": 1e-8,
            "R3.R": 150.0,
            "C2.C": 1e-6,
            "R4.R": 200.0,
            "C3.C": 1e-4,
        },
        1e-2,
        1e7,
        (100.0 * 1e-8, 150.0 * 1e-6, 200.0 * 1e-4),
        (100.0, 150.0, 200.0),
    ),
]

#: [measured] Worst case over all cases, noise levels and seeds 0..9 is 0.026 decades of tau
#: error and 1.4% of weight error; the tolerances below leave comfortable headroom.
_TAU_TOLERANCE_DECADES = 0.2
_WEIGHT_TOLERANCE_REL = 0.05


@pytest.mark.parametrize("noise", [0.0, 0.01])
@pytest.mark.parametrize("case", _GATE_G4_CASES, ids=lambda c: c.circuit)
def test_gate_g4_peak_count_is_exact_across_all_ten_seeds(
    case: _PeakCase, noise: float
) -> None:
    f = log_frequencies(case.f_min, case.f_max, 10)
    for seed in range(10):
        data = simulate(case.circuit, f, case.params, noise=noise, seed=seed)
        result = drt(data)
        assert result.n_relaxations == len(case.true_taus), (
            f"{case.circuit!r} noise={noise} seed={seed}: expected "
            f"{len(case.true_taus)} relaxations, got {result.n_relaxations}"
        )


@pytest.mark.parametrize("noise", [0.0, 0.01])
@pytest.mark.parametrize("case", _GATE_G4_CASES, ids=lambda c: c.circuit)
def test_gate_g4_recovers_peak_positions_and_weights(case: _PeakCase, noise: float) -> None:
    f = log_frequencies(case.f_min, case.f_max, 10)
    for seed in range(10):
        data = simulate(case.circuit, f, case.params, noise=noise, seed=seed)
        result = drt(data)
        assert len(result.peaks) == len(case.true_taus)
        for peak, true_tau, true_weight in zip(
            result.peaks, case.true_taus, case.true_weights, strict=True
        ):
            tau_error_decades = abs(math.log10(peak.tau) - math.log10(true_tau))
            assert tau_error_decades < _TAU_TOLERANCE_DECADES, (
                f"{case.circuit!r} noise={noise} seed={seed}: tau {peak.tau:.4g} is "
                f"{tau_error_decades:.3f} decades from the true {true_tau:.4g}"
            )
            weight_error = abs(peak.weight - true_weight) / true_weight
            assert weight_error < _WEIGHT_TOLERANCE_REL, (
                f"{case.circuit!r} noise={noise} seed={seed}: weight {peak.weight:.4g} is "
                f"{weight_error:.1%} off the true {true_weight:.4g}"
            )


# =================================================================================================
# 2. The Maxwell-Wagner two-block case -- regression test for the peak-significance criterion
# =================================================================================================


def test_maxwell_wagner_two_blocks_of_very_uneven_size_both_count() -> None:
    """The smaller block carries only ~2% of the total polarisation resistance here (R1 = 1e4
    ohm against R2 = 5e5 ohm), which is exactly the case DEFAULT_SIGNIFICANCE (see drt.py) was
    tuned against: prominence relative to the *tallest* peak would reject it outright, so this
    is the regression test that the weight-vs-noise criterion still finds it.
    """
    f = log_frequencies(1e-1, 1e7, 10)
    params = {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8}
    for seed in range(5):
        data = simulate("p(R1,C1)-p(R2,C2)", f, params, noise=0.01, seed=seed)
        result = drt(data)
        assert result.n_relaxations == 2, f"seed={seed}: got {result.n_relaxations} relaxations"


# =================================================================================================
# 3. Broadening detection
# =================================================================================================


def test_depressed_semicircle_from_a_cpe_is_flagged_broadened() -> None:
    data = simulate(
        "R1-p(R2,CPE1)",
        log_frequencies(1e-1, 1e6, 10),
        {"R1.R": 10.0, "R2.R": 100.0, "CPE1.Q": 1e-5, "CPE1.n": 0.7},
        noise=0.0,
        seed=0,
    )
    result = drt(data)
    assert len(result.peaks) >= 1
    assert result.peaks[0].broadened is True


def test_ideal_debye_peak_is_not_flagged_broadened() -> None:
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 10),
        {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-5},
        noise=0.0,
        seed=0,
    )
    result = drt(data)
    assert len(result.peaks) == 1
    assert result.peaks[0].broadened is False


# Deliberately no assertion on peak *count* for the CPE case at 1% noise: a CPE is genuinely an
# infinite distribution of relaxation times, not a finite sum, so how many discrete peaks the
# regularised inversion resolves out of it is inherently noise-sensitive. [measured] Across
# seeds 0..9 the count observed is 1 or 2 (the plan's own note allows up to 3); this is a
# property of the inversion under noise, not a library bug, so it is deliberately not pinned
# down here.


# =================================================================================================
# 4. well_described
# =================================================================================================


def test_capacitor_reference_is_not_well_described() -> None:
    """C1-R1-L1-SKINF1's skin-effect term is a distributed inductive process; no sum of
    capacitive RC relaxations can represent it. [measured] Max residual is about 64.8%.
    """
    data = simulate(
        "C1-R1-L1-SKINF1",
        log_frequencies(1e2, 1e9, 10),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
        noise=0.01,
        seed=0,
    )
    result = drt(data)
    assert result.well_described is False
    hints = result.hints()
    assert any("cannot represent" in line for line in hints)
    assert not any("relaxation" in line and "shows" in line for line in hints)


def test_clean_debye_spectrum_is_well_described() -> None:
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 10),
        {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-5},
        noise=0.01,
        seed=0,
    )
    result = drt(data)
    assert result.well_described is True
    assert any("DRT shows" in line for line in result.hints())


# =================================================================================================
# 5. Series-term recovery and auto-detection
# =================================================================================================


def test_series_terms_switches_on_inductance_for_inductive_high_frequency_data() -> None:
    data = simulate(
        "R1-L1", log_frequencies(1e0, 1e9, 10), {"R1.R": 10.0, "L1.L": 1e-6}, seed=0
    )
    add_l, add_c = _series_terms(data, None, None)
    assert add_l is True
    assert add_c is False


def test_series_terms_switches_on_capacitance_for_blocking_low_frequency_data() -> None:
    data = simulate(
        "R1-C1", log_frequencies(1e-1, 1e5, 10), {"R1.R": 10.0, "C1.C": 1e-6}, seed=0
    )
    add_l, add_c = _series_terms(data, None, None)
    assert add_l is False
    assert add_c is True


def test_series_terms_switches_off_both_for_a_purely_resistive_endpoint_spectrum() -> None:
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 10),
        {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-5},
        seed=0,
    )
    add_l, add_c = _series_terms(data, None, None)
    assert add_l is False
    assert add_c is False


def test_explicit_series_arguments_override_the_automatic_choice() -> None:
    # This spectrum's endpoints are purely resistive, so the automatic choice is (False, False)
    # (checked above); forcing both on must override that regardless of the data.
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 10),
        {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-5},
        seed=0,
    )
    assert _series_terms(data, True, True) == (True, True)
    assert _series_terms(data, False, False) == (False, False)
    assert _series_terms(data, True, None) == (True, False)
    assert _series_terms(data, None, True) == (False, True)


def test_series_resistance_is_recovered_within_a_few_percent() -> None:
    # [measured] Worst case across seeds 0..9 at 1% noise is 3.1% error; 0% noise is ~0.002%.
    f = log_frequencies(1e-1, 1e6, 10)
    params = {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-5}
    for seed in range(10):
        data = simulate("R1-p(R2,C1)", f, params, noise=0.01, seed=seed)
        result = drt(data)
        assert result.r_inf == pytest.approx(10.0, rel=0.05), f"seed={seed}"


# =================================================================================================
# 6. Determinism and knobs
# =================================================================================================


def _two_peak_spectrum(seed: int = 3, noise: float = 0.01) -> Spectrum:
    return simulate(
        "R1-p(R2,C1)-p(R3,C2)",
        log_frequencies(1e-2, 1e6, 10),
        {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-7, "R3.R": 200.0, "C2.C": 1e-4},
        noise=noise,
        seed=seed,
    )


def test_drt_is_deterministic_on_repeated_calls() -> None:
    data = _two_peak_spectrum()
    first = drt(data)
    second = drt(data)
    assert np.array_equal(first.gamma, second.gamma)
    assert np.array_equal(first.tau, second.tau)
    assert first.lam == second.lam
    assert first.lam_rule == second.lam_rule
    assert first.r_inf == second.r_inf
    assert first.n_relaxations == second.n_relaxations
    for peak_a, peak_b in zip(first.peaks, second.peaks, strict=True):
        assert peak_a == peak_b


def test_fixed_lam_sets_lam_rule_and_the_given_value() -> None:
    data = _two_peak_spectrum()
    result = drt(data, lam=0.5)
    assert result.lam_rule == "fixed"
    assert result.lam == pytest.approx(0.5)


def test_larger_points_per_decade_gives_a_finer_tau_grid() -> None:
    data = _two_peak_spectrum()
    coarse = drt(data, points_per_decade=5)
    fine = drt(data, points_per_decade=20)
    assert fine.tau.size > coarse.tau.size


def test_raising_significance_never_increases_the_peak_count() -> None:
    data = _two_peak_spectrum(seed=0, noise=0.01)
    grid = [1.0, 4.0, 8.0, 16.0, 32.0, 64.0]
    counts = [drt(data, significance=s).n_relaxations for s in grid]
    # Pairwise adjacent comparison: counts and counts[1:] are the same list offset by one, so
    # they differ in length by design.
    assert all(a >= b for a, b in zip(counts, counts[1:], strict=False)), counts


def test_raising_prominence_never_increases_the_peak_count() -> None:
    data = _two_peak_spectrum(seed=0, noise=0.01)
    grid = [0.1, 0.3, 0.5, 0.7, 0.9]
    counts = [drt(data, prominence=p).n_relaxations for p in grid]
    # Pairwise adjacent comparison: counts and counts[1:] are the same list offset by one, so
    # they differ in length by design.
    assert all(a >= b for a, b in zip(counts, counts[1:], strict=False)), counts


# =================================================================================================
# 7. Helper-level unit tests
# =================================================================================================


def test_tau_grid_spans_the_measured_range_extended_by_extension_decades() -> None:
    omega = 2.0 * math.pi * np.logspace(2.0, 6.0, 20)
    extension = 1.0
    tau = _tau_grid(omega, points_per_decade=10, extension_decades=extension)
    expected_lo = 10.0 ** (math.log10(1.0 / omega.max()) - extension)
    expected_hi = 10.0 ** (math.log10(1.0 / omega.min()) + extension)
    assert tau.min() == pytest.approx(expected_lo, rel=1e-9)
    assert tau.max() == pytest.approx(expected_hi, rel=1e-9)


def test_tau_grid_density_matches_points_per_decade() -> None:
    omega = 2.0 * math.pi * np.logspace(2.0, 6.0, 20)
    coarse = _tau_grid(omega, points_per_decade=10, extension_decades=1.0)
    fine = _tau_grid(omega, points_per_decade=20, extension_decades=1.0)
    # Range is unchanged (6 decades of data + 1 at each end = 8 decades), so density doubling
    # should roughly double the point count.
    assert fine.size == pytest.approx(2 * coarse.size, rel=0.05)


def test_penalty_matrix_leaves_series_columns_unpenalised() -> None:
    n_tau, n_series = 6, 2
    n_columns = n_tau + n_series
    rng = np.random.default_rng(0)
    scale = rng.uniform(0.5, 5.0, n_columns)
    penalty = _penalty_matrix(n_tau, n_columns, scale)
    assert penalty.shape == (n_tau - 2, n_columns)
    assert np.all(penalty[:, :n_series] == 0.0)


def test_penalty_matrix_reproduces_the_second_difference_of_physical_gamma() -> None:
    n_tau, n_series = 6, 2
    n_columns = n_tau + n_series
    rng = np.random.default_rng(0)
    scale = rng.uniform(0.5, 5.0, n_columns)
    penalty = _penalty_matrix(n_tau, n_columns, scale)

    physical = rng.uniform(-1.0, 1.0, n_columns)
    scaled = physical * scale
    result = penalty @ scaled

    gamma = physical[n_series:]
    expected = gamma[:-2] - 2.0 * gamma[1:-1] + gamma[2:]
    np.testing.assert_allclose(result, expected)


def test_magnitude_at_interpolates_exactly_at_measured_points() -> None:
    data = simulate(
        "R1-C1", log_frequencies(1e2, 1e6, 10), {"R1.R": 100.0, "C1.C": 1e-7}, seed=0
    )
    omega = data.omega
    magnitude = np.abs(data.z)
    i = 5
    tau_peak = 1.0 / omega[i]
    assert _magnitude_at(omega, magnitude, tau_peak) == pytest.approx(magnitude[i], rel=1e-9)


def test_magnitude_at_clamps_outside_the_measured_range() -> None:
    data = simulate(
        "R1-C1", log_frequencies(1e2, 1e6, 10), {"R1.R": 100.0, "C1.C": 1e-7}, seed=0
    )
    omega = data.omega
    magnitude = np.abs(data.z)
    # A huge tau corresponds to an omega far below the measured range -> clamped at the bottom.
    below = _magnitude_at(omega, magnitude, 1e10)
    assert below == pytest.approx(magnitude[0], rel=1e-6)
    # A tiny tau corresponds to an omega far above the measured range -> clamped at the top.
    above = _magnitude_at(omega, magnitude, 1e-10)
    assert above == pytest.approx(magnitude[-1], rel=1e-6)


def test_solve_nonnegative_never_returns_a_negative_coefficient() -> None:
    # A system whose unconstrained least-squares solution is strictly negative (a = identity,
    # b < 0 everywhere): the constrained solve must clip to zero rather than go negative.
    a = np.eye(3)
    penalty = np.zeros((0, 3))
    b = np.array([-1.0, -1.0, -1.0])
    scale = np.ones(3)
    x = _solve_nonnegative(a, b, penalty, 0.0, scale)
    assert np.all(x >= 0.0)


# =================================================================================================
# 8. CLI
# =================================================================================================

# Kept small so the tests stay fast; noise-free / low-noise circuits so the results are
# unambiguous with few points.
_DEBYE_CIRCUIT = "R1-p(R2,C1)"
_DEBYE_PARAMS = {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-5}
_CAPACITOR_CIRCUIT = "C1-R1-L1-SKINF1"
_CAPACITOR_PARAMS = {
    "C1.C": 1e-6,
    "R1.R": 1e-2,
    "L1.L": 5e-10,
    "SKINF1.A": 2e-5,
    "SKINF1.n": 0.5,
}


def _simulate_csv(
    tmp_path: Path,
    circuit: str,
    params: dict[str, float],
    name: str,
    *,
    f_min: float = 10.0,
    f_max: float = 1e6,
    points_per_decade: int = 6,
    noise: float = 0.0,
) -> Path:
    out = tmp_path / name
    argv = ["simulate", "-c", circuit]
    for key, value in params.items():
        argv += ["-p", f"{key}={value}"]
    argv += [
        "-o", str(out),
        "--fmin", str(f_min), "--fmax", str(f_max),
        "--points-per-decade", str(points_per_decade),
    ]
    if noise:
        argv += ["--noise", str(noise)]
    rc = main(argv)
    assert rc == 0
    return out


def test_cli_drt_runs_and_prints_a_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _simulate_csv(
        tmp_path, _DEBYE_CIRCUIT, _DEBYE_PARAMS, "debye.csv", f_min=1e-1, f_max=1e6,
        points_per_decade=10,
    )
    rc = main(["drt", str(data)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Distribution of relaxation times" in out
    assert "Relaxations" in out


def test_cli_drt_writes_json_and_distribution_files_with_expected_shape(
    tmp_path: Path,
) -> None:
    data = _simulate_csv(
        tmp_path, _DEBYE_CIRCUIT, _DEBYE_PARAMS, "debye.csv", f_min=1e-1, f_max=1e6,
        points_per_decade=10,
    )
    json_path = tmp_path / "drt.json"
    distribution_path = tmp_path / "drt_dist.csv"
    rc = main(
        ["drt", str(data), "--json", str(json_path), "--distribution", str(distribution_path)]
    )
    assert rc == 0

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    for key in (
        "n_relaxations", "well_described", "r_inf_ohm", "r_polarisation_ohm",
        "inductance_h", "capacitance_f", "lambda", "lambda_rule",
        "max_residual", "rms_residual", "peaks", "tau_s", "gamma_ohm",
    ):
        assert key in payload
    assert payload["n_relaxations"] == 1

    lines = distribution_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "tau_s,gamma_ohm"
    assert len(lines) > 1


def test_cli_drt_exit_code_1_when_data_is_not_well_described(tmp_path: Path) -> None:
    data = _simulate_csv(
        tmp_path, _CAPACITOR_CIRCUIT, _CAPACITOR_PARAMS, "cap.csv", f_min=1e2, f_max=1e9,
        points_per_decade=10, noise=0.01,
    )
    rc = main(["drt", str(data)])
    assert rc == 1


def test_cli_drt_exit_code_0_when_data_is_well_described(tmp_path: Path) -> None:
    data = _simulate_csv(
        tmp_path, _DEBYE_CIRCUIT, _DEBYE_PARAMS, "debye.csv", f_min=1e-1, f_max=1e6,
        points_per_decade=10,
    )
    rc = main(["drt", str(data)])
    assert rc == 0


_DISCOVER_KWARGS = ["--pool", "R,C", "--exhaustive-limit", "3", "--mode", "exhaustive"]


def test_cli_discover_prints_structure_probe_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _simulate_csv(tmp_path, "p(R1,C1)", {"R1.R": 220.0, "C1.C": 1e-7}, "disc.csv")
    rc = main(["discover", str(data), "--no-validate"] + _DISCOVER_KWARGS)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Structure probe" in out


def test_cli_discover_no_drt_suppresses_the_structure_probe(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _simulate_csv(tmp_path, "p(R1,C1)", {"R1.R": 220.0, "C1.C": 1e-7}, "disc.csv")
    rc = main(["discover", str(data), "--no-validate", "--no-drt"] + _DISCOVER_KWARGS)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Structure probe" not in out
