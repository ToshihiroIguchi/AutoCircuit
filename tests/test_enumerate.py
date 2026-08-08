"""Regression tests for exhaustive topology enumeration (docs/DISCOVERY_V2_PLAN.md gate G2).

The enumeration counts below are the acceptance gate itself: they must reproduce, element for
element, the measured table in ``benchmarks/README.md``. Beyond the raw counts, this file
checks the properties that make the counts trustworthy at all -- every yielded topology is
valid and of the requested size, nothing is yielded twice, the redundancy and plausibility
filters that shrink the raw count are actually applied (not merely documented), and a handful
of textbook circuits are genuinely found, since the whole point of exhaustive enumeration is
completeness.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator

import pytest

from autocircuit.core.circuit import Circuit, canonical_form, count_elements, simplify
from autocircuit.core.enumerate import (
    count_topologies,
    enumerate_topologies,
    enumerate_up_to,
    integer_partitions,
    is_plausible_node,
)

# =============================================================================================
# Measured reference table (benchmarks/README.md, "topology_space.py (a)")
# =============================================================================================

#: Per-size counts (n = 1..6), after the redundancy and plausibility filters.
PER_SIZE_COUNTS: dict[tuple[str, ...], list[int]] = {
    ("R", "C"): [2, 2, 4, 12, 36, 114],
    ("R", "C", "L"): [3, 5, 17, 75, 349, 1725],
    ("R", "C", "L", "CPE"): [4, 12, 61, 376, 2523, 18081],
    ("R", "C", "L", "CPE", "SKINF"): [5, 22, 146, 1163, 10214, 95984],
}

#: Cumulative counts at n <= 3, 4, 5, 6, straight from the benchmarks/README.md table.
CUMULATIVE_COUNTS: dict[tuple[str, ...], dict[int, int]] = {
    ("R", "C"): {3: 8, 4: 20, 5: 56, 6: 170},
    ("R", "C", "L"): {3: 25, 4: 100, 5: 449, 6: 2174},
    ("R", "C", "L", "CPE"): {3: 77, 4: 453, 5: 2976, 6: 21057},
    ("R", "C", "L", "CPE", "SKINF"): {3: 173, 4: 1336, 5: 11550, 6: 107534},
}

SMALLER_POOLS = [("R", "C"), ("R", "C", "L"), ("R", "C", "L", "CPE")]
WIDEST_POOL = ("R", "C", "L", "CPE", "SKINF")

#: Pools/sizes exercised by the per-topology structural checks below. Kept small (n <= 4) so
#: the checks stay fast; completeness of the *counts* is covered separately, up to n = 6.
STRUCTURAL_POOLS = [("R", "C"), ("R", "C", "L"), ("R", "C", "L", "CPE")]
STRUCTURAL_SIZES = [1, 2, 3, 4]


def _assert_counts_match_table(pool: tuple[str, ...]) -> None:
    per_size = PER_SIZE_COUNTS[pool]
    cumulative = CUMULATIVE_COUNTS[pool]
    running = 0
    for n in range(1, 7):
        count = count_topologies(pool, n)
        assert count == per_size[n - 1], (
            f"pool {pool}, n={n}: expected {per_size[n - 1]} topologies, got {count}"
        )
        running += count
        if n in cumulative:
            assert running == cumulative[n], (
                f"pool {pool}, cumulative n<={n}: expected {cumulative[n]}, got {running}"
            )


# =============================================================================================
# integer_partitions
# =============================================================================================


def test_integer_partitions_of_five_into_two_parts() -> None:
    assert list(integer_partitions(5, 2)) == [(4, 1), (3, 2)]


def test_integer_partitions_of_four_into_four_parts() -> None:
    assert list(integer_partitions(4, 4)) == [(1, 1, 1, 1)]


def test_integer_partitions_with_too_many_parts_is_empty() -> None:
    assert list(integer_partitions(2, 3)) == []


# =============================================================================================
# Laziness -- checked early, before any other test forces the widest pool's n=6 level to be
# fully materialised (which would defeat the point of checking that a partial read is cheap).
# =============================================================================================


def test_enumerate_topologies_is_a_lazy_iterator() -> None:
    it = enumerate_topologies(WIDEST_POOL, 6)
    assert isinstance(it, Iterator)
    first_three = list(itertools.islice(it, 3))
    assert len(first_three) == 3
    for node in first_three:
        Circuit(node)  # must be constructible
        assert count_elements(node) == 6


# =============================================================================================
# Every yielded topology is valid, of the requested size, and built only from the pool
# =============================================================================================


@pytest.mark.parametrize("n", STRUCTURAL_SIZES)
@pytest.mark.parametrize("pool", STRUCTURAL_POOLS)
def test_every_yielded_topology_is_valid_and_of_the_requested_size(
    pool: tuple[str, ...], n: int
) -> None:
    for node in enumerate_topologies(pool, n):
        circuit = Circuit(node)  # must be constructible
        assert count_elements(node) == n
        assert all(leaf.code in pool for leaf in circuit.leaves)


# =============================================================================================
# No duplicates within a level
# =============================================================================================


@pytest.mark.parametrize("n", STRUCTURAL_SIZES)
@pytest.mark.parametrize("pool", STRUCTURAL_POOLS)
def test_no_duplicate_canonical_forms_within_a_level(pool: tuple[str, ...], n: int) -> None:
    forms = [canonical_form(node) for node in enumerate_topologies(pool, n)]
    assert len(forms) == len(set(forms))


# =============================================================================================
# The filters are actually applied, not merely documented
# =============================================================================================


@pytest.mark.parametrize("n", STRUCTURAL_SIZES)
@pytest.mark.parametrize("pool", STRUCTURAL_POOLS)
def test_nothing_yielded_collapses_under_simplify(pool: tuple[str, ...], n: int) -> None:
    for node in enumerate_topologies(pool, n):
        assert count_elements(simplify(node)) == n


@pytest.mark.parametrize("n", STRUCTURAL_SIZES)
@pytest.mark.parametrize("pool", STRUCTURAL_POOLS)
def test_everything_yielded_is_plausible(pool: tuple[str, ...], n: int) -> None:
    for node in enumerate_topologies(pool, n):
        assert is_plausible_node(node)


def test_redundant_series_resistors_never_appear_at_n2() -> None:
    # R1-R2 collapses to a single R under `simplify`, so it belongs at n=1, not n=2.
    forbidden = canonical_form(Circuit.parse("R1-R2").root)
    forms = {canonical_form(node) for node in enumerate_topologies(("R", "C"), 2)}
    assert forbidden not in forms


def test_bare_lc_tank_never_appears_at_n2() -> None:
    # A lone inductor across a lone capacitor is a pure resonator: not plausible.
    forbidden = canonical_form(Circuit.parse("p(L1,C1)").root)
    forms = {canonical_form(node) for node in enumerate_topologies(("R", "C", "L"), 2)}
    assert forbidden not in forms


# =============================================================================================
# Completeness spot checks -- known circuits must actually be found, not just counted
# =============================================================================================


def test_series_rlc_is_found_for_the_rcl_pool_at_n3() -> None:
    expected = Circuit.parse("C1-R1-L1").canonical_form()
    forms = {canonical_form(node) for node in enumerate_topologies(("R", "C", "L"), 3)}
    assert expected in forms


def test_randles_like_topology_is_found_for_the_rc_pool_at_n3() -> None:
    expected = Circuit.parse("R1-p(R2,C1)").canonical_form()
    forms = {canonical_form(node) for node in enumerate_topologies(("R", "C"), 3)}
    assert expected in forms


def test_two_parallel_rc_blocks_in_series_is_found_for_the_rc_pool_at_n4() -> None:
    expected = Circuit.parse("p(R1,C1)-p(R2,C2)").canonical_form()
    forms = {canonical_form(node) for node in enumerate_topologies(("R", "C"), 4)}
    assert expected in forms


# =============================================================================================
# enumerate_up_to
# =============================================================================================


def test_enumerate_up_to_yields_sizes_in_non_decreasing_order() -> None:
    sizes = [count_elements(node) for node in enumerate_up_to(("R", "C"), 4)]
    assert sizes == sorted(sizes)


def test_enumerate_up_to_length_matches_the_summed_counts() -> None:
    pool = ("R", "C", "L")
    total = sum(1 for _ in enumerate_up_to(pool, 4))
    expected = sum(count_topologies(pool, n) for n in range(1, 5))
    assert total == expected


def test_enumerate_topologies_of_zero_elements_yields_nothing() -> None:
    assert list(enumerate_topologies(("R", "C"), 0)) == []


def test_enumerate_topologies_rejects_unknown_element_code() -> None:
    with pytest.raises(KeyError):
        list(enumerate_topologies(("Q",), 1))


def test_enumerate_topologies_rejects_empty_pool() -> None:
    with pytest.raises(ValueError):
        list(enumerate_topologies((), 1))


# =============================================================================================
# The counts table -- the acceptance gate itself (docs/DISCOVERY_V2_PLAN.md gate G2)
# =============================================================================================


@pytest.mark.parametrize("pool", SMALLER_POOLS)
def test_topology_counts_per_size_and_cumulative(pool: tuple[str, ...]) -> None:
    _assert_counts_match_table(pool)


def test_topology_counts_widest_pool_through_n6() -> None:
    """The widest pool's n=6 level (~10^5 topologies) gets its own test so a mismatch here is
    not lost among the assertions for the three smaller pools above."""
    _assert_counts_match_table(WIDEST_POOL)
