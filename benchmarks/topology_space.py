"""How large is the topology search space, and how much of it is distinguishable?

This is the measurement that motivated the exhaustive-first redesign in
``docs/DISCOVERY_V2_PLAN.md``. It answers two separate questions:

(a) **Search space.** Exhaustively enumerate every distinct series-parallel network with n
    elements from a pool, before and after the redundancy and plausibility filters that
    discovery already applies.

(b) **Distinguishability.** Fit *every* topology of the right size to noise-free data from a
    known circuit and count how many reach machine precision. Those are exact
    reparameterisations of the truth: no impedance measurement can separate them.

Run: ``python benchmarks/topology_space.py`` (needs PYTHONPATH=src). Part (b) fits a few
hundred circuits and takes a couple of minutes.

The ``enumerate_topologies`` prototype here is the direct ancestor of
``autocircuit.core.enumerate``, and is **deliberately not replaced by it**. The library version
streams the requested level and filters its sub-levels, which is a real optimisation with a
real correctness argument behind it (see that module's ``_compose`` docstring); this one is the
naive, obviously-correct formulation. Keeping both means gate G2 is checked against an
independent implementation rather than against itself. Their outputs were compared as *sets*,
not just counts, for every pool up to six elements: identical.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable

from autocircuit.core.circuit import (
    Circuit,
    ElementNode,
    Node,
    canonical_form,
    count_elements,
    parallel,
    series,
    simplify,
)
from autocircuit.core.discover import is_plausible
from autocircuit.core.fit import fit
from autocircuit.core.simulate import log_frequencies, simulate

POOLS = [
    ("R", "C"),
    ("R", "C", "L"),
    ("R", "C", "L", "CPE"),
    ("R", "C", "L", "CPE", "SKINF"),
]
MAX_N = 6

# (circuit, true parameters, pool, element count, f_min, f_max)
REFERENCES = [
    ("R1-p(R2,C1)", {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8}, ("R", "C"), 3, 1e0, 1e7),
    ("C1-R1-L1", {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10}, ("R", "C", "L"), 3, 1e2, 1e9),
    (
        "p(R1,C1)-p(R2,C2)",
        {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8},
        ("R", "C"),
        4,
        1e-1,
        1e7,
    ),
]


def partitions(total: int, parts: int) -> Iterable[tuple[int, ...]]:
    """Non-increasing integer partitions of ``total`` into exactly ``parts`` positive parts."""
    if parts == 1:
        yield (total,)
        return
    for first in range(total - parts + 1, 0, -1):
        for rest in partitions(total - first, parts - 1):
            if rest[0] <= first:
                yield (first, *rest)


def enumerate_topologies(pool: tuple[str, ...], n: int) -> dict[str, Node]:
    """Every distinct series-parallel network with exactly ``n`` elements from ``pool``.

    Builds up by size: a network of n elements is a series or parallel composition of smaller
    networks whose sizes partition n. Deduplication is by canonical form, which absorbs the
    commutativity of both operators and the flattening of nested same-type nodes.
    """
    levels: dict[int, dict[str, Node]] = {1: {code: ElementNode(code) for code in pool}}
    for size in range(2, n + 1):
        found: dict[str, Node] = {}
        for n_parts in range(2, size + 1):
            for parts in partitions(size, n_parts):
                for combo in itertools.product(*(levels[p].values() for p in parts)):
                    for node in (series(*combo), parallel(*combo)):
                        found.setdefault(canonical_form(node), node)
        levels[size] = found
    return levels[n]


def filtered(topologies: dict[str, Node], n: int) -> set[str]:
    """Apply the same redundancy and plausibility filters the discovery search uses."""
    kept: set[str] = set()
    for node in topologies.values():
        reduced = simplify(node)
        # A topology that collapses to fewer elements was already enumerated at that size.
        if count_elements(reduced) != n:
            continue
        if not is_plausible(Circuit(reduced)):
            continue
        kept.add(canonical_form(reduced))
    return kept


def report_search_space() -> None:
    print("=" * 78)
    print("(a) SEARCH SPACE: distinct topologies with exactly n elements")
    print("=" * 78)
    print(f"{'pool':<26}{'n':>3}{'raw':>10}{'after filters':>15}{'cumulative':>12}")
    for pool in POOLS:
        cumulative = 0
        for n in range(1, MAX_N + 1):
            raw = enumerate_topologies(pool, n)
            kept = filtered(raw, n)
            cumulative += len(kept)
            label = ",".join(pool) if n == 1 else ""
            print(f"{label:<26}{n:>3}{len(raw):>10,}{len(kept):>15,}{cumulative:>12,}")
        print()


def report_distinguishability() -> None:
    print("=" * 78)
    print("(b) DISTINGUISHABILITY: same-size topologies fitting to machine precision")
    print("=" * 78)
    for dsl, truth, pool, n, f_min, f_max in REFERENCES:
        data = simulate(dsl, log_frequencies(f_min, f_max, 10), truth, seed=0)
        candidates = enumerate_topologies(pool, n)

        identical: list[str] = []
        for node in candidates.values():
            circuit = Circuit(node)
            try:
                result = fit(circuit, data, restarts=3, seed=0)
            except Exception:  # noqa: BLE001 - a candidate that cannot be fitted is not a match
                continue
            if result.relative_error(data) < 1e-9:
                identical.append(circuit.to_string())

        print(f"\ntrue circuit : {dsl}   (pool {','.join(pool)}, {n} elements)")
        print(f"  topologies of this size  : {len(candidates)}")
        print(f"  indistinguishable from it: {len(identical)}")
        for name in sorted(identical):
            print(f"      {name}")


if __name__ == "__main__":
    report_search_space()
    report_distinguishability()
