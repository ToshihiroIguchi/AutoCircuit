"""End-to-end tests for the autocircuit command line, driven through main(argv) directly."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from autocircuit.cli.main import main
from autocircuit.core.elements import REGISTRY
from autocircuit.io import read as read_spectrum

# Kept small so the whole suite stays fast; the circuits below are noise-free and unambiguous,
# so a couple of cheap restarts already converge to the exact answer.
_FIT_KWARGS = ["--restarts", "2", "--popsize", "10", "--maxiter", "80", "--no-validate"]


def _simulate_csv(
    tmp_path: Path, circuit: str, params: dict[str, float], name: str = "sim.csv"
) -> Path:
    out = tmp_path / name
    argv = ["simulate", "-c", circuit]
    for key, value in params.items():
        argv += ["-p", f"{key}={value}"]
    argv += [
        "-o", str(out),
        "--fmin", "10", "--fmax", "1000000", "--points-per-decade", "6",
    ]
    rc = main(argv)
    assert rc == 0
    return out


# =============================================================================================
# elements
# =============================================================================================


def test_elements_lists_every_registry_code_and_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["elements"])
    assert rc == 0
    out = capsys.readouterr().out
    for code in REGISTRY:
        assert code in out


# =============================================================================================
# simulate
# =============================================================================================


def test_simulate_writes_a_csv_readable_back_with_the_right_point_count(tmp_path: Path) -> None:
    out = tmp_path / "spectrum.csv"
    rc = main(
        [
            "simulate", "-c", "R1-C1",
            "-p", "R1.R=100", "-p", "C1.C=1e-7",
            "-o", str(out),
            "--fmin", "100", "--fmax", "100000", "--points-per-decade", "5",
        ]
    )
    assert rc == 0
    assert out.exists()

    spectrum = read_spectrum(out)
    # 3 decades (100 Hz .. 100 kHz) at 5 points/decade + 1 endpoint.
    assert spectrum.n == 16
    assert spectrum.f[0] == pytest.approx(100.0)
    assert spectrum.f[-1] == pytest.approx(100000.0)


# =============================================================================================
# fit
# =============================================================================================


def test_fit_recovers_true_parameters_from_noise_free_data(tmp_path: Path) -> None:
    true_values = {"R1.R": 220.0, "C1.C": 1e-7}
    data = _simulate_csv(tmp_path, "p(R1,C1)", true_values)
    report_path = tmp_path / "fit.json"

    rc = main(
        ["fit", str(data), "-c", "p(R1,C1)", "--json", str(report_path)] + _FIT_KWARGS
    )
    assert rc == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    for name, true_value in true_values.items():
        fitted = report["parameters"][name]["value"]
        assert fitted == pytest.approx(true_value, rel=0.01)


def test_fit_fix_holds_a_parameter_exactly_at_the_given_value(tmp_path: Path) -> None:
    true_values = {"R1.R": 220.0, "C1.C": 1e-7}
    data = _simulate_csv(tmp_path, "p(R1,C1)", true_values)
    report_path = tmp_path / "fit_fixed.json"

    fixed_c = 5e-7  # deliberately wrong, to prove it is held rather than fitted
    rc = main(
        [
            "fit", str(data), "-c", "p(R1,C1)",
            "--fix", f"C1.C={fixed_c}",
            "--json", str(report_path),
        ] + _FIT_KWARGS
    )
    assert rc == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["parameters"]["C1.C"]["fixed"] is True
    assert report["parameters"]["C1.C"]["value"] == pytest.approx(fixed_c, rel=1e-12)
    assert report["parameters"]["R1.R"]["fixed"] is False


# =============================================================================================
# validate
# =============================================================================================


def test_validate_exits_0_on_clean_data_and_1_on_drifting_data(tmp_path: Path) -> None:
    import numpy as np

    from autocircuit.core.spectrum import Spectrum
    from autocircuit.io import write_csv

    clean = _simulate_csv(tmp_path, "R1-C1", {"R1.R": 100.0, "C1.C": 1e-7})
    rc = main(["validate", str(clean)])
    assert rc == 0

    spectrum = read_spectrum(clean)
    ramp = np.linspace(1.0, 1.3, spectrum.n)
    drifted = Spectrum(spectrum.f, spectrum.z * ramp)
    drifted_path = tmp_path / "drift.csv"
    write_csv(drifted, drifted_path)

    rc = main(["validate", str(drifted_path)])
    assert rc == 1


def test_validate_exits_2_when_the_test_could_not_be_applied(tmp_path: Path) -> None:
    """A Butterworth-Van Dyke resonator is KK-compliant, and the Voigt basis cannot express it.

    Neither 0 nor 1 is honest here: 0 would claim the data had been validated, and 1 would make
    `validate && fit` refuse a perfectly good measurement. Hence a third code.
    """
    out = tmp_path / "bvd.csv"
    rc = main([
        "simulate", "-c", "p(C1,R1-L1-C2)",
        "-p", "C1.C=2e-9", "-p", "R1.R=40", "-p", "L1.L=0.0032", "-p", "C2.C=2e-10",
        "--fmin", "160000", "--fmax", "260000", "--points-per-decade", "1500",
        "-o", str(out),
    ])
    assert rc == 0

    assert main(["validate", str(out)]) == 2


# =============================================================================================
# convert
# =============================================================================================


def test_convert_round_trips_csv_through_zview_and_back(tmp_path: Path) -> None:
    csv_path = _simulate_csv(tmp_path, "R1-C1", {"R1.R": 100.0, "C1.C": 1e-7})
    z_path = tmp_path / "roundtrip.z"
    rc = main(["convert", str(csv_path), "-o", str(z_path)])
    assert rc == 0
    assert z_path.exists()

    csv_back = tmp_path / "back.csv"
    rc = main(["convert", str(z_path), "-o", str(csv_back)])
    assert rc == 0

    original = read_spectrum(csv_path)
    round_tripped = read_spectrum(csv_back)
    import numpy as np

    np.testing.assert_allclose(round_tripped.f, original.f)
    np.testing.assert_allclose(round_tripped.z, original.z, rtol=1e-9)


# =============================================================================================
# discover
# =============================================================================================

# Kept tiny (few points, two-element pool, a low exhaustive limit) so these tests run in
# seconds rather than minutes.
_DISCOVER_KWARGS = ["--pool", "R,C", "--exhaustive-limit", "3", "--no-validate"]


def _simulate_discover_csv(tmp_path: Path) -> Path:
    return _simulate_csv(
        tmp_path,
        "p(R1,C1)",
        {"R1.R": 220.0, "C1.C": 1e-7},
        name="discover_sim.csv",
    )


def test_discover_mode_exhaustive_reports_mode_and_completeness(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _simulate_discover_csv(tmp_path)

    rc = main(["discover", str(data), "--mode", "exhaustive"] + _DISCOVER_KWARGS)
    assert rc == 0

    out = capsys.readouterr().out
    assert "mode: exhaustive" in out
    assert "Coverage: every plausible topology with up to 3 elements" in out


def test_discover_mode_exhaustive_json_payload_has_mode_and_complete_up_to(
    tmp_path: Path,
) -> None:
    data = _simulate_discover_csv(tmp_path)
    report_path = tmp_path / "discover.json"

    rc = main(
        ["discover", str(data), "--mode", "exhaustive", "--json", str(report_path)]
        + _DISCOVER_KWARGS
    )
    assert rc == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "exhaustive"
    assert report["complete_up_to"] == 3


def test_discover_interpret_reads_the_class_and_not_only_the_recommendation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`CLAUDE.md` purpose point 2, on the mode that is the project's headline.

    A discovery report interpreting only its recommendation would state a form-dependent number
    -- how many relaxations the part shows -- as if the measurement had decided it. So the
    reading is checked against the recommendation's whole equivalence class, and the report says
    what the class agreed on. Asserted on both the printed report and the JSON one.
    """
    data = _simulate_discover_csv(tmp_path)
    report_path = tmp_path / "discover.json"

    rc = main(
        ["discover", str(data), "--mode", "exhaustive", "--interpret", "--no-drt",
         "--json", str(report_path)]
        + _DISCOVER_KWARGS
    )
    assert rc == 0

    out = capsys.readouterr().out
    assert "From the spectrum (the same for every equivalent topology):" in out
    assert "r_polarisation" in out

    report = json.loads(report_path.read_text(encoding="utf-8"))
    reading = report["interpretation"]
    assert reading["circuit"] == report["recommended"]["circuit"]
    # The class is carried, and so is the per-quantity agreement it was checked with -- a claim
    # of invariance nothing measures is the label this whole module exists to avoid.
    assert reading["class_members"][0] == reading["circuit"]
    invariant = [s for s in reading["class_spread"] if s["invariant"]]
    assert invariant, "nothing was marked invariant, so the check proved nothing"
    assert all(s["spread"] < 1e-6 for s in invariant), invariant


def test_discover_mode_evolve_does_not_claim_completeness(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _simulate_discover_csv(tmp_path)

    rc = main(
        [
            "discover", str(data), "--mode", "evolve",
            "--pool", "R,C", "--no-validate",
            "--generations", "2", "--population", "8", "--max-elements", "3",
        ]
    )
    assert rc == 0

    out = capsys.readouterr().out
    assert "sampled, not exhaustive" in out


def test_discover_with_an_invalid_mode_exits_non_zero(tmp_path: Path) -> None:
    data = _simulate_discover_csv(tmp_path)

    with pytest.raises(SystemExit):
        main(["discover", str(data), "--mode", "bogus"] + _DISCOVER_KWARGS)


def test_discover_with_skeleton_prints_the_pre_run_arithmetic_and_named_coverage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--skeleton`` prints the size-to-limit arithmetic before the search runs (a total
    element count is not what a user thinking in "elements I'm adding" expects), and the
    coverage line that follows the search must name the skeleton -- an unconstrained-looking
    "Coverage:" line under a skeleton run would be exactly the misleading report
    docs/PARTIAL_TOPOLOGY_PLAN.md section 3 warns about.
    """
    data = _simulate_discover_csv(tmp_path)

    rc = main(
        ["discover", str(data), "--mode", "exhaustive", "--skeleton", "R1-C1"]
        + _DISCOVER_KWARGS
    )
    assert rc == 0

    out = capsys.readouterr().out
    assert "Skeleton" in out
    assert "i.e. up to" in out
    assert "that contains R1-C1" in out


def test_discover_excluded_equivalents_requires_a_skeleton(tmp_path: Path) -> None:
    """Without a skeleton nothing was excluded, so the flag has nothing to compute -- and
    silently doing nothing would look like "nothing was excluded", which is a different claim.

    It must also fail *before* the search: this test runs in milliseconds only because the
    check happens up front, and a user given the same message after a multi-minute enumeration
    would have waited for nothing.
    """
    data = _simulate_discover_csv(tmp_path)
    with pytest.raises(SystemExit, match="needs --skeleton"):
        main(["discover", str(data), "--excluded-equivalents"] + _DISCOVER_KWARGS)


def test_discover_excluded_equivalents_reports_what_the_assertion_removed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The opt-in pass of section 3.3, end to end. It is opt-in because it costs about as much
    as the search itself (1,132 screens and 137 s on one core at four elements), so the flag
    existing and doing the work is the thing to check.
    """
    data = _simulate_discover_csv(tmp_path)
    rc = main(
        ["discover", str(data), "--mode", "exhaustive", "--skeleton", "p(R1,C1)",
         "--excluded-equivalents"] + _DISCOVER_KWARGS
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "What the skeleton excluded" in out
    assert "topologies with" in out


def test_discover_csv_writes_the_candidate_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The table the browser downloads, written by the same renderer. It exists on the command
    line so that there is one implementation of it and one place to notice when it is wrong.
    """
    data = _simulate_discover_csv(tmp_path)
    table = tmp_path / "candidates.csv"
    rc = main(["discover", str(data), "--mode", "exhaustive", "--csv", str(table)]
              + _DISCOVER_KWARGS)
    assert rc == 0
    assert "Wrote the candidate table" in capsys.readouterr().out

    rows = list(csv.DictReader(table.read_text(encoding="utf-8").splitlines()))
    assert rows
    assert sum(int(row["recommended"]) for row in rows) == 1
    assert all(row["circuit"] for row in rows)
    # A circuit string contains commas -- p(R1,C1) -- so the quoting has to be real CSV
    # quoting rather than a join, or every parallel block would split into two columns.
    assert any("," in row["circuit"] for row in rows)


def test_discover_json_report_with_skeleton_has_skeleton_and_named_coverage(
    tmp_path: Path,
) -> None:
    data = _simulate_discover_csv(tmp_path)
    report_path = tmp_path / "discover_skeleton.json"

    rc = main(
        [
            "discover", str(data), "--mode", "exhaustive", "--skeleton", "R1-C1",
            "--json", str(report_path),
        ]
        + _DISCOVER_KWARGS
    )
    assert rc == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["skeleton"] == "R1-C1"
    assert "that contains" in report["coverage"]


# =============================================================================================
# Error handling
# =============================================================================================


def test_fit_with_a_bad_circuit_string_returns_a_non_zero_exit_code(tmp_path: Path) -> None:
    data = _simulate_csv(tmp_path, "R1-C1", {"R1.R": 100.0, "C1.C": 1e-7})
    # "Q1" is not a known element code, so Circuit.parse raises CircuitSyntaxError, a subclass
    # of ValueError, which main() catches and turns into exit code 2.
    rc = main(["fit", str(data), "-c", "Q1", "--no-validate"])
    assert rc != 0


def test_simulate_with_a_missing_param_value_raises_systemexit(tmp_path: Path) -> None:
    out = tmp_path / "unused.csv"
    # R1-C1 needs both R1.R and C1.C; only R1.R is supplied. cmd_simulate raises SystemExit
    # directly (not routed through main()'s try/except), so it propagates as SystemExit.
    with pytest.raises(SystemExit):
        main(
            [
                "simulate", "-c", "R1-C1", "-p", "R1.R=100",
                "-o", str(out), "--fmin", "100", "--fmax", "1000",
            ]
        )
    assert not out.exists()


def test_param_option_without_an_equals_sign_raises_systemexit(tmp_path: Path) -> None:
    out = tmp_path / "unused2.csv"
    with pytest.raises(SystemExit):
        main(["simulate", "-c", "R1", "-p", "R1.R", "-o", str(out)])
