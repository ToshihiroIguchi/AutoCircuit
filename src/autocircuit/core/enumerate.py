"""Exhaustive enumeration of series-parallel topologies.

This is the foundation of discovery v2 (``docs/DISCOVERY_V2_PLAN.md``). Where the genetic
search in :mod:`autocircuit.core.discover` samples the topology space, this module walks all
of it: for a given element pool and element count it produces every distinct series-parallel
network exactly once. That is what turns "the search did not find X" into the much stronger
"X does not fit this data".

The enumeration is affordable because the *distinct* space is far smaller than the raw one.
Three filters do the shrinking, and all three are exact -- none of them can discard a
topology the data might have preferred:

1. **Canonical deduplication.** ``canonical_form`` absorbs the commutativity of both
   operators and the flattening of nested same-type nodes, so ``R-p(C,R)`` and ``p(R,C)-R``
   are recognised as one topology.
2. **Redundancy collapse.** ``simplify`` folds R-R, R||R, C-C, C||C, L-L and L||L into a
   single element; a candidate that shrinks below the requested size was already enumerated
   at its true size, so it is dropped here rather than fitted twice.
3. **Plausibility.** :func:`is_plausible_node` rejects structures that cannot describe a real
   lossy two-terminal component (see its docstring).

Only levels *below* the requested size are materialised and memoised; the requested level is
streamed, so a caller can start fitting -- or stop early -- without paying for the whole
space first.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator, Sequence

from . import elements
from .circuit import (
    Circuit,
    ElementNode,
    Node,
    Parallel,
    canonical_form,
    count_elements,
    parallel,
    series,
    simplify,
)

__all__ = [
    "count_topologies",
    "enumerate_topologies",
    "enumerate_up_to",
    "integer_partitions",
    "is_plausible",
    "is_plausible_node",
]


def integer_partitions(total: int, parts: int) -> Iterator[tuple[int, ...]]:
    """Non-increasing partitions of ``total`` into exactly ``parts`` positive parts.

    ``integer_partitions(4, 2)`` yields ``(3, 1)`` and ``(2, 2)``. These are the ways an
    n-element network can be split into the sizes of its top-level branches.
    """
    if parts < 1 or total < parts:
        return
    if parts == 1:
        yield (total,)
        return
    for first in range(total - parts + 1, 0, -1):
        for rest in integer_partitions(total - first, parts - 1):
            if rest[0] <= first:
                yield (first, *rest)


# -- Plausibility --------------------------------------------------------------------------
# Lives here rather than in discover.py because it is a property of the topology, applied
# during enumeration and long before anything is fitted. discover.py re-exports it.


def is_plausible_node(node: Node) -> bool:
    """Reject topologies that cannot describe a real two-terminal passive component.

    The rules are structural, not statistical, so they cost nothing to apply before fitting:

    * a parallel block containing a lone capacitor together with a lone CPE is degenerate,
      since a CPE with n = 1 is a capacitor;
    * a parallel block that puts an inductor across a capacitor with nothing else is a pure
      LC resonator, which cannot represent a lossy measured spectrum on its own.

    (Same-element redundancy -- R||R, C-C and friends -- is handled by ``simplify`` instead.)
    """
    if isinstance(node, ElementNode):
        return True
    if isinstance(node, Parallel):
        codes = [c.code for c in node.children if isinstance(c, ElementNode)]
        if "C" in codes and "CPE" in codes:
            return False
        if len(node.children) == 2 and set(codes) == {"L", "C"}:
            return False
    return all(is_plausible_node(child) for child in node.children)


def is_plausible(circuit: Circuit) -> bool:
    """:func:`is_plausible_node` for a built :class:`Circuit`."""
    return is_plausible_node(circuit.root)


# -- Enumeration ---------------------------------------------------------------------------

#: Memoised sub-levels, keyed by (pool, size). Only sizes strictly below the largest size
#: ever requested are stored, and those levels are small: the level-5 count for the widest
#: pool is ~10^4 nodes, while level 6 is ~10^5 and is deliberately never retained.
_LEVELS: dict[tuple[tuple[str, ...], int], tuple[Node, ...]] = {}


def _normalise_pool(pool: Iterable[str]) -> tuple[str, ...]:
    """Validate element codes and drop duplicates, preserving the caller's order."""
    seen: dict[str, None] = {}
    for code in pool:
        elements.get(code)  # raises KeyError for unknown codes
        seen.setdefault(code, None)
    if not seen:
        raise ValueError("the element pool is empty")
    return tuple(seen)


def _survives(node: Node, size: int) -> Node | None:
    """Return the reduced form of ``node`` if it is a genuine topology of ``size`` elements.

    Returns ``None`` when the candidate collapses to a smaller network (it belongs to that
    smaller level, where it is enumerated once) or is structurally implausible.
    """
    reduced = simplify(node)
    if count_elements(reduced) != size:
        return None
    return reduced if is_plausible_node(reduced) else None


def _compose(pool: tuple[str, ...], size: int) -> Iterator[Node]:
    """Stream the distinct surviving topologies with exactly ``size`` elements.

    A network of ``size`` elements is a series or parallel composition of smaller networks
    whose sizes partition ``size``. Because ``series``/``parallel`` flatten nested nodes of
    the same type, every topology is reached through the partition matching its own top-level
    branches, so partitioning is complete.

    Sub-networks are taken from the *filtered* levels, which is safe in both directions: if a
    branch collapses under ``simplify`` then so does the whole network, and if a branch is
    implausible then so is the whole network -- because both properties are defined by
    recursion over every node of the tree.
    """
    if size < 1:
        return
    if size == 1:
        for code in pool:
            yield ElementNode(code)
        return

    seen: set[str] = set()
    for n_parts in range(2, size + 1):
        for parts in integer_partitions(size, n_parts):
            levels = [_level(pool, part) for part in parts]
            for combo in itertools.product(*levels):
                for node in (series(*combo), parallel(*combo)):
                    key = canonical_form(node)
                    if key in seen:
                        continue
                    seen.add(key)
                    reduced = _survives(node, size)
                    if reduced is not None:
                        yield reduced


def _level(pool: tuple[str, ...], size: int) -> tuple[Node, ...]:
    """Materialise and memoise one complete level of the enumeration."""
    key = (pool, size)
    cached = _LEVELS.get(key)
    if cached is None:
        cached = tuple(_compose(pool, size))
        _LEVELS[key] = cached
    return cached


def enumerate_topologies(pool: Sequence[str], n: int) -> Iterator[Node]:
    """Every distinct plausible topology built from ``pool`` with exactly ``n`` elements.

    Args:
        pool: Element codes the enumeration may use, e.g. ``("R", "C", "L")``. Duplicates are
            ignored; unknown codes raise ``KeyError``.
        n: Element count. ``n < 1`` yields nothing.

    Returns:
        An iterator over bare topology trees in their reduced form, each canonical form
        exactly once. Wrap one in :class:`~autocircuit.core.circuit.Circuit` to fit it.

    The pool is validated eagerly -- a bad element code raises here, not on first ``next``.
    """
    codes = _normalise_pool(pool)
    if n < 1:
        return iter(())
    cached = _LEVELS.get((codes, n))
    return iter(cached) if cached is not None else _compose(codes, n)


def enumerate_up_to(pool: Sequence[str], n_max: int, n_min: int = 1) -> Iterator[Node]:
    """Enumerate every size from ``n_min`` to ``n_max`` inclusive, smallest first."""
    codes = _normalise_pool(pool)
    return itertools.chain.from_iterable(
        enumerate_topologies(codes, n) for n in range(max(1, n_min), n_max + 1)
    )


def count_topologies(pool: Sequence[str], n: int) -> int:
    """How many distinct plausible topologies exist at exactly ``n`` elements."""
    return sum(1 for _ in enumerate_topologies(pool, n))
