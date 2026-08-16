"""Model-selection criteria: the six information-criterion scores plus the sequential F-test.

Covers :mod:`autocircuit.core.stats` (the formulae, ``Statistics.criterion_value`` and the wire
round trip) and the criterion plumbing through :mod:`autocircuit.core.discover`
(``Candidate.score``, ``pareto_front``, ``DiscoveryResult`` and ``discover(..., criterion=...)``).
"""

from __future__ import annotations

import json
import math
import time

import numpy as np
import pytest

from autocircuit.core.discover import SCREENING_FALLBACK, _screening_score, discover, pareto_front
from autocircuit.core.fit import fit
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.stats import (
    CRITERIA,
    CRITERION_LABELS,
    CRITERION_NOTES,
    DEFAULT_CRITERION,
    FTEST_RANKING,
    SCORE_CRITERIA,
    Criterion,
    Statistics,
    f_test,
    information_criteria,
)

#: Truth used by every synthetic fixture in this module: one series resistor, one RC block.
TRUTH = {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8}


def _statistics(**overrides: float) -> Statistics:
    """A Statistics instance with distinct, easily-checked field values."""
    fields: dict[str, float] = {
        "aic": 1.0,
        "aicc": 2.0,
        "bic": 3.0,
        "caic": 4.0,
        "hqc": 5.0,
        "waic": 6.0,
        "p_waic": 2.5,
    }
    fields.update(overrides)
    return Statistics(
        n_data=84,
        n_params=3,
        ssr=1.5,
        chi2_reduced=0.02,
        stderr=np.zeros(3, dtype=np.float64),
        correlation=np.eye(3, dtype=np.float64),
        rank=3,
        aic=fields["aic"],
        aicc=fields["aicc"],
        bic=fields["bic"],
        caic=fields["caic"],
        hqc=fields["hqc"],
        waic=fields["waic"],
        p_waic=fields["p_waic"],
    )


@pytest.fixture(scope="module")
def small_spectrum() -> Spectrum:
    """~43-point, 1% noise spectrum of R1-p(R2,C1); shared by the WAIC and discover tests."""
    f = log_frequencies(1e0, 1e6, 7)
    return simulate("R1-p(R2,C1)", f, TRUTH, noise=0.01, seed=0)


# =============================================================================================
# 1. The registry is internally consistent
# =============================================================================================


def test_criteria_registry_is_internally_consistent() -> None:
    """A criterion missing from a label/note table would surface as a KeyError in a report."""
    assert tuple(c for c in CRITERIA if c != "ftest") == SCORE_CRITERIA
    assert set(CRITERION_LABELS) == set(CRITERIA)
    assert set(CRITERION_NOTES) == set(CRITERIA)
    assert DEFAULT_CRITERION in CRITERIA
    assert FTEST_RANKING in SCORE_CRITERIA


# =============================================================================================
# 2. information_criteria: algebra, checked against independently written formulae
# =============================================================================================


def test_information_criteria_match_independently_written_formulae() -> None:
    """Each score must match its textbook formula, not merely be internally consistent."""
    ssr, n_data, n_params = 3.7, 60, 5
    result = information_criteria(ssr, n_data, n_params)

    deviance = n_data * math.log(ssr / n_data)
    expected_aic = deviance + 2.0 * n_params
    expected_aicc = expected_aic + 2.0 * n_params * (n_params + 1) / (n_data - n_params - 1)
    log_n = math.log(n_data)
    expected_bic = deviance + n_params * log_n
    expected_caic = deviance + n_params * (log_n + 1.0)
    expected_hqc = deviance + 2.0 * n_params * math.log(log_n)

    assert result["aic"] == pytest.approx(expected_aic)
    assert result["aicc"] == pytest.approx(expected_aicc)
    assert result["bic"] == pytest.approx(expected_bic)
    assert result["caic"] == pytest.approx(expected_caic)
    assert result["hqc"] == pytest.approx(expected_hqc)


def test_information_criteria_reports_waic_as_nan_without_residuals() -> None:
    """WAIC needs a Jacobian; without one it must be NaN, not a silently wrong number."""
    result = information_criteria(3.7, 60, 5)
    assert math.isnan(result["waic"])
    assert math.isnan(result["p_waic"])


# =============================================================================================
# 3. Ordering properties
# =============================================================================================


def test_every_score_increases_with_parameter_count_at_fixed_fit_quality() -> None:
    """A criterion that did not penalise extra parameters would prefer any bigger model."""
    ssr, n_data = 4.2, 80
    for name in ("aic", "aicc", "bic", "caic", "hqc"):
        values = [information_criteria(ssr, n_data, k)[name] for k in range(1, 20)]
        assert all(b > a for a, b in zip(values, values[1:], strict=False)), name


def test_bic_penalty_exceeds_aic_penalty_only_once_n_passes_e_squared() -> None:
    """The crossover CRITERION_NOTES relies on (BIC beats AIC's penalty past n = e^2) must hold."""
    ssr, n_params = 5.0, 4
    large = information_criteria(ssr, 50, n_params)  # log(50) ~= 3.91 > 2
    small = information_criteria(ssr, 5, n_params)  # log(5) ~= 1.61 < 2
    assert (large["bic"] - large["aic"]) > 0.0
    assert (small["bic"] - small["aic"]) < 0.0


def test_caic_penalty_always_exceeds_bic_penalty() -> None:
    """CAIC is documented as 'BIC's penalty plus one per parameter'; the offset must be exact."""
    for n_data, n_params in [(30, 2), (200, 6), (1000, 10)]:
        result = information_criteria(1.0, n_data, n_params)
        assert result["caic"] - result["bic"] == pytest.approx(n_params)


# =============================================================================================
# 4. Statistics.criterion_value
# =============================================================================================


def test_criterion_value_returns_the_matching_attribute_for_each_score() -> None:
    """criterion_value must read the field with the same name as the criterion, not a fixed one."""
    stats = _statistics()
    for name in SCORE_CRITERIA:
        assert stats.criterion_value(name) == getattr(stats, name)


def test_criterion_value_of_ftest_reads_off_the_ftest_ranking_field() -> None:
    """ftest provides no score of its own; criterion_value must answer with FTEST_RANKING's."""
    stats = _statistics()
    assert FTEST_RANKING == "aic"
    assert stats.criterion_value("ftest") == stats.aic


# =============================================================================================
# 5. WAIC, on a real fit
# =============================================================================================


def test_waic_uses_the_data_resolved_parameter_count(small_spectrum: Spectrum) -> None:
    """WAIC's effective parameter count and score must track n_params and AIC respectively."""
    # Measured on this fixture: p_waic ~= 3.02 against n_params = 3 (seeds 0-4 range 2.75-3.26),
    # and waic - aic ranges -0.07 to +0.50 across those seeds. Both tolerances below carry
    # margin around those measurements rather than asserting bit equality, since WAIC and AIC
    # differ by construction (effective vs. nominal parameter count).
    result = fit("R1-p(R2,C1)", small_spectrum, restarts=3, seed=0)
    stats = result.statistics
    assert math.isfinite(stats.waic)
    assert stats.p_waic > 0.0
    assert 0.5 * stats.n_params < stats.p_waic < 2.0 * stats.n_params
    assert abs(stats.waic - stats.aic) < 5.0


# =============================================================================================
# 6. f_test
# =============================================================================================


def test_f_test_is_significant_for_genuinely_nested_models() -> None:
    """R1-R2 is nested in R1-p(R2,C1); on data with a real capacitor the test must catch it."""
    f = log_frequencies(1e0, 1e6, 7)
    data = simulate("R1-p(R2,C1)", f, TRUTH, noise=0.01, seed=2)
    simple = fit("R1-R2", data, restarts=3, seed=0)
    complex_ = fit("R1-p(R2,C1)", data, restarts=3, seed=0)

    result = f_test(
        simple.statistics.ssr,
        simple.statistics.n_params,
        complex_.statistics.ssr,
        complex_.statistics.n_params,
        complex_.statistics.n_data,
    )
    assert result is not None
    assert result.significant
    assert result.p < 1e-6


def test_f_test_returns_none_when_the_larger_model_has_no_more_parameters() -> None:
    """The comparison needs df1 > 0; equal or fewer parameters is not 'larger' at all."""
    assert f_test(ssr_simple=1.0, k_simple=3, ssr_complex=0.5, k_complex=3, n_data=50) is None
    assert f_test(ssr_simple=1.0, k_simple=4, ssr_complex=0.5, k_complex=3, n_data=50) is None


def test_f_test_returns_none_when_no_residual_degrees_of_freedom_remain() -> None:
    """The comparison needs df2 > 0; a model that uses up every residual cannot be tested."""
    assert f_test(ssr_simple=1.0, k_simple=2, ssr_complex=0.5, k_complex=10, n_data=10) is None
    assert f_test(ssr_simple=1.0, k_simple=2, ssr_complex=0.5, k_complex=11, n_data=10) is None


def test_f_test_reports_no_significance_when_the_larger_model_fits_no_better() -> None:
    """A larger model that does not reduce SSR must come back f=0, p=1, not an error."""
    tied = f_test(ssr_simple=1.0, k_simple=2, ssr_complex=1.0, k_complex=4, n_data=50)
    assert tied is not None
    assert tied.f == 0.0
    assert tied.p == 1.0
    assert not tied.significant

    worse = f_test(ssr_simple=1.0, k_simple=2, ssr_complex=1.2, k_complex=4, n_data=50)
    assert worse is not None
    assert worse.f == 0.0
    assert worse.p == 1.0


# =============================================================================================
# 7. pareto_front honours the criterion
# =============================================================================================


class _FakeCandidate:
    """A stand-in for Candidate, scored differently per criterion (like test_discover.py:138)."""

    def __init__(self, complexity: float, circuit: str, scores: dict[Criterion, float]) -> None:
        self.complexity = complexity
        self.circuit = circuit
        self._scores = scores

    def score(self, criterion: Criterion = DEFAULT_CRITERION) -> float:
        return self._scores[criterion]


def test_pareto_front_honours_the_chosen_criterion() -> None:
    """pareto_front must rank by whatever criterion it is given, not always the same one."""
    candidates = [
        _FakeCandidate(1.0, "A", {"aic": 10.0, "bic": 5.0}),
        _FakeCandidate(2.0, "B", {"aic": 5.0, "bic": 12.0}),
        _FakeCandidate(3.0, "C", {"aic": 6.0, "bic": 6.0}),
    ]
    front_aic = pareto_front(candidates, "aic")  # type: ignore[arg-type]
    front_bic = pareto_front(candidates, "bic")  # type: ignore[arg-type]
    assert [c.circuit for c in front_aic] == ["A", "B"]
    assert [c.circuit for c in front_bic] == ["A"]


# =============================================================================================
# 8. discover(..., criterion=...), end to end
# =============================================================================================


def test_discover_runs_and_ranks_by_every_criterion(small_spectrum: Spectrum) -> None:
    """Every criterion in CRITERIA must run through discover() and actually drive the ranking."""
    started = time.perf_counter()
    for criterion in CRITERIA:
        result = discover(
            small_spectrum,
            pool=("R", "C"),
            exhaustive_limit=3,
            mode="exhaustive",
            seed=0,
            criterion=criterion,
        )
        assert result.criterion == criterion
        scores = [c.score(criterion) for c in result.candidates]
        assert scores == sorted(scores)
        if criterion == "ftest":
            assert result.score_label == "AIC"
        else:
            assert result.score_label == CRITERION_LABELS[criterion]
    elapsed = time.perf_counter() - started
    print(f"discover() over all {len(CRITERIA)} criteria took {elapsed:.1f}s")
    assert elapsed < 90.0


def test_discover_rejects_an_unknown_criterion(small_spectrum: Spectrum) -> None:
    """An unrecognised criterion string must fail fast rather than silently fall back."""
    with pytest.raises(ValueError):
        discover(
            small_spectrum,
            pool=("R", "C"),
            exhaustive_limit=3,
            mode="exhaustive",
            criterion="bogus",  # type: ignore[arg-type]
        )


# =============================================================================================
# 9. _screening_score
# =============================================================================================


def test_screening_score_matches_information_criteria_for_the_computable_criteria() -> None:
    """For the five criteria a screening cost alone can answer, the two must agree exactly."""
    # The fallback for "waic" and "ftest" is already covered by
    # tests/test_discover_exhaustive.py::test_screening_falls_back_where_a_cost_is_not_enough.
    cost, n_params, n_data = 2.5e-3, 4, 140
    for name in ("aic", "aicc", "bic", "caic", "hqc"):
        expected = information_criteria(cost, n_data, n_params)[name]
        assert _screening_score(cost, n_params, n_data, name) == expected
    assert SCREENING_FALLBACK == "aic"


# =============================================================================================
# 10. Statistics wire round trip
# =============================================================================================


def test_statistics_wire_round_trip_preserves_the_new_fields() -> None:
    """to_wire/from_wire must not silently drop caic, hqc, waic or p_waic."""
    stats = _statistics()
    payload = json.loads(json.dumps(stats.to_wire()))
    back = Statistics.from_wire(payload)
    assert back.caic == stats.caic
    assert back.hqc == stats.hqc
    assert back.waic == stats.waic
    assert back.p_waic == stats.p_waic


def test_statistics_wire_round_trip_preserves_a_non_finite_waic() -> None:
    """A degenerate fit's WAIC can be -inf; the wire format must carry that exactly, not NaN it."""
    stats = _statistics(waic=float("-inf"))
    payload = json.loads(json.dumps(stats.to_wire()))
    back = Statistics.from_wire(payload)
    assert math.isinf(back.waic) and back.waic < 0.0


def test_statistics_wire_payload_is_json_javascript_can_parse() -> None:
    """json.dumps(..., allow_nan=False) must accept the payload: no bare Infinity/NaN tokens."""
    stats = _statistics(waic=float("-inf"))
    text = json.dumps(stats.to_wire(), allow_nan=False)
    assert "Infinity" not in text
    assert "NaN" not in text
    back = Statistics.from_wire(json.loads(text))
    assert math.isinf(back.waic) and back.waic < 0.0
