"""Tests for the pure scoring helpers of ``benchmarks/autoeis_round/score.py``.

The referee itself needs fitted spectra and is exercised by the round; these are the two pieces
that decide what the round is *allowed to conclude* -- the paired test and the value-matched
parameter comparison -- and both are small enough to check exactly.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "autoeis_round"))

from score import _worst_deviation, mcnemar_exact, resolvable_discordant  # noqa: E402


class TestMcNemarExact:
    def test_no_discordant_pairs_is_no_evidence(self) -> None:
        assert mcnemar_exact(0, 0) == 1.0

    @pytest.mark.parametrize(
        ("only_a", "expected"),
        [(1, 1.0), (2, 0.5), (3, 0.25), (4, 0.125), (5, 0.0625), (6, 0.03125)],
    )
    def test_one_sided_counts_match_the_binomial(self, only_a: int, expected: float) -> None:
        # Two-sided exact p for an all-in-one-direction split is 2 * (1/2)**n.
        assert mcnemar_exact(only_a, 0) == pytest.approx(expected)

    def test_is_symmetric_in_its_two_arguments(self) -> None:
        assert mcnemar_exact(8, 4) == mcnemar_exact(4, 8)

    def test_an_even_split_is_no_evidence(self) -> None:
        assert mcnemar_exact(10, 10) == 1.0

    def test_never_exceeds_one(self) -> None:
        for a in range(6):
            for b in range(6):
                assert mcnemar_exact(a, b) <= 1.0


class TestResolvableDiscordant:
    def test_six_discordant_runs_are_needed_however_many_pairs(self) -> None:
        # This is the number the round pre-registers: five all in one direction reach only
        # p = 0.0625, so no arena, however large, can call a difference on fewer than six.
        for n_pairs in (6, 20, 40, 100, 1000):
            assert resolvable_discordant(n_pairs) == 6

    def test_reports_unreachable_when_there_are_too_few_pairs(self) -> None:
        # With fewer pairs than that, the answer must exceed the pair count rather than
        # pretending some smaller difference would have been significant.
        for n_pairs in (1, 2, 3, 4, 5):
            assert resolvable_discordant(n_pairs) > n_pairs


class TestWorstDeviation:
    def test_exact_recovery_is_zero(self) -> None:
        truth = {"R1.R": 10.0, "R2.R": 1000.0, "CPE1.Q": 1e-6, "CPE1.n": 0.9}
        assert _worst_deviation(dict(truth), truth) == 0.0

    def test_permuted_labels_still_score_zero(self) -> None:
        # Blocks in series carry a permutation symmetry, so a name-by-name comparison of a
        # recovered R1 against a generating R1 is meaningless. Only value matching means
        # anything, and this is the case that proves the difference.
        truth = {"R1.R": 10.0, "R2.R": 1000.0, "CPE1.Q": 1e-6, "CPE1.n": 0.9}
        permuted = {"R1.R": 1000.0, "R2.R": 10.0, "CPE1.Q": 1e-6, "CPE1.n": 0.9}
        assert _worst_deviation(permuted, truth) == 0.0

    def test_reports_the_worst_relative_error(self) -> None:
        truth = {"R1.R": 10.0, "R2.R": 1000.0}
        recovered = {"R1.R": 11.0, "R2.R": 1000.0}
        assert _worst_deviation(recovered, truth) == pytest.approx(0.1)

    def test_worst_wins_over_best(self) -> None:
        truth = {"R1.R": 10.0, "R2.R": 1000.0}
        recovered = {"R1.R": 10.0, "R2.R": 1500.0}
        assert _worst_deviation(recovered, truth) == pytest.approx(0.5)

    def test_a_different_parameter_shape_is_not_a_score(self) -> None:
        truth = {"R1.R": 10.0, "R2.R": 1000.0, "CPE1.Q": 1e-6, "CPE1.n": 0.9}
        assert math.isnan(_worst_deviation({"R1.R": 10.0}, truth))

    def test_a_different_element_mix_is_not_a_score(self) -> None:
        truth = {"R1.R": 10.0, "C1.C": 1e-6}
        assert math.isnan(_worst_deviation({"R1.R": 10.0, "L1.L": 1e-6}, truth))
