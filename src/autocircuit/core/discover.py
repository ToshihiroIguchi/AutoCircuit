"""Automatic equivalent-circuit discovery by genetic programming.

Where :mod:`autocircuit.core.fit` answers "what are the parameters of *this* circuit?", this
module answers "what circuit?". It evolves a population of topologies, fitting each one with
the same no-initial-values engine and scoring it by AICc.

Why not reuse a symbolic-regression package such as PySR? The search *design* transfers, but
the machinery does not. PySR evolves scalar arithmetic expression trees over a Julia backend,
and neither its operator grammar nor its runtime maps onto two-terminal networks or onto a
browser. What is worth borrowing is how it presents results: regularised evolution over a
typed grammar, and an **accuracy-versus-complexity Pareto front** rather than one winner.
That last point matters more here than in ordinary symbolic regression, because equivalent
circuits are genuinely degenerate -- several different topologies routinely fit the same
spectrum equally well, and the honest output is the trade-off curve plus the statistics
needed to choose, not a single confident answer.

The approach follows the published precedent for this specific problem: gene-expression
programming over circuit configurations (Van Haeverbeke et al., IEEE Trans. Instrum. Meas.
70, 2021) and the physics-based post-filtering and model down-selection of AutoEIS (Zhang
et al., J. Electrochem. Soc. 170, 086502, 2023).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from .circuit import (
    Circuit,
    CircuitError,
    ElementNode,
    Node,
    Series,
    count_elements,
    parallel,
    series,
    simplify,
)
from .elements import DEFAULT_POOL

# The structural plausibility filter now lives with the enumerator, which is what applies it
# in bulk; it is re-exported here because it was part of this module's public surface first.
from .enumerate import is_plausible, is_plausible_node  # noqa: F401
from .fit import FitResult, Weighting, fit
from .spectrum import Spectrum

#: Relative standard error above which a parameter counts as unresolved by the data.
UNRESOLVED_STDERR = 1.0

#: Two fitted candidates whose responses agree to better than this everywhere are treated as
#: the same model. The threshold is far below any real measurement uncertainty, so matching it
#: means the topologies are algebraic reparameterisations of one another, not merely similar.
EQUIVALENCE_RTOL = 1e-6

#: A candidate fitting within this factor of the best chi-squared seen is counted as fitting
#: "as well as" the best one, and is then preferred if it is simpler.
PARSIMONY_CHI2_FACTOR = 2.0


@dataclass
class Candidate:
    """One topology that was fitted and scored."""

    circuit: Circuit
    result: FitResult
    generation: int

    @property
    def aicc(self) -> float:
        return self.result.statistics.aicc

    @property
    def complexity(self) -> float:
        return self.circuit.complexity

    @property
    def n_unresolved(self) -> int:
        """Parameters whose standard error exceeds their own value."""
        values = np.abs(self.result.values)
        errors = self.result.statistics.stderr
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(values > 0, errors / values, np.inf)
        return int(np.count_nonzero(ratio > UNRESOLVED_STDERR))

    def to_dict(self) -> dict[str, Any]:
        payload = self.result.to_dict()
        payload["complexity"] = self.complexity
        payload["n_unresolved"] = self.n_unresolved
        payload["generation"] = self.generation
        return payload


@dataclass
class DiscoveryResult:
    """Outcome of a topology search."""

    candidates: list[Candidate]
    """Every distinct topology evaluated, best AICc first."""
    pareto: list[Candidate]
    """The accuracy-versus-complexity trade-off curve, simplest first."""
    n_evaluated: int
    generations: int
    elapsed_s: float
    pool: tuple[str, ...]

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def recommended(self) -> Candidate | None:
        """The candidate actually worth reporting: the simplest one that fits as well as any.

        Picking the minimum-AICc model is the wrong headline. AICc's parameter penalty is
        modest next to the residual gain available from fitting noise, so on a real spectrum
        it routinely lands on an over-parameterised circuit whose extra elements come with
        standard errors larger than their own values -- a model that is numerically excellent
        and physically meaningless. This applies the parsimony rule instead: among candidates
        that fit essentially as well as the best one found, and whose parameters are all
        actually resolved by the data, take the structurally simplest.
        """
        if not self.candidates:
            return None
        best_chi2 = min(c.result.chi2_reduced for c in self.candidates)
        threshold = best_chi2 * PARSIMONY_CHI2_FACTOR
        viable = [
            c
            for c in self.pareto
            if c.result.chi2_reduced <= threshold and c.n_unresolved == 0
        ]
        if not viable:
            viable = [c for c in self.pareto if c.result.chi2_reduced <= threshold]
        if not viable:
            return self.best
        return min(viable, key=lambda c: (c.complexity, c.aicc))

    def equivalence_classes(self) -> list[list[Candidate]]:
        """Group candidates whose fitted responses are numerically indistinguishable.

        Different topologies are routinely exact reparameterisations of each other. A series
        resistance with a parallel RC block, ``R1-p(R2,C1)``, and a resistance in parallel
        with a series RC branch, ``p(R1,C1-R2)``, both describe every possible single
        semicircle; fitted to the same data they agree to machine precision. No impedance
        measurement can prefer one over the other, and presenting whichever the search
        happened to reach first would be misleading. Reporting the class instead makes the
        ambiguity explicit, so that it gets resolved where it belongs -- with physical
        knowledge of the sample.
        """
        classes: list[list[Candidate]] = []
        for candidate in sorted(self.candidates, key=lambda c: c.aicc):
            for group in classes:
                if _same_response(candidate, group[0]):
                    group.append(candidate)
                    break
            else:
                classes.append([candidate])
        return classes

    def equivalents_of(self, candidate: Candidate) -> list[Candidate]:
        """Other evaluated topologies that fit this data identically to ``candidate``."""
        return [
            other
            for other in self.candidates
            if other is not candidate and _same_response(other, candidate)
        ]

    def summary(self, spectrum: Spectrum | None = None, limit: int = 10) -> str:
        lines = [
            f"Evaluated {self.n_evaluated} distinct topologies over {self.generations} "
            f"generations in {self.elapsed_s:.1f} s",
            f"Element pool: {', '.join(self.pool)}",
            "",
            "Pareto front (accuracy versus complexity):",
            f"  {'circuit':<34}{'AICc':>11}{'chi2_red':>11}{'cplx':>7}{'free?':>7}",
        ]
        aliases: list[str] = []
        for candidate in self.pareto[:limit]:
            unresolved = candidate.n_unresolved
            mark = "ok" if unresolved == 0 else f"{unresolved} bad"
            lines.append(
                f"  {candidate.circuit.to_string():<34}{candidate.aicc:>11.2f}"
                f"{candidate.result.chi2_reduced:>11.3g}{candidate.complexity:>7.1f}"
                f"{mark:>7}"
            )
            equivalents = self.equivalents_of(candidate)
            if equivalents:
                names = ", ".join(e.circuit.to_string() for e in equivalents[:4])
                aliases.append(f"  {candidate.circuit.to_string()} == {names}")

        if aliases:
            lines += [
                "",
                "Indistinguishable topologies (identical response; the data cannot choose):",
                *aliases,
            ]

        recommended = self.recommended
        if recommended is not None and self.best is not None:
            lines += ["", f"Recommended    : {recommended.circuit.to_string()}"]
            if recommended is not self.best:
                lines.append(
                    f"Lowest AICc    : {self.best.circuit.to_string()} "
                    f"({self.best.circuit.n_params} parameters, "
                    f"{self.best.n_unresolved} of them unresolved) -- better numerically, but "
                    "the extra elements are not supported by the data."
                )
        if spectrum is not None and recommended is not None:
            lines += ["", "Recommended model:", recommended.result.summary(spectrum)]
        lines += [
            "",
            "Equivalent circuits are degenerate: several topologies often fit the same data",
            "equally well. Choose using physical knowledge of the sample, not a score alone.",
        ]
        return "\n".join(lines)


# -- Tree utilities ------------------------------------------------------------------------


def _paths(node: Node, prefix: tuple[int, ...] = ()) -> list[tuple[int, ...]]:
    """Every subtree position, as a path of child indices from the root."""
    out = [prefix]
    if not isinstance(node, ElementNode):
        for index, child in enumerate(node.children):
            out.extend(_paths(child, (*prefix, index)))
    return out


def _element_paths(node: Node, prefix: tuple[int, ...] = ()) -> list[tuple[int, ...]]:
    if isinstance(node, ElementNode):
        return [prefix]
    out: list[tuple[int, ...]] = []
    for index, child in enumerate(node.children):
        out.extend(_element_paths(child, (*prefix, index)))
    return out


def _get(node: Node, path: Sequence[int]) -> Node:
    for index in path:
        assert not isinstance(node, ElementNode)
        node = node.children[index]
    return node


def _replace(node: Node, path: Sequence[int], new: Node) -> Node:
    if not path:
        return new
    assert not isinstance(node, ElementNode)
    index, rest = path[0], path[1:]
    children = list(node.children)
    children[index] = _replace(children[index], rest, new)
    return series(*children) if isinstance(node, Series) else parallel(*children)


def _delete(node: Node, path: Sequence[int]) -> Node | None:
    """Remove the subtree at ``path``; returns None if that would empty the circuit."""
    if not path:
        return None
    if len(path) == 1:
        assert not isinstance(node, ElementNode)
        children = [c for i, c in enumerate(node.children) if i != path[0]]
        if not children:
            return None
        return series(*children) if isinstance(node, Series) else parallel(*children)
    assert not isinstance(node, ElementNode)
    index = path[0]
    children = list(node.children)
    replacement = _delete(children[index], path[1:])
    if replacement is None:
        children.pop(index)
    else:
        children[index] = replacement
    if not children:
        return None
    return series(*children) if isinstance(node, Series) else parallel(*children)


# -- Genetic operators ---------------------------------------------------------------------


def random_topology(
    rng: np.random.Generator, pool: Sequence[str], n_elements: int
) -> Node:
    """Build a random topology by repeatedly combining nodes in series or in parallel."""
    nodes: list[Node] = [ElementNode(str(rng.choice(pool))) for _ in range(n_elements)]
    while len(nodes) > 1:
        i = int(rng.integers(len(nodes)))
        first = nodes.pop(i)
        j = int(rng.integers(len(nodes)))
        second = nodes.pop(j)
        combined = series(first, second) if rng.random() < 0.55 else parallel(first, second)
        nodes.append(combined)
    return nodes[0]


def mutate(
    node: Node, rng: np.random.Generator, pool: Sequence[str], max_elements: int
) -> Node:
    """Apply one random structural or element-type change."""
    operations = ["retype", "insert_series", "insert_parallel", "delete"]
    weights = np.array([0.35, 0.25, 0.25, 0.15])
    if count_elements(node) >= max_elements:
        weights[1] = weights[2] = 0.0
    if count_elements(node) <= 1:
        weights[3] = 0.0
    weights = weights / weights.sum()
    operation = str(rng.choice(operations, p=weights))

    if operation == "retype":
        path = _element_paths(node)[int(rng.integers(len(_element_paths(node))))]
        return _replace(node, path, ElementNode(str(rng.choice(pool))))

    if operation == "delete":
        paths = _element_paths(node)
        path = paths[int(rng.integers(len(paths)))]
        result = _delete(node, path)
        return result if result is not None else node

    paths = _paths(node)
    path = paths[int(rng.integers(len(paths)))]
    subtree = _get(node, path)
    fresh = ElementNode(str(rng.choice(pool)))
    combined = (
        series(subtree, fresh) if operation == "insert_series" else parallel(subtree, fresh)
    )
    return _replace(node, path, combined)


def crossover(a: Node, b: Node, rng: np.random.Generator) -> Node:
    """Graft a random subtree of ``b`` onto a random position of ``a``."""
    a_paths = _paths(a)
    b_paths = _paths(b)
    target = a_paths[int(rng.integers(len(a_paths)))]
    donor = _get(b, b_paths[int(rng.integers(len(b_paths)))])
    return _replace(a, target, donor)


# -- Search --------------------------------------------------------------------------------


@dataclass
class _Evaluator:
    """Fits topologies with a reduced budget and caches the outcome by canonical form."""

    spectrum: Spectrum
    weighting: Weighting
    restarts: int
    popsize: int
    maxiter: int
    tol: float
    seed: int
    cache: dict[str, Candidate | None] = field(default_factory=dict)

    def evaluate(self, node: Node, generation: int) -> Candidate | None:
        try:
            circuit = Circuit(simplify(node))
        except CircuitError:
            return None
        key = circuit.canonical_form()
        if key in self.cache:
            return self.cache[key]
        if not is_plausible(circuit):
            self.cache[key] = None
            return None

        candidate: Candidate | None
        try:
            result = fit(
                circuit,
                self.spectrum,
                weighting=self.weighting,
                restarts=self.restarts,
                popsize=self.popsize,
                maxiter=self.maxiter,
                tol=self.tol,
                seed=self.seed,
            )
            candidate = (
                Candidate(circuit, result, generation)
                if math.isfinite(result.statistics.aicc)
                else None
            )
        except (ValueError, CircuitError, np.linalg.LinAlgError):
            candidate = None
        self.cache[key] = candidate
        return candidate


def _same_response(a: Candidate, b: Candidate) -> bool:
    """True when two fitted candidates produce the same spectrum to within EQUIVALENCE_RTOL."""
    za, zb = a.result.z_model, b.result.z_model
    if za.shape != zb.shape:
        return False
    magnitude = np.abs(zb)
    if not np.all(magnitude > 0.0):
        return False
    return bool(np.max(np.abs(za - zb) / magnitude) <= EQUIVALENCE_RTOL)


def pareto_front(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Candidates not beaten on both complexity and AICc by any other candidate."""
    front: list[Candidate] = []
    for candidate in candidates:
        dominated = any(
            other is not candidate
            and other.complexity <= candidate.complexity
            and other.aicc <= candidate.aicc
            and (other.complexity < candidate.complexity or other.aicc < candidate.aicc)
            for other in candidates
        )
        if not dominated:
            front.append(candidate)
    return sorted(front, key=lambda c: (c.complexity, c.aicc))


def discover(
    spectrum: Spectrum,
    *,
    pool: Sequence[str] = DEFAULT_POOL,
    generations: int = 30,
    population: int = 40,
    max_elements: int = 7,
    min_elements: int = 2,
    seed: int = 0,
    weighting: Weighting = "modulus",
    search_restarts: int = 1,
    search_popsize: int = 12,
    search_maxiter: int = 60,
    search_tol: float = 1e-5,
    final_restarts: int = 5,
    n_refine: int = 8,
    time_limit: float | None = None,
    seeds: Sequence[str] | None = None,
) -> DiscoveryResult:
    """Search for equivalent-circuit topologies that explain a spectrum.

    Args:
        spectrum: The measured data.
        pool: Element codes the search may use. Restricting this is the main way to inject
            physical knowledge -- e.g. ``("R", "C", "L", "CPE", "SKINF")`` for components.
        generations: Evolutionary generations.
        population: Topologies per generation.
        max_elements: Cap on elements per topology.
        min_elements: Smallest random topology in the initial population.
        seed: Random seed; the whole search is reproducible from it.
        weighting: Residual weighting passed through to the fitter.
        search_restarts, search_popsize, search_maxiter: Reduced fitting budget used while
            searching. Survivors are refitted properly at the end.
        final_restarts: Restart count for the final refit of the reported candidates.
        n_refine: How many top candidates to refit at full budget.
        time_limit: Wall-clock budget in seconds; the search stops cleanly when exceeded.
        seeds: Optional circuit strings to inject into the initial population, for example
            textbook models worth testing alongside the evolved ones.

    Returns:
        A :class:`DiscoveryResult` holding every distinct topology evaluated and the
        accuracy-versus-complexity Pareto front.
    """
    started = time.perf_counter()
    rng = np.random.default_rng(seed)
    pool = tuple(pool)
    evaluator = _Evaluator(
        spectrum, weighting, search_restarts, search_popsize, search_maxiter, search_tol, seed
    )

    trees: list[Node] = []
    for text in seeds or ():
        trees.append(Circuit.parse(text).root)
    while len(trees) < population:
        n = int(rng.integers(min_elements, max_elements + 1))
        trees.append(random_topology(rng, pool, n))

    scored: list[Candidate] = []
    generation = 0
    for generation in range(generations):
        for tree in trees:
            candidate = evaluator.evaluate(tree, generation)
            if candidate is not None:
                scored.append(candidate)
        if time_limit is not None and time.perf_counter() - started > time_limit:
            break

        alive = _unique_best(scored)
        if not alive:
            trees = [
                random_topology(rng, pool, int(rng.integers(min_elements, max_elements + 1)))
                for _ in range(population)
            ]
            continue

        trees = _next_generation(alive, rng, pool, max_elements, population)

    alive = _unique_best(scored)
    alive.sort(key=lambda c: c.aicc)
    refined = _refine(alive[:n_refine], spectrum, weighting, final_restarts, seed)
    merged = _unique_best(refined + alive)
    merged.sort(key=lambda c: c.aicc)

    return DiscoveryResult(
        candidates=merged,
        pareto=pareto_front(merged),
        n_evaluated=len(evaluator.cache),
        generations=generation + 1,
        elapsed_s=time.perf_counter() - started,
        pool=pool,
    )


def _unique_best(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Keep the best-scoring instance of each distinct topology."""
    best: dict[str, Candidate] = {}
    for candidate in candidates:
        key = candidate.circuit.canonical_form()
        if key not in best or candidate.aicc < best[key].aicc:
            best[key] = candidate
    return list(best.values())


def _next_generation(
    alive: list[Candidate],
    rng: np.random.Generator,
    pool: tuple[str, ...],
    max_elements: int,
    population: int,
) -> list[Node]:
    """Elitism over the Pareto front, then tournament selection with mutation/crossover.

    Breeding from the Pareto front rather than from the AICc ranking alone keeps simple
    topologies in play. Otherwise the population converges on whatever fits best regardless
    of size, and the trade-off curve -- the actual deliverable -- collapses to one point.
    """
    front = pareto_front(alive)
    elite = front[: max(2, population // 6)]
    trees: list[Node] = [candidate.circuit.root for candidate in elite]

    while len(trees) < population:
        parent = _tournament(alive, rng)
        if rng.random() < 0.3 and len(alive) > 1:
            other = _tournament(alive, rng)
            child = crossover(parent.circuit.root, other.circuit.root, rng)
        else:
            child = parent.circuit.root
        child = mutate(child, rng, pool, max_elements)
        if count_elements(child) <= max_elements:
            trees.append(child)
    return trees


def _tournament(alive: list[Candidate], rng: np.random.Generator, size: int = 3) -> Candidate:
    picks = rng.integers(0, len(alive), size=min(size, len(alive)))
    return min((alive[int(i)] for i in picks), key=lambda c: c.aicc)


def _refine(
    candidates: Sequence[Candidate],
    spectrum: Spectrum,
    weighting: Weighting,
    restarts: int,
    seed: int,
) -> list[Candidate]:
    """Refit the shortlist at full budget, since the search used a reduced one."""
    out: list[Candidate] = []
    for candidate in candidates:
        try:
            result = fit(
                candidate.circuit,
                spectrum,
                weighting=weighting,
                restarts=restarts,
                seed=seed,
            )
        except (ValueError, CircuitError, np.linalg.LinAlgError):
            continue
        if math.isfinite(result.statistics.aicc):
            out.append(Candidate(candidate.circuit, result, candidate.generation))
    return out
