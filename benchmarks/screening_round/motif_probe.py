"""Does a two-element insertion step ever beat `discover.mutate`'s one-element step?

`docs/CLAUDE.md`'s web-UI review (item 4) asked whether the genetic search should be able to
emit common EIS "motifs" (`p(R,C)` and the like) as a set. A hard-coded motif *library* is ruled
out on inspection, not measurement: it is exactly the shape of bet
`docs/EVOLVE_SEARCH_PLAN.md` section 3.5.2 already measured and rejected for `MUTATION_WEIGHTS`
-- a change that wins on parallel-shaped truths and loses on series-shaped ones, dressed up as
domain knowledge the search is not supposed to have (`CLAUDE.md`: "a `mode` choice encodes no
knowledge about the part... asymmetric setting is the software deciding what kind of part this
is").

What *is* worth measuring is narrower: whether inserting **two** elements at once, combined with
an exactly even series/parallel coin and both elements drawn from `pool` (never a fixed pair),
crosses the "worse intermediate" valley that a one-element-at-a-time insertion must otherwise
cross over two separate, usually-worse generations. This is a step-size claim, not a shape claim,
and section 3.5.2's own conclusion is the pre-registered test it must pass: it ships only if it
wins on a parallel-shaped arena **and does not lose** on a series-shaped one. A win-on-parallel/
lose-on-series result is itself the rejected `mut_par_hi` signature and is a rejection to record,
not a tuning knob.

This file does not edit `discover.py` or `arms.py`. It borrows `arm_ga_bounded`'s exact loop by
temporarily monkeypatching the module-level `mutate` name `_propose_child` resolves at call
time -- restored immediately after, and never active outside one `Trace` -- so the search loop
under test is the library's own `_next_generation`/`_propose_child`, unmodified, exactly as
`arm_ga_bounded` docstring's "a reimplementation would measure this file" rule requires.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/screening_round/motif_probe.py land_rcl6.json targets_rcl6.json \\
        --budget 150 --motif-rate 0.30 --seeds 480 \\
        --out benchmarks/screening_round/motif_rcl6_030.json

``--budget`` has no default -- see its ``--help`` text for why 450 (this script's own earlier
default, and ``arms.py``'s) is the wrong number for these arenas.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

from arms import CRITERION, Ind, Table, Trace, _sign_test  # noqa: E402

import autocircuit.core.discover as discover_module  # noqa: E402
from autocircuit.core.circuit import (  # noqa: E402
    Circuit,
    ElementNode,
    Node,
    count_elements,
    parallel,
    replace_subtree,
    series,
    subtree_at,
    subtree_paths,
)
from autocircuit.core.discover import (  # noqa: E402
    MUTATION_WEIGHTS,
    _breeding_pool,
    _delete,
    _element_paths,
    _next_generation,
    _unique_best,
    random_topology,
)


def mutate_motif(
    node: Node,
    rng: np.random.Generator,
    pool: Sequence[str],
    max_elements: int,
    *,
    weights: Sequence[float] = MUTATION_WEIGHTS,
    motif_rate: float = 0.0,
) -> Node:
    """`discover.mutate`, with a `motif_rate` chance that an insertion places two fresh
    elements (as `series(A,B)` or `parallel(A,B)`, an even coin, A and B drawn from `pool`)
    instead of one. Every other branch (retype, delete) and every weight is untouched -- this
    changes only what an `insert_series`/`insert_parallel` operation inserts, never how often
    one is chosen.
    """
    operations = ["retype", "insert_series", "insert_parallel", "delete"]
    active = np.array(weights, dtype=float)
    if count_elements(node) >= max_elements:
        active[1] = active[2] = 0.0
    if count_elements(node) <= 1:
        active[3] = 0.0
    active = active / active.sum()
    operation = str(rng.choice(operations, p=active))

    if operation == "retype":
        paths = _element_paths(node)
        path = paths[int(rng.integers(len(paths)))]
        return replace_subtree(node, path, ElementNode(str(rng.choice(pool))))

    if operation == "delete":
        # Identical to `discover.mutate`'s own delete branch -- this operator is untouched by
        # `motif_rate`, so it is reused rather than restated only insofar as `_delete` (the
        # library's tree-surgery helper) is imported directly; the branch itself is copied
        # because `mutate` is the very name this module patches during a `Trace`, and calling
        # it recursively here would call back into whichever function is currently bound to it.
        paths = _element_paths(node)
        path = paths[int(rng.integers(len(paths)))]
        result = _delete(node, path)
        return result if result is not None else node

    paths = subtree_paths(node)
    path = paths[int(rng.integers(len(paths)))]
    subtree = subtree_at(node, path)

    if rng.random() < motif_rate and count_elements(node) + 2 <= max_elements:
        a = ElementNode(str(rng.choice(pool)))
        b = ElementNode(str(rng.choice(pool)))
        fresh: Node = series(a, b) if rng.random() < 0.5 else parallel(a, b)
    else:
        fresh = ElementNode(str(rng.choice(pool)))

    combined = series(subtree, fresh) if operation == "insert_series" else parallel(subtree, fresh)
    return replace_subtree(node, path, combined)


@contextmanager
def _patched_mutate(motif_rate: float, weights: Sequence[float]) -> Iterator[None]:
    """Monkeypatch `discover.mutate` for the duration of one arm's `Trace`, then restore it.

    `_propose_child` looks up `mutate` as a global in `discover.py` at call time, so rebinding
    the module attribute redirects every call `_next_generation` makes without altering
    `_next_generation`, `_propose_child` or `_tournament` themselves.
    """
    original = discover_module.mutate
    discover_module.mutate = (  # type: ignore[assignment]
        lambda node, rng, pool, max_elements, *, weights=weights: mutate_motif(
            node, rng, pool, max_elements, weights=weights, motif_rate=motif_rate
        )
    )
    try:
        yield
    finally:
        discover_module.mutate = original  # type: ignore[assignment]


def arm_motif(
    table: Table,
    rng: np.random.Generator,
    pool: tuple[str, ...],
    max_elements: int,
    population: int,
    *,
    motif_rate: float,
    pool_bound: int | None = 0,
) -> Trace:
    """`arm_ga_bounded` at `pool_bound=0` (the shipped Pareto-front-only pool), with
    `mutate_motif` patched in for the duration of this call only.
    """
    with _patched_mutate(motif_rate, MUTATION_WEIGHTS):
        trees: list[tuple[Node, Ind | None]] = [
            (random_topology(rng, pool, int(rng.integers(2, max_elements + 1))), None)
            for _ in range(population)
        ]
        scored: list[Ind] = []
        pressure: list[float] = []
        generation = 0
        while not table.exhausted:
            for tree, _parent in trees:
                ind = table.evaluate(tree, generation)
                if ind is not None:
                    scored.append(ind)
                if table.exhausted:
                    break
            alive_all = _unique_best(scored, CRITERION)
            if not alive_all:
                trees = [
                    (random_topology(rng, pool, int(rng.integers(2, max_elements + 1))), None)
                    for _ in range(population)
                ]
                continue
            bound = population if pool_bound is None else pool_bound
            alive = _breeding_pool(alive_all, bound, CRITERION)
            pressure.append(1.0 - (1.0 - 1.0 / len(alive)) ** 3)
            trees = _next_generation(
                alive, rng, pool, max_elements, population, CRITERION,
                frequencies=None, parsimony=0.0, weights=MUTATION_WEIGHTS,
            )
            generation += 1
    return Trace(table.hit_at, table.fits, table.best, pressure, table.sizes)


def _wilson(hits: int, n: int) -> tuple[float, float]:
    import math

    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("landscape", type=Path)
    ap.add_argument("targets", type=Path)
    ap.add_argument(
        "--budget",
        type=int,
        required=True,
        help=(
            "No default on purpose. `arm_ga_bounded` (pool_bound=0, what this file's arm "
            "reuses) recomputes canonical_form() over an ever-growing, never-deduplicated "
            "scored list once per generation, so its per-run cost rises sharply above the "
            "'unsaturated' budget an arena was calibrated at -- 450 (this script's old "
            "default, and arms.py's own CLI default) is far past that point for these two "
            "arenas and turns a sub-second run into one lasting minutes; this is a pre-"
            "existing property of the shipped arm, confirmed by profiling the unmodified "
            "arms.py code, not something this file introduces. Use the project's own "
            "established unsaturated budgets (docs/EVOLVE_SEARCH_PLAN.md section 3.4.3): "
            "150 for land_rcl6/land_rclcpe6, 40 for land_series_rcl6/land_series_rcl7."
        ),
    )
    ap.add_argument("--seeds", type=int, default=480)
    ap.add_argument("--population", type=int, default=40)
    ap.add_argument("--max-elements", type=int, default=6)
    ap.add_argument("--motif-rate", type=float, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    data = json.loads(args.landscape.read_text(encoding="utf-8"))
    targets = frozenset(json.loads(args.targets.read_text(encoding="utf-8"))["targets"])
    pool = tuple(data["pool"])
    rows: dict[str, tuple[int, int, float]] = {}
    for r in data["rows"]:
        rows[Circuit.parse(r["text"]).canonical_form()] = (
            r["n_elements"], r["n_params"], r["cost"]
        )

    base_hits: list[int | None] = []
    motif_hits: list[int | None] = []
    for seed in range(args.seeds):
        rng = np.random.default_rng(seed)
        table = Table(rows, data["n_data"], targets, args.budget)
        trace = arm_motif(
            table, rng, pool, args.max_elements, args.population, motif_rate=0.0
        )
        base_hits.append(trace.hit_at)

        rng = np.random.default_rng(seed)
        table = Table(rows, data["n_data"], targets, args.budget)
        trace = arm_motif(
            table, rng, pool, args.max_elements, args.population, motif_rate=args.motif_rate
        )
        motif_hits.append(trace.hit_at)

    base_found = [h for h in base_hits if h is not None]
    motif_found = [h for h in motif_hits if h is not None]
    lo_b, hi_b = _wilson(len(base_found), args.seeds)
    lo_m, hi_m = _wilson(len(motif_found), args.seeds)
    only_base = sum(
        1 for a, b in zip(base_hits, motif_hits, strict=True) if a is not None and b is None
    )
    only_motif = sum(
        1 for a, b in zip(base_hits, motif_hits, strict=True) if a is None and b is not None
    )
    p = _sign_test(only_motif, only_base)

    result = {
        "landscape": args.landscape.name,
        "motif_rate": args.motif_rate,
        "seeds": args.seeds,
        "budget": args.budget,
        "base_hit_rate": [len(base_found), args.seeds, lo_b, hi_b],
        "motif_hit_rate": [len(motif_found), args.seeds, lo_m, hi_m],
        "only_base": only_base,
        "only_motif": only_motif,
        "mcnemar_p": p,
    }
    print(json.dumps(result, indent=2))
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
