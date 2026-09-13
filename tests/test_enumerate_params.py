"""Tests for parameter-budgeted topology enumeration (docs/PARAM_BUDGET_PLAN.md, phase 1).

This module is deliberately separate from ``tests/test_enumerate.py`` rather than appended to
it: phase 1's own gate is that the *existing* element-axis suite stays untouched, and a new file
makes that trivially true rather than something to audit in a diff.

Everything here exercises :mod:`autocircuit.core.enumerate`'s parameter axis, which is *dark* at
this phase -- nothing in ``discover.py`` calls it yet. Three kinds of check, in the order the
plan lists them:

1. **The two free correctness gates.** On a pool where every element costs exactly one
   parameter, the parameter axis must reproduce the element axis exactly, sequence for
   sequence -- not just as a set, since the ordering is what the project's byte fingerprints
   depend on later. And on a mixed-cost pool, the pruned enumerator must match a naive
   enumerate-then-filter exactly, as a set (order need not agree with the naive path, which
   walks a different axis first).
2. **The completeness lemma (docs/PARAM_BUDGET_PLAN.md section 6)**: a parameter budget ``P``
   contains every topology of ``n`` elements iff ``n <= P // m``, where ``m`` is the pool's most
   expensive element. Checked both ways -- a level at or below the floor is present in full, one
   above it is a strict, partial subset.
3. **Ordinary enumeration hygiene** on the new axis: every yielded topology is valid and costs
   exactly the requested number of parameters, no duplicates within a level, laziness, and the
   edge cases the element axis already covers (``p < 1``, unknown codes, an empty pool).
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator

import pytest

from autocircuit.core.circuit import Circuit, canonical_form, count_elements, count_params
from autocircuit.core.elements import get as get_element
from autocircuit.core.enumerate import (
    count_topologies,
    count_topologies_by_params,
    enumerate_topologies,
    enumerate_topologies_by_params,
    enumerate_up_to,
    enumerate_up_to_params,
)

# =============================================================================================
# Measured reference table -- the acceptance gate itself, the parameter-axis counterpart of
# tests/test_enumerate.py's PER_SIZE_COUNTS / CUMULATIVE_COUNTS.
# =============================================================================================

#: Per-parameter-level counts (p = 1..7), after the same redundancy and plausibility filters
#: the element axis uses. Where every code in the pool costs one parameter (("R", "C"),
#: ("R", "C", "L")) these are identical to the element-axis PER_SIZE_COUNTS at p <= 6, which is
#: the list-identity gate restated as fixed numbers rather than a live comparison.
PER_PARAM_COUNTS: dict[tuple[str, ...], list[int]] = {
    ("R", "C"): [2, 2, 4, 12, 36, 114, 372],
    ("R", "C", "L"): [3, 5, 17, 75, 349, 1725, 8859],
    ("R", "C", "L", "CPE"): [3, 6, 22, 101, 495, 2585, 14061],
}

#: Cumulative counts at p <= 4, 5, 6, 7.
CUMULATIVE_PARAM_COUNTS: dict[tuple[str, ...], dict[int, int]] = {
    ("R", "C"): {4: 20, 5: 56, 6: 170, 7: 542},
    ("R", "C", "L"): {4: 100, 5: 449, 6: 2174, 7: 11033},
    ("R", "C", "L", "CPE"): {4: 132, 5: 627, 6: 3212, 7: 17273},
}

REFERENCE_POOLS = [("R", "C"), ("R", "C", "L"), ("R", "C", "L", "CPE")]

#: Pools/levels exercised by the per-topology structural checks below. Kept small so the checks
#: stay fast; the counts table above covers completeness up to p = 7 separately.
STRUCTURAL_POOLS = [("R", "C"), ("R", "C", "L"), ("R", "C", "L", "CPE")]
STRUCTURAL_LEVELS = [1, 2, 3, 4]


def _assert_param_counts_match_table(pool: tuple[str, ...]) -> None:
    per_param = PER_PARAM_COUNTS[pool]
    cumulative = CUMULATIVE_PARAM_COUNTS[pool]
    running = 0
    for p in range(1, 8):
        count = count_topologies_by_params(pool, p)
        assert count == per_param[p - 1], (
            f"pool {pool}, p={p}: expected {per_param[p - 1]} topologies, got {count}"
        )
        running += count
        if p in cumulative:
            assert running == cumulative[p], (
                f"pool {pool}, cumulative p<={p}: expected {cumulative[p]}, got {running}"
            )


@pytest.mark.parametrize("pool", REFERENCE_POOLS)
def test_param_counts_per_level_and_cumulative(pool: tuple[str, ...]) -> None:
    _assert_param_counts_match_table(pool)


# =============================================================================================
# Gate 1a -- list identity with the element axis on unit-parameter-cost pools
# =============================================================================================


@pytest.mark.parametrize("pool", [("R", "C", "L"), ("R", "C", "L", "W")])
def test_param_axis_reproduces_element_axis_on_unit_cost_pools(pool: tuple[str, ...]) -> None:
    """Every code in ``pool`` costs exactly one parameter, so 'up to 6 elements' and 'up to 6
    parameters' name the identical space -- and, because both enumerators build it the same
    way (partition, product, series/parallel, canonical dedup, ``_survives``), in the identical
    order. ``("R", "C", "L", "W")`` is the sharper of the two pools: ``W`` costs one parameter
    like the other three but carries a different ``Circuit.complexity`` weight (1.5 against
    1.0), so this checks the parameter axis rather than accidentally checking the complexity
    axis instead.
    """
    assert all(get_element(code).n_params == 1 for code in pool)
    old = [canonical_form(node) for node in enumerate_up_to(pool, 6)]
    new = [canonical_form(node) for node in enumerate_up_to_params(pool, 6)]
    assert new == old


# =============================================================================================
# Gate 1b -- set equality with a naive enumerate-then-filter, on mixed-parameter-cost pools
# =============================================================================================


@pytest.mark.parametrize(
    "pool",
    [
        ("R", "C", "L", "CPE"),
        ("R", "C", "CPE", "HN"),
        ("CPE", "Ws"),
        ("R", "CPE", "W", "Wo", "CC"),
    ],
)
@pytest.mark.parametrize("p", [4, 5, 6])
def test_pruned_enumeration_matches_naive_filter(pool: tuple[str, ...], p: int) -> None:
    """The pruned, parameter-axis composition must find exactly what a naive "enumerate every
    element level up to ``p`` elements, then keep what costs ``p`` parameters or fewer" pass
    finds -- as a set, since the two paths walk different axes and need not agree on order.

    Every element in ``pool`` costs at least one parameter, so no topology of more than ``p``
    elements can cost ``p`` parameters or fewer; enumerating the element axis only up to ``p``
    is therefore already exhaustive for this comparison; it need not go any higher.

    ``("CPE", "Ws")`` is the pool that matters most here: both codes cost two parameters, so
    every odd parameter level is unattainable, exercising the "some level is empty" pruning
    path rather than only the "too few elements fit" one.
    """
    naive = {canonical_form(node) for node in enumerate_up_to(pool, p) if count_params(node) <= p}
    pruned = {canonical_form(node) for node in enumerate_up_to_params(pool, p)}
    assert pruned == naive


# =============================================================================================
# The completeness lemma (docs/PARAM_BUDGET_PLAN.md section 6)
# =============================================================================================


def test_completeness_lemma_element_level_at_the_floor_is_full() -> None:
    """With m = max(n_params) over the pool, a budget P contains every n-element topology
    whenever n <= P // m. R,C,L,CPE has m = 2; at P = 6 the floor is 3, and the 61 three-element
    topologies present at that budget must be exactly the 61 the element axis enumerates on its
    own -- not merely the same count, the same set.
    """
    pool = ("R", "C", "L", "CPE")
    p = 6
    floor = p // max(get_element(code).n_params for code in pool)
    assert floor == 3

    full = {canonical_form(node) for node in enumerate_topologies(pool, floor)}
    present = {
        canonical_form(node)
        for node in enumerate_up_to_params(pool, p)
        if count_elements(node) == floor
    }
    assert present == full
    assert len(full) == count_topologies(pool, floor)


def test_completeness_lemma_element_level_past_the_floor_is_a_strict_subset() -> None:
    """One element level past the floor, the same budget is provably incomplete: the
    all-worst-element topology of ``floor + 1`` elements costs ``(floor + 1) * m > P`` on its
    own, and since its code (CPE) is not among the ``_MERGEABLE`` codes ``simplify`` collapses,
    it cannot be reached by any smaller reduced form either -- so it is genuinely absent, not
    merely unlucky to enumerate. R,C,L,CPE at P = 6 is measured to keep 318 of the 376
    four-element topologies.
    """
    pool = ("R", "C", "L", "CPE")
    p = 6
    floor = p // max(get_element(code).n_params for code in pool)
    level = floor + 1

    full_count = count_topologies(pool, level)
    present_count = sum(
        1 for node in enumerate_up_to_params(pool, p) if count_elements(node) == level
    )
    assert present_count < full_count
    assert (full_count, present_count) == (376, 318)

    # The all-worst-element topology of this size costs (floor + 1) * m = 8, past P = 6, and
    # CPE is not among the _MERGEABLE codes simplify() can collapse -- so it is not merely
    # absent from this particular scan, it cannot be reached by any reduced form either.
    all_cpe = canonical_form(Circuit.parse("CPE1-CPE2-CPE3-CPE4").root)
    present_forms = {
        canonical_form(node)
        for node in enumerate_up_to_params(pool, p)
        if count_elements(node) == level
    }
    assert all_cpe not in present_forms


# =============================================================================================
# Every yielded topology is valid, costs exactly the requested parameters, and uses only the pool
# =============================================================================================


@pytest.mark.parametrize("p", STRUCTURAL_LEVELS)
@pytest.mark.parametrize("pool", STRUCTURAL_POOLS)
def test_every_yielded_topology_is_valid_and_of_the_requested_param_count(
    pool: tuple[str, ...], p: int
) -> None:
    for node in enumerate_topologies_by_params(pool, p):
        circuit = Circuit(node)  # must be constructible
        assert count_params(node) == p
        assert all(leaf.code in pool for leaf in circuit.leaves)


@pytest.mark.parametrize("p", STRUCTURAL_LEVELS)
@pytest.mark.parametrize("pool", STRUCTURAL_POOLS)
def test_no_duplicate_canonical_forms_within_a_param_level(pool: tuple[str, ...], p: int) -> None:
    forms = [canonical_form(node) for node in enumerate_topologies_by_params(pool, p)]
    assert len(forms) == len(set(forms))


# =============================================================================================
# Laziness -- checked before anything forces a wide level to be fully materialised
# =============================================================================================


def test_enumerate_topologies_by_params_is_a_lazy_iterator() -> None:
    it = enumerate_topologies_by_params(("R", "C", "L", "CPE"), 6)
    assert isinstance(it, Iterator)
    first_three = list(itertools.islice(it, 3))
    assert len(first_three) == 3
    for node in first_three:
        Circuit(node)
        assert count_params(node) == 6


# =============================================================================================
# enumerate_up_to_params
# =============================================================================================


def test_enumerate_up_to_params_yields_levels_in_non_decreasing_order() -> None:
    counts = [count_params(node) for node in enumerate_up_to_params(("R", "C"), 4)]
    assert counts == sorted(counts)


def test_enumerate_up_to_params_length_matches_summed_counts() -> None:
    pool = ("R", "C", "L")
    total = sum(1 for _ in enumerate_up_to_params(pool, 4))
    expected = sum(count_topologies_by_params(pool, p) for p in range(1, 5))
    assert total == expected


# =============================================================================================
# Edge cases, mirroring the element axis
# =============================================================================================


def test_enumerate_topologies_by_params_of_zero_yields_nothing() -> None:
    assert list(enumerate_topologies_by_params(("R", "C"), 0)) == []


def test_enumerate_topologies_by_params_rejects_unknown_element_code() -> None:
    with pytest.raises(KeyError):
        list(enumerate_topologies_by_params(("Q",), 1))


def test_enumerate_topologies_by_params_rejects_empty_pool() -> None:
    with pytest.raises(ValueError):
        list(enumerate_topologies_by_params((), 1))


# =============================================================================================
# A pool whose costs share no common divisor other than themselves leaves gaps -- checked
# directly, since the pruning inside _compose_params relies on those gaps being real rather
# than an artefact of the pmin bound alone.
# =============================================================================================


def test_a_pool_of_two_parameter_elements_only_has_even_levels() -> None:
    pool = ("CPE", "Ws")  # both cost 2 parameters
    for p in range(1, 8):
        count = count_topologies_by_params(pool, p)
        if p % 2 == 1:
            assert count == 0, f"p={p} should be unattainable with only 2-parameter elements"
        else:
            assert count > 0
