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
from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple

import numpy as np

from .circuit import (
    Circuit,
    CircuitError,
    ElementNode,
    Node,
    Series,
    count_elements,
    parallel,
    replace_subtree,
    series,
    simplify,
    subtree_at,
    subtree_paths,
)
from .elements import DEFAULT_POOL
from .enumerate import (
    DEFAULT_DEGENERACY_BUDGET,
    EndpointBehaviour,
    contains_skeleton,
    count_skeleton_placements,
    enumerate_topologies,
    grow_up_to,
    is_feasible,
    # The structural plausibility filter now lives with the enumerator, which is what applies
    # it in bulk; it is re-exported here because it was this module's public surface first.
    is_plausible,  # noqa: F401
    is_plausible_node,  # noqa: F401
    skeleton_placements,
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


class ScreenBudget(NamedTuple):
    """The tier-1 differential-evolution budget, as one injectable object.

    The screen is the dominant cost of an exhaustive run, so how far it can be cut without
    losing the truth from the tier-2 shortlist is an empirical question. Bundling the budget
    here lets ``benchmarks/discovery_v2.py screen-rank`` sweep it without monkey-patching
    module constants; nothing in the library ever passes anything but the default.
    """

    popsize: int = SCREEN_POPSIZE
    maxiter: int = SCREEN_MAXITER


SCREEN_BUDGET = ScreenBudget()

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

#: Largest element count the exhaustive stage enumerates when the caller names no limit.
DEFAULT_EXHAUSTIVE_LIMIT = 5

#: How many elements a skeleton run reaches for beyond the skeleton itself, by default.
#:
#: This is a *reach*, not a budget, and the difference is the whole point. [measured,
#: docs/PARTIAL_TOPOLOGY_PLAN.md section 4.1] A fixed offset used as the limit would be wrong
#: in both directions: +2 is the affordable ceiling for a ten-element skeleton (11,418
#: candidates) while a three-element one reaches +3 comfortably (9,857). What varies is the
#: skeleton's shape, not a number anyone can pick in advance -- so the run simply reaches high
#: and lets ``max_candidates`` and the frontier clamp stop it where the space actually gets
#: expensive, reporting where that was through :attr:`DiscoveryResult.complete_up_to`.
SKELETON_REACH = 5

#: How much larger than ``max_candidates`` a skeleton's frontier may grow before growth stops.
#:
#: [measured] The frontier holds every grown tree; the level holds only those that survive
#: simplification and the plausibility rules, and the ratio between them rises level by level --
#: 1.3, 1.6, 1.9 at +1, +2, +3 from ``C1-R1-L1`` on the component pool, and 1.5, 2.4, 3.9 from
#: ``R1-C1-L1`` on R,C,L. Bounding the frontier at ``max_candidates`` itself would therefore
#: stop short of the budget it exists to enforce: six elements from ``C1-R1-L1`` is 9,857
#: candidates grown from a frontier of 18,682, so a run allowed 20,000 candidates would lose
#: the level that brings six elements into range at all -- and it is the first level a
#: skeleton makes affordable that an unconstrained search never could (section 1 of
#: docs/PARTIAL_TOPOLOGY_PLAN.md). Four covers the measured ratios with room to spare while
#: still stopping the 40-70x jump to the next level.
FRONTIER_HEADROOM = 4


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
    def unresolved(self) -> np.ndarray:
        """Per-parameter mask: True where the standard error exceeds the value itself.

        Kept as a mask rather than only a count because the count answers "is this model
        identifiable?" while the mask answers "*which* element is not" -- and under a skeleton
        the second question is the one that matters, since an asserted element the fit could
        not pin down is an assertion the data never tested (see
        :meth:`DiscoveryResult.unsupported_assertion`).
        """
        values = np.abs(self.result.values)
        errors = self.result.statistics.stderr
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(values > 0, errors / values, np.inf)
        return np.asarray(ratio > UNRESOLVED_STDERR)

    @property
    def n_unresolved(self) -> int:
        """Parameters whose standard error exceeds their own value."""
        return int(np.count_nonzero(self.unresolved))

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
    skeleton: str | None = None
    """The circuit the user asserted, when the search was constrained to contain it.

    Its presence narrows every claim this object makes, which is why it is stored beside them
    rather than left with the caller: nothing outside the skeleton was evaluated, so nothing
    in the report is evidence for or against it. See :meth:`completeness`.
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
        well_fitting = self._well_fitting()
        viable = [c for c in well_fitting if c.n_unresolved == 0] or well_fitting
        if not viable:
            return self.best
        return min(viable, key=lambda c: (c.complexity, c.aicc))

    def _well_fitting(self) -> list[Candidate]:
        """Pareto candidates that fit essentially as well as the best one found."""
        if not self.candidates:
            return []
        threshold = min(c.result.chi2_reduced for c in self.candidates) * PARSIMONY_CHI2_FACTOR
        return [c for c in self.pareto if c.result.chi2_reduced <= threshold]

    @property
    def unresolved_everywhere(self) -> bool:
        """True when *every* candidate that fits the data leaves parameters it cannot resolve.

        This is a finding about the experiment rather than about the search, and it deserves to
        be reported as one. When it holds, the parsimony rule in :attr:`recommended` has nothing
        left to prefer: each model that fits carries at least one parameter whose standard error
        exceeds its own value, so the report is a set of circuits that describe the data and
        pin down nothing.

        A large skeleton is the systematic way to arrive here -- a thirteen-element candidate
        carries 14-15 parameters against the 142 real residuals of a 71-point spectrum -- but
        the condition is not particular to one, and neither is the answer: no amount of
        enumeration speed fixes it, because the missing constraint is measurement. More data
        does (a wider frequency window, more points, several bias points).
        """
        well_fitting = self._well_fitting()
        return bool(well_fitting) and all(c.n_unresolved > 0 for c in well_fitting)

    def unsupported_assertion(self, candidate: Candidate) -> tuple[str, ...]:
        """The user's asserted elements this fit could not pin down; empty when it could.

        [measured, docs/PARTIAL_TOPOLOGY_PLAN.md section 3.2] **This is what a wrong skeleton
        looks like.** Over three reference spectra and ten seeds each, a skeleton the truth did
        not contain left no trace in the two places a reader would look: residual structure
        0/30, and a chi-squared equal to what the *truth itself* achieves on the same data, to
        two figures, every time. What it did leave was this. Asserting ``R1-p(R2,C1)`` against
        a capacitor whose truth is ``C1-R1-L1-SKINF1`` returns ``R1-p(R2,C1-L1-SKINF1)``, which
        becomes the truth exactly when R2 goes to an open -- so the fit neutralises the
        asserted branch, and the element it had to neutralise is the one whose standard error
        exceeds its own value. 9/10 seeds.

        The answer is taken over placements (§3.5): if *any* way of reading the skeleton into
        this circuit resolves all of its elements, the assertion is supported and the result is
        empty. Otherwise the most favourable reading is reported, so the message names as few
        elements as the data allows rather than as many.

        Note what this is not. It is not a claim that the skeleton is wrong: an element the
        data cannot pin down is an element the data has not tested, which is a weaker and more
        honest statement. A skeleton that merely *generalises* the truth -- a CPE where the
        sample has an ideal capacitance -- fits identically with everything resolved, and this
        correctly stays silent for it.
        """
        if self.skeleton is None:
            return ()
        placements = skeleton_placements(
            candidate.circuit.root, Circuit.parse(self.skeleton).root
        )
        unresolved = candidate.unresolved
        leaves = candidate.circuit.leaves
        spans = candidate.circuit.slices()
        best: tuple[str, ...] | None = None
        for placement in placements:
            labels = tuple(
                leaves[index].label
                for index in sorted(placement)
                if bool(np.any(unresolved[spans[leaves[index].label]]))
            )
            if not labels:
                return ()
            if best is None or len(labels) < len(best):
                best = labels
        return best or ()

    def placements_of(self, candidate: Candidate) -> int:
        """How many structurally distinct ways the skeleton sits inside ``candidate``.

        Zero when the search was unconstrained. Above one means the fit cannot attribute the
        user's assertion to particular elements of this topology; see
        :func:`~autocircuit.core.enumerate.count_skeleton_placements`.
        """
        if self.skeleton is None:
            return 0
        return count_skeleton_placements(
            candidate.circuit.root, Circuit.parse(self.skeleton).root
        )

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
        """Exactly how much of the topology space was covered, and of *which* space.

        Under a skeleton the unconstrained sentence is simply false: "every plausible
        topology with up to N elements" was not evaluated, only the ones containing the
        skeleton were. The claim is still a completeness claim and a more useful one inside
        its own space, but it is a different one, and the difference goes on the same line
        rather than into a footnote -- a reader who skims past the constraint has been misled
        by a true sentence, which is this mode's central risk
        (docs/PARTIAL_TOPOLOGY_PLAN.md sections 3.1 and 7).
        """
        if self.complete_up_to is None or self.complete_up_to < 1:
            if self.skeleton is not None:
                return (
                    "Coverage: sampled, not exhaustive, and restricted to topologies "
                    f"containing {self.skeleton} -- absence from this report is not evidence "
                    "against a topology."
                )
            return (
                "Coverage: sampled, not exhaustive -- absence from this report is not "
                "evidence against a topology."
            )
        if self.skeleton is not None:
            return (
                f"Coverage: every plausible topology with up to {self.complete_up_to} "
                f"elements that contains {self.skeleton} was evaluated, with the added "
                "elements taken from this pool. Topologies without that skeleton were never "
                "considered, so this report is not evidence against them."
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
        ]
        if self.skeleton is not None:
            lines.append(f"Skeleton     : {self.skeleton} (asserted by you, not discovered)")
        lines += [
            self.completeness(),
            "",
            "Pareto front (accuracy versus complexity):",
            f"  {'circuit':<34}{'AICc':>11}{'chi2_red':>11}{'cplx':>7}{'free?':>7}",
        ]
        aliases: list[str] = []
        ambiguous: list[str] = []
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
            placements = self.placements_of(candidate)
            if placements > 1:
                ambiguous.append(
                    f"  {candidate.circuit.to_string()}: {placements} ways"
                )

        if aliases:
            lines += [
                "",
                "Indistinguishable topologies (identical response; the data cannot choose):",
                *aliases,
            ]

        if ambiguous:
            lines += [
                "",
                f"Where {self.skeleton} sits in these (it fits in more than one place, and the",
                "fit cannot say which elements are the ones you asserted):",
                *ambiguous,
            ]

        if self.unresolved_everywhere:
            lines += [
                "",
                "! Every candidate that fits this data leaves parameters the data cannot",
                "  resolve -- their standard errors exceed their own values. That is a finding",
                "  about the measurement, not about the search: a wider frequency window or",
                "  more points would fix it, a longer search would not.",
            ]

        recommended = self.recommended
        if recommended is not None and self.best is not None:
            lines += ["", f"Recommended    : {recommended.circuit.to_string()}"]
            unsupported = self.unsupported_assertion(recommended)
            if unsupported:
                named = ", ".join(unsupported)
                lines += [
                    f"! The data does not test part of your skeleton: {named} came back with a",
                    "  standard error larger than its own value, under every way the skeleton",
                    "  fits this circuit. The fit is what it is with that element switched off,",
                    "  so the data neither supports nor refutes that part of your assertion --",
                    "  which is also what a wrong skeleton looks like.",
                ]
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


def _element_paths(node: Node, prefix: tuple[int, ...] = ()) -> list[tuple[int, ...]]:
    if isinstance(node, ElementNode):
        return [prefix]
    out: list[tuple[int, ...]] = []
    for index, child in enumerate(node.children):
        out.extend(_element_paths(child, (*prefix, index)))
    return out


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
        return replace_subtree(node, path, ElementNode(str(rng.choice(pool))))

    if operation == "delete":
        paths = _element_paths(node)
        path = paths[int(rng.integers(len(paths)))]
        result = _delete(node, path)
        return result if result is not None else node

    paths = subtree_paths(node)
    path = paths[int(rng.integers(len(paths)))]
    subtree = subtree_at(node, path)
    fresh = ElementNode(str(rng.choice(pool)))
    combined = (
        series(subtree, fresh) if operation == "insert_series" else parallel(subtree, fresh)
    )
    return replace_subtree(node, path, combined)


def crossover(a: Node, b: Node, rng: np.random.Generator) -> Node:
    """Graft a random subtree of ``b`` onto a random position of ``a``."""
    a_paths = subtree_paths(a)
    b_paths = subtree_paths(b)
    target = a_paths[int(rng.integers(len(a_paths)))]
    donor = subtree_at(b, b_paths[int(rng.integers(len(b_paths)))])
    return replace_subtree(a, target, donor)


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
    skeleton: str | None = None,
    mode: Mode = "auto",
    exhaustive_limit: int | None = None,
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

    ``skeleton`` narrows the space to the topologies that contain a circuit the caller
    asserts, which is a much sharper instrument than restricting the pool: [measured] at five
    elements from the component pool, ``C1-R1-L1`` cuts 10,214 candidates to 601. It is also
    the only argument here that can remove the right answer while leaving the report looking
    healthy, so what the result is allowed to claim changes with it -- see
    :meth:`DiscoveryResult.completeness` and docs/PARTIAL_TOPOLOGY_PLAN.md section 3.

    Args:
        spectrum: The measured data.
        pool: Element codes the search may use. Restricting this is the main way to inject
            physical knowledge -- e.g. ``("R", "C", "L", "CPE", "SKINF")`` for components.
        skeleton: A circuit every candidate must contain, e.g. ``"C1-R1-L1"``. The search
            adds elements to it and never removes them, so it is an assertion rather than a
            finding. ``pool`` governs the *added* elements only: the skeleton may use codes
            outside it. Containment is deletion-and-collapse, not subtree matching
            (:func:`~autocircuit.core.enumerate.contains_skeleton`). Only the exhaustive
            stage can honour it, so ``mode="evolve"`` with a skeleton is an error and
            ``mode="auto"`` runs the exhaustive stage alone.
        mode: ``auto``, ``exhaustive`` or ``evolve`` (see above).
        exhaustive_limit: Largest *total* element count to enumerate exhaustively -- with a
            skeleton too, so a limit below the skeleton's own size is an error rather than an
            empty result. Clamped down automatically when a level would push the candidate
            count past ``max_candidates``; the resulting coverage is reported as
            :attr:`DiscoveryResult.complete_up_to`, never silently. Defaults to
            :data:`DEFAULT_EXHAUSTIVE_LIMIT`, or to the skeleton's size plus
            :data:`SKELETON_REACH` when one is given.
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
        n_refine: Refit budget for the full-budget second tier. In the exhaustive stage it is
            a *total* that is split into a quota per element count, so that every complexity
            reaches the Pareto front; see :func:`_shortlist`. :data:`REFINE_DEFAULT` holds the
            per-mode default.
        time_limit: Wall-clock budget in seconds; the search stops cleanly when exceeded.
        seeds: Optional circuit strings to inject into the initial population, for example
            textbook models worth testing alongside the evolved ones. Under a skeleton every
            seed must contain it, since a seed is a hint that adds to the candidate list while
            a skeleton is a constraint on what that list may hold.

    Returns:
        A :class:`DiscoveryResult` holding every distinct topology evaluated, the
        accuracy-versus-complexity Pareto front, and how far the coverage is complete.
    """
    if mode not in ("auto", "exhaustive", "evolve"):
        raise ValueError(f"unknown discovery mode {mode!r}")
    started = time.perf_counter()
    codes = tuple(pool)
    refine = REFINE_DEFAULT[mode] if n_refine is None else n_refine
    frame = None if skeleton is None else Circuit.parse(skeleton)

    if frame is not None and mode == "evolve":
        raise ValueError(
            "mode='evolve' cannot honour a skeleton: its mutation operator deletes and "
            "retypes elements, so the population is not confined to circuits containing "
            "one. Use mode='exhaustive'."
        )
    if frame is not None:
        # A seed is a hint that adds a circuit to the candidate list; a skeleton is a
        # constraint on what the list may contain. Asking for both is contradictory when the
        # seed does not satisfy the constraint, and the harm is not hypothetical: the seed
        # could be recommended, under a coverage line saying only topologies containing the
        # skeleton were considered. Refuse before anything is fitted rather than choose for
        # the user which of their two instructions to drop.
        for text in seeds or ():
            if not contains_skeleton(Circuit.parse(text).root, frame.root):
                raise ValueError(
                    f"seed circuit {text!r} does not contain the skeleton {skeleton!r}, so it "
                    "cannot be evaluated under it. Drop one of the two."
                )
    limit = exhaustive_limit_for(None if frame is None else len(frame.leaves), exhaustive_limit)

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
        skeleton=None if frame is None else frame.root,
        # ``max_elements`` caps the genetic search, which never runs under a skeleton, so
        # letting it clamp the enumeration there would silently cut a ten-element skeleton
        # off below its own size.
        limit=limit if frame is not None else min(limit, max_elements),
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

    # The genetic fallback is skipped under a skeleton rather than filtered: its operators can
    # delete the asserted elements, and a report that mixed constrained and unconstrained
    # candidates could not state which space it had covered.
    if (
        mode == "auto"
        and frame is None
        and _is_underfitted(candidates)
        and max_elements > (complete_up_to or 0)
    ):
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
        skeleton=None if frame is None else frame.to_string(),
    )


@dataclass(frozen=True)
class ExcludedEquivalents:
    """What a skeleton removed from the report, at the size of one reported candidate."""

    circuit: str
    """The reported candidate this was computed for."""
    skeleton: str
    size: int
    kept: int
    """Topologies of that size that contain the skeleton -- the ones the search evaluated."""
    excluded: int
    """Topologies of that size that do not, and were therefore never fitted."""
    equivalents: tuple[str, ...]
    """Excluded topologies found to reproduce ``circuit``'s fitted response exactly."""
    elapsed_s: float

    def summary(self) -> str:
        if not self.equivalents:
            return (
                f"Your skeleton {self.skeleton} excluded {self.excluded} of the "
                f"{self.kept + self.excluded} topologies with {self.size} elements, and none "
                f"of them reproduces {self.circuit} exactly on this frequency window. Nothing "
                "the data could not already distinguish was lost."
            )
        names = ", ".join(self.equivalents)
        return (
            f"Your skeleton {self.skeleton} excluded {self.excluded} of the "
            f"{self.kept + self.excluded} topologies with {self.size} elements, and "
            f"{len(self.equivalents)} of them fit {self.circuit} exactly on this frequency "
            f"window: {names}. The data cannot tell these apart from the reported one -- "
            "choosing between them is something you did, not something the fit found."
        )


def excluded_equivalents(
    candidate: Candidate,
    skeleton: str,
    spectrum: Spectrum,
    *,
    pool: Sequence[str] = DEFAULT_POOL,
    weighting: Weighting = "modulus",
    seed: int = 0,
    workers: int = 1,
    budget: ScreenBudget = SCREEN_BUDGET,
) -> ExcludedEquivalents:
    """Which topologies the skeleton removed that would have fitted identically.

    A skeleton chooses among forms the data cannot distinguish: `R1-p(R2,C1)` and
    `p(R1,C1-R2)` fit any single semicircle to 1.2e-15, and asserting a series resistance keeps
    the first and excludes the second. That is legitimate -- a physical electrode really does
    have an electrolyte resistance -- but it is a choice the *user* made, and the report must
    not let it read as something the data supported (docs/PARTIAL_TOPOLOGY_PLAN.md section
    3.3).

    The excluded topologies are, by definition, the ones the search never fitted, so their
    equivalence has to be established here rather than read off the search. **The target is
    ``candidate``'s fitted response, not the measured data**: an exact reparameterisation
    reaches a noise-free target to machine precision, which noise would otherwise mask, and it
    turns the question from "does this fit the sample?" into the algebraic one actually being
    asked. Every excluded topology of the same size gets one tier-1 screen against it, and
    those reaching :data:`PERFECT_COST` are reported.

    [measured] On the capacitor reference at four elements this is 1,132 screens, 137 s on one
    core (121 ms each) or well under a minute across eight workers, and it finds exactly one
    excluded equivalent: `R1-L1-CPE1-SKINF1`, because a CPE with n = -1 *is* a capacitor. Two
    consequences, both deliberate. It is **opt-in**, since a size-5 pass is ~20 min single-core
    and the search it accompanies takes one. And the list is what the screen *found*: a tier-1
    budget can miss an exact equivalent, so the count is a floor, never a proof that nothing
    else was lost.
    """
    started = time.perf_counter()
    frame = Circuit.parse(skeleton).root
    size = len(candidate.circuit.leaves)
    # Noise-free: the question is whether the algebra can reach this response, not whether the
    # topology also happens to absorb this sample's noise.
    target = Spectrum(spectrum.f, candidate.result.z_model)

    outside: list[str] = []
    kept = 0
    for node in enumerate_topologies(pool, size):
        if contains_skeleton(node, frame):
            kept += 1
        else:
            outside.append(Circuit(node).to_string())

    with _worker_pool(workers, target, weighting) as executor:
        if executor is not None and len(outside) > 1:
            costs = list(
                executor.map(
                    _screen_worker,
                    [(text, seed, math.inf, budget.popsize, budget.maxiter) for text in outside],
                )
            )
        else:
            costs = [
                _screen_one(
                    ScreenTask(text, math.inf), target, weighting=weighting, seed=seed,
                    budget=budget,
                )
                for text in outside
            ]

    found = sorted(
        (cost, text) for cost, text in zip(costs, outside, strict=True) if cost <= PERFECT_COST
    )
    return ExcludedEquivalents(
        circuit=candidate.circuit.to_string(),
        skeleton=skeleton,
        size=size,
        kept=kept,
        excluded=len(outside),
        equivalents=tuple(text for _, text in found),
        elapsed_s=time.perf_counter() - started,
    )


def exhaustive_limit_for(skeleton_size: int | None, requested: int | None) -> int:
    """Resolve ``exhaustive_limit`` into a total element count, defaults included.

    Split out because the CLI has to print the arithmetic before the search starts -- a total
    is not what a user with a ten-element skeleton is thinking in -- and a second copy of the
    default would be a second thing to get wrong.
    """
    if skeleton_size is None:
        return DEFAULT_EXHAUSTIVE_LIMIT if requested is None else requested
    limit = skeleton_size + SKELETON_REACH if requested is None else requested
    if limit < skeleton_size:
        raise ValueError(
            f"exhaustive_limit={limit} is below the skeleton's own {skeleton_size} elements, "
            "so nothing could be evaluated. It is a total element count, not a count of "
            f"added ones: pass {skeleton_size + 1} to allow one added element."
        )
    return limit


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
    skeleton: Node | None,
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

    # Both level sources yield whole element counts in ascending order; the constrained one
    # grows the skeleton outwards and stops itself before materialising a level too large to
    # hold, which is the limit that binds first (docs/PARTIAL_TOPOLOGY_PLAN.md section 4.1).
    levels: Iterable[tuple[int, Iterable[Node]]]
    if skeleton is None:
        levels = ((n, enumerate_topologies(pool, n)) for n in range(floor, limit + 1))
    else:
        levels = grow_up_to(
            skeleton, pool, limit, max_frontier=max_candidates * FRONTIER_HEADROOM
        )

    texts: list[str] = []
    # (element count, how many topologies have been queued once that level is complete), used
    # to work out afterwards how far the coverage really got if the screen ran out of time.
    boundaries: list[tuple[int, int]] = []
    for n, nodes in levels:
        if n < floor:
            continue
        level: list[str] = []
        overflowed = False
        for node in nodes:
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
    # true when the smaller sizes were looked at too. A skeleton is not such a start, even
    # though its levels begin at its own size: no topology smaller than the skeleton can
    # contain it, so the sizes below it are empty rather than skipped.
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


def _refit_worker(task: tuple[str, int, int]) -> dict[str, Any] | None:
    """Tier-2 refit in a worker process. The whole FitResult comes back, statistics included.

    Returning the finished fit rather than just the parameter values keeps the restart spread
    -- which is how a non-identifiable model announces itself -- instead of quietly losing it
    to a single-restart reconstruction in the parent.

    It travels as :meth:`FitResult.to_wire` rather than as a pickled object, even though this
    process pool could pickle it. That is deliberate: it is the one transport a Web Worker can
    also use, so every parallel run on the desktop exercises the browser's path instead of
    leaving it to be tested only in the browser.
    """
    text, restarts, seed = task
    result = _full_fit(text, _WORKER["spectrum"], _WORKER["weighting"], restarts, seed)
    return None if result is None else result.to_wire()


class RefitTask(NamedTuple):
    """One tier-2 job: a topology, and the full-budget fit settings to run it with."""

    text: str
    restarts: int
    seed: int


#: What a driver hands back for one :class:`RefitTask`: the fit, its wire form, or ``None`` if
#: the topology could not be fitted at all. In-process drivers pass the object straight through
#: rather than serialising it for their own benefit.
type RefitOutcome = FitResult | dict[str, Any] | None


def refit_plan(
    scored: Sequence[tuple[float, str]],
    *,
    n_refine: int,
    n_data: int,
    restarts: int,
    seed: int,
    chunk: int | None = None,
) -> Generator[list[RefitTask], Sequence[RefitOutcome], list[Candidate]]:
    """Tier 2 with the *running* of it left to the caller, mirroring :func:`screen_plan`.

    Yields batches of :class:`RefitTask`, expects one outcome per task back through ``send``,
    and returns the scored :class:`Candidate` list the report is built from.

    The reason this exists is the same as for the screen: the decisions must have exactly one
    implementation. Which topologies are worth a full-budget refit is :func:`_shortlist`, and
    gate G1 rests on its per-element-count quota; what happens to a topology that cannot be
    fitted, and the ordering of what comes out, are decisions too. A browser driving this from
    JavaScript fans out the fits and nothing else.

    ``chunk`` exists for that driver rather than for correctness -- unlike the screen, no
    decision here depends on an earlier batch, so batching costs nothing and buys a partial
    Pareto front that can be streamed to the UI while the rest is still running
    (``docs/WEB_UI_PLAN.md`` section 3). ``None`` means one batch.
    """
    texts = _shortlist(scored, n_refine, n_data)
    results: list[FitResult] = []
    size = max(len(texts) if chunk is None else chunk, 1)
    for start in range(0, len(texts), size):
        window = texts[start : start + size]
        outcomes = yield [RefitTask(text, restarts, seed) for text in window]
        if len(outcomes) != len(window):
            raise ValueError(
                f"refit_plan was sent {len(outcomes)} outcomes for {len(window)} tasks"
            )
        results.extend(r for r in map(_as_fit_result, outcomes) if r is not None)
    out = [Candidate(r.circuit, r, 0) for r in results]
    out.sort(key=lambda c: c.aicc)
    return out


def _as_fit_result(outcome: RefitOutcome) -> FitResult | None:
    if outcome is None or isinstance(outcome, FitResult):
        return outcome
    return FitResult.from_wire(outcome)


def _refit_shortlist(
    scored: Sequence[tuple[float, str]],
    spectrum: Spectrum,
    weighting: Weighting,
    restarts: int,
    seed: int,
    n_refine: int,
    executor: multiprocessing.pool.Pool | None = None,
) -> list[Candidate]:
    """Tier 2: refit the shortlist at full budget. Only these numbers are ever reported.

    A thin driver over :func:`refit_plan`, exactly as :func:`_screen_parallel` is over
    :func:`screen_plan`: it runs the fits and holds no opinion about which ones to run.
    """
    plan = refit_plan(
        scored, n_refine=n_refine, n_data=2 * spectrum.n, restarts=restarts, seed=seed
    )
    try:
        tasks = next(plan)
        while True:
            outcomes: list[RefitOutcome]
            if executor is not None and len(tasks) > 1:
                outcomes = list(
                    executor.map(
                        _refit_worker, [(t.text, t.restarts, t.seed) for t in tasks]
                    )
                )
            else:
                outcomes = [
                    _full_fit(t.text, spectrum, weighting, t.restarts, t.seed) for t in tasks
                ]
            tasks = plan.send(outcomes)
    except StopIteration as done:
        return list(done.value)


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
    budget: ScreenBudget = SCREEN_BUDGET,
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
            budget=budget,
        )

    # Chunk of one: in-process, every candidate is judged against everything screened before it.
    plan = screen_plan(texts, chunk=1)
    tracker = _BestTracker()
    scored: list[tuple[float, str]] = []
    try:
        tasks = next(plan)
        while True:
            costs = [
                _screen_one(task, spectrum, weighting=weighting, seed=seed, budget=budget)
                for task in tasks
            ]
            tracker.update(costs, tasks)
            scored.extend(zip(costs, (task.text for task in tasks), strict=True))
            if on_progress is not None:
                on_progress(len(scored), len(texts), tracker.best_text)
            if time_limit is not None and time.perf_counter() - started > time_limit:
                return scored
            tasks = plan.send(costs)
    except StopIteration as done:
        return list(done.value)


def _screen_one(
    task: ScreenTask,
    spectrum: Spectrum,
    *,
    weighting: Weighting,
    seed: int,
    budget: ScreenBudget,
) -> float:
    """One screening fit. A candidate that cannot be fitted at all scores infinity, not an
    exception: it is a hopeless topology, which is an answer."""
    try:
        return screen(
            task.text,
            spectrum,
            weighting=weighting,
            seed=seed,
            popsize=budget.popsize,
            maxiter=budget.maxiter,
            tol=SCREEN_TOL,
            abandon_above=task.abandon_above,
        )
    except (ValueError, CircuitError, np.linalg.LinAlgError):
        return math.inf


class _BestTracker:
    """Best-scoring topology seen so far, for the progress callback only."""

    def __init__(self) -> None:
        self.best_cost = math.inf
        self.best_text: str | None = None

    def update(self, costs: Sequence[float], tasks: Sequence[ScreenTask]) -> None:
        for cost, task in zip(costs, tasks, strict=True):
            if cost < self.best_cost:
                self.best_cost, self.best_text = cost, task.text


class ScreenTask(NamedTuple):
    """One tier-1 screening job: a topology, and the cost above which to skip its polish."""

    text: str
    abandon_above: float


def screen_plan(
    texts: Sequence[str], *, chunk: int = 1
) -> Generator[list[ScreenTask], Sequence[float], list[tuple[float, str]]]:
    """The tier-1 screen with the *running* of it left to the caller.

    Yields a batch of :class:`ScreenTask`, expects the matching costs back through ``send``,
    and finally returns the ``(cost, circuit)`` pairs the shortlist is built from. Every
    decision that has to be made *between* batches lives here: which candidates go in a batch,
    and what early-abandon threshold each one carries, which depends on the best cost seen so
    far at that complexity and therefore cannot be computed up front.

    The point of the inversion is that there is exactly one copy of that logic. In-process the
    driver is :func:`_screen_all`; across processes it is :func:`_screen_parallel`; in a
    browser it is JavaScript fanning batches across Web Workers, and none of those get to hold
    their own opinion about ordering or abandonment. Gate G1 rests on this stage feeding the
    per-element-count quota in :func:`_shortlist` correctly, and a second implementation of it
    in another language is a second thing that can be wrong.

    ``chunk=1`` reproduces a strictly sequential screen, where every candidate is judged
    against everything before it. Larger chunks let a batch run concurrently at the cost of a
    slightly stale threshold within it -- which can waste time but cannot change a result,
    since abandoning only ever skips a polish that was already 100x off the pace.
    """
    scored: list[tuple[float, str]] = []
    best_by_complexity: dict[float, float] = {}
    complexity_of = {text: Circuit.parse(text).complexity for text in texts}
    for start in range(0, len(texts), max(chunk, 1)):
        window = list(texts[start : start + max(chunk, 1)])
        costs = yield [
            ScreenTask(text, _abandon_at(best_by_complexity, complexity_of[text]))
            for text in window
        ]
        for cost, text in zip(costs, window, strict=True):
            scored.append((float(cost), text))
            complexity = complexity_of[text]
            if cost < best_by_complexity.get(complexity, math.inf):
                best_by_complexity[complexity] = float(cost)
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


def _screen_worker(task: tuple[str, int, float, int, int]) -> float:
    """Screen one topology in a worker process; the task carries only strings and numbers."""
    text, seed, abandon, popsize, maxiter = task
    return _screen_one(
        ScreenTask(text, abandon),
        _WORKER["spectrum"],
        weighting=_WORKER["weighting"],
        seed=seed,
        budget=ScreenBudget(popsize, maxiter),
    )


def _screen_parallel(
    texts: Sequence[str],
    executor: multiprocessing.pool.Pool,
    *,
    seed: int,
    on_progress: Callable[[int, int, str | None], None] | None,
    time_limit: float | None,
    started: float,
    budget: ScreenBudget = SCREEN_BUDGET,
) -> list[tuple[float, str]]:
    """The same screen, and the same :func:`screen_plan`, fanned across processes.

    Tasks are submitted a chunk at a time rather than all at once so that the early-abandon
    threshold can be refreshed between chunks; within a chunk it is necessarily stale, which
    costs a little time but can never change a result.
    """
    plan = screen_plan(texts, chunk=WORKER_CHUNK)
    tracker = _BestTracker()
    scored: list[tuple[float, str]] = []
    try:
        tasks = next(plan)
        while True:
            # ``map`` and not ``imap_unordered``: the plan wants costs back in task order, and
            # buying an unordered stream would mean sorting them again on this side.
            costs = list(
                executor.map(
                    _screen_worker,
                    [
                        (task.text, seed, task.abandon_above, budget.popsize, budget.maxiter)
                        for task in tasks
                    ],
                )
            )
            tracker.update(costs, tasks)
            scored.extend(zip(costs, (task.text for task in tasks), strict=True))
            if on_progress is not None:
                on_progress(len(scored), len(texts), tracker.best_text)
            if time_limit is not None and time.perf_counter() - started > time_limit:
                return scored
            tasks = plan.send(costs)
    except StopIteration as done:
        return list(done.value)


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
