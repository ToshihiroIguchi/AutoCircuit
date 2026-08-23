"""Topology-search arms, measured against the frozen landscape.

Every arm here searches the *same* table of pre-screened topologies, so the only thing that
differs between them is how they choose what to look at next. The budget is therefore counted
in **fits** -- table lookups that were not already cached -- and never in seconds, which makes
the comparison immune to what else is running on the machine (`benchmarks/README.md` records
three separate occasions where a wall-clock budget measured the machine instead of the search).

The incumbent arm is not a reimplementation: `current` drives `discover._next_generation`,
`discover.mutate`, `discover.crossover`, `discover._tournament`, `discover.random_topology` and
`discover._unique_best` directly, with only the evaluator swapped for the table. A
reimplementation would measure this file.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from autocircuit.core.circuit import (
    Circuit,
    ElementNode,
    Node,
    count_elements,
    parallel,
    replace_subtree,
    series,
    simplify,
    subtree_at,
    subtree_paths,
)
from autocircuit.core.discover import (
    _next_generation,
    _screening_score,
    _unique_best,
    crossover,
    mutate,
    pareto_front,
    random_topology,
)

CRITERION = "aicc"


@dataclass
class Ind:
    """A scored topology. Duck-types `discover.Candidate` for the operators that consume one."""

    circuit: Circuit
    _score: float
    complexity: float
    generation: int = 0
    age: int = 0

    def score(self, criterion: str = CRITERION) -> float:
        return self._score


@dataclass
class Table:
    """The frozen landscape plus the bookkeeping every arm shares."""

    rows: dict[str, tuple[int, int, float]]  # canonical -> (n_elements, n_params, cost)
    n_data: int
    targets: frozenset[str]
    budget: int
    cache: dict[str, Ind | None] = field(default_factory=dict)
    fits: int = 0
    hit_at: int | None = None
    best: float = math.inf
    #: How many charged fits landed at each element count. The genetic search is free to
    #: spend its budget wherever `mutate` takes it, and where that is decides how large a
    #: haystack it is actually searching.
    sizes: dict[int, int] = field(default_factory=dict)

    def evaluate(self, node: Node, generation: int = 0) -> Ind | None:
        try:
            circuit = Circuit(simplify(node))
        except Exception:
            return None
        key = circuit.canonical_form()
        if key in self.cache:
            return self.cache[key]
        row = self.rows.get(key)
        if row is None:
            # Implausible, or outside the enumerated space. Costs nothing in the real search
            # either -- `_Evaluator` rejects it before any fitting -- so it is not charged.
            self.cache[key] = None
            return None
        self.fits += 1
        n_elements, n_params, cost = row
        self.sizes[n_elements] = self.sizes.get(n_elements, 0) + 1
        ind = Ind(circuit, _screening_score(cost, n_params, self.n_data, CRITERION),
                  circuit.complexity, generation)
        self.cache[key] = ind
        if ind._score < self.best:
            self.best = ind._score
        if self.hit_at is None and key in self.targets:
            self.hit_at = self.fits
        return ind

    @property
    def exhausted(self) -> bool:
        return self.fits >= self.budget


@dataclass
class Trace:
    """What one run of one arm produced."""

    hit_at: int | None
    fits: int
    best: float
    pressure: list[float] = field(default_factory=list)
    sizes: dict[int, int] = field(default_factory=dict)


# -- Arms ------------------------------------------------------------------------------------


def arm_random(table: Table, rng: np.random.Generator, pool: tuple[str, ...],
               max_elements: int, population: int) -> Trace:
    """The null hypothesis: the genetic search's own proposal distribution, with no selection.

    Not uniform sampling of canonical forms -- deliberately. `random_topology` is what fills
    `_evolve`'s initial population, so using it here isolates *selection and variation* from the
    proposal bias they inherit. An arm that cannot beat this one is not searching.
    """
    while not table.exhausted:
        n = int(rng.integers(2, max_elements + 1))
        table.evaluate(random_topology(rng, pool, n))
    return Trace(table.hit_at, table.fits, table.best, sizes=table.sizes)


def arm_current(table: Table, rng: np.random.Generator, pool: tuple[str, ...],
                max_elements: int, population: int) -> Trace:
    """`_evolve` exactly as it is today, with the table standing in for `_Evaluator`."""
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
        alive = _unique_best(scored, CRITERION)
        if not alive:
            trees = [(random_topology(rng, pool, int(rng.integers(2, max_elements + 1))), None)
                     for _ in range(population)]
            continue
        pressure.append(1.0 - (1.0 - 1.0 / len(alive)) ** 3)
        trees = _next_generation(alive, rng, pool, max_elements, population, CRITERION)
        generation += 1
    return Trace(table.hit_at, table.fits, table.best, pressure, table.sizes)


def arm_ga_bounded(table: Table, rng: np.random.Generator, pool: tuple[str, ...],
                   max_elements: int, population: int) -> Trace:
    """Step 4's minimal half: the same search, but the breeding pool stops growing.

    `_evolve` breeds from the entire history, so `_tournament` draws 3 of N with N rising every
    generation -- the 8.2x pressure collapse of `EVOLVE_SEARCH_PLAN.md` section 1.2. Here the
    pool is the Pareto front plus the best `population` by score, and nothing else changes.
    """
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
            trees = [(random_topology(rng, pool, int(rng.integers(2, max_elements + 1))), None)
                     for _ in range(population)]
            continue
        front = pareto_front(alive_all, CRITERION)
        ranked = sorted(alive_all, key=lambda c: c.score(CRITERION))[:population]
        keys = {id(c) for c in front}
        alive = front + [c for c in ranked if id(c) not in keys]
        scored = list(alive)
        pressure.append(1.0 - (1.0 - 1.0 / len(alive)) ** 3)
        trees = _next_generation(alive, rng, pool, max_elements, population, CRITERION)
        generation += 1
    return Trace(table.hit_at, table.fits, table.best, pressure, table.sizes)


def arm_staged(table: Table, rng: np.random.Generator, pool: tuple[str, ...],
               max_elements: int, population: int, *, patience: int = 3) -> Trace:
    """The same genetic search, but the element cap is *earned* rather than granted.

    `_evolve` is handed `max_elements` on the first generation and `mutate` immediately fills
    the largest layer, which is where the candidates are most numerous and -- for any truth
    smaller than the cap -- where none of them are right. This arm starts the cap at 2 and
    raises it by one whenever the best score has not improved for `patience` generations, so
    the budget reaches a layer only after the layer below has stopped paying. Nothing else
    differs from `current`: the same operators, the same selection, the same population.
    """
    cap = 2
    stale = 0
    best = math.inf
    trees: list[tuple[Node, Ind | None]] = [
        (random_topology(rng, pool, int(rng.integers(2, cap + 1))), None)
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
        alive = _unique_best(scored, CRITERION)
        if not alive:
            trees = [(random_topology(rng, pool, int(rng.integers(2, cap + 1))), None)
                     for _ in range(population)]
            continue
        now = min(c.score(CRITERION) for c in alive)
        if now < best - 1e-9:
            best, stale = now, 0
        else:
            stale += 1
            if stale >= patience and cap < max_elements:
                cap += 1
                stale = 0
        pressure.append(1.0 - (1.0 - 1.0 / len(alive)) ** 3)
        trees = _next_generation(alive, rng, pool, cap, population, CRITERION)
        generation += 1
    return Trace(table.hit_at, table.fits, table.best, pressure, table.sizes)


def _cell(ind: Ind) -> int:
    return len(ind.circuit.leaves)


def arm_mapelites(table: Table, rng: np.random.Generator, pool: tuple[str, ...],
                  max_elements: int, population: int, *, k: int = 8,
                  alps: bool = False, inject: int = 4) -> Trace:
    """Survey candidate (e): the archive becomes the breeding population.

    Behaviour descriptor is element count -- the same axis `_quota_by_size` already keeps a
    quota on -- with `k` elites per cell. Selection draws a cell uniformly and then an elite
    uniformly inside it, so pressure is `1/(cells*k)` and cannot decay with generation number,
    which is the pathology section 1.2 measured. With `alps=True` the cell key gains an age
    layer and `inject` fresh random topologies enter layer 0 every generation, which is what
    stops one lineage owning every cell.
    """
    archive: dict[tuple[int, int], list[Ind]] = {}

    def layer(ind: Ind) -> int:
        return min(ind.age // 5, 3) if alps else 0

    def admit(ind: Ind) -> None:
        key = (_cell(ind), layer(ind))
        cell = archive.setdefault(key, [])
        seen = {c.circuit.canonical_form() for c in cell}
        if ind.circuit.canonical_form() in seen:
            return
        cell.append(ind)
        cell.sort(key=lambda c: c.score(CRITERION))
        del cell[k:]

    for _ in range(population):
        ind = table.evaluate(random_topology(rng, pool, int(rng.integers(2, max_elements + 1))))
        if ind is not None:
            admit(ind)
        if table.exhausted:
            break

    pressure: list[float] = []
    generation = 0
    while not table.exhausted:
        occupants = [c for cell in archive.values() for c in cell]
        if not occupants:
            ind = table.evaluate(
                random_topology(rng, pool, int(rng.integers(2, max_elements + 1)))
            )
            if ind is not None:
                admit(ind)
            continue
        pressure.append(1.0 / len(occupants))
        keys = list(archive)
        for i in range(population):
            if table.exhausted:
                break
            if alps and i < inject:
                child: Node = random_topology(
                    rng, pool, int(rng.integers(2, max_elements + 1))
                )
                age = 0
            else:
                cell = archive[keys[int(rng.integers(len(keys)))]]
                parent = cell[int(rng.integers(len(cell)))]
                child = parent.circuit.root
                age = parent.age + 1
                if rng.random() < 0.3 and len(keys) > 1:
                    other_cell = archive[keys[int(rng.integers(len(keys)))]]
                    other = other_cell[int(rng.integers(len(other_cell)))]
                    child = crossover(child, other.circuit.root, rng)
                child = mutate(child, rng, pool, max_elements)
                if count_elements(child) > max_elements:
                    continue
            ind = table.evaluate(child, generation)
            if ind is not None:
                ind.age = age
                admit(ind)
        generation += 1
    return Trace(table.hit_at, table.fits, table.best, pressure, table.sizes)


def _fronts(pop: Sequence[Ind]) -> list[list[Ind]]:
    """Non-dominated sorting on (complexity, score)."""
    remaining = list(pop)
    out: list[list[Ind]] = []
    while remaining:
        front = pareto_front(remaining, CRITERION)
        if not front:
            break
        out.append(front)
        ids = {id(c) for c in front}
        remaining = [c for c in remaining if id(c) not in ids]
    return out


def arm_nsga2(table: Table, rng: np.random.Generator, pool: tuple[str, ...],
              max_elements: int, population: int) -> Trace:
    """Survey candidate (f): selection aligned with the fact that the deliverable is a front."""
    pop: list[Ind] = []
    for _ in range(population):
        ind = table.evaluate(random_topology(rng, pool, int(rng.integers(2, max_elements + 1))))
        if ind is not None:
            pop.append(ind)
        if table.exhausted:
            break
    pressure: list[float] = []
    generation = 0
    while not table.exhausted:
        rank = {}
        crowd: dict[int, float] = {}
        for level, front in enumerate(_fronts(pop)):
            ordered = sorted(front, key=lambda c: c.complexity)
            for c in ordered:
                rank[id(c)] = level
                crowd[id(c)] = 0.0
            if len(ordered) > 2:
                lo, hi = ordered[0].score(CRITERION), ordered[-1].score(CRITERION)
                span = max(abs(hi - lo), 1e-12)
                crowd[id(ordered[0])] = crowd[id(ordered[-1])] = math.inf
                for j in range(1, len(ordered) - 1):
                    crowd[id(ordered[j])] = abs(
                        ordered[j + 1].score(CRITERION) - ordered[j - 1].score(CRITERION)
                    ) / span
        pressure.append(1.0 / max(len(pop), 1))

        # The three loop variables are bound as defaults rather than closed over: the closure is
        # only ever called inside the iteration that built them, but a late-bound `pop` in a
        # generational loop is the kind of thing that stops being true the moment somebody moves
        # the call, and ruff is right to say so.
        def pick(pop: list[Ind] = pop, rank: dict = rank, crowd: dict = crowd) -> Ind:
            a, b = (pop[int(rng.integers(len(pop)))] for _ in range(2))
            if rank[id(a)] != rank[id(b)]:
                return a if rank[id(a)] < rank[id(b)] else b
            return a if crowd[id(a)] >= crowd[id(b)] else b

        children: list[Ind] = []
        for _ in range(population):
            if table.exhausted:
                break
            parent = pick()
            child = parent.circuit.root
            if rng.random() < 0.3:
                child = crossover(child, pick().circuit.root, rng)
            child = mutate(child, rng, pool, max_elements)
            if count_elements(child) > max_elements:
                continue
            ind = table.evaluate(child, generation)
            if ind is not None:
                children.append(ind)
        merged = _unique_best(pop + children, CRITERION)
        keep: list[Ind] = []
        for front in _fronts(merged):
            if len(keep) + len(front) <= population:
                keep.extend(front)
            else:
                front.sort(key=lambda c: c.score(CRITERION))
                keep.extend(front[: population - len(keep)])
                break
        pop = keep or merged[:population]
        generation += 1
    return Trace(table.hit_at, table.fits, table.best, pressure, table.sizes)


def _grow(node: Node, pool: Sequence[str]) -> list[Node]:
    """Every one-element extension of `node`: a new element in series or parallel anywhere."""
    out: list[Node] = []
    for path in subtree_paths(node):
        subtree = subtree_at(node, path)
        for code in pool:
            fresh = ElementNode(code)
            out.append(replace_subtree(node, path, series(subtree, fresh)))
            out.append(replace_subtree(node, path, parallel(subtree, fresh)))
    return out


def arm_beam(table: Table, rng: np.random.Generator, pool: tuple[str, ...],
             max_elements: int, population: int, *, width: int = 24) -> Trace:
    """HANDOFF option (2) / survey candidate (g): grow one element at a time, keep the best.

    Deterministic given the landscape: level 1 is every single element, each level is every
    one-element extension of the level below, and only the best `width` of each level survive.
    Its claim is not "a better random search" but "no randomness at all" -- so it either finds
    the truth's class or it does not, and there is no seed to average over.
    """
    level: list[Ind] = []
    for code in pool:
        ind = table.evaluate(ElementNode(code))
        if ind is not None:
            level.append(ind)
    for _ in range(2, max_elements + 1):
        children: list[Ind] = []
        for parent in level:
            for child in _grow(parent.circuit.root, pool):
                if table.exhausted:
                    break
                ind = table.evaluate(child)
                if ind is not None:
                    children.append(ind)
            if table.exhausted:
                break
        if not children:
            break
        children = _unique_best(children, CRITERION)
        children.sort(key=lambda c: c.score(CRITERION))
        level = children[:width]
        if table.exhausted:
            break
    return Trace(table.hit_at, table.fits, table.best, sizes=table.sizes)


ARMS: dict[str, Callable[..., Trace]] = {
    "random": arm_random,
    "current": arm_current,
    "ga_bounded": arm_ga_bounded,
    "staged": arm_staged,
    "mapelites": arm_mapelites,
    "mapelites_alps": lambda *a, **k: arm_mapelites(*a, alps=True, **k),
    "nsga2": arm_nsga2,
    "beam1": lambda *a, **k: arm_beam(*a, width=1, **k),
    "beam2": lambda *a, **k: arm_beam(*a, width=2, **k),
    "beam4": lambda *a, **k: arm_beam(*a, width=4, **k),
    "beam8": lambda *a, **k: arm_beam(*a, width=8, **k),
    "beam24": lambda *a, **k: arm_beam(*a, width=24, **k),
}


def _wilson(hits: int, n: int) -> tuple[float, float]:
    """Wilson 95% interval, so a hit fraction out of a few dozen seeds carries its own width."""
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("landscape", type=Path)
    ap.add_argument("targets", type=Path)
    ap.add_argument("--budget", type=int, default=450)
    ap.add_argument("--seeds", type=int, default=60)
    ap.add_argument("--population", type=int, default=40)
    ap.add_argument("--max-elements", type=int, default=6)
    ap.add_argument("--arms", default=",".join(ARMS))
    args = ap.parse_args()

    data = json.loads(args.landscape.read_text(encoding="utf-8"))
    targets = frozenset(json.loads(args.targets.read_text(encoding="utf-8"))["targets"])
    pool = tuple(data["pool"])
    rows: dict[str, tuple[int, int, float]] = {}
    for r in data["rows"]:
        rows[Circuit.parse(r["text"]).canonical_form()] = (
            r["n_elements"], r["n_params"], r["cost"]
        )
    optimum = min(
        _screening_score(c, p, data["n_data"], CRITERION) for _, p, c in rows.values()
    )

    print(f"arena: {args.landscape.name}  pool={pool}  n<={args.max_elements}  "
          f"{len(rows)} topologies, {len(targets)} targets "
          f"({len(targets) / len(rows):.3%})")
    print(f"budget: {args.budget} fits per run, {args.seeds} seeds, population {args.population}")
    print(f"landscape optimum AICc {optimum:.3f}")
    print()
    header = (f"{'arm':16s} {'hit rate':>9s} {'95% CI':>15s} {'median fits':>12s} "
              f"{'mean fits':>10s} {'best AICc':>11s} {'pressure':>17s}")
    print(header)
    print("-" * len(header))

    for name in args.arms.split(","):
        fn = ARMS[name]
        hits: list[int | None] = []
        bests: list[float] = []
        press: list[tuple[float, float]] = []
        size_traces: list[dict[int, int]] = []
        seeds = 1 if name.startswith("beam") else args.seeds
        for seed in range(seeds):
            table = Table(rows, data["n_data"], targets, args.budget)
            rng = np.random.default_rng(seed)
            trace = fn(table, rng, pool, args.max_elements, args.population)
            hits.append(trace.hit_at)
            bests.append(trace.best)
            size_traces.append(trace.sizes)
            if trace.pressure:
                press.append((trace.pressure[0], trace.pressure[-1]))
        sizes: dict[int, int] = {}
        for h in size_traces:
            for k, v in h.items():
                sizes[k] = sizes.get(k, 0) + v
        total = sum(sizes.values()) or 1
        size_txt = " ".join(f"n{k}:{v / total:.0%}" for k, v in sorted(sizes.items()))
        found = [h for h in hits if h is not None]
        lo, hi = _wilson(len(found), seeds)
        median = float(np.median(found)) if found else math.nan
        mean = float(np.mean(found)) if found else math.nan
        p_txt = (f"{np.mean([p[0] for p in press]):.3f}->{np.mean([p[1] for p in press]):.3f}"
                 if press else "-")
        print(f"{name:16s} {len(found)}/{seeds:<5d} [{lo:.2f},{hi:.2f}]      "
              f"{median:12.0f} {mean:10.0f} {np.mean(bests):11.2f} {p_txt:>17s}  {size_txt}")


if __name__ == "__main__":
    main()
