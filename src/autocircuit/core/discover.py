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

import contextlib
import math
import multiprocessing
import multiprocessing.pool
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

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
from .enumerate import (
    DEFAULT_DEGENERACY_BUDGET,
    EndpointBehaviour,
    enumerate_topologies,
    is_feasible,
    # The structural plausibility filter now lives with the enumerator, which is what applies
    # it in bulk; it is re-exported here because it was this module's public surface first.
    is_plausible,  # noqa: F401
    is_plausible_node,  # noqa: F401
)
from .fit import FitResult, Weighting, fit, screen
from .spectrum import Spectrum

# The runs test on residual signs, borrowed from the Kramers-Kronig validator: it answers the
# same question ("are these residuals noise, or structure the model failed to describe?"), so
# ``mode="auto"`` uses it to decide whether the exhaustive front is under-fitted.
from .validate import RUNS_Z_LIMIT, _runs_z

Mode = Literal["auto", "exhaustive", "evolve"]

#: Tier-1 screening budget. Enough to rank thousands of topologies, nowhere near enough to
#: publish: every number that reaches the user comes from the tier-2 refit.
SCREEN_POPSIZE = 8
SCREEN_MAXITER = 40
SCREEN_TOL = 1e-4

#: A screened candidate whose global stage is already this many times worse than the best
#: candidate of the same complexity has its local polish skipped (see :func:`fit.screen`).
ABANDON_FACTOR = 100.0

#: Screening cost below which a fit counts as exact. With modulus weighting the cost is the
#: sum of squared *relative* residuals, so this is a part-per-million agreement. Early abandon
#: is switched off against such a reference: on noise-free data every exact equivalent of the
#: truth would otherwise be abandoned by whichever one happened to be screened first, and
#: those equivalents are precisely what the report exists to surface.
PERFECT_COST = 1e-9

#: Default number of candidates refitted at full budget, per mode. The exhaustive stage ranks
#: thousands of topologies with one sloppy fit each, so it needs a wider shortlist than the
#: genetic search, which has already refitted its survivors many times over.
REFINE_DEFAULT = {"evolve": 8, "exhaustive": 30, "auto": 30}

#: Every candidate within this factor of the best screening cost is refitted at full budget,
#: on top of the ``n_refine`` best. A sloppy screen must not be able to drop a near-tie.
REFINE_COST_FACTOR = 10.0

#: ...but no more than this many times the per-size quota. Without a ceiling the near-tie rule
#: is unbounded, and on noisy data it selects hundreds of candidates (see `_shortlist`).
REFINE_CEILING_FACTOR = 2

#: Floor on the per-element-count refit quota, so that a size class is never represented by one
#: or two candidates just because the run happened to span many sizes.
MIN_REFINE_PER_SIZE = 5

#: Tier-1 tasks handed to a worker process at a time. Large enough to amortise the ~1 s
#: interpreter start-up on Windows, small enough that the early-abandon threshold keeps up.
WORKER_CHUNK = 64

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
    mode: str = "evolve"
    """Which search produced this: ``exhaustive``, ``evolve``, or ``auto`` for both."""
    complete_up_to: int | None = None
    """Largest element count whose topologies were *all* evaluated, or None if none were.

    This is the completeness statement that motivates exhaustive discovery: when it is 5,
    every plausible topology with up to five elements from this pool was fitted, so a
    topology absent from the report is absent because it does not fit -- not because the
    search happened to miss it. The genetic search can never set this.
    """

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

    def completeness(self) -> str:
        """One line stating exactly how much of the topology space was covered."""
        if self.complete_up_to is None or self.complete_up_to < 1:
            return (
                "Coverage: sampled, not exhaustive -- absence from this report is not "
                "evidence against a topology."
            )
        return (
            f"Coverage: every plausible topology with up to {self.complete_up_to} elements "
            f"from this pool was evaluated."
        )

    def summary(self, spectrum: Spectrum | None = None, limit: int = 10) -> str:
        scope = f"in {self.elapsed_s:.1f} s"
        if self.generations:
            scope = f"over {self.generations} generations {scope}"
        lines = [
            f"Evaluated {self.n_evaluated} distinct topologies {scope} (mode: {self.mode})",
            f"Element pool: {', '.join(self.pool)}",
            self.completeness(),
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
    mode: Mode = "auto",
    exhaustive_limit: int = 5,
    exhaustive_min: int = 1,
    max_candidates: int = 20_000,
    feasibility_filter: bool = True,
    feasibility_budget: int = DEFAULT_DEGENERACY_BUDGET,
    workers: int = 1,
    on_progress: Callable[[int, int, str | None], None] | None = None,
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
    n_refine: int | None = None,
    time_limit: float | None = None,
    seeds: Sequence[str] | None = None,
) -> DiscoveryResult:
    """Search for equivalent-circuit topologies that explain a spectrum.

    Three modes:

    * ``"exhaustive"`` enumerates *every* plausible topology up to ``exhaustive_limit``
      elements and fits them all in two tiers -- a cheap screen for everything, the full
      budget for the shortlist. It is the only mode that can report completeness.
    * ``"evolve"`` is the genetic search, unchanged; use it above ``exhaustive_limit``
      elements or with pools too wide to enumerate.
    * ``"auto"`` (the default) runs the exhaustive stage, then falls back to the genetic
      search for larger topologies only if the best exhaustive fit still shows *systematic*
      residuals -- a runs test on the residual signs, the same criterion the Kramers-Kronig
      validator uses. Data that is already explained does not pay for a second search.

    Args:
        spectrum: The measured data.
        pool: Element codes the search may use. Restricting this is the main way to inject
            physical knowledge -- e.g. ``("R", "C", "L", "CPE", "SKINF")`` for components.
        mode: ``auto``, ``exhaustive`` or ``evolve`` (see above).
        exhaustive_limit: Largest element count to enumerate exhaustively. Clamped down
            automatically when a level would push the candidate count past
            ``max_candidates``; the resulting coverage is reported as
            :attr:`DiscoveryResult.complete_up_to`, never silently.
        exhaustive_min: Smallest element count to enumerate. Raise it only with an
            independent reason to believe the model is at least that big.
        max_candidates: Ceiling on how many topologies the exhaustive stage may screen.
        feasibility_filter: Apply the structural endpoint-behaviour screen before fitting.
        feasibility_budget: How many elements that screen may treat as degenerate; larger is
            more conservative and removes fewer candidates.
        workers: Processes for the tier-1 screen. Keep at 1 under Pyodide.
        on_progress: Called as ``on_progress(done, total, best)`` during the screen, where
            ``best`` is the DSL string of the best-scoring topology so far.
        generations: Evolutionary generations (genetic search only).
        population: Topologies per generation (genetic search only).
        max_elements: Cap on elements per topology in the genetic search.
        min_elements: Smallest random topology in the initial population.
        seed: Random seed; the whole search is reproducible from it.
        weighting: Residual weighting passed through to the fitter.
        search_restarts, search_popsize, search_maxiter: Reduced fitting budget used by the
            genetic search. Survivors are refitted properly at the end.
        final_restarts: Restart count for the final refit of the reported candidates.
        n_refine: How many top candidates to refit at full budget; see :data:`REFINE_DEFAULT`
            for the per-mode default.
        time_limit: Wall-clock budget in seconds; the search stops cleanly when exceeded.
        seeds: Optional circuit strings to inject into the initial population, for example
            textbook models worth testing alongside the evolved ones.

    Returns:
        A :class:`DiscoveryResult` holding every distinct topology evaluated, the
        accuracy-versus-complexity Pareto front, and how far the coverage is complete.
    """
    if mode not in ("auto", "exhaustive", "evolve"):
        raise ValueError(f"unknown discovery mode {mode!r}")
    started = time.perf_counter()
    codes = tuple(pool)
    refine = REFINE_DEFAULT[mode] if n_refine is None else n_refine

    if mode == "evolve":
        return _evolve(
            spectrum,
            pool=codes,
            generations=generations,
            population=population,
            max_elements=max_elements,
            min_elements=min_elements,
            seed=seed,
            weighting=weighting,
            search_restarts=search_restarts,
            search_popsize=search_popsize,
            search_maxiter=search_maxiter,
            search_tol=search_tol,
            final_restarts=final_restarts,
            n_refine=refine,
            time_limit=time_limit,
            seeds=seeds,
            started=started,
        )

    candidates, complete_up_to, n_screened = _exhaustive(
        spectrum,
        pool=codes,
        limit=min(exhaustive_limit, max_elements),
        floor=max(1, exhaustive_min),
        max_candidates=max_candidates,
        feasibility_filter=feasibility_filter,
        feasibility_budget=feasibility_budget,
        weighting=weighting,
        seed=seed,
        n_refine=refine,
        final_restarts=final_restarts,
        workers=workers,
        on_progress=on_progress,
        time_limit=time_limit,
        started=started,
        extra=seeds,
    )
    generations_run = 0

    if mode == "auto" and _is_underfitted(candidates) and max_elements > (complete_up_to or 0):
        remaining = None if time_limit is None else time_limit - (time.perf_counter() - started)
        if remaining is None or remaining > 0.0:
            evolved = _evolve(
                spectrum,
                pool=codes,
                generations=generations,
                population=population,
                max_elements=max_elements,
                min_elements=max((complete_up_to or 0) + 1, min_elements),
                seed=seed,
                weighting=weighting,
                search_restarts=search_restarts,
                search_popsize=search_popsize,
                search_maxiter=search_maxiter,
                search_tol=search_tol,
                final_restarts=final_restarts,
                n_refine=refine,
                time_limit=remaining,
                seeds=[c.circuit.to_string() for c in candidates[:5]],
                started=time.perf_counter(),
            )
            candidates = _unique_best(candidates + evolved.candidates)
            n_screened += evolved.n_evaluated
            generations_run = evolved.generations

    candidates.sort(key=lambda c: c.aicc)
    return DiscoveryResult(
        candidates=candidates,
        pareto=pareto_front(candidates),
        n_evaluated=n_screened,
        generations=generations_run,
        elapsed_s=time.perf_counter() - started,
        pool=codes,
        mode=mode,
        complete_up_to=complete_up_to,
    )


def _is_underfitted(candidates: Sequence[Candidate]) -> bool:
    """True when the best model leaves residuals that look like structure, not noise.

    The residual vector is the real parts followed by the imaginary parts, so it is split
    before the runs test -- a sign pattern that alternates within each half but flips between
    them would otherwise read as random.
    """
    if not candidates:
        return True
    best = min(candidates, key=lambda c: c.result.chi2_reduced)
    residuals = best.result.residuals
    if residuals.size < 4:
        return False
    half = residuals.size // 2
    z = min(_runs_z(residuals[:half]), _runs_z(residuals[half:]))
    return bool(z < RUNS_Z_LIMIT)


def _evolve(
    spectrum: Spectrum,
    *,
    pool: tuple[str, ...],
    generations: int,
    population: int,
    max_elements: int,
    min_elements: int,
    seed: int,
    weighting: Weighting,
    search_restarts: int,
    search_popsize: int,
    search_maxiter: int,
    search_tol: float,
    final_restarts: int,
    n_refine: int,
    time_limit: float | None,
    seeds: Sequence[str] | None,
    started: float,
) -> DiscoveryResult:
    """The genetic search, unchanged: regularised evolution over the topology grammar."""
    rng = np.random.default_rng(seed)
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
        mode="evolve",
        complete_up_to=None,
    )


# -- Exhaustive search ---------------------------------------------------------------------


def _exhaustive(
    spectrum: Spectrum,
    *,
    pool: tuple[str, ...],
    limit: int,
    floor: int,
    max_candidates: int,
    feasibility_filter: bool,
    feasibility_budget: int,
    weighting: Weighting,
    seed: int,
    n_refine: int,
    final_restarts: int,
    workers: int,
    on_progress: Callable[[int, int, str | None], None] | None,
    time_limit: float | None,
    started: float,
    extra: Sequence[str] | None = None,
) -> tuple[list[Candidate], int | None, int]:
    """Enumerate, screen and refit. Returns (candidates, complete_up_to, topologies seen)."""
    behaviour = (
        EndpointBehaviour.from_spectrum(spectrum) if feasibility_filter else None
    )

    texts: list[str] = []
    # (element count, how many topologies have been queued once that level is complete), used
    # to work out afterwards how far the coverage really got if the screen ran out of time.
    boundaries: list[tuple[int, int]] = []
    for n in range(floor, limit + 1):
        level: list[str] = []
        overflowed = False
        for node in enumerate_topologies(pool, n):
            if behaviour is not None and not is_feasible(
                node, behaviour, budget=feasibility_budget
            ):
                continue
            level.append(Circuit(node).to_string())
            # Abandon the level as soon as it cannot fit. Enumeration is lazy, so an oversized
            # level -- 10^5 candidates on the electrochemical pool at n = 5 -- is never built
            # in full just to be thrown away.
            if texts and len(texts) + len(level) > max_candidates:
                overflowed = True
                break
        # A level is taken whole or not at all: half a level is not a completeness claim.
        if overflowed:
            break
        texts.extend(level)
        boundaries.append((n, len(texts)))

    # The enumerator already yields each canonical form once per level, and a level is defined
    # by its element count, so the only possible duplicates are user-supplied seed circuits.
    seen = {Circuit.parse(text).canonical_form() for text in texts}
    for text in extra or ():
        circuit = Circuit.parse(text)
        if circuit.canonical_form() not in seen:
            seen.add(circuit.canonical_form())
            texts.append(circuit.to_string())

    # One worker pool for the whole run: both tiers use it, so the ~1 s interpreter start-up
    # each process pays on Windows is amortised across everything rather than paid twice.
    with _worker_pool(workers, spectrum, weighting) as executor:
        scored = _screen_all(
            texts,
            spectrum,
            weighting=weighting,
            seed=seed,
            executor=executor,
            on_progress=on_progress,
            time_limit=time_limit,
            started=started,
        )
        candidates = _refit_shortlist(
            scored, spectrum, weighting, final_restarts, seed, n_refine, executor
        )
    # Topologies are screened in size order, so a truncated screen still covers whole levels.
    # Starting above one element forfeits the claim entirely: "all topologies up to N" is only
    # true when the smaller sizes were looked at too.
    complete_up_to = (
        next((n for n, end in reversed(boundaries) if end <= len(scored)), None)
        if floor == 1
        else None
    )
    return candidates, complete_up_to, len(scored)


def _screening_aicc(cost: float, n_params: int, n_data: int) -> float:
    """AICc from a screening cost alone, without the covariance a full fit would give.

    The same formula :func:`stats.compute_statistics` uses, fed the weighted sum of squared
    residuals and the parameter count. That is everything AICc needs; the expensive part of a
    full fit is the Jacobian, which only the uncertainties require.
    """
    if not math.isfinite(cost) or cost <= 0.0 or n_data - n_params - 1 <= 0:
        return math.inf
    aic = n_data * math.log(cost / n_data) + 2.0 * n_params
    return aic + 2.0 * n_params * (n_params + 1) / (n_data - n_params - 1)


def _shortlist(
    scored: Sequence[tuple[float, str]], n_refine: int, n_data: int
) -> list[str]:
    """The screened candidates worth a full-budget refit.

    **The quota is per element count, and that is not a detail.** [measured] Ranking the whole
    screen by cost puts nothing but the largest circuits on the shortlist: raw residual always
    improves with parameters, so on the capacitor reference every one of the 60 best-scoring
    candidates had five elements and the four-element truth -- the circuit that generated the
    data -- never reached tier 2 at all. Two corrections, both needed:

    * rank *within* a size by screening AICc rather than raw cost, so an extra CPE has to earn
      its two parameters even against its own size class;
    * give every size its own quota, so the Pareto front has candidates at each complexity
      instead of a cluster at the top.

    Within a size the list is the AICc-best ``quota``, plus every candidate whose cost is
    within :data:`REFINE_COST_FACTOR` of that size's best -- the near-tie rule, which is what
    stops an exact equivalent from being dropped because the sloppy screen ranked it one place
    too low. [measured] That rule needs a ceiling: at 1% noise a factor 10 in cost is only a
    factor 3.2 in relative error, so hundreds of candidates land inside it and refitting them
    all cost half an hour per run while surfacing nothing new.
    """
    usable = [(cost, text) for cost, text in scored if math.isfinite(cost)]
    if not usable:
        return []

    by_size: dict[int, list[tuple[float, float, str]]] = {}
    for cost, text in usable:
        circuit = Circuit.parse(text)
        aicc = _screening_aicc(cost, circuit.n_params, n_data)
        by_size.setdefault(len(circuit.leaves), []).append((aicc, cost, text))

    quota = max(MIN_REFINE_PER_SIZE, n_refine // len(by_size))
    keep: list[str] = []
    for group in by_size.values():
        group.sort()
        best_cost = min(cost for _, cost, _ in group)
        threshold = best_cost * REFINE_COST_FACTOR if best_cost > 0.0 else math.inf
        near_ties = sum(1 for _, cost, _ in group if cost <= threshold)
        take = min(max(quota, near_ties), quota * REFINE_CEILING_FACTOR)
        keep.extend(text for _, _, text in group[:take])
    return keep


def _full_fit(
    text: str, spectrum: Spectrum, weighting: Weighting, restarts: int, seed: int
) -> FitResult | None:
    """One full-budget fit, or None if the circuit could not be fitted at all."""
    try:
        result = fit(
            Circuit.parse(text), spectrum, weighting=weighting, restarts=restarts, seed=seed
        )
    except (ValueError, CircuitError, np.linalg.LinAlgError):
        return None
    return result if math.isfinite(result.statistics.aicc) else None


def _refit_worker(task: tuple[str, int, int]) -> FitResult | None:
    """Tier-2 refit in a worker process. The whole FitResult comes back, statistics included.

    Returning the finished object rather than just the parameter values keeps the restart
    spread -- which is how a non-identifiable model announces itself -- instead of quietly
    losing it to a single-restart reconstruction in the parent.
    """
    text, restarts, seed = task
    return _full_fit(text, _WORKER["spectrum"], _WORKER["weighting"], restarts, seed)


def _refit_shortlist(
    scored: Sequence[tuple[float, str]],
    spectrum: Spectrum,
    weighting: Weighting,
    restarts: int,
    seed: int,
    n_refine: int,
    executor: multiprocessing.pool.Pool | None = None,
) -> list[Candidate]:
    """Tier 2: refit the shortlist at full budget. Only these numbers are ever reported."""
    texts = _shortlist(scored, n_refine, 2 * spectrum.n)
    if executor is not None and len(texts) > 1:
        results = list(executor.map(_refit_worker, [(t, restarts, seed) for t in texts]))
    else:
        results = [_full_fit(text, spectrum, weighting, restarts, seed) for text in texts]
    out = [Candidate(r.circuit, r, 0) for r in results if r is not None]
    out.sort(key=lambda c: c.aicc)
    return out


@contextlib.contextmanager
def _worker_pool(
    workers: int, spectrum: Spectrum, weighting: Weighting
) -> Iterator[multiprocessing.pool.Pool | None]:
    """A process pool for the whole search, or None when running single-process.

    ``workers=1`` must create nothing at all: that is the Pyodide-safe path, where
    ``multiprocessing`` is unavailable rather than merely slow.
    """
    if not workers or workers <= 1:
        yield None
        return
    with multiprocessing.Pool(
        processes=workers,
        initializer=_init_worker,
        initargs=(spectrum.f, spectrum.z, weighting),
    ) as executor:
        yield executor


def _screen_all(
    texts: Sequence[str],
    spectrum: Spectrum,
    *,
    weighting: Weighting,
    seed: int,
    executor: multiprocessing.pool.Pool | None,
    on_progress: Callable[[int, int, str | None], None] | None,
    time_limit: float | None,
    started: float,
) -> list[tuple[float, str]]:
    """Tier 1: one cheap fit per topology, returning (cost, circuit) pairs."""
    if executor is not None:
        return _screen_parallel(
            texts,
            executor,
            seed=seed,
            on_progress=on_progress,
            time_limit=time_limit,
            started=started,
        )

    scored: list[tuple[float, str]] = []
    best_by_complexity: dict[float, float] = {}
    best_overall = math.inf
    best_text: str | None = None
    for done, text in enumerate(texts, start=1):
        circuit = Circuit.parse(text)
        complexity = circuit.complexity
        try:
            cost = screen(
                circuit,
                spectrum,
                weighting=weighting,
                seed=seed,
                popsize=SCREEN_POPSIZE,
                maxiter=SCREEN_MAXITER,
                tol=SCREEN_TOL,
                abandon_above=_abandon_at(best_by_complexity, complexity),
            )
        except (ValueError, CircuitError, np.linalg.LinAlgError):
            cost = math.inf
        scored.append((cost, text))
        if cost < best_by_complexity.get(complexity, math.inf):
            best_by_complexity[complexity] = cost
        if cost < best_overall:
            best_overall, best_text = cost, text
        if on_progress is not None:
            on_progress(done, len(texts), best_text)
        if time_limit is not None and time.perf_counter() - started > time_limit:
            break
    return scored


def _abandon_at(best_by_complexity: dict[float, float], complexity: float) -> float:
    """Cost above which the local polish is not worth running, for this complexity.

    Returns infinity -- i.e. never abandon -- while the reference fit is still exact, because
    on clean data an exact equivalent screened second would otherwise be judged against a
    reference of order 1e-30 and dropped without ever being polished.
    """
    reference = best_by_complexity.get(complexity, math.inf)
    if reference <= PERFECT_COST:
        return math.inf
    return reference * ABANDON_FACTOR


#: Per-process state for the parallel screen. Filled once per worker by the pool initializer
#: so that the spectrum is not pickled with every task.
_WORKER: dict[str, Any] = {}


def _init_worker(f: Any, z: Any, weighting: Weighting) -> None:
    _WORKER["spectrum"] = Spectrum(f, z)
    _WORKER["weighting"] = weighting


def _screen_worker(task: tuple[str, int, float]) -> tuple[float, str]:
    """Screen one topology in a worker process; the task carries only strings and numbers."""
    text, seed, abandon = task
    try:
        cost = screen(
            text,
            _WORKER["spectrum"],
            weighting=_WORKER["weighting"],
            seed=seed,
            popsize=SCREEN_POPSIZE,
            maxiter=SCREEN_MAXITER,
            tol=SCREEN_TOL,
            abandon_above=abandon,
        )
    except (ValueError, CircuitError, np.linalg.LinAlgError):
        cost = math.inf
    return cost, text


def _screen_parallel(
    texts: Sequence[str],
    executor: multiprocessing.pool.Pool,
    *,
    seed: int,
    on_progress: Callable[[int, int, str | None], None] | None,
    time_limit: float | None,
    started: float,
) -> list[tuple[float, str]]:
    """The same screen fanned across processes.

    Tasks are submitted in chunks rather than all at once so that the early-abandon threshold
    can be refreshed between chunks; within a chunk it is necessarily stale, which costs a
    little time but can never change a result.
    """
    scored: list[tuple[float, str]] = []
    complexity_of = {text: Circuit.parse(text).complexity for text in texts}
    best_by_complexity: dict[float, float] = {}
    best_overall = math.inf
    best_text: str | None = None
    for start in range(0, len(texts), WORKER_CHUNK):
        tasks = [
            (text, seed, _abandon_at(best_by_complexity, complexity_of[text]))
            for text in texts[start : start + WORKER_CHUNK]
        ]
        for cost, text in executor.imap_unordered(_screen_worker, tasks):
            scored.append((cost, text))
            complexity = complexity_of[text]
            if cost < best_by_complexity.get(complexity, math.inf):
                best_by_complexity[complexity] = cost
            if cost < best_overall:
                best_overall, best_text = cost, text
        if on_progress is not None:
            on_progress(len(scored), len(texts), best_text)
        if time_limit is not None and time.perf_counter() - started > time_limit:
            break
    return scored


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
