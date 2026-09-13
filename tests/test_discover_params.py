"""The parameter budget: what ``discover(max_params=...)`` enumerates, and what it may claim.

A ``C`` costs one free parameter and a ``CPE`` two, so an element cap is a different amount of
model freedom in every pool. ``max_params`` budgets the enumeration in the currency the data is
actually commensurable with, and the reporting question that comes with it is the one this file
is mostly about: :attr:`DiscoveryResult.complete_up_to` keeps its exact meaning (largest element
count whose topologies were *all* evaluated) and is *derived* from the parameter level reached,
never repurposed -- so every existing consumer keeps reading a field that is still true, merely
smaller.

See ``docs/PARAM_BUDGET_PLAN.md`` sections 4 and 6.
"""

from __future__ import annotations

import pytest

from autocircuit.core.circuit import count_elements
from autocircuit.core.discover import (
    MAX_PARAM_BUDGET,
    discover,
    enumerate_candidates,
)
from autocircuit.core.enumerate import count_topologies_by_params
from autocircuit.core.simulate import log_frequencies, simulate

TWO_BLOCK = {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8, "R3.R": 2e3, "C2.C": 1e-5}


def _spectrum(noise: float = 0.0, seed: int = 0, points: int = 8):
    """``R1-p(R2,C1)-p(R3,C2)``: five elements, five parameters, two relaxations."""
    return simulate(
        "R1-p(R2,C1)-p(R3,C2)",
        log_frequencies(1e-1, 1e6, points),
        TWO_BLOCK,
        noise=noise,
        seed=seed,
    )


# -- what gets enumerated --------------------------------------------------------------------


def test_the_budget_enumerates_the_whole_parameter_axis_space() -> None:
    """Against the independent per-level count, with the feasibility filter switched off.

    The filter is data-dependent, so leaving it on would compare the enumeration against a
    number that describes a different thing. With it off the two must agree exactly: this is
    ``docs/PARAM_BUDGET_PLAN.md`` F1's table reproduced through ``discover``'s own entry point
    rather than through the enumerator it calls.
    """
    pool = ("R", "C", "L", "CPE")
    plan = enumerate_candidates(
        _spectrum(),
        pool=pool,
        skeleton=None,
        limit=5,
        floor=1,
        max_candidates=200_000,
        feasibility_filter=False,
        feasibility_budget=1,
        max_params=6,
    )
    expected = sum(count_topologies_by_params(pool, p) for p in range(1, 7))
    assert plan.axis == "params"
    assert len(plan.texts) == expected


def test_the_element_axis_is_still_the_default() -> None:
    """No ``max_params`` means nothing about the enumeration changes, tag included."""
    plan = enumerate_candidates(
        _spectrum(),
        pool=("R", "C", "L"),
        skeleton=None,
        limit=3,
        floor=1,
        max_candidates=20_000,
        feasibility_filter=False,
        feasibility_budget=1,
    )
    assert plan.axis == "elements"
    assert plan.element_cost is None
    # Levels are element counts, so the last boundary is the element limit asked for.
    assert plan.boundaries[-1][0] == 3


def test_levels_are_parameter_counts_not_element_counts() -> None:
    """A CPE-bearing pool separates the two axes; a unit-cost pool cannot.

    On ``("R", "CPE")`` the two-parameter level already holds ``CPE1`` (one element) alongside
    the two-element ``R1-R2`` family, which is exactly the mixing an element level never shows.
    """
    plan = enumerate_candidates(
        _spectrum(),
        pool=("R", "CPE"),
        skeleton=None,
        limit=4,
        floor=1,
        max_candidates=20_000,
        feasibility_filter=False,
        feasibility_budget=1,
        max_params=4,
    )
    assert [level for level, _end in plan.boundaries] == [1, 2, 3, 4]
    assert plan.element_cost == 2


# -- the completeness lemma ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pool", "budget", "expected_elements"),
    [
        # m = 2 (CPE): a budget of 6 covers every 3-element topology and no 4-element one.
        (("R", "C", "L", "CPE"), 6, 3),
        (("R", "C", "L", "CPE"), 7, 3),
        (("R", "C", "L", "CPE"), 4, 2),
        # m = 1: the two axes coincide, so the lemma is the identity.
        (("R", "C", "L"), 5, 5),
    ],
)
def test_element_coverage_follows_the_lemma(
    pool: tuple[str, ...], budget: int, expected_elements: int
) -> None:
    """``complete_up_to == complete_up_to_params // m``, checked against the pool's own ``m``."""
    plan = enumerate_candidates(
        _spectrum(),
        pool=pool,
        skeleton=None,
        limit=5,
        floor=1,
        max_candidates=200_000,
        feasibility_filter=False,
        feasibility_budget=1,
        max_params=budget,
    )
    n = len(plan.texts)
    assert plan.coverage(n) == budget
    assert plan.element_coverage(n) == expected_elements


def test_a_budget_below_the_costliest_element_claims_nothing() -> None:
    """``P < m`` completes no element level at all, and the claim has to be 0, not 1.

    The pool's cheapest code still fits, so topologies *are* enumerated -- what does not exist
    is any element count all of whose topologies are inside the budget.
    """
    plan = enumerate_candidates(
        _spectrum(),
        pool=("CPE", "Ws"),
        skeleton=None,
        limit=5,
        floor=1,
        max_candidates=20_000,
        feasibility_filter=False,
        feasibility_budget=1,
        max_params=1,
    )
    assert plan.element_coverage(len(plan.texts)) in (None, 0)


# -- what discover() reports -----------------------------------------------------------------


def test_discover_reports_both_axes_and_derives_the_element_claim() -> None:
    result = discover(
        _spectrum(),
        pool=("R", "C", "L", "CPE"),
        mode="exhaustive",
        max_params=6,
        max_candidates=400,
        seed=0,
    )
    assert result.max_params == 6
    assert result.complete_up_to_params is not None
    # The lemma, on the object the user actually receives.
    assert result.complete_up_to == result.complete_up_to_params // 2


def test_the_coverage_sentence_says_parameters_and_shows_its_arithmetic() -> None:
    """The sentence must not read as an element-count completeness claim.

    A reader who carries "every plausible topology up to N" across from the element axis has
    been misled by a true sentence, which is the failure ``complete_up_to``'s whole discipline
    exists to prevent (``docs/HANDOFF.md`` section 3). So the parameter-budget sentence states
    the budget, the element count it does cover, and *why* the next one up is outside it.
    """
    result = discover(
        _spectrum(),
        pool=("R", "C", "L", "CPE"),
        mode="exhaustive",
        max_params=6,
        max_candidates=400,
        seed=0,
    )
    sentence = result.completeness()
    assert "6 free parameters" in sentence
    assert "a budget in parameters, not elements" in sentence
    assert "CPE costs 2 parameters on its own" in sentence


def test_a_recommendation_above_the_covered_size_is_flagged_as_such() -> None:
    """E.1's honesty reading, as a test rather than as a benchmark run.

    [measured, ``docs/PARAM_BUDGET_PLAN.md`` phase 3] Under a budget of 6 on a truth costing 8,
    the search correctly fails to find the truth and recommends a five-element circuit instead,
    every parameter of it resolved, while the coverage sentence claims completeness only to three
    elements. Every clause of that sentence was true and the report still misled, because nothing
    connected the two numbers. The note this asserts is what connects them.
    """
    # A truth outside the budget: 5 elements, 8 parameters, against a budget of 6.
    spectrum = simulate(
        "p(R1,CPE1)-p(R2,CPE2)-CPE3",
        log_frequencies(1e-1, 1e6, 6),
        {
            "R1.R": 0.470506,
            "CPE1.Q": 2.47434e-06,
            "CPE1.n": 0.899557,
            "R2.R": 173.044,
            "CPE2.Q": 0.000132465,
            "CPE2.n": 0.9,
            "CPE3.Q": 0.0103155,
            "CPE3.n": 0.9,
        },
        noise=0.01,
        seed=1,
    )
    result = discover(
        spectrum,
        pool=("R", "C", "L", "CPE"),
        mode="exhaustive",
        max_params=6,
        max_candidates=600,
        seed=0,
    )
    assert result.recommended is not None
    assert result.complete_up_to is not None
    size = count_elements(result.recommended.circuit.root)
    sentence = result.completeness()
    if size > result.complete_up_to:
        assert f"the recommended circuit has {size} elements" in sentence
        assert "not a completeness claim" in sentence
    else:
        # The note must not fire when the recommendation is inside the covered size.
        assert "the recommended circuit has" not in sentence


def test_the_element_path_keeps_its_own_sentence_untouched() -> None:
    """``max_params=None`` must reach the sentence it always did, word for word.

    This is the report-side half of the byte-identity requirement
    (``docs/PARAM_BUDGET_PLAN.md`` phase 3): the element path takes every branch it took before
    the budget existed.
    """
    result = discover(
        _spectrum(),
        pool=("R", "C", "L"),
        mode="exhaustive",
        exhaustive_limit=3,
        seed=0,
    )
    assert result.max_params is None
    assert result.complete_up_to_params is None
    assert result.completeness().startswith(
        "Coverage: every plausible topology with up to 3 elements from this pool was evaluated."
    )


def test_the_wire_payload_is_unchanged_on_the_element_path() -> None:
    """The parameter fields are deliberately absent from ``to_dict``.

    Measured, not assumed: adding them unconditionally broke ``benchmarks/ev5_fingerprint.py``'s
    byte comparison on every existing reference, because an always-null key is still a key. The
    schema gets them in phase 9, with the browser that needs them.
    """
    result = discover(_spectrum(), pool=("R", "C"), mode="exhaustive", exhaustive_limit=2, seed=0)
    payload = result.to_dict()
    assert "complete_up_to" in payload
    assert "max_params" not in payload
    assert "complete_up_to_params" not in payload
    assert "base_complete_up_to_params" not in payload


# -- the two refusals ------------------------------------------------------------------------


def test_a_skeleton_and_a_parameter_budget_are_refused_together() -> None:
    """``grow_up_to`` grows by elements and clamps its frontier by an element-level budget."""
    with pytest.raises(ValueError, match="skeleton"):
        discover(
            _spectrum(),
            pool=("R", "C", "L"),
            mode="exhaustive",
            skeleton="R1",
            max_params=5,
        )


def test_growth_and_a_parameter_budget_are_refused_together() -> None:
    """Growth seeds its beam from one completed *element* level, which a budget does not give."""
    with pytest.raises(ValueError, match="growth_width"):
        discover(
            _spectrum(),
            pool=("R", "C", "L"),
            mode="exhaustive",
            growth_width=4,
            max_params=5,
        )


def test_an_oversized_budget_is_clamped_rather_than_refused() -> None:
    """Same treatment an oversized ``exhaustive_limit`` already gets from ``max_candidates``."""
    result = discover(
        _spectrum(),
        pool=("R", "C"),
        mode="exhaustive",
        max_params=MAX_PARAM_BUDGET + 5,
        max_candidates=200,
        seed=0,
    )
    assert result.max_params == MAX_PARAM_BUDGET
