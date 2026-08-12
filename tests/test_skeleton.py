"""Tests for skeleton-constrained enumeration (autocircuit.core.enumerate).

Two public functions are under test, and the central claim of this file is that they agree:

* ``grow_from_skeleton`` generates every distinct plausible topology of a given size that
  contains a user-supplied skeleton, by growing the skeleton outward.
* ``contains_skeleton`` is the independent *definition* of that same space, written as a
  deletion-and-collapse predicate rather than as a generator.

Because the two are independent implementations of the same space, cross-checking one against
``enumerate_topologies`` filtered by the other is a much stronger test than either alone -- and
the exact counts below are a second, numeric cross-check on top of that (docs/DISCOVERY_V2_PLAN.md).
"""

from __future__ import annotations

import pytest

from autocircuit.core.circuit import Circuit, canonical_form, count_elements
from autocircuit.core.enumerate import (
    contains_skeleton,
    enumerate_topologies,
    grow_from_skeleton,
    grow_up_to,
    is_plausible_node,
)

# =============================================================================================
# Measured reference table: (skeleton, pool, per-size counts, n ascending from the skeleton's
# own element count). Verified numbers -- a mismatch is a library regression, not a number to
# update (see the module docstring in enumerate.py and the task's own gate).
# =============================================================================================

CASE_TABLE: list[tuple[str, tuple[str, ...], list[int]]] = [
    ("R1", ("R", "C"), [1, 2, 4, 12, 36]),
    ("R1", ("R", "C", "L"), [1, 4, 15, 69, 333]),
    ("R1-C1", ("R", "C"), [1, 4, 12, 36]),
    ("R1-C1", ("R", "C", "L"), [1, 7, 44, 250]),
    ("p(R1,C1)", ("R", "C", "L"), [1, 8, 46, 258]),
    ("R1-p(R2,C1)", ("R", "C", "L"), [1, 12, 95]),
    ("R1-C1-L1", ("R", "C", "L"), [1, 16, 139, 973]),
    ("R1-C1-L1", ("R", "C", "L", "CPE"), [1, 23, 318]),
    ("p(R1,C1)-p(R2,C2)", ("R", "C", "L"), [1, 11, 100]),
]

#: (skeleton_text, pool, n, expected_count), n starting at the skeleton's own element count.
FLAT_CASES: list[tuple[str, tuple[str, ...], int, int]] = [
    (skeleton_text, pool, count_elements(Circuit.parse(skeleton_text).root) + offset, expected)
    for skeleton_text, pool, counts in CASE_TABLE
    for offset, expected in enumerate(counts)
]

#: The n=6 rows (R1-C1-L1/RCL and p(R1,C1)-p(R2,C2)/RCL) are dropped for the generator-vs-
#: definition cross-check, which is much slower than a plain count, but kept for the count
#: table below.
EQUIVALENCE_CASES = [case for case in FLAT_CASES if case[2] <= 5]


def _case_id(case: tuple[str, tuple[str, ...], int, int]) -> str:
    skeleton_text, pool, n, _ = case
    return f"{skeleton_text}|{''.join(pool)}|n={n}"


# =============================================================================================
# 1. Generator equals definition -- the central test
# =============================================================================================


@pytest.mark.parametrize("case", EQUIVALENCE_CASES, ids=[_case_id(c) for c in EQUIVALENCE_CASES])
def test_grow_from_skeleton_matches_enumerate_filtered_by_contains_skeleton(
    case: tuple[str, tuple[str, ...], int, int],
) -> None:
    skeleton_text, pool, n, _ = case
    skeleton = Circuit.parse(skeleton_text).root
    grown = {canonical_form(node) for node in grow_from_skeleton(skeleton, pool, n)}
    filtered = {
        canonical_form(node)
        for node in enumerate_topologies(pool, n)
        if contains_skeleton(node, skeleton)
    }
    assert grown == filtered


# =============================================================================================
# 2. Exact counts
# =============================================================================================


@pytest.mark.parametrize("case", FLAT_CASES, ids=[_case_id(c) for c in FLAT_CASES])
def test_grow_from_skeleton_exact_counts(
    case: tuple[str, tuple[str, ...], int, int],
) -> None:
    skeleton_text, pool, n, expected = case
    skeleton = Circuit.parse(skeleton_text).root
    count = sum(1 for _ in grow_from_skeleton(skeleton, pool, n))
    assert count == expected, (
        f"{skeleton_text!r} pool={pool} n={n}: expected {expected}, got {count}"
    )


# =============================================================================================
# 3. Named regression: the subset-grouping move in `_insertions`
# =============================================================================================


def test_subset_grouping_move_is_required_to_find_c_across_c_l_half() -> None:
    """``R1-C1-L1`` is one three-child series node (series/parallel nodes are n-ary and
    flattened), so ``Series(C1, L1)`` is not an addressable subtree of it -- there is no
    existing position an "attach an element here" move could target to build it. The only way
    to reach it is to group a proper subset of the three children ({C1, L1}), and attach a
    fresh element beside that group. This is exactly the second family of move documented on
    ``_insertions``; the first family ("attach at a position") cannot reach this topology at
    all.

    Concretely: group {C1, L1} into a series pair, put a fresh capacitor in parallel with that
    pair, and leave R1 in series with the result. That topology's canonical form is
    ``[C-p(C,[L-R])]`` (per the docstring on ``_insertions``). If someone removes the
    subset-grouping branch, this topology silently disappears from the output -- it is one of
    the 16 four-element topologies containing ``R1-C1-L1``, and per that docstring, attachment
    alone only reaches 7 of them.
    """
    skeleton = Circuit.parse("R1-C1-L1").root
    forms = {canonical_form(node) for node in grow_from_skeleton(skeleton, ("R", "C", "L"), 4)}

    expected = canonical_form(Circuit.parse("C1-p(C2,R1-L1)").root)
    assert expected == "[C-p(C,[L-R])]"  # matches the literal form named in _insertions' docstring
    assert expected in forms


# =============================================================================================
# 4. Invariants over the output
# =============================================================================================

INVARIANT_CASES: list[tuple[str, tuple[str, ...], int]] = [
    ("R1", ("R", "C"), 4),
    ("R1-C1", ("R", "C", "L"), 4),
    ("p(R1,C1)", ("R", "C", "L"), 4),
    ("R1-C1-L1", ("R", "C", "L"), 5),
    ("R1-p(R2,C1)", ("R", "C", "L"), 4),
]


_INVARIANT_IDS = [f"{s}|{''.join(p)}|n={n}" for s, p, n in INVARIANT_CASES]


@pytest.mark.parametrize("skeleton_text,pool,n", INVARIANT_CASES, ids=_INVARIANT_IDS)
def test_output_invariants(skeleton_text: str, pool: tuple[str, ...], n: int) -> None:
    skeleton = Circuit.parse(skeleton_text).root
    nodes = list(grow_from_skeleton(skeleton, pool, n))
    assert nodes  # sanity: these cases are all non-empty per the count table

    forms = [canonical_form(node) for node in nodes]
    assert len(forms) == len(set(forms)), "duplicate canonical forms in the stream"

    for node in nodes:
        assert count_elements(node) == n
        assert is_plausible_node(node)
        assert contains_skeleton(node, skeleton)


# =============================================================================================
# 5. Edge cases
# =============================================================================================


def test_n_below_skeleton_size_yields_nothing() -> None:
    skeleton = Circuit.parse("R1-C1").root
    assert list(grow_from_skeleton(skeleton, ("R", "C"), 1)) == []


def test_n_equal_to_skeleton_size_yields_only_the_skeleton() -> None:
    skeleton = Circuit.parse("R1-C1").root
    nodes = list(grow_from_skeleton(skeleton, ("R", "C"), 2))
    assert len(nodes) == 1
    assert canonical_form(nodes[0]) == canonical_form(skeleton)


@pytest.mark.parametrize("skeleton_text", ["R1-R2", "p(R1,R2)"])
def test_redundant_skeleton_raises_value_error(skeleton_text: str) -> None:
    skeleton = Circuit.parse(skeleton_text).root
    with pytest.raises(ValueError) as excinfo:
        list(grow_from_skeleton(skeleton, ("R", "C"), 3))
    # "R1-R2" and "p(R1,R2)" both cancel exactly to a single R; the message must name that
    # reduced form so the caller knows what circuit they actually described.
    assert "R" in str(excinfo.value)
    assert "reduces to" in str(excinfo.value)


def test_unknown_element_code_in_pool_raises_key_error() -> None:
    skeleton = Circuit.parse("R1").root
    with pytest.raises(KeyError):
        list(grow_from_skeleton(skeleton, ("Q",), 2))


def test_empty_pool_raises_value_error() -> None:
    skeleton = Circuit.parse("R1").root
    with pytest.raises(ValueError):
        list(grow_from_skeleton(skeleton, (), 2))


def test_skeleton_code_outside_pool_is_an_assertion_not_a_search_result() -> None:
    # SKINF is not in the pool, but it is a fixed part of the assertion, so it must survive
    # into every generated topology.
    skeleton = Circuit.parse("SKINF1-R1").root
    nodes = list(grow_from_skeleton(skeleton, ("R", "C"), 3))
    assert nodes
    for node in nodes:
        leaves = Circuit(node).leaves
        assert any(leaf.code == "SKINF" for leaf in leaves)


# =============================================================================================
# 6. contains_skeleton unit tests
# =============================================================================================


def test_contains_skeleton_true_when_flattened_series_reduces_to_it() -> None:
    # R1-C1 is NOT a subtree of R1-C1-p(R2,L1): that tree is a single three-child series node.
    # It is what remains once p(R2,L1) is deleted -- exactly the case flattening breaks a plain
    # subtree search.
    candidate = Circuit.parse("R1-C1-p(R2,L1)").root
    skeleton = Circuit.parse("R1-C1").root
    assert contains_skeleton(candidate, skeleton) is True


def test_contains_skeleton_false_when_topology_differs() -> None:
    candidate = Circuit.parse("p(R1,C1)").root
    skeleton = Circuit.parse("R1-C1").root
    assert contains_skeleton(candidate, skeleton) is False


@pytest.mark.parametrize(
    "text", ["R1", "R1-C1", "p(R1,C1)", "R1-p(R2,C1)", "p(R1,C1)-p(R2,C2)"]
)
def test_a_topology_contains_itself(text: str) -> None:
    node = Circuit.parse(text).root
    assert contains_skeleton(node, node) is True


def test_a_smaller_topology_does_not_contain_a_larger_one() -> None:
    small = Circuit.parse("R1").root
    large = Circuit.parse("R1-C1").root
    assert contains_skeleton(small, large) is False


# =============================================================================================
# 7. grow_up_to -- the level-by-level closure
# =============================================================================================


def test_grow_up_to_yields_levels_matching_grow_from_skeleton() -> None:
    """This is the core contract: the incremental driver must not be a second, different
    enumeration. discover() (docs/PARTIAL_TOPOLOGY_PLAN.md) relies on ``grow_up_to`` to stop
    between levels rather than call ``grow_from_skeleton`` once per size, so if the two ever
    disagreed on what a level *is*, the search would silently cover a different space than
    ``grow_from_skeleton`` -- and the two files' exact-count tables above -- describe.
    """
    skeleton = Circuit.parse("R1-C1-L1").root
    pool = ("R", "C", "L")
    levels = list(grow_up_to(skeleton, pool, 5))
    assert [n for n, _ in levels] == [3, 4, 5]
    for n, level in levels:
        got = {canonical_form(node) for node in level}
        expected = {canonical_form(node) for node in grow_from_skeleton(skeleton, pool, n)}
        assert got == expected


def test_grow_up_to_max_frontier_stops_early_without_truncating_a_level() -> None:
    """A completeness claim may only rest on whole levels; a clamp that truncated a level in
    place would silently turn a complete claim into a false one. ``max_frontier`` must abort
    *between* levels, so every level this function ever yields stays a genuine subset of the
    unbounded run -- never a partial, cheaper approximation of one.
    """
    skeleton = Circuit.parse("R1-C1-L1").root
    pool = ("R", "C", "L")
    full = list(grow_up_to(skeleton, pool, 5))
    clamped = list(grow_up_to(skeleton, pool, 5, max_frontier=50))

    assert len(clamped) < len(full), "fixture assumes max_frontier=50 actually cuts the run short"
    assert [n for n, _ in clamped] == [n for n, _ in full[: len(clamped)]]
    for n, level in clamped:
        got = {canonical_form(node) for node in level}
        expected = {canonical_form(node) for node in grow_from_skeleton(skeleton, pool, n)}
        assert got == expected


def test_grow_up_to_n_max_below_skeleton_size_yields_nothing() -> None:
    skeleton = Circuit.parse("R1-C1-L1").root
    assert list(grow_up_to(skeleton, ("R", "C", "L"), 2)) == []


@pytest.mark.parametrize("skeleton_text", ["R1-R2", "p(R1,R2)"])
def test_grow_up_to_redundant_skeleton_raises_value_error_eagerly(skeleton_text: str) -> None:
    # Not wrapped in list()/next(): the call itself must raise, matching
    # test_redundant_skeleton_raises_value_error above for grow_from_skeleton.
    skeleton = Circuit.parse(skeleton_text).root
    with pytest.raises(ValueError) as excinfo:
        grow_up_to(skeleton, ("R", "C"), 3)
    assert "R" in str(excinfo.value)
    assert "reduces to" in str(excinfo.value)


def test_grow_up_to_unknown_element_code_in_pool_raises_key_error_eagerly() -> None:
    # Not wrapped in list()/next(): the call itself must raise.
    skeleton = Circuit.parse("R1").root
    with pytest.raises(KeyError):
        grow_up_to(skeleton, ("Q",), 2)
