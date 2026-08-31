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
    MUTATION_WEIGHTS,
    _breeding_pool,
    _complexity_frequencies,
    _next_generation,
    _screening_score,
    _unique_best,
    crossover,
    mutate,
    pareto_front,
    random_topology,
)
from autocircuit.core.enumerate import _insertions, enumerate_up_to

CRITERION = "aicc"

#: Fraction of an island's members that its neighbour also breeds from, per generation.
#:
#: This and the three helpers below used to live in `discover.py`. They were removed when this
#: round measured the islands out of the library (`EVOLVE_SEARCH_PLAN.md` section 3.4.4) and
#: they live here now for the reason `arm_nsga2` and `arm_map_elites` do: an arm that recorded
#: a rejection has to stay runnable, or the rejection is a claim rather than a measurement.
MIGRATION_FRACTION = 0.1


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
                   max_elements: int, population: int, *, pool_bound: int | None = None,
                   parsimony: float = 0.0,
                   weights: Sequence[float] = MUTATION_WEIGHTS) -> Trace:
    """Step 4's minimal half: the same search, but the breeding pool stops growing.

    `_evolve` breeds from the entire history, so `_tournament` draws 3 of N with N rising every
    generation -- the 8.2x pressure collapse of `EVOLVE_SEARCH_PLAN.md` section 1.2. Here the
    pool is the Pareto front plus the best `pool_bound` by score, and nothing else changes.

    ``pool_bound`` is how many members past the Pareto front the pool keeps, and the ladder
    registered below walks it from a whole generation down to **none**. It began as the control
    the islands arm needed -- islands narrow the pool *and* split it, so without an arm that only
    narrows, a win could be either -- and it ended as the measurement that removed them and
    changed what ships: `EVOLUTION`'s width is now `discover.BREEDING_EXTRA` = 0, the front
    itself. `None` here means "a whole generation", which is the width step 4 first shipped, so
    `ga_bounded` still reproduces the arm this round originally measured.

    Since the measurement that this arm won, the rule has shipped as `discover._breeding_pool`
    and this arm **calls it** rather than restating it -- the same reason `current` drives
    `_next_generation` instead of copying it. Two differences from the arm as first measured,
    both of them the library's: the archive is no longer truncated to the pool (it is what the
    report's shortlist is drawn from, and the pool provably contains the whole history's front
    and top `population` anyway), and equal scores break on the canonical form rather than on
    insertion order. The re-measured number is in `docs/SEARCH_ALGORITHM_SCREENING.md`.
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
        # `or` would fold a bound of zero into the default, and zero is the arm that
        # decided the question: it is the Pareto front on its own, which is what the ladder
        # converges to and what now ships. It produced a plausible number rather than an error.
        bound = population if pool_bound is None else pool_bound
        alive = _breeding_pool(alive_all, bound, CRITERION)
        pressure.append(1.0 - (1.0 - 1.0 / len(alive)) ** 3)
        # Step 5's two knobs, both of them the library's own and both defaulting to what ships,
        # so `ga_front` is still the shipped search and the sweeps below differ from it in
        # exactly one thing. The frequency map is taken over `alive_all` rather than `alive`
        # for the reason `_complexity_frequencies` gives: the pool is the front, which is one
        # member per complexity and therefore uniformly "crowded".
        trees = _next_generation(
            alive, rng, pool, max_elements, population, CRITERION,
            frequencies=_complexity_frequencies(alive_all) if parsimony else None,
            parsimony=parsimony,
            weights=weights,
        )
        generation += 1
    return Trace(table.hit_at, table.fits, table.best, pressure, table.sizes)


def _island_sizes(population: int, islands: int) -> list[int]:
    """Split one generation across the islands, largest remainders first.

    ``population`` is the size of a *generation*, not of an island, so turning islands on
    subdivides the same budget instead of multiplying it. That is what makes the arms
    comparable: a generation costs the same number of fits either way.
    """
    if islands < 1:
        raise ValueError("islands must be at least 1")
    if population < islands:
        raise ValueError(f"population {population} cannot be split across {islands} islands")
    base, extra = divmod(population, islands)
    return [base + (1 if index < extra else 0) for index in range(islands)]


def _migrants(alive: Sequence[Ind], count: int, criterion: str) -> list[Ind]:
    """The ``count`` best-scoring members an island offers its neighbour."""
    if count <= 0:
        return []
    return sorted(alive, key=lambda c: (c.score(criterion), c.circuit.canonical_form()))[:count]


def _with_migrants(
    alive_by_island: Sequence[list[Ind]],
    sizes: Sequence[int],
    fraction: float,
    criterion: str,
) -> list[list[Ind]]:
    """Ring migration: island *i* also breeds from the best of island *i-1* this generation.

    The exchange is **transient** -- the migrants join the set island *i* breeds from now, and
    not island *i*'s archive. Permanent adoption would leave every island holding every other
    island's best after one lap of the ring, which is the single shared pool islands exist to
    split, reached more slowly.

    A positive fraction always moves at least one member: `round(0.1 * 5)` is 0, so an island
    sweep at a fixed fraction would silently turn migration off at the higher island counts and
    neither result would say what it had measured.
    """
    migrants = [
        _migrants(alive, 0 if fraction <= 0.0 else max(1, round(fraction * size)), criterion)
        for alive, size in zip(alive_by_island, sizes, strict=True)
    ]
    return [
        _unique_best(list(alive) + migrants[index - 1], criterion)
        for index, alive in enumerate(alive_by_island)
    ]


def arm_islands(table: Table, rng: np.random.Generator, pool: tuple[str, ...],
                max_elements: int, population: int, *, islands: int = 4,
                migration: float = MIGRATION_FRACTION,
                pool_bound: int | None = None) -> Trace:
    """Step 4's second half: the same generation, split across sub-populations that breed apart.

    `ga_bounded` bounds the set the search breeds from and EV4 measured what that costs: two
    thirds of the late proposals are topologies already fitted, because one bounded pool is one
    neighbourhood. Islands keep the bound and multiply the neighbourhoods -- `islands` pools,
    each the front-plus-best of its *own* archive, exchanging their best round a ring.

    ``population`` is split rather than multiplied, so a generation costs the same number of
    fits here as in `ga_bounded` and the two arms are comparable at equal budget. Everything
    structural is the library's -- `_island_sizes`, `_with_migrants`, `_breeding_pool`,
    `_next_generation` -- so this arm cannot drift from what ships. Only the random streams are
    the arena's own: the harness hands every arm one `Generator` and spawning from it is the
    same derivation `_island_streams` performs on a seed.

    ``pool_bound`` exists so the islands can be tried under the rule the single-pool ladder
    settled on rather than the one they were written against. Without it the comparison is
    rigged: the ladder's winner breeds from the Pareto front alone, and an islands arm still
    breeding from front-plus-ten would lose for the reason the ladder already measured instead
    of for anything to do with islands.
    """
    sizes = _island_sizes(population, islands)
    streams = list(rng.spawn(islands))
    flocks: list[list[tuple[Node, Ind | None]]] = [
        [(random_topology(stream, pool, int(stream.integers(2, max_elements + 1))), None)
         for _ in range(size)]
        for stream, size in zip(streams, sizes, strict=True)
    ]
    archives: list[list[Ind]] = [[] for _ in range(islands)]
    pressure: list[float] = []
    generation = 0
    while not table.exhausted:
        for index, trees in enumerate(flocks):
            for tree, _parent in trees:
                ind = table.evaluate(tree, generation)
                if ind is not None:
                    archives[index].append(ind)
                if table.exhausted:
                    break
            if table.exhausted:
                break
        alive_by_island = [_unique_best(archive, CRITERION) for archive in archives]
        if islands > 1:
            alive_by_island = _with_migrants(alive_by_island, sizes, migration, CRITERION)
        flocks = []
        for index, (stream, size) in enumerate(zip(streams, sizes, strict=True)):
            alive = alive_by_island[index]
            if not alive:
                flocks.append([
                    (random_topology(stream, pool, int(stream.integers(2, max_elements + 1))),
                     None)
                    for _ in range(size)
                ])
                continue
            bred = _breeding_pool(alive, size if pool_bound is None else pool_bound, CRITERION)
            pressure.append(1.0 - (1.0 - 1.0 / len(bred)) ** 3)
            flocks.append(_next_generation(bred, stream, pool, max_elements, size, CRITERION))
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


def arm_beam_full(table: Table, rng: np.random.Generator, pool: tuple[str, ...],
                  max_elements: int, population: int, *, width: int = 4,
                  seed_level: int = 0) -> Trace:
    """`arm_beam` with the library's own growth operator instead of a local one.

    [measured, ``enumerate._insertions``] ``arm_beam._grow`` attaches a new element *at a
    position*, and that is not all the one-element extensions there are: series and parallel
    nodes are n-ary and flattened, so a proper subset of a node's children is not an addressable
    position and no attachment can put a capacitor across only the ``C1-L1`` half of
    ``R1-C1-L1``. Cross-checked over the whole enumerated space, attachment alone reaches 7 of
    the 16 four-element topologies containing ``R1-C1-L1`` and 58 of 139 at five elements. So
    the beam number already on record was measured with an operator that cannot reach most of
    its own level, and this arm is the same search with the hole closed. It costs more fits per
    level, which is the trade the comparison is for.

    ``seed_level`` is the other half of the question. At 0 the beam grows from single elements,
    as ``arm_beam`` does. Above 0 it starts from **every** topology up to that size -- the
    complete enumeration -- ranks them, and grows the best ``width``. That is what the production
    pipeline actually has in hand: ``_exhaustive`` finishes level 5 and throws the ranking away.
    Those lookups are charged here like any other, so this arm's fit count includes an
    enumeration the real pipeline has already paid for; ``main`` reports the sunk constant
    beside the total so the marginal cost can be read off.
    """
    level: list[Ind] = []
    if seed_level > 0:
        for node in enumerate_up_to(pool, seed_level):
            if table.exhausted:
                break
            ind = table.evaluate(node)
            if ind is not None:
                level.append(ind)
        start = seed_level + 1
    else:
        for code in pool:
            ind = table.evaluate(ElementNode(code))
            if ind is not None:
                level.append(ind)
        start = 2

    level = _unique_best(level, CRITERION)
    level.sort(key=lambda c: c.score(CRITERION))
    level = level[:width]

    for _ in range(start, max_elements + 1):
        children: list[Ind] = []
        for parent in level:
            for child in _insertions(parent.circuit.root, pool):
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
    "islands2": lambda *a, **k: arm_islands(*a, islands=2, **k),
    "islands4": lambda *a, **k: arm_islands(*a, islands=4, **k),
    "islands8": lambda *a, **k: arm_islands(*a, islands=8, **k),
    # The migration sweep, at the island count the sweep above settles on. `iso` is full
    # isolation, which is the arm that says whether the ring is doing anything at all.
    "islands4_iso": lambda *a, **k: arm_islands(*a, islands=4, migration=0.0, **k),
    "islands4_m25": lambda *a, **k: arm_islands(*a, islands=4, migration=0.25, **k),
    "islands4_m50": lambda *a, **k: arm_islands(*a, islands=4, migration=0.5, **k),
    "islands4_m75": lambda *a, **k: arm_islands(*a, islands=4, migration=0.75, **k),
    "islands4_m100": lambda *a, **k: arm_islands(*a, islands=4, migration=1.0, **k),
    "islands2_m50": lambda *a, **k: arm_islands(*a, islands=2, migration=0.5, **k),
    "islands8_m50": lambda *a, **k: arm_islands(*a, islands=8, migration=0.5, **k),
    # The control that separates "several pools" from "one smaller pool": same generation, one
    # neighbourhood, bounded to what a quarter-sized island's would be.
    # The ladder runs down to a pool of one on purpose: a bound that keeps improving all the way
    # there is not "a well-chosen neighbourhood", it is hill climbing wearing a population, and
    # the two are told apart only by measuring the end of the ladder rather than a point on it.
    "ga_tight20": lambda *a, **k: arm_ga_bounded(*a, pool_bound=20, **k),
    "ga_tight10": lambda *a, **k: arm_ga_bounded(*a, pool_bound=10, **k),
    "ga_tight5": lambda *a, **k: arm_ga_bounded(*a, pool_bound=5, **k),
    "ga_tight3": lambda *a, **k: arm_ga_bounded(*a, pool_bound=3, **k),
    "ga_tight1": lambda *a, **k: arm_ga_bounded(*a, pool_bound=1, **k),
    "ga_front": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0, **k),
    "islands2_front": lambda *a, **k: arm_islands(*a, islands=2, migration=0.5,
                                                  pool_bound=0, **k),
    "islands4_front": lambda *a, **k: arm_islands(*a, islands=4, migration=0.5,
                                                  pool_bound=0, **k),
    "islands4_front_iso": lambda *a, **k: arm_islands(*a, islands=4, migration=0.0,
                                                      pool_bound=0, **k),
    # -- Step 5, both sweeps run on top of `ga_front` (the shipped arm) ---------------------
    # Adaptive parsimony: a crowding penalty in units of AICc, applied when picking a parent
    # and nowhere else. The ladder spans four orders of magnitude on purpose -- the frequency
    # is a fraction in [0,1] and the levels a run visits are a handful, so the term a level
    # actually receives is roughly `scaling / (number of levels)`, and anything below ~1 AICc
    # cannot outrank a real score difference.
    "pars0.5": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0, parsimony=0.5, **k),
    "pars2": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0, parsimony=2.0, **k),
    "pars5": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0, parsimony=5.0, **k),
    "pars10": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0, parsimony=10.0, **k),
    "pars20": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0, parsimony=20.0, **k),
    "pars100": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0, parsimony=100.0, **k),
    # The top of the ladder is here to answer a question the middle cannot: `pars20` and
    # `pars100` were byte-identical on the first twelve seeds, which is either saturation --
    # the penalty already outranks every score difference a tournament can show it -- or a
    # sweep that stopped one rung short. Three orders of magnitude past the last change says
    # which.
    "pars300": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0, parsimony=300.0, **k),
    "pars1000": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0, parsimony=1000.0, **k),
    "pars3000": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0, parsimony=3000.0, **k),
    "pars1e4": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0, parsimony=1e4, **k),
    # The limit of the ladder rather than another rung on it. At 1e6 the crowding term outranks
    # every score difference the front can show, so the tournament is "take the least-crowded
    # complexity, score only as a tiebreak" -- selection that has stopped consulting fitness.
    # It is here because a ladder whose top rung wins needs to say whether the win belongs to a
    # setting or to the limit.
    "pars1e6": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0, parsimony=1e6, **k),
    # The mutation weights, in the order `mutate` reads them: retype, insert-series,
    # insert-parallel, delete. `mut_ship` is the shipped tuple under another name, so a run
    # can carry its own control without relying on `ga_front` being listed first.
    "mut_ship": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0,
                                               weights=MUTATION_WEIGHTS, **k),
    "mut_uniform": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0,
                                                  weights=(0.25, 0.25, 0.25, 0.25), **k),
    "mut_retype_hi": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0,
                                                    weights=(0.55, 0.175, 0.175, 0.10), **k),
    "mut_retype_lo": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0,
                                                    weights=(0.15, 0.325, 0.325, 0.20), **k),
    "mut_struct_hi": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0,
                                                    weights=(0.10, 0.35, 0.35, 0.20), **k),
    "mut_del_hi": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0,
                                                 weights=(0.30, 0.20, 0.20, 0.30), **k),
    "mut_del_lo": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0,
                                                 weights=(0.39, 0.28, 0.28, 0.05), **k),
    "mut_series_hi": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0,
                                                    weights=(0.35, 0.35, 0.15, 0.15), **k),
    "mut_par_hi": lambda *a, **k: arm_ga_bounded(*a, pool_bound=0,
                                                 weights=(0.35, 0.15, 0.35, 0.15), **k),
    "staged": arm_staged,
    "mapelites": arm_mapelites,
    "mapelites_alps": lambda *a, **k: arm_mapelites(*a, alps=True, **k),
    "nsga2": arm_nsga2,
    "beam1": lambda *a, **k: arm_beam(*a, width=1, **k),
    "beam2": lambda *a, **k: arm_beam(*a, width=2, **k),
    "beam4": lambda *a, **k: arm_beam(*a, width=4, **k),
    "beam8": lambda *a, **k: arm_beam(*a, width=8, **k),
    "beam24": lambda *a, **k: arm_beam(*a, width=24, **k),
    # -- Growth with the library's complete one-element operator (docs/TOPOLOGY_6PLUS_PLAN.md
    # X4/X5). `beamf*` grows from single elements; `beams5w*` starts from the complete
    # five-element enumeration, which is what `_exhaustive` already produces and discards.
    "beamf1": lambda *a, **k: arm_beam_full(*a, width=1, **k),
    "beamf2": lambda *a, **k: arm_beam_full(*a, width=2, **k),
    "beamf4": lambda *a, **k: arm_beam_full(*a, width=4, **k),
    "beamf8": lambda *a, **k: arm_beam_full(*a, width=8, **k),
    "beamf16": lambda *a, **k: arm_beam_full(*a, width=16, **k),
    "beams5w2": lambda *a, **k: arm_beam_full(*a, width=2, seed_level=5, **k),
    "beams5w4": lambda *a, **k: arm_beam_full(*a, width=4, seed_level=5, **k),
    "beams5w8": lambda *a, **k: arm_beam_full(*a, width=8, seed_level=5, **k),
    "beams5w16": lambda *a, **k: arm_beam_full(*a, width=16, seed_level=5, **k),
}


def _sign_test(faster: int, slower: int) -> float:
    """Two-sided exact sign test on paired wins, ties discarded.

    Every arm walks the *same* table from the same seeds, so the runs are paired seed by seed
    and the paired comparison is the one with power. Reading two medians side by side is not:
    120/120 against 120/120 says the arena has saturated, and 252 against 308 is then the only
    signal left -- which is exactly the situation where an unpaired eyeball turns noise into a
    recommendation.
    """
    n = faster + slower
    if n == 0:
        return 1.0
    extreme = min(faster, slower)
    tail = sum(math.comb(n, k) for k in range(extreme + 1)) / 2**n
    return min(1.0, 2 * tail)


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

    paired: dict[str, list[int | None]] = {}
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
        paired[name] = hits
        found = [h for h in hits if h is not None]
        lo, hi = _wilson(len(found), seeds)
        median = float(np.median(found)) if found else math.nan
        mean = float(np.mean(found)) if found else math.nan
        p_txt = (f"{np.mean([p[0] for p in press]):.3f}->{np.mean([p[1] for p in press]):.3f}"
                 if press else "-")
        # Flushed, because a redirected run of eight arms is otherwise a file that stays
        # empty for twenty minutes and then arrives all at once -- indistinguishable from a
        # process that has died.
        print(f"{name:16s} {len(found)}/{seeds:<5d} [{lo:.2f},{hi:.2f}]      "
              f"{median:12.0f} {mean:10.0f} {np.mean(bests):11.2f} {p_txt:>17s}  {size_txt}",
              flush=True)

    names = args.arms.split(",")
    if len(names) > 1:
        base = names[0]
        # The hit rates are paired too, and the fits table below cannot test them: it drops
        # exactly the seeds where the two arms disagree about hitting at all, which at an
        # unsaturated budget is the entire signal. McNemar is that test -- an exact binomial on
        # the discordant seeds, which is `_sign_test` again with a different pair of counts.
        print()
        print(f"Hit/miss paired against {base} (McNemar, exact):")
        print(f"{'arm':16s} {'both':>6s} {'only base':>10s} {'only arm':>9s} {'neither':>8s} "
              f"{'p':>8s}")
        for name in names[1:]:
            pairs = list(zip(paired[base], paired[name], strict=True))
            both = sum(1 for a, b in pairs if a is not None and b is not None)
            only_base = sum(1 for a, b in pairs if a is not None and b is None)
            only_arm = sum(1 for a, b in pairs if a is None and b is not None)
            neither = sum(1 for a, b in pairs if a is None and b is None)
            print(f"{name:16s} {both:>6d} {only_base:>10d} {only_arm:>9d} {neither:>8d} "
                  f"{_sign_test(only_arm, only_base):>8.4f}")

        print()
        print(f"Paired against {base}, seed by seed (a seed either arm missed is dropped):")
        print(f"{'arm':16s} {'faster':>7s} {'slower':>7s} {'tied':>5s} {'median dfits':>13s} "
              f"{'sign test p':>12s}")
        for name in names[1:]:
            pairs = [
                (a, b)
                for a, b in zip(paired[base], paired[name], strict=True)
                if a is not None and b is not None
            ]
            faster = sum(1 for a, b in pairs if b < a)
            slower = sum(1 for a, b in pairs if b > a)
            tied = len(pairs) - faster - slower
            delta = float(np.median([b - a for a, b in pairs])) if pairs else math.nan
            print(f"{name:16s} {faster:>7d} {slower:>7d} {tied:>5d} {delta:>13.0f} "
                  f"{_sign_test(faster, slower):>12.4f}")


if __name__ == "__main__":
    main()
