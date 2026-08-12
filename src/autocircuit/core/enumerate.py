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
import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import numpy as np

from . import elements
from .circuit import (
    Circuit,
    ElementNode,
    Node,
    Parallel,
    Series,
    canonical_form,
    count_elements,
    parallel,
    replace_subtree,
    series,
    simplify,
    subtree_at,
    subtree_paths,
)
from .spectrum import Spectrum

__all__ = [
    "DEFAULT_DEGENERACY_BUDGET",
    "DEFAULT_SLOPE_TOLERANCE",
    "EndpointBehaviour",
    "contains_skeleton",
    "count_topologies",
    "endpoint_exponents",
    "enumerate_topologies",
    "enumerate_up_to",
    "feasible_topologies",
    "grow_from_skeleton",
    "integer_partitions",
    "is_feasible",
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


# -- Skeleton-constrained enumeration ------------------------------------------------------
#
# The user often knows part of the answer before the search starts: a capacitor has an ESR and
# an ESL in series with it, a cell has an electrolyte resistance in series with everything.
# Asserting that part -- the *skeleton* -- and letting the search supply the rest is a stronger
# version of the knowledge injection that restricting the pool already provides.
#
# What must not be lost is that this is a *constraint*, so the completeness statement it
# supports is narrower ("every plausible topology up to N elements that contains this
# skeleton") and a wrong skeleton removes the truth from the space while leaving a report that
# still looks healthy. Those obligations belong to the caller and the report; this module only
# has to define the space exactly and enumerate it without gaps.


def _remove_leaves(node: Node, keep: frozenset[int], cursor: list[int]) -> Node | None:
    """Drop every leaf whose index is not in ``keep``; None if nothing is left."""
    if isinstance(node, ElementNode):
        index = cursor[0]
        cursor[0] = index + 1
        return node if index in keep else None
    kept = [child for child in (_remove_leaves(c, keep, cursor) for c in node.children)
            if child is not None]
    if not kept:
        return None
    return series(*kept) if isinstance(node, Series) else parallel(*kept)


def contains_skeleton(candidate: Node, skeleton: Node) -> bool:
    """True when ``candidate`` reduces to ``skeleton`` once some of its elements are removed.

    This *is* the definition of the constrained space, written out independently of how
    :func:`grow_from_skeleton` generates it, so the two can be checked against each other.

    Containment is deliberately not "the skeleton appears as a subtree". ``series`` and
    ``parallel`` flatten nested nodes of the same type, so the skeleton ``R1-C1`` is nowhere to
    be found as a subtree of ``R1-C1-p(R2,L1)`` -- that tree is one three-child series node.
    Deletion-and-collapse is the notion that survives flattening, and it is also the one that
    matches what the user means: *these components are in the circuit, connected like this,
    and something else is there too.*
    """
    target = canonical_form(simplify(skeleton))
    n_keep = count_elements(skeleton)
    total = count_elements(candidate)
    if total < n_keep:
        return False
    for keep in itertools.combinations(range(total), n_keep):
        remaining = _remove_leaves(candidate, frozenset(keep), [0])
        if remaining is not None and canonical_form(simplify(remaining)) == target:
            return True
    return False


def _insertions(node: Node, codes: tuple[str, ...]) -> Iterator[Node]:
    """Every way of adding one element from ``codes`` to ``node``, in series or in parallel.

    Two families of move, and the second one is not optional. [measured]

    1. **Attach at a position** -- any subtree, the root and the leaves included. This is the
       move ``discover.mutate`` makes.
    2. **Group a proper subset of a node's children and attach beside that group.** Series and
       parallel nodes are n-ary and flattened, so a sub-group of their children is *not* an
       addressable position: the skeleton ``R1-C1-L1`` is one three-child series node, and
       putting a capacitor across only its ``C1-L1`` half is a real topology
       (``[C-p(C,[L-R])]``) that no attachment to an existing position can build.

    Leaving out family 2 is not a small loss. Cross-checked against
    :func:`contains_skeleton` over the whole enumerated space, attachment alone found 7 of the
    16 four-element topologies containing ``R1-C1-L1`` and 58 of 139 at five elements -- a
    silent hole in exactly the completeness guarantee this mode exists to provide.

    Wrapping a subset in a node of its *own* type just flattens back into the parent, so only
    the opposite orientation yields anything new; family 1 already covers the whole-node and
    single-child cases.
    """
    for path in subtree_paths(node):
        subtree = subtree_at(node, path)
        for code in codes:
            fresh = ElementNode(code)
            yield replace_subtree(node, path, series(subtree, fresh))
            yield replace_subtree(node, path, parallel(subtree, fresh))
        if isinstance(subtree, ElementNode):
            continue
        children = subtree.children
        same = series if isinstance(subtree, Series) else parallel
        opposite = parallel if isinstance(subtree, Series) else series
        for size in range(2, len(children)):
            for combo in itertools.combinations(range(len(children)), size):
                chosen = [children[i] for i in combo]
                rest = [children[i] for i in range(len(children)) if i not in combo]
                for code in codes:
                    block = opposite(same(*chosen), ElementNode(code))
                    yield replace_subtree(node, path, same(*rest, block))


def grow_from_skeleton(skeleton: Node, pool: Sequence[str], n: int) -> Iterator[Node]:
    """Every distinct plausible topology with exactly ``n`` elements that contains ``skeleton``.

    Args:
        skeleton: The part of the circuit the user is asserting. It must not be redundant --
            a skeleton that ``simplify`` collapses (``R1-R2``) is rejected rather than
            silently reinterpreted as the smaller circuit it really is.
        pool: Element codes the *added* elements may use. The skeleton may contain codes
            outside the pool; it is an assertion, not a search result.
        n: Total element count of the candidates. ``n`` below the skeleton's own size yields
            nothing; ``n`` equal to it yields the skeleton alone.

    Returns:
        Bare topology trees in reduced form, each canonical form exactly once -- the same
        contract as :func:`enumerate_topologies`, so the two are interchangeable downstream.

    Growing the skeleton is not merely faster than enumerating the full space and keeping what
    :func:`contains_skeleton` accepts; enumerate-then-filter also does redundant work that
    grows with the pool, whereas the insertion closure is bounded by the skeleton's own shape.

    **Intermediate trees are not filtered**, only the final level is. A partially grown tree
    that ``simplify`` would collapse, or that :func:`is_plausible_node` would reject, may still
    be on the only path to a valid larger candidate, and completeness is what this mode exists
    to provide. Pruning them would be an optimisation that can only lose topologies.

    The pool and the skeleton are validated eagerly, as in :func:`enumerate_topologies`: a bad
    element code or a redundant skeleton raises here, not on the first ``next``.
    """
    codes = _normalise_pool(pool)
    size = count_elements(skeleton)
    if count_elements(simplify(skeleton)) != size:
        raise ValueError(
            "the skeleton is redundant: it contains elements that cancel exactly "
            f"({canonical_form(skeleton)} reduces to {canonical_form(simplify(skeleton))}). "
            "State the circuit it actually describes instead."
        )
    if n < size:
        return iter(())
    return _grow(skeleton, codes, size, n)


def _grow(skeleton: Node, codes: tuple[str, ...], size: int, n: int) -> Iterator[Node]:
    """The insertion closure itself; see :func:`grow_from_skeleton` for the contract."""
    frontier: dict[str, Node] = {canonical_form(skeleton): skeleton}
    for _ in range(n - size):
        grown: dict[str, Node] = {}
        for node in frontier.values():
            for candidate in _insertions(node, codes):
                grown.setdefault(canonical_form(candidate), candidate)
        frontier = grown
    for node in frontier.values():
        reduced = _survives(node, n)
        if reduced is not None:
            yield reduced


# -- Structural feasibility filter ---------------------------------------------------------
#
# A symbolic screen that runs before any fitting. Each element declares the log-log slope of
# its |Z| at the two ends of the frequency axis (``dc_exponent`` / ``hf_exponent`` in
# :mod:`autocircuit.core.elements`); those slopes combine along the topology tree, and the
# result is compared with the slopes the data actually shows at the edges of its window.
#
# The filter is deliberately weaker than it could be, because completeness is the whole point
# of exhaustive discovery: it may only drop a topology that *cannot* match, never one that is
# merely unlikely to. Three separate margins enforce that:
#
# 1. **Degeneracy budget.** Any element can be pushed towards a short or an open by driving
#    its scale parameter to a bound, which changes the endpoint slope. A topology is kept if
#    it matches with up to ``budget`` elements treated that way (default 1), so a model with
#    one corner frequency just outside the measured window is not thrown away. Allowing every
#    element to degenerate at once would reduce the test to "does the pool contain a suitable
#    element", which is why the budget is finite -- and topologies that need more degeneracy
#    than that are, by construction, indistinguishable from a smaller topology that the
#    enumeration already covers on its own.
# 2. **Convex hull, not exact match.** A real spectrum is measured over a finite window, so
#    its edge slope can sit anywhere between two asymptotic regimes -- an R-C series pair with
#    its corner inside the first decade shows about -0.5, not the -1 of its DC limit. The
#    topology is therefore represented by the hull of everything it can reach, not by a set of
#    isolated exponents.
# 3. **Data-side tolerance.** The band around the measured slope covers the least-squares
#    slope over the edge decade, the slope over twice that span, and the exponent implied by
#    the measured phase, each widened by ``tolerance`` plus three standard errors. Near a
#    sharp feature these estimates disagree, the band grows, and the filter switches itself
#    off exactly where it would be least trustworthy.

#: Which end of the frequency axis a slope refers to.
End = Literal["low", "high"]

_Band = tuple[float, float]

#: Sentinels for an element driven to a short (|Z| -> 0) or an open (|Z| -> infinity). They
#: propagate correctly through the min/max rules below: a short wins a parallel combination
#: and vanishes from a series one, and an open does the reverse.
_SHORT: _Band = (math.inf, math.inf)
_OPEN: _Band = (-math.inf, -math.inf)

#: Elements the filter may treat as degenerate when matching one endpoint. See note 1 above.
DEFAULT_DEGENERACY_BUDGET = 1

#: Half-width of the tolerance band around a measured endpoint slope, before the data-derived
#: widening is added. 0.35 is wide enough that a -0.93 slope is still "capacitive-ish" and so
#: compatible with both a capacitor and a CPE.
DEFAULT_SLOPE_TOLERANCE = 0.35


@lru_cache(maxsize=200_000)
def _attainable(node: Node, end: End, budget: int) -> tuple[tuple[_Band, int], ...]:
    """Endpoint slope intervals this topology can reach, each with its degeneracy cost.

    Series impedances add, so at low frequency the largest |Z| wins -- that is the *smallest*
    exponent -- and at high frequency the largest exponent wins. Parallel admittances add, so
    the rule is mirrored. Element leaves contribute their declared interval at cost 0, plus a
    short and an open at cost 1 each.
    """
    if isinstance(node, ElementNode):
        element = elements.get(node.code)
        base = element.dc_exponent if end == "low" else element.hf_exponent
        if budget < 1:
            return ((base, 0),)
        return ((base, 0), (_SHORT, 1), (_OPEN, 1))

    take_min = isinstance(node, Series) == (end == "low")
    combine = min if take_min else max

    acc = _attainable(node.children[0], end, budget)
    for child in node.children[1:]:
        merged: dict[_Band, int] = {}
        for left, cost_left in acc:
            for right, cost_right in _attainable(child, end, budget):
                cost = cost_left + cost_right
                if cost > budget:
                    continue
                band = (combine(left[0], right[0]), combine(left[1], right[1]))
                if cost < merged.get(band, budget + 1):
                    merged[band] = cost
        acc = tuple(merged.items())
    return acc


def endpoint_exponents(
    node: Node, end: End, budget: int = DEFAULT_DEGENERACY_BUDGET
) -> _Band:
    """Convex hull of the log-log |Z| slopes ``node`` can show at one edge of the window.

    Pure shorts and opens are excluded from the hull: they describe a network with no finite
    impedance at all, which no measurement can look like.
    """
    lo, hi = math.inf, -math.inf
    for (low, high), _ in _attainable(node, end, budget):
        if math.isfinite(low) and math.isfinite(high):
            lo, hi = min(lo, low), max(hi, high)
    if lo > hi:  # nothing finite is reachable; keep the candidate rather than guess
        return (-math.inf, math.inf)
    return (lo, hi)


def _least_squares_slope(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Slope of ``y`` against ``x`` and its standard error; (nan, inf) when undetermined."""
    if x.size < 3:
        return math.nan, math.inf
    xc = x - x.mean()
    yc = y - y.mean()
    sxx = float(np.dot(xc, xc))
    if sxx <= 0.0:
        return math.nan, math.inf
    slope = float(np.dot(xc, yc) / sxx)
    residual = yc - slope * xc
    variance = float(np.dot(residual, residual)) / (x.size - 2)
    return slope, math.sqrt(max(variance, 0.0) / sxx)


def _edge_window(log_omega: np.ndarray, side: End, decades: float, min_points: int) -> slice:
    """The points within ``decades`` of one end, always at least ``min_points`` of them."""
    n = log_omega.size
    if side == "low":
        count = int(np.count_nonzero(log_omega <= log_omega[0] + decades))
        return slice(0, min(max(count, min_points), n))
    count = int(np.count_nonzero(log_omega >= log_omega[-1] - decades))
    return slice(max(n - max(count, min_points), 0), n)


def _edge_band(
    log_omega: np.ndarray,
    log_magnitude: np.ndarray,
    phase_exponent: np.ndarray,
    side: End,
    decades: float,
    tolerance: float,
    min_points: int,
) -> tuple[_Band, float]:
    """Tolerance band of endpoint slopes compatible with the data, plus the fitted slope."""
    if log_omega.size < min_points:
        return (-math.inf, math.inf), math.nan

    near = _edge_window(log_omega, side, decades, min_points)
    wide = _edge_window(log_omega, side, 2.0 * decades, min_points + 2)
    slope, stderr = _least_squares_slope(log_omega[near], log_magnitude[near])
    if not math.isfinite(slope) or not math.isfinite(stderr):
        return (-math.inf, math.inf), slope

    wide_slope, _ = _least_squares_slope(log_omega[wide], log_magnitude[wide])
    # The phase of a power-law impedance is (pi/2) times its exponent, so the measured phase
    # is a second, independent estimate of the same quantity -- and a far less noisy one when
    # |Z| barely moves across the edge decade.
    centres = [slope, float(np.median(phase_exponent[near]))]
    if math.isfinite(wide_slope):
        centres.append(wide_slope)
    half = tolerance + 3.0 * stderr
    return (min(centres) - half, max(centres) + half), slope


@dataclass(frozen=True)
class EndpointBehaviour:
    """What the two edges of a measured spectrum say about the model's asymptotic behaviour.

    ``low_band`` and ``high_band`` are the intervals of log-log |Z| slope compatible with the
    data at the low- and high-frequency edge. ``(-inf, inf)`` means "this edge tells us
    nothing", which switches the filter off at that end -- the case for spectra that are too
    short or too noisy to give a slope at all.
    """

    low_band: _Band
    high_band: _Band
    low_slope: float
    high_slope: float

    @classmethod
    def from_spectrum(
        cls,
        spectrum: Spectrum,
        *,
        decades: float = 1.0,
        tolerance: float = DEFAULT_SLOPE_TOLERANCE,
        min_points: int = 5,
    ) -> EndpointBehaviour:
        """Measure the endpoint slopes of ``spectrum`` with an honest uncertainty band."""
        magnitude = np.abs(spectrum.z)
        if not np.all(magnitude > 0.0) or spectrum.n < min_points:
            return cls((-math.inf, math.inf), (-math.inf, math.inf), math.nan, math.nan)
        log_omega = np.log10(spectrum.omega)
        log_magnitude = np.log10(magnitude)
        phase_exponent = np.angle(spectrum.z) / (0.5 * math.pi)

        low_band, low_slope = _edge_band(
            log_omega, log_magnitude, phase_exponent, "low", decades, tolerance, min_points
        )
        high_band, high_slope = _edge_band(
            log_omega, log_magnitude, phase_exponent, "high", decades, tolerance, min_points
        )
        return cls(low_band, high_band, low_slope, high_slope)

    @property
    def active(self) -> bool:
        """False when neither edge constrains anything, so filtering is a no-op."""
        return any(
            math.isfinite(edge) for band in (self.low_band, self.high_band) for edge in band
        )

    def describe(self) -> str:
        return (
            f"low-frequency slope {self.low_slope:+.2f} (accepting "
            f"[{self.low_band[0]:+.2f}, {self.low_band[1]:+.2f}]), "
            f"high-frequency slope {self.high_slope:+.2f} (accepting "
            f"[{self.high_band[0]:+.2f}, {self.high_band[1]:+.2f}])"
        )


def is_feasible(
    node: Node,
    behaviour: EndpointBehaviour,
    *,
    budget: int = DEFAULT_DEGENERACY_BUDGET,
) -> bool:
    """True unless ``node`` provably cannot reproduce the measured endpoint behaviour."""
    ends: tuple[tuple[End, _Band], ...] = (
        ("low", behaviour.low_band),
        ("high", behaviour.high_band),
    )
    for end, (lo, hi) in ends:
        if lo == -math.inf and hi == math.inf:
            continue
        reachable_lo, reachable_hi = endpoint_exponents(node, end, budget)
        if reachable_hi < lo or reachable_lo > hi:
            return False
    return True


def feasible_topologies(
    nodes: Iterable[Node],
    behaviour: EndpointBehaviour,
    *,
    budget: int = DEFAULT_DEGENERACY_BUDGET,
) -> Iterator[Node]:
    """Stream only the topologies that survive the feasibility screen."""
    for node in nodes:
        if is_feasible(node, behaviour, budget=budget):
            yield node
