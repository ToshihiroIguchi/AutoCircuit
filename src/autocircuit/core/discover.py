"""Automatic equivalent-circuit discovery by genetic programming.

Where :mod:`autocircuit.core.fit` answers "what are the parameters of *this* circuit?", this
module answers "what circuit?". It evolves a population of topologies, fitting each one with
the same no-initial-values engine and scoring it by a model-selection criterion
the caller chooses (AIC by default; see :mod:`autocircuit.core.stats`).

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
import csv
import io
import math
import multiprocessing
import multiprocessing.pool
import time
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple, cast

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
from .descriptors import PoolChoice, choose_pool
from .elements import DEFAULT_POOL
from .enumerate import (
    DEFAULT_DEGENERACY_BUDGET,
    EndpointBehaviour,
    # The one-element growth operator. Private to `enumerate` because the skeleton mode is its
    # only other caller, and shared rather than reimplemented here because a second copy would
    # be a second thing that can miss the subset-grouping moves -- which is exactly the hole
    # `benchmarks/screening_round/arms.py`'s own local `_grow` has.
    _insertions,
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
from .fit import PUBLISH_LOCAL, SCREEN_LOCAL, FitResult, Weighting, fit, screen
from .spectrum import Spectrum
from .stats import (
    CRITERIA,
    CRITERION_LABELS,
    DEFAULT_CRITERION,
    FTEST_ALPHA,
    FTEST_RANKING,
    SCORE_CRITERIA,
    Criterion,
    f_test,
    information_criteria,
    unresolved_mask,
)

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

#: Independent global searches the tier-1 screen runs per topology, keeping the best.
#:
#: **This is a different axis from the budget above and the measurement says so loudly.**
#: [measured, docs/TOPOLOGY_6PLUS_PLAN.md section 5.7.2] For a topology whose screening landscape
#: is bimodal, one draw decides its place on the shortlist by luck: ``p(p(R1,C1)-R2,C2)-R3``
#: screens at 0.0141 or at 33.78 depending only on the seed -- a factor of 2400 -- and raising
#: ``popsize`` 8 -> 40 and ``maxiter`` 40 -> 400 moves *neither* number. Over 360 sampled
#: topologies from three spectra, one seed is within 1% of the best of five for 72-80% of them,
#: more than 2x off for 8-12%, and more than 100x off for up to 1.7%; the mean ratio to the
#: best-of-five falls from 1.07-41.4 at one seed to 1.04-1.16 at two.
#:
#: It stays at 1 rather than 2. The screen is the dominant cost of an exhaustive run, so this
#: doubles the whole search, and the case for paying that is a *recovery* measurement -- does a
#: second seed put truths on the shortlist that the first one lost -- which is X4 and is not in
#: yet. Every number recorded in this repository was taken at 1; raising the default moves all
#: of them, so it waits for the measurement that would justify moving them.
SCREEN_RESTARTS = 1


class ScreenBudget(NamedTuple):
    """The tier-1 differential-evolution budget, as one injectable object.

    The screen is the dominant cost of an exhaustive run, so how far it can be cut without
    losing the truth from the tier-2 shortlist is an empirical question. Bundling the budget
    here lets ``benchmarks/discovery_v2.py screen-rank`` sweep it without monkey-patching
    module constants; nothing in the library ever passes anything but the default.
    """

    popsize: int = SCREEN_POPSIZE
    maxiter: int = SCREEN_MAXITER
    #: Independent global searches per topology, best of which is kept. See
    #: :data:`SCREEN_RESTARTS` for why this is a separate axis from ``popsize`` and ``maxiter``.
    restarts: int = SCREEN_RESTARTS


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

#: Default number of candidates refitted at full budget, per mode.
#:
#: One value for all three since both searches now shortlist by :func:`_quota_by_size`. The old
#: split -- 8 for the genetic search against 30 for the exhaustive one -- was justified by the
#: genetic search "having already refitted its survivors many times over", which stopped being
#: true when it started reporting only refitted candidates
#: (docs/EVOLVE_SEARCH_PLAN.md section 3.2).
#:
#: Note what this number does *not* do. The quota is ``max(MIN_REFINE_PER_SIZE, n_refine //
#: sizes)``, and a genetic archive spans about seven element counts, so 8, 16 and 30 all reduce
#: to the same quota of 5: below ``MIN_REFINE_PER_SIZE * sizes`` this constant has no effect at
#: all, and the floor is the knob. That is arithmetic rather than a measurement, and it is
#: recorded here so nobody sweeps this value looking for a difference that cannot appear.
REFINE_DEFAULT = {"evolve": 30, "exhaustive": 30, "auto": 30}

#: Every candidate within this factor of the best screening cost is refitted at full budget,
#: on top of the ``n_refine`` best. A sloppy screen must not be able to drop a near-tie.
REFINE_COST_FACTOR = 10.0

#: ...but no more than this many times the per-size quota. Without a ceiling the near-tie rule
#: is unbounded, and on noisy data it selects hundreds of candidates (see `_shortlist`).
REFINE_CEILING_FACTOR = 2

#: Floor on the per-element-count refit quota, so that a size class is never represented by one
#: or two candidates just because the run happened to span many sizes.
MIN_REFINE_PER_SIZE = 5

#: How far past ``time_limit`` the genetic search's refit may run, as a multiple of it.
#:
#: ``time_limit`` has always governed the evolutionary loop and not the refit that follows it --
#: the loop checks the clock between generations, so a run overshoots by up to one generation
#: before the refit even starts. That was harmless while the refit was a fixed eight fits. It is
#: not harmless now that the shortlist is a per-size quota: [measured] the refit of a
#: seven-size archive is 35-70 full fits, and a run given 5 s spent 222 s in it.
#:
#: Bounding the refit at ``time_limit`` itself is the obvious fix and it is wrong, because the
#: loop has usually already passed that mark: the deadline would be spent before the tier began
#: and the run would report **nothing at all**, having done all of the work. So the refit gets
#: its own share on top. The loop keeps the budget it was promised; the report gets half as much
#: again to be worth reading.
REFIT_HEADROOM = 1.5

#: How far off the best cost known at the same complexity a warm-started polish may land and
#: still be taken as that topology's tier-1 score, skipping the global stage.
#:
#: A child of a mutated parent starts from the parent's fitted values rather than from nothing
#: (see :func:`_inherited_values`), so a global search becomes a local polish -- [measured] 21%
#: of its cost in the median, once the polish is held to
#: :data:`~autocircuit.core.fit.SCREEN_LOCAL` rather than the publication budget. The polish is
#: only worth taking when it lands somewhere sensible, and "sensible" needs a yardstick that
#: does not depend on the topology: the best cost seen so far at the *same* complexity. Nothing
#: known at that complexity yet means no yardstick, and the global stage runs -- an unmeasured
#: cheap fit is exactly what tier 1 must not become.
#:
#: **The default is infinite, and the sweep is why.** [measured, docs/EVOLVE_SEARCH_PLAN.md
#: section 3.3.1] 1.5, 3 and 10 all sit inside the run-to-run spread, and 1.5 is *below* the
#: control: a strict factor pays for the polish and then runs the global search anyway on most
#: children, so it buys the cost of inheritance with none of the benefit. There is no useful
#: middle setting -- the knob is nearly binary, and the two settings that mean anything are
#: "off" and "accept the polish once there is something to compare it against".
#:
#: Zero switches inheritance off entirely, which is the control arm gate EV3 is measured
#: against and, for the same reason, the way back to the pre-step-3 search.
WARM_ACCEPT_FACTOR = math.inf

#: How many best-scoring candidates join the Pareto front in the set a generation breeds from.
#:
#: [measured] Zero, and that is a rule rather than a tuned width -- see
#: docs/EVOLVE_SEARCH_PLAN.md section 3.4.3. The ladder that measured it ran the width down to
#: one and then to none, and the last two rungs are *the same arm on every seed*, because the
#: best-scoring candidate is by definition non-dominated and is therefore already on the front.
#: So the search breeds from the front, which is naturally bounded at roughly one member per
#: complexity level and needs no number chosen for it. Adding members back is measurably worse:
#: on the 21,057-topology arena at 150 fits, front alone reaches 65/120 where front-plus-three
#: reaches 64/120, front-plus-five 47/120 and the shipped front-plus-forty 7/120.
#:
#: It stays a parameter of `_breeding_pool` and not of `discover()`: `benchmarks/ev4_diversity.py`
#: and `benchmarks/screening_round/arms.py` re-measure the ladder by passing other values, and a
#: search internal that a user cannot set correctly is not a knob (CLAUDE.md).
BREEDING_EXTRA = 0

#: Relative weights of `mutate`'s four operations: retype, insert-series, insert-parallel,
#: delete.
#:
#: **The equality of the middle two is the measured part, and it is the only part.** [measured,
#: docs/EVOLVE_SEARCH_PLAN.md section 3.5.2] Nine weightings over 480 seeds on two frozen arenas
#: whose truths have opposite shape. Moving weight from insert-series to insert-parallel
#: (0.15/0.35) reaches the truth's class in 308/480 against this tuple's 282 on a truth that is
#: three parallel RC blocks (McNemar p = 0.018) -- and 281/480 against 306 on a truth that is
#: four series elements and one parallel block (p = 0.0001). The mirror weighting reverses both
#: signs. So an asymmetric setting is not a better search, it is a bet on the shape of the
#: answer, and CLAUDE.md rules that out: it is the software deciding what kind of part this is,
#: reached from inside the search rather than from the CLI.
#:
#: The rest of the tuple is arbitrary and measured to be so: uniform weights, (0.25, 0.25, 0.25,
#: 0.25), tie it on both arenas (p = 1.00 and p = 0.92). One arm never lost -- delete cut to 0.05
#: -- and was not taken, because both arenas' truths sit at or one below the element cap, which
#: is the regime that flatters a low delete weight; section 3.5.3 measures that confound out.
#:
#: A parameter of `mutate` and of `_next_generation` so that the sweep can drive the real
#: operator, and not of `discover()`, for the reason :data:`BREEDING_EXTRA` is not.
MUTATION_WEIGHTS: tuple[float, float, float, float] = (0.35, 0.25, 0.25, 0.15)

#: How hard a crowded complexity level is penalised **when choosing a parent**, in units of the
#: criterion. PySR's adaptive parsimony; see :func:`_tournament` for the two ways this differs
#: from PySR's own form and why.
#:
#: **[measured] Zero, because the term does nothing.** docs/EVOLVE_SEARCH_PLAN.md section 3.5.1.
#: The ladder runs 0.5, 2, 5, 10, 20, 100, 300, 1000, 3000, 1e4, 1e6 on the 21,057-topology
#: arena: everything below 300 is inert (the penalty is at most `scaling`, and front members'
#: scores differ by hundreds of AICc), and above it the ladder wanders between 57/120 and 78/120
#: with no ordering. The best-looking rung was 77/120 against 65/120 at 120 seeds, p = 0.03 --
#: the same counts, control and p as the two-island arm that section 3.4.4 also had to demote --
#: and at 480 seeds it is 293/480 against 282/480, p = 0.32, with p = 0.92 on the second
#: reference. The limit of the ladder is the worst arm on it: at 1e6 the crowding term outranks
#: every score difference, so selection stops consulting fitness.
#:
#: Kept rather than deleted, which is the opposite disposal from the islands of section 3.4.4
#: and deliberately so. Those were measurably worse and their arm owned its own generation loop;
#: this is a keyword on `_tournament`, and removing it would force the benchmark arm that
#: records the rejection to reimplement `_next_generation` -- the one thing
#: `benchmarks/screening_round/arms.py` says an arm may not do.
PARSIMONY_SCALING = 0.0

#: Tier-1 tasks handed to a worker process at a time. Large enough to amortise the ~1 s
#: interpreter start-up on Windows, small enough that the early-abandon threshold keeps up.
WORKER_CHUNK = 64

#: Two fitted candidates whose responses agree to better than this everywhere are treated as
#: the same model. The threshold is far below any real measurement uncertainty, so matching it
#: means the topologies are algebraic reparameterisations of one another, not merely similar.
EQUIVALENCE_RTOL = 1e-6

#: A candidate fitting within this factor of the best chi-squared seen is counted as fitting
#: "as well as" the best one, and is then preferred if it is simpler.
PARSIMONY_CHI2_FACTOR = 2.0

#: How many topologies of each completed level the growth stage extends, when it is asked to run.
#:
#: [measured, docs/TOPOLOGY_6PLUS_PLAN.md section 5.5] Width 2 misses the truth's class on the
#: incumbent arena where width 4 reaches it, so this parameter decides something. It is not
#: tuned past that: a wider beam costs one extra fan-out per level and cannot lose a candidate a
#: narrower one keeps, so the risk of raising it is runtime and the risk of lowering it is the
#: answer.
GROWTH_WIDTH = 4

#: How many element counts past the last *complete* level the growth stage may reach.
#:
#: A reach and not a cap, the same distinction :data:`SKELETON_REACH` draws, and for a reason
#: rather than for symmetry. Each grown level chooses its ``GROWTH_WIDTH`` survivors from the
#: level below, so the further growth runs from the completed enumeration the narrower the sample
#: those survivors were drawn from -- growing four levels from a complete level 3 is a much
#: weaker claim than growing two from a complete level 5, and the coverage sentence cannot tell
#: the two apart. Bounding the *distance* keeps the sentence honest at any exhaustive limit.
#:
#: It also bounds the cost where it would otherwise run away: with the production limit of 5 and
#: ``max_elements=7`` this changes nothing, and on a small test space with the limit at 3 it is
#: the difference between two grown levels and four.
GROWTH_REACH = 2

#: Whether growth runs when the caller says nothing. **Zero, and that is a decision.**
#:
#: The width above is what to use *if* growing; this is whether to grow at all, and the two are
#: separate because the evidence for them is separate. Growth is measured to reach the six-element
#: truth's equivalence class three screening fits after the five-element enumeration ends
#: (docs/TOPOLOGY_6PLUS_PLAN.md section 5.5) -- a strong result about the *search*. What is not
#: measured is that it changes what the **report** says, and the price is not small: [measured] on
#: the six-element reference it takes a run from 23 s to 46 s and from 303 topologies to 548, and
#: switching it on by default made `tests/test_web_job.py` alone run longer than the entire suite
#: had, because every driven search then grew to seven elements.
#:
#: So the lever ships and the default does not move until the end-to-end measurement
#: (`benchmarks/six_plus/recovery.py`) shows growth putting truths in the report that the
#: enumeration alone loses. Ask for it with ``discover(growth_width=GROWTH_WIDTH)`` or
#: ``--growth-width 4``. This is the same rule `SCREEN_RESTARTS` follows and for the same reason:
#: every number recorded in this repository was taken without it.
GROWTH_DEFAULT = 0


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
    def relative_error(self) -> float:
        """RMS ``|Z_model - Z_data| / |Z_data|``: how far this topology is from the data.

        The front's other two numbers are computed from the *weighted* residuals, so neither is
        readable without knowing the weighting: a chi-squared of 0.13 says nothing about how
        close the curve is under ``modulus`` weighting and something completely different under
        ``unit``. This says it in the one unit every reader of an impedance spectrum already
        has -- percent -- and it is the same quantity the Fit screen puts under a manual fit, so
        a row here and a fit there can be compared at all.

        It is *not* a substitute for the score. It falls monotonically as elements are added,
        which is precisely why the score carries a parameter penalty and why the recommendation
        is a parsimony rule rather than either number's minimum.
        """
        return self.result.relative_error

    def score(self, criterion: Criterion = DEFAULT_CRITERION) -> float:
        """This topology's value under ``criterion``, smaller being better.

        Under ``ftest`` it answers with :data:`~autocircuit.core.stats.FTEST_RANKING`, because a
        test between two models provides no axis to sort one list by. What the test decides is
        :attr:`DiscoveryResult.by_criterion`, and the report says which of the two happened.
        """
        return self.result.statistics.criterion_value(criterion)

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
        return unresolved_mask(self.result.values, self.result.statistics.stderr)

    @property
    def n_unresolved(self) -> int:
        """Parameters whose standard error exceeds their own value."""
        return int(np.count_nonzero(self.unresolved))

    def to_dict(self, criterion: Criterion = DEFAULT_CRITERION) -> dict[str, Any]:
        payload = self.result.to_dict()
        payload["complexity"] = self.complexity
        payload["n_unresolved"] = self.n_unresolved
        payload["generation"] = self.generation
        # Every criterion is already under ``statistics``; this is the one the report ranked by,
        # named, so a reader does not have to re-derive which column the ordering came from.
        payload["score"] = self.score(criterion)
        return payload


@dataclass
class DiscoveryResult:
    """Outcome of a topology search."""

    candidates: list[Candidate]
    """Every distinct topology evaluated, best first under :attr:`criterion`."""
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
    refit_progress: tuple[int, int] | None = None
    """``(refitted, shortlisted)`` when the second tier was stopped part-way, else None.

    A search that screened everything and then had its refit cut short -- which is what
    cancelling from the browser does, since the screen is the stage that can be resumed and
    the refit is the stage that takes minutes -- produces a report that looks exactly like a
    finished one. ``complete_up_to`` is still true, because it describes the *screen*; the
    ranking and the Pareto front below it are built from part of the shortlist. That
    difference is invisible in the numbers, which is this project's characteristic failure
    (docs/HANDOFF.md section 3), so it travels with the claims rather than with the caller.
    """
    criterion: Criterion = DEFAULT_CRITERION
    """Which rule ranked :attr:`candidates` and drew :attr:`pareto`.

    It travels with the result for the same reason :attr:`skeleton` does: it changes what the
    numbers underneath mean, and a front labelled only "score" is a front whose column heading
    the reader has to guess. It does **not** change :attr:`recommended`; see there.
    """
    pool_choice: PoolChoice | None = None
    """How :attr:`pool` was arrived at, when the spectrum chose it rather than the caller.

    None when the caller named a pool, since then the narrowing is the caller's and they
    already know about it. Present on the automatic path whether or not anything was added,
    because the case that says nothing is the one the rule exists for: a report silent about
    the diffusion elements has excluded them exactly as thoroughly as one that names them.
    See :mod:`autocircuit.core.descriptors`.
    """
    grown_to: int | None = None
    """Largest element count the growth stage reached above :attr:`complete_up_to`, or None.

    **This is not a completeness claim and must never be printed as one.** Above the exhaustive
    limit the search stops enumerating and starts *growing*: it takes the best
    :data:`GROWTH_WIDTH` topologies of the last completed level and evaluates every one-element
    extension of each, then repeats. So the sentence it licenses is narrower than
    :attr:`complete_up_to`'s and is stated separately in :meth:`completeness` -- a topology of
    this size that is not one insertion away from that shortlist was never considered, and its
    absence from the report is not evidence against it.

    The distinction matters here more than it looks. This project has measured three separate
    occasions where a search that had quietly stopped covering its space still produced a report
    that looked healthy (docs/HANDOFF.md section 3, docs/DISCOVERY_V2_PLAN.md section 3.4,
    docs/PARTIAL_TOPOLOGY_PLAN.md section 3), and a growth stage is exactly that shape: it
    returns larger circuits with good numbers and nothing in the numbers says how it found them.
    """
    base_complete_up_to: int | None = None
    """Coverage reached before the pool was widened, when a widening happened.

    Two pools were searched, so there are two completeness statements and neither implies the
    other: every topology up to this size was evaluated from the *base* pool, and every
    topology up to :attr:`complete_up_to` from the widened one. Widening costs a level
    (docs/POOL_FROM_SPECTRUM_PLAN.md section 2), so this is normally the larger number, and
    collapsing the two into one would either overclaim the wide pool or throw away what the
    narrow one actually covered.
    """

    @property
    def best(self) -> Candidate | None:
        """Lowest score under :attr:`criterion`. Under ``ftest`` that ranking is AIC's."""
        return self.candidates[0] if self.candidates else None

    @property
    def by_criterion(self) -> Candidate | None:
        """What the chosen criterion picks, which is not what this report recommends.

        For the six scores it is :attr:`best`. For ``ftest`` it is a sequential
        extra-sum-of-squares test along the Pareto front, simplest first: hold the current
        choice until a larger model's residual gain is significant at
        :data:`~autocircuit.core.stats.FTEST_ALPHA`, then move to it. **The test assumes the
        smaller model is nested in the larger one and front rows generally are not**, which
        :meth:`summary` states on the line that reports the answer rather than in a footnote.
        """
        if not self.candidates:
            return None
        if self.criterion != "ftest":
            return self.best
        choice: Candidate | None = None
        for candidate in self.pareto:  # already simplest first
            if choice is None:
                choice = candidate
                continue
            test = f_test(
                choice.result.statistics.ssr,
                choice.result.statistics.n_params,
                candidate.result.statistics.ssr,
                candidate.result.statistics.n_params,
                candidate.result.statistics.n_data,
            )
            if test is not None and test.significant:
                choice = candidate
        return choice

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

        **This does not follow :attr:`criterion`, on purpose.** Choosing BIC instead of AIC
        changes which model a penalty term prefers; it does not make "the extra parameter has a
        standard error larger than its own value" a different kind of mistake. What the chosen
        criterion picks is :attr:`by_criterion`, and :meth:`summary` prints both lines whenever
        they disagree.
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
        placements = skeleton_placements(candidate.circuit.root, Circuit.parse(self.skeleton).root)
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
        return count_skeleton_placements(candidate.circuit.root, Circuit.parse(self.skeleton).root)

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
        for candidate in sorted(self.candidates, key=lambda c: c.score(self.criterion)):
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
        if self.n_evaluated == 0:
            # [measured] Reachable, and it looks healthy without this: the component pool
            # ("R", "C") against a spectrum that turns inductive above its resonance has *every*
            # candidate rejected by the structural feasibility screen, so the search evaluates
            # nothing and the sentence below would still have said "every plausible topology up
            # to 3 elements was evaluated" -- true of an empty set, and read by a human as an
            # assurance. An empty report has two very different causes and they are worth
            # distinguishing: no candidate to fit, or nothing that fitted.
            return self._with_refit_note(
                "Coverage: no topology was evaluated at all. Every candidate this pool can "
                "build was ruled out before any fitting -- structurally inconsistent with the "
                "data, or outside the element limit -- so this report is empty for want of "
                "candidates, not because nothing fitted. Widen the pool or raise the limit."
            )
        if self.complete_up_to is None or self.complete_up_to < 1:
            if self.skeleton is not None:
                return self._with_refit_note(
                    "Coverage: sampled, not exhaustive, and restricted to topologies "
                    f"containing {self.skeleton} -- absence from this report is not evidence "
                    "against a topology."
                )
            return self._with_refit_note(
                "Coverage: sampled, not exhaustive -- absence from this report is not "
                "evidence against a topology."
            )
        if self.skeleton is not None:
            return self._with_refit_note(
                f"Coverage: every plausible topology with up to {self.complete_up_to} "
                f"elements that contains {self.skeleton} was evaluated, with the added "
                "elements taken from this pool. Topologies without that skeleton were never "
                "considered, so this report is not evidence against them."
            )
        return self._with_refit_note(
            self._with_growth_note(
                f"Coverage: every plausible topology with up to {self.complete_up_to} elements "
                f"from this pool was evaluated."
            )
        )

    def _with_growth_note(self, coverage: str) -> str:
        """The coverage sentence, plus the weaker one the growth stage above it earns.

        Two claims of different strengths on one line, in the order of their strength, because
        the risk here is a reader carrying the first sentence's "every" across to the second.
        Below the exhaustive limit absence from the report *is* evidence; above it, absence
        means only that no member of a small shortlist was one element away.
        """
        if self.grown_to is None or self.complete_up_to is None:
            return coverage
        if self.grown_to <= self.complete_up_to:
            return coverage
        return (
            f"{coverage} Above {self.complete_up_to} elements the search grew rather than "
            f"enumerated: every one-element extension of the best {GROWTH_WIDTH} topologies of "
            f"each completed size was evaluated, up to {self.grown_to} elements. That is not a "
            f"completeness claim -- a topology of {self.complete_up_to + 1} elements or more "
            "that is not one insertion away from those is absent because it was never "
            "considered, not because it did not fit."
        )

    def _with_pool_note(self, coverage: str) -> str:
        """The coverage sentence, plus how the pool it refers to was arrived at.

        Appended rather than merged, because the two claims are about different things and a
        reader who takes one for the other has been misled. The coverage sentence bounds the
        *size* of what was searched; this one bounds the *vocabulary*, and a pool that never
        contained an element excludes it at every size at once.
        """
        if self.pool_choice is None:
            return coverage
        note = self.pool_choice.sentence()
        base = self.base_complete_up_to
        if base is None or base == self.complete_up_to:
            return f"{coverage} {note}"
        narrow = ", ".join(self.pool_choice.base)
        if self.complete_up_to is None:
            # The wide pool overflowed its budget before finishing even one size. What the
            # narrow pool covered is still true and is the only completeness claim left, so it
            # has to be stated here or it is lost with the level it describes.
            return (
                f"{coverage} {note} The widened pool reached no complete size at all, so the "
                f"only completeness claim that survives is the narrower one: every plausible "
                f"topology with up to {base} elements from {narrow} was evaluated."
            )
        return (
            f"{coverage} {note} Widening cost a level: the narrower pool ({narrow}) was "
            f"complete to {base} elements and the wider one to {self.complete_up_to}, so a "
            f"topology of {self.complete_up_to + 1} elements using an added code was not "
            "evaluated."
        )

    def _with_refit_note(self, coverage: str) -> str:
        """The coverage sentence, plus what a half-finished second tier does to it.

        The screen is what the first sentence describes and it can be complete while the
        numbers underneath it are not: only the refitted candidates have publishable
        statistics, so a shortlist that was stopped part-way leaves a ranking that may still
        change. Saying so on the same line is the same rule a skeleton follows -- a reader who
        skims past the qualification has been misled by a true sentence.
        """
        coverage = self._with_pool_note(coverage)
        if self.refit_progress is None:
            return coverage
        done, total = self.refit_progress
        if total == 0:
            return (
                f"{coverage} The run was stopped before anything reached the second stage, so "
                "there are no fitted parameters to report -- only the coverage above."
            )
        return (
            f"{coverage} The run was stopped during the second stage, so only {done} of the "
            f"{total} shortlisted topologies have fitted parameters: the ranking and the "
            "Pareto front below are partial, and the ones never refitted are absent for that "
            "reason rather than on the evidence."
        )

    @property
    def score_label(self) -> str:
        """The column heading the scores in this report are under.

        Under ``ftest`` the column is AIC -- a test has no axis -- and calling it "F-test" would
        put a heading over numbers that are not the thing named.
        """
        return CRITERION_LABELS[FTEST_RANKING if self.criterion == "ftest" else self.criterion]

    def summary(self, limit: int = 10) -> str:
        scope = f"in {self.elapsed_s:.1f} s"
        if self.generations:
            scope = f"over {self.generations} generations {scope}"
        lines = [
            f"Evaluated {self.n_evaluated} distinct topologies {scope} (mode: {self.mode})",
            f"Element pool: {', '.join(self.pool)}",
            f"Criterion   : {CRITERION_LABELS[self.criterion]}",
        ]
        if self.skeleton is not None:
            lines.append(f"Skeleton     : {self.skeleton} (asserted by you, not discovered)")
        lines += [
            self.completeness(),
            "",
            "Pareto front (accuracy versus complexity):",
            # Three numbers for "accuracy" rather than one, because they answer different
            # questions and this project's characteristic failure is a report that looks healthy.
            # The score ranks; chi2_red says whether the misfit is at the level of the weighting's
            # implied noise; RMS |dZ|/|Z| says how far off the curve actually is, in a unit that
            # survives a change of weighting and matches what the Fit screen shows.
            f"  {'circuit':<34}{self.score_label:>11}{'chi2_red':>11}"
            f"{'RMS|dZ/Z|':>11}{'cplx':>7}{'free?':>7}",
        ]
        aliases: list[str] = []
        ambiguous: list[str] = []
        for candidate in self.pareto[:limit]:
            unresolved = candidate.n_unresolved
            mark = "ok" if unresolved == 0 else f"{unresolved} bad"
            lines.append(
                f"  {candidate.circuit.to_string():<34}"
                f"{candidate.score(self.criterion):>11.2f}"
                f"{candidate.result.chi2_reduced:>11.3g}"
                f"{candidate.relative_error:>11.3%}"
                f"{candidate.complexity:>7.1f}"
                f"{mark:>7}"
            )
            equivalents = self.equivalents_of(candidate)
            if equivalents:
                names = ", ".join(e.circuit.to_string() for e in equivalents[:4])
                aliases.append(f"  {candidate.circuit.to_string()} == {names}")
            placements = self.placements_of(candidate)
            if placements > 1:
                ambiguous.append(f"  {candidate.circuit.to_string()}: {placements} ways")

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
            chosen = self.by_criterion
            if chosen is not None and chosen is not recommended:
                if self.criterion == "ftest":
                    lines += [
                        f"F-test (a={FTEST_ALPHA:g}): {chosen.circuit.to_string()} "
                        f"({chosen.circuit.n_params} parameters, "
                        f"{chosen.n_unresolved} of them unresolved) -- the last step up this",
                        "  front whose extra parameters were significant. The test assumes each",
                        "  row is nested in the next and these topologies generally are not, so",
                        "  read it as a guide to whether the extra elements earned their place,",
                        "  not as a p-value you could publish.",
                    ]
                else:
                    lines.append(
                        f"Lowest {self.score_label:<8}: {chosen.circuit.to_string()} "
                        f"({chosen.circuit.n_params} parameters, "
                        f"{chosen.n_unresolved} of them unresolved) -- better numerically, but "
                        "the extra elements are not supported by the data."
                    )
        if recommended is not None:
            lines += ["", "Recommended model:", recommended.result.summary()]
        lines += [
            "",
            "Equivalent circuits are degenerate: several topologies often fit the same data",
            "equally well. Choose using physical knowledge of the sample, not a score alone.",
        ]
        return "\n".join(lines)

    def to_dict(
        self, *, top: int | None = None, excluded: ExcludedEquivalents | None = None
    ) -> dict[str, Any]:
        """The machine-readable report: the CLI's ``--json`` file, and the browser's download.

        One implementation, because a report is a set of claims and the two front ends must not
        make different ones. The three keys a reader of the numbers alone would miss are here
        rather than in the prose: that no candidate is identifiable, that the asserted skeleton
        fits into a reported topology in more than one place, and which of the reported
        candidate's exact equivalents the skeleton removed from consideration.

        ``top`` limits the ``candidates`` list only -- the Pareto front and the coverage claim
        are never truncated, since they are what the report is *for*.
        """
        return {
            "pool": list(self.pool),
            "mode": self.mode,
            "criterion": self.criterion,
            "criterion_label": CRITERION_LABELS[self.criterion],
            "by_criterion": (
                None if self.by_criterion is None else self.by_criterion.circuit.to_string()
            ),
            "skeleton": self.skeleton,
            "complete_up_to": self.complete_up_to,
            "base_complete_up_to": self.base_complete_up_to,
            "grown_to": self.grown_to,
            "pool_choice": (None if self.pool_choice is None else self.pool_choice.to_dict()),
            "coverage": self.completeness(),
            "unresolved_everywhere": self.unresolved_everywhere,
            "excluded_equivalents": (
                None
                if excluded is None
                else {
                    "size": excluded.size,
                    "kept": excluded.kept,
                    "excluded": excluded.excluded,
                    "screened": excluded.screened,
                    "equivalents": list(excluded.equivalents),
                    "summary": excluded.summary(),
                }
            ),
            "unsupported_assertion": (
                None
                if self.skeleton is None or self.recommended is None
                else list(self.unsupported_assertion(self.recommended))
            ),
            "skeleton_placements": (
                None
                if self.skeleton is None
                else {c.circuit.to_string(): self.placements_of(c) for c in self.pareto}
            ),
            "n_evaluated": self.n_evaluated,
            "generations": self.generations,
            "elapsed_s": self.elapsed_s,
            "refit_progress": (None if self.refit_progress is None else list(self.refit_progress)),
            "recommended": (
                self.recommended.to_dict(self.criterion) if self.recommended is not None else None
            ),
            "pareto": [c.to_dict(self.criterion) for c in self.pareto],
            "candidates": [
                c.to_dict(self.criterion)
                for c in (self.candidates if top is None else self.candidates[:top])
            ],
            "equivalence_classes": [
                [c.circuit.to_string() for c in group]
                for group in self.equivalence_classes()
                if len(group) > 1
            ],
        }

    def to_csv(self, *, top: int | None = None) -> str:
        """Every evaluated topology as a spreadsheet, one row each, best first.

        A flat table cannot carry the coverage sentence or an equivalence class, so this is the
        least honest of the three exports and the columns are chosen accordingly: ``equivalents``
        names the other rows that fit identically, so a reader sorting by a score in a
        spreadsheet still meets the ambiguity rather than reading the top row as the answer.

        **All six scores are columns, not just the chosen one.** The row *order* is the chosen
        criterion's and nothing in a CSV can say which that was, so a file carrying one unnamed
        "score" column would be a file whose ordering the reader has to guess at. Naming them
        all costs five columns and removes the guess.
        """
        rows = self.candidates if top is None else self.candidates[:top]
        front = {id(c) for c in self.pareto}
        recommended = self.recommended
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(
            [
                "circuit",
                "canonical",
                "n_elements",
                "n_params",
                "complexity",
                "aic",
                "aicc",
                "bic",
                "caic",
                "hqc",
                "waic",
                "chi2_reduced",
                "relative_error",
                "n_unresolved",
                "unresolved",
                "on_pareto",
                "recommended",
                "equivalents",
            ]
        )
        for candidate in rows:
            unresolved = [
                name
                for name, bad in zip(
                    candidate.circuit.param_names, candidate.unresolved, strict=True
                )
                if bad
            ]
            writer.writerow(
                [
                    candidate.circuit.to_string(),
                    candidate.circuit.canonical_form(),
                    len(candidate.circuit.leaves),
                    candidate.circuit.n_params,
                    f"{candidate.complexity:.6g}",
                    *(
                        f"{candidate.result.statistics.criterion_value(name):.10g}"
                        for name in SCORE_CRITERIA
                    ),
                    f"{candidate.result.chi2_reduced:.10g}",
                    # A fraction, not a percentage: a spreadsheet formats its own percentages
                    # and a column that has already been multiplied by 100 cannot be told from
                    # one that has not.
                    f"{candidate.relative_error:.10g}",
                    candidate.n_unresolved,
                    ";".join(unresolved),
                    int(id(candidate) in front),
                    int(candidate is recommended),
                    ";".join(e.circuit.to_string() for e in self.equivalents_of(candidate)),
                ]
            )
        return buffer.getvalue()


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


def random_topology(rng: np.random.Generator, pool: Sequence[str], n_elements: int) -> Node:
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
    node: Node,
    rng: np.random.Generator,
    pool: Sequence[str],
    max_elements: int,
    *,
    weights: Sequence[float] = MUTATION_WEIGHTS,
) -> Node:
    """Apply one random structural or element-type change.

    ``weights`` is :data:`MUTATION_WEIGHTS` and is a parameter only so that the benchmarks can
    sweep it; it is not reachable from :func:`discover`, for the reason
    :data:`BREEDING_EXTRA` is not.
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
    combined = series(subtree, fresh) if operation == "insert_series" else parallel(subtree, fresh)
    return replace_subtree(node, path, combined)


def crossover(a: Node, b: Node, rng: np.random.Generator) -> Node:
    """Graft a random subtree of ``b`` onto a random position of ``a``."""
    a_paths = subtree_paths(a)
    b_paths = subtree_paths(b)
    target = a_paths[int(rng.integers(len(a_paths)))]
    donor = subtree_at(b, b_paths[int(rng.integers(len(b_paths)))])
    return replace_subtree(a, target, donor)


def _leaf_params(circuit: Circuit) -> list[tuple[str, tuple[str, ...]]]:
    """Every leaf as ``(element code, its parameter names)``, in evaluation order."""
    slices = circuit.slices()
    return [(leaf.code, circuit.param_names[slices[leaf.label]]) for leaf in circuit.leaves]


def _inherited_values(parent: Candidate, child: Circuit) -> dict[str, float]:
    """The parent's fitted values, carried onto whichever of the child's elements match.

    A child usually differs from its parent by one inserted, deleted or retyped element, so
    almost all of the parent's parameters are still meaningful -- and refitting from scratch
    throws them away. This is the correspondence that lets them travel.

    **It cannot be keyed on labels, and that is not a detail.** ``simplify`` returns
    ``ElementNode(node.code)`` with the label dropped (``circuit.py``), and
    :meth:`_Evaluator.evaluate` calls ``Circuit(simplify(node))`` before anything else, so by
    the time a child exists its elements have been renumbered from scratch: the parent's ``R2``
    and the child's ``R2`` are related by nothing but a counter. (That stripping is also why
    crossover children never collide on labels, which is worth knowing before someone "fixes"
    it.) So the correspondence is structural: for each element code, the parent's leaves of that
    code are zipped in evaluation order with the child's, and anything the child has spare keeps
    the template default. ``fit`` accepts exactly that -- a *partial* dict of starting values --
    and clips it to the child's own bounds, so a value that no longer makes sense in the child
    cannot push the polish outside the search space.

    The result is a starting point, never an answer: what it is worth is decided by the fit it
    produces, against :data:`WARM_ACCEPT_FACTOR`.
    """
    values = parent.result.params
    donors: dict[str, list[tuple[str, ...]]] = {}
    for code, names in _leaf_params(parent.circuit):
        donors.setdefault(code, []).append(names)

    taken: dict[str, int] = {}
    out: dict[str, float] = {}
    for code, names in _leaf_params(child):
        index = taken.get(code, 0)
        taken[code] = index + 1
        available = donors.get(code, ())
        if index >= len(available):
            continue
        for name, source in zip(names, available[index], strict=True):
            value = values.get(source)
            if value is not None and math.isfinite(value):
                out[name] = value
    return out


def _fit_cost(result: FitResult) -> float:
    """Sum of squared weighted residuals -- what the fitter itself minimised."""
    return float(np.dot(result.residuals, result.residuals))


def _cheaper(a: Candidate | None, b: Candidate | None) -> Candidate | None:
    """The better of two fits **of the same topology**, by residual cost.

    Cost rather than :meth:`Candidate.score` on purpose. These two candidates share a topology,
    so they share ``k`` and ``n``, and every criterion in :data:`~autocircuit.core.stats.CRITERIA`
    is then monotone in the cost -- which lets the evaluator keep the better of a warm-started
    polish and a global search without knowing, or caring, which criterion the run was asked
    for.
    """
    if a is None:
        return b
    if b is None:
        return a
    return a if _fit_cost(a.result) <= _fit_cost(b.result) else b


# -- Search --------------------------------------------------------------------------------


#: One tree to evaluate, and the fitted candidate it was bred from -- ``None`` for the initial
#: population, which was not bred from anything. Kept as a pair rather than as a field on some
#: richer object because the parent is not a property of the child topology: the same tree
#: proposed by two different parents inherits two different starting points, and the evaluator's
#: best-wins cache exists precisely to keep the better of them.
type _Offspring = tuple[Node, Candidate | None]


@dataclass
class _Evaluator:
    """Fits topologies with a reduced budget and caches the outcome by canonical form.

    Two stages, in this order: a local polish from the parent's fitted values when there is a
    parent to inherit from (:func:`_inherited_values`), and the reduced-budget global search
    when there is not, or when the polish landed too far off the best cost known at that
    complexity to stand on its own (:data:`WARM_ACCEPT_FACTOR`).

    The cache is **best-wins, not first-wins**, which is the half of this that is easy to miss.
    [measured, docs/EVOLVE_SEARCH_PLAN.md section 1.3] Over half of each late generation
    re-proposes a topology already evaluated; without inheritance those hits are free and
    information-free. With it, a hit arriving with a *new* warm start is worth a polish -- a few
    milliseconds -- and the better of the two fits is kept. That also removes the path
    dependence a warm start would otherwise introduce, where a topology's score depended on
    which parent happened to propose it first.

    Both stages are tier 1 and neither is publishable: nothing this class returns reaches the
    user without ``_refine`` fitting it again at full budget.
    """

    spectrum: Spectrum
    weighting: Weighting
    restarts: int
    popsize: int
    maxiter: int
    tol: float
    seed: int
    warm_accept: float = WARM_ACCEPT_FACTOR
    cache: dict[str, Candidate | None] = field(default_factory=dict)
    #: Best residual cost seen at each complexity, the yardstick a polish is judged against.
    best_cost: dict[float, float] = field(default_factory=dict)

    def evaluate(
        self, node: Node, generation: int, parent: Candidate | None = None
    ) -> Candidate | None:
        try:
            circuit = Circuit(simplify(node))
        except CircuitError:
            return None
        key = circuit.canonical_form()
        seen = key in self.cache
        known = self.cache.get(key)
        # A topology that could not be fitted, or is implausible, stays decided. Only a fit
        # that succeeded is ever revisited.
        if seen and known is None:
            return None
        if not seen and not is_plausible(circuit):
            self.cache[key] = None
            return None

        warm = self._warm_start(parent, circuit, known)
        candidate = None if warm is None else self._polish(circuit, generation, warm)
        # A topology already searched globally is not searched again: the polish refines it.
        # One never searched needs the global stage unless its polish is close enough to the
        # best known at its complexity to be believed.
        if not seen and (candidate is None or not self._close_enough(candidate)):
            candidate = _cheaper(candidate, self._search(circuit, generation))

        best = _cheaper(candidate, known)
        self.cache[key] = best
        if best is not None:
            cost = _fit_cost(best.result)
            if cost < self.best_cost.get(best.complexity, math.inf):
                self.best_cost[best.complexity] = cost
        return best

    def _warm_start(
        self, parent: Candidate | None, circuit: Circuit, known: Candidate | None
    ) -> dict[str, float] | None:
        """The inherited starting values, or None when there is nothing to gain by polishing."""
        if parent is None or self.warm_accept <= 0.0:
            return None
        warm = _inherited_values(parent, circuit)
        if not warm:
            return None
        # The elite are re-proposed unchanged every generation, so this is the common case: a
        # cached fit polished from its own values lands where it already is.
        if known is not None and all(
            known.result.params.get(name) == value for name, value in warm.items()
        ):
            return None
        return warm

    def _close_enough(self, candidate: Candidate) -> bool:
        """Whether a polish may stand in for the global stage at this complexity."""
        reference = self.best_cost.get(candidate.complexity)
        if reference is None:
            return False
        return _fit_cost(candidate.result) <= self.warm_accept * reference

    def _polish(
        self, circuit: Circuit, generation: int, initial: dict[str, float]
    ) -> Candidate | None:
        """One local refinement from the inherited values, with no global stage at all.

        At :data:`~autocircuit.core.fit.SCREEN_LOCAL`, which is the whole reason this is worth
        doing. [measured] Left at the publication budget the polish is cheap in the median --
        21% of the global search it replaces -- and its tail is not: two of ten children took
        13.1 s and 16.6 s against global searches of 14.6 s and 14.9 s, so the refinement cost
        as much as the search it was meant to save. That tail is rare enough to be invisible in
        a two-minute run and decisive in a ten-minute one, which is exactly the shape of the
        first EV3 measurement (+39% topologies at 120 s, +7% at 600 s).
        """
        return self._fitted(circuit, generation, initial=initial, global_search=False, restarts=1)

    def _search(self, circuit: Circuit, generation: int) -> Candidate | None:
        """The reduced-budget global search this class has always run."""
        return self._fitted(
            circuit, generation, initial=None, global_search=True, restarts=self.restarts
        )

    def _fitted(
        self,
        circuit: Circuit,
        generation: int,
        *,
        initial: dict[str, float] | None,
        global_search: bool,
        restarts: int,
    ) -> Candidate | None:
        # The population/iteration budget is passed either way; with ``global_search=False``
        # it is simply unused, since those three govern the global stage alone.
        #
        # ``local`` is bounded only for the warm polish. The global path keeps the budget it
        # has always had -- not because that is right, but because changing it would move every
        # number the control arm of gate EV3 is measured against, and a comparison whose
        # control moved measures nothing. Whether tier 1's global path should also drop to
        # SCREEN_LOCAL is a separate question with its own before/after.
        try:
            result = fit(
                circuit,
                self.spectrum,
                weighting=self.weighting,
                initial=initial,
                global_search=global_search,
                restarts=restarts,
                popsize=self.popsize,
                maxiter=self.maxiter,
                tol=self.tol,
                local=SCREEN_LOCAL if not global_search else PUBLISH_LOCAL,
                seed=self.seed,
            )
        except (ValueError, CircuitError, np.linalg.LinAlgError):
            return None
        if not math.isfinite(result.statistics.aicc):
            return None
        return Candidate(circuit, result, generation)

    def evaluate_all(
        self,
        items: Sequence[_Offspring],
        generation: int,
        executor: multiprocessing.pool.Pool | None,
    ) -> list[Candidate | None]:
        """The whole-population counterpart of :meth:`evaluate`.

        ``executor=None`` calls :meth:`evaluate` once per item, in the given order, and is
        therefore byte-identical to the loop it replaces -- cache and ``best_cost`` are read
        and written between items exactly as they always were. With an executor, the two
        expensive stages -- the warm polish and the reduced-budget global search -- are fanned
        across processes a generation at a time, so a lookup sees the cache and ``best_cost``
        as of the *start* of the generation rather than the update-as-you-go ordering
        :meth:`evaluate` gives them. That is the same staleness :func:`_screen_parallel`
        already accepts within one chunk, and for the same reason it cannot change which fit is
        ultimately reported: tier 2 always refits the shortlist at full budget regardless of
        which tier-1 path a topology took. It can change which topologies *reach* the
        shortlist, which is exactly what X6 (``docs/TOPOLOGY_6PLUS_PLAN.md`` section 5) exists
        to measure.
        """
        if executor is None:
            return [self.evaluate(node, generation, parent) for node, parent in items]

        prepared: list[_Prepared | None] = []
        for node, parent in items:
            try:
                circuit = Circuit(simplify(node))
            except CircuitError:
                prepared.append(None)
                continue
            key = circuit.canonical_form()
            seen = key in self.cache
            known = self.cache.get(key)
            if seen and known is None:
                prepared.append(None)
                continue
            if not seen and not is_plausible(circuit):
                self.cache[key] = None
                prepared.append(None)
                continue
            prepared.append(
                _Prepared(circuit, key, seen, known, self._warm_start(parent, circuit, known))
            )

        polish_indices: list[int] = []
        polish_tasks: list[tuple[str, int, dict[str, float]]] = []
        for i, p in enumerate(prepared):
            if p is not None and p.warm is not None:
                polish_indices.append(i)
                polish_tasks.append((p.circuit.to_string(), self.seed, p.warm))

        polished: dict[int, Candidate | None] = {}
        if polish_tasks:
            for i, wire in zip(
                polish_indices, executor.map(_evolve_polish_worker, polish_tasks), strict=True
            ):
                p = prepared[i]
                assert p is not None
                polished[i] = (
                    None
                    if wire is None
                    else Candidate(p.circuit, FitResult.from_wire(wire), generation)
                )

        search_indices: list[int] = []
        search_tasks: list[tuple[str, int, int, int, int, float]] = []
        for i, p in enumerate(prepared):
            if p is None or p.seen:
                continue
            polished_candidate = polished.get(i)
            if polished_candidate is None or not self._close_enough(polished_candidate):
                search_indices.append(i)
                search_tasks.append(
                    (
                        p.circuit.to_string(),
                        self.seed,
                        self.restarts,
                        self.popsize,
                        self.maxiter,
                        self.tol,
                    )
                )

        searched: dict[int, Candidate | None] = {}
        if search_tasks:
            for i, wire in zip(
                search_indices, executor.map(_evolve_search_worker, search_tasks), strict=True
            ):
                p = prepared[i]
                assert p is not None
                searched[i] = (
                    None
                    if wire is None
                    else Candidate(p.circuit, FitResult.from_wire(wire), generation)
                )

        results: list[Candidate | None] = []
        for i, p in enumerate(prepared):
            if p is None:
                results.append(None)
                continue
            best = _cheaper(_cheaper(polished.get(i), searched.get(i)), p.known)
            self.cache[p.key] = best
            if best is not None:
                cost = _fit_cost(best.result)
                if cost < self.best_cost.get(best.complexity, math.inf):
                    self.best_cost[best.complexity] = cost
            results.append(best)
        return results


class _Prepared(NamedTuple):
    """One tree's cache lookup, resolved before either expensive fit stage runs."""

    circuit: Circuit
    key: str
    seen: bool
    known: Candidate | None
    warm: dict[str, float] | None


def _evolve_polish_worker(task: tuple[str, int, dict[str, float]]) -> dict[str, Any] | None:
    """One warm polish in a worker process, the parallel counterpart of
    :meth:`_Evaluator._polish`."""
    text, seed, initial = task
    try:
        result = fit(
            text,
            _WORKER["spectrum"],
            weighting=_WORKER["weighting"],
            initial=initial,
            global_search=False,
            restarts=1,
            local=SCREEN_LOCAL,
            seed=seed,
        )
    except (ValueError, CircuitError, np.linalg.LinAlgError):
        return None
    if not math.isfinite(result.statistics.aicc):
        return None
    return result.to_wire()


def _evolve_search_worker(task: tuple[str, int, int, int, int, float]) -> dict[str, Any] | None:
    """One reduced-budget global search in a worker process, the parallel counterpart of
    :meth:`_Evaluator._search`."""
    text, seed, restarts, popsize, maxiter, tol = task
    try:
        result = fit(
            text,
            _WORKER["spectrum"],
            weighting=_WORKER["weighting"],
            global_search=True,
            restarts=restarts,
            popsize=popsize,
            maxiter=maxiter,
            tol=tol,
            local=PUBLISH_LOCAL,
            seed=seed,
        )
    except (ValueError, CircuitError, np.linalg.LinAlgError):
        return None
    if not math.isfinite(result.statistics.aicc):
        return None
    return result.to_wire()


def _same_response(a: Candidate, b: Candidate) -> bool:
    """True when two fitted candidates produce the same spectrum to within EQUIVALENCE_RTOL."""
    za, zb = a.result.z_model, b.result.z_model
    if za.shape != zb.shape:
        return False
    magnitude = np.abs(zb)
    if not np.all(magnitude > 0.0):
        return False
    return bool(np.max(np.abs(za - zb) / magnitude) <= EQUIVALENCE_RTOL)


def pareto_front(
    candidates: Sequence[Candidate], criterion: Criterion = DEFAULT_CRITERION
) -> list[Candidate]:
    """Candidates not beaten on both complexity and the chosen criterion by any other."""
    scores = {id(c): c.score(criterion) for c in candidates}
    front: list[Candidate] = []
    for candidate in candidates:
        mine = scores[id(candidate)]
        dominated = any(
            other is not candidate
            and other.complexity <= candidate.complexity
            and scores[id(other)] <= mine
            and (other.complexity < candidate.complexity or scores[id(other)] < mine)
            for other in candidates
        )
        if not dominated:
            front.append(candidate)
    return sorted(front, key=lambda c: (c.complexity, scores[id(c)]))


def discover(
    spectrum: Spectrum,
    *,
    pool: Sequence[str] | None = None,
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
    growth_width: int = GROWTH_DEFAULT,
    screen_restarts: int = SCREEN_RESTARTS,
    seed: int = 0,
    weighting: Weighting = "modulus",
    search_restarts: int = 1,
    search_popsize: int = 12,
    search_maxiter: int = 60,
    search_tol: float = 1e-5,
    warm_accept: float = WARM_ACCEPT_FACTOR,
    final_restarts: int = 5,
    n_refine: int | None = None,
    time_limit: float | None = None,
    seeds: Sequence[str] | None = None,
    criterion: Criterion = DEFAULT_CRITERION,
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
        pool: Element codes the search may use, or None -- the default -- to let the spectrum
            choose. Naming one is how a caller who *does* know something about the part injects
            it, e.g. ``("R", "C", "L", "CPE", "SKINF")`` for components; it narrows the search
            and the report says so. Left as None the search starts from
            :data:`~autocircuit.core.elements.DEFAULT_POOL` and widens it only when that pool's
            own completed fit leaves a systematic residual, which is the only evidence
            available that an element is missing rather than merely unused. See
            :mod:`autocircuit.core.descriptors` for what fires it and which codes it may add.
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
        max_elements: Cap on elements per topology, for both the genetic search and the growth
            stage that runs above ``exhaustive_limit``.
        min_elements: Smallest random topology in the initial population.
        growth_width: How many topologies of each completed level the growth stage extends. See
            :data:`GROWTH_WIDTH`; zero switches growth off entirely, which is how a caller asks
            for the pre-growth behaviour rather than by lowering ``max_elements``.
        screen_restarts: Independent global searches per topology in the tier-1 screen, best of
            which is kept. See :data:`SCREEN_RESTARTS`: raising it to 2 is the measured remedy
            for a bimodal screening landscape and it doubles the dominant cost of the search,
            which is why the default is 1 and why moving it needs a recovery measurement rather
            than an argument.
        seed: Random seed; the whole search is reproducible from it.
        weighting: Residual weighting passed through to the fitter.
        search_restarts, search_popsize, search_maxiter: Reduced fitting budget used by the
            genetic search. Survivors are refitted properly at the end.
        warm_accept: How far off the best cost known at the same complexity a warm-started
            polish may land and still skip the global stage (genetic search only); zero turns
            parameter inheritance off. See :data:`WARM_ACCEPT_FACTOR`.
        final_restarts: Restart count for the final refit of the reported candidates.
        n_refine: Refit budget for the full-budget second tier. In **both** searches it is a
            *total* that is split into a quota per element count, so that every complexity
            reaches the Pareto front; see :func:`_quota_by_size`. :data:`REFINE_DEFAULT` holds
            the default, and says why raising it below a threshold changes nothing.
        time_limit: Wall-clock budget in seconds; the search stops cleanly when exceeded.
        criterion: Which model-selection rule ranks the candidates, draws the Pareto front and
            ranks the tier-1 shortlist -- one of :data:`~autocircuit.core.stats.CRITERIA`,
            default :data:`~autocircuit.core.stats.DEFAULT_CRITERION`. It does **not** change
            :attr:`DiscoveryResult.recommended`, which is a rule about identifiability rather
            than about a penalty term. ``"ftest"`` is not a score: it ranks by AIC and then
            tests each step up the front, which :attr:`DiscoveryResult.by_criterion` applies and
            :meth:`DiscoveryResult.summary` labels.
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
    if criterion not in CRITERIA:
        known = ", ".join(CRITERIA)
        raise ValueError(f"unknown model-selection criterion {criterion!r}; known: {known}")
    started = time.perf_counter()
    # None means "the spectrum decides". The base pool is where that decision starts, never
    # where it is allowed to end silently: a run that adds nothing still reports having
    # considered the diffusion elements (docs/POOL_FROM_SPECTRUM_PLAN.md).
    derive_pool = pool is None
    codes = DEFAULT_POOL if pool is None else tuple(pool)
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
        evolved = _evolve(
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
            warm_accept=warm_accept,
            criterion=criterion,
            workers=workers,
        )
        # The genetic search never completes a pool, so it cannot produce the evidence the
        # widening rests on. Saying "unasked" rather than leaving the field empty is the
        # difference between a check that came back negative and no check at all.
        if derive_pool:
            evolved.pool_choice = choose_pool(spectrum, residual_runs_z=math.nan, base=codes)
        return evolved

    candidates, complete_up_to, n_screened, grown_to = _exhaustive(
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
        criterion=criterion,
        # Growth is skipped under a skeleton, for the reason the genetic fallback is: the
        # skeleton run already reaches past the default limit on its own (`SKELETON_REACH`),
        # and a report that mixed "complete up to N containing the skeleton" with "grown from
        # the best W of level N" could not state which space it had covered.
        grow_to=None if frame is not None else max_elements,
        growth_width=growth_width,
        screen_restarts=screen_restarts,
    )
    generations_run = 0
    pool_choice: PoolChoice | None = None
    base_complete_up_to: int | None = None

    # Widening the pool, when either reading of the data asks for an element it lacks.
    #
    # This runs *before* the genetic fallback and not after, because the two are answers to the
    # same symptom on different axes -- a systematic residual means either the vocabulary is
    # too small or the circuit is -- and the pool axis stays inside the exhaustive stage, which
    # is the half of discovery that recovers the truth 30 times in 30 rather than 1 time in 9
    # (docs/EVOLVE_SEARCH_PLAN.md section 1). It also costs a completeness level, so trying it
    # first and the genetic search second means the expensive, unreliable stage is only reached
    # once the cheap, reliable one has been given every element the data admits.
    if derive_pool:
        pool_choice = choose_pool(spectrum, residual_runs_z=_best_runs_z(candidates), base=codes)
        remaining = None if time_limit is None else time_limit - (time.perf_counter() - started)
        if pool_choice.added and (remaining is None or remaining > 0.0):
            base_complete_up_to = complete_up_to
            codes = pool_choice.pool
            widened, complete_up_to, n_widened, grown_to = _exhaustive(
                spectrum,
                pool=codes,
                skeleton=None if frame is None else frame.root,
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
                criterion=criterion,
                grow_to=max_elements,
                growth_width=growth_width,
                screen_restarts=screen_restarts,
            )
            # The base-pool candidates are kept rather than discarded: they were fitted against
            # the same data with the same budget, and every one of them is also a member of the
            # wider pool's space. Dropping them would lose the sizes the wider enumeration could
            # no longer afford, which is precisely what ``base_complete_up_to`` records.
            candidates = _unique_best(candidates + widened, criterion)
            n_screened += n_widened

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
                warm_accept=warm_accept,
                criterion=criterion,
                workers=workers,
            )
            candidates = _unique_best(candidates + evolved.candidates, criterion)
            n_screened += evolved.n_evaluated
            generations_run = evolved.generations

    candidates.sort(key=lambda c: c.score(criterion))
    return DiscoveryResult(
        candidates=candidates,
        pareto=pareto_front(candidates, criterion),
        n_evaluated=n_screened,
        generations=generations_run,
        elapsed_s=time.perf_counter() - started,
        pool=codes,
        mode=mode,
        complete_up_to=complete_up_to,
        skeleton=None if frame is None else frame.to_string(),
        criterion=criterion,
        pool_choice=pool_choice,
        base_complete_up_to=base_complete_up_to,
        grown_to=grown_to,
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
    screened: int
    """How many of ``excluded`` were actually checked; below it when the pass was stopped.

    The pass takes about as long as the search it follows, so it is the second thing in this
    project a user is likely to cancel -- and a half-finished one reads exactly like a finished
    one, which is the failure this codebase keeps meeting (docs/HANDOFF.md section 3). "None of
    them reproduces the reported circuit" is a claim about every excluded topology; what a
    stopped pass knows is a claim about the ones it reached. :meth:`summary` says which it has.
    """
    equivalents: tuple[str, ...]
    """Excluded topologies found to reproduce ``circuit``'s fitted response exactly."""
    elapsed_s: float
    """Screening time accounted for, i.e. up to the last batch whose costs came back."""

    @property
    def partial(self) -> bool:
        """True when the pass was stopped before every excluded topology was checked."""
        return self.screened < self.excluded

    def summary(self) -> str:
        removed = (
            f"Your skeleton {self.skeleton} excluded {self.excluded} of the "
            f"{self.kept + self.excluded} topologies with {self.size} elements"
        )
        if not self.partial:
            if not self.equivalents:
                return (
                    f"{removed}, and none of them reproduces {self.circuit} exactly on this "
                    "frequency window. Nothing the data could not already distinguish was lost."
                )
            names = ", ".join(self.equivalents)
            return (
                f"{removed}, and {len(self.equivalents)} of them fit {self.circuit} exactly on "
                f"this frequency window: {names}. The data cannot tell these apart from the "
                "reported one -- choosing between them is something you did, not something the "
                "fit found."
            )
        # Deliberately not "the check was stopped": this same sentence describes a pass still
        # running, and what is true of both is how many topologies have been looked at.
        unchecked = self.excluded - self.screened
        if not self.equivalents:
            return (
                f"{removed}. Only {self.screened} of them have been checked, and none of those "
                f"reproduces {self.circuit} exactly on this frequency window -- which is not "
                f"the same as nothing having been lost, because {unchecked} were never checked."
            )
        names = ", ".join(self.equivalents)
        return (
            f"{removed}. Only {self.screened} of them have been checked, and "
            f"{len(self.equivalents)} of those fit {self.circuit} exactly on this frequency "
            f"window: {names}. The data cannot tell these apart from the reported one -- "
            "choosing between them is something you did, not something the fit found. Another "
            f"{unchecked} were never checked, so this list is not the whole of what was lost."
        )


class ExcludedBatch(NamedTuple):
    """One batch of excluded topologies to screen, and the report as it stands before them.

    ``so_far`` is here for the same reason :attr:`RefitBatch.done` is: it is what a stopped
    pass reports from. A driver that assembled its own partial report would be writing a second
    copy of the rule that separates "checked and found nothing" from "did not check".
    """

    tasks: list[ScreenTask]
    so_far: ExcludedEquivalents


def excluded_target(candidate: Candidate, spectrum: Spectrum) -> Spectrum:
    """The response an excluded topology has to reproduce to count as an equivalent.

    The candidate's *fitted* response at the data's frequencies, not the data. An exact
    reparameterisation reaches a noise-free target to machine precision, which the sample's
    noise would otherwise mask, and it turns the question from "does this fit the sample?" into
    the algebraic one actually being asked (docs/PARTIAL_TOPOLOGY_PLAN.md section 3.3).
    """
    return Spectrum(spectrum.f, candidate.result.z_model)


def excluded_plan(
    candidate: Candidate,
    skeleton: str,
    spectrum: Spectrum,
    *,
    pool: Sequence[str] = DEFAULT_POOL,
    chunk: int | None = None,
) -> Generator[ExcludedBatch, Sequence[float], ExcludedEquivalents]:
    """The excluded-equivalents pass with the *running* of it left to the caller.

    The third generator of this shape, after :func:`screen_plan` and :func:`refit_plan`, and
    for the same reason: which topologies the skeleton excluded, what response they are judged
    against, how exact "exact" is, and what a stopped pass may then claim are decisions, and
    they get one implementation. A driver fans the screens out and nothing else --
    :func:`excluded_equivalents` in-process or across a process pool, JavaScript across Pyodide
    workers (``docs/WEB_UI_PLAN.md`` section 2.6).

    Yields an :class:`ExcludedBatch`, expects one cost per task back through ``send``, and
    returns the finished :class:`ExcludedEquivalents`. ``chunk`` is the driver's scheduling
    knob only: no decision here depends on an earlier batch, since every screen runs against
    the same target with no early abandon, so batching buys a progress count and a cancel point
    and costs nothing. ``None`` means one batch.
    """
    started = time.perf_counter()
    frame = Circuit.parse(skeleton).root
    size = len(candidate.circuit.leaves)

    outside: list[str] = []
    kept = 0
    for node in enumerate_topologies(pool, size):
        if contains_skeleton(node, frame):
            kept += 1
        else:
            outside.append(Circuit(node).to_string())

    found: list[tuple[float, str]] = []
    screened = 0

    def report() -> ExcludedEquivalents:
        return ExcludedEquivalents(
            circuit=candidate.circuit.to_string(),
            skeleton=skeleton,
            size=size,
            kept=kept,
            excluded=len(outside),
            screened=screened,
            equivalents=tuple(text for _, text in sorted(found)),
            elapsed_s=time.perf_counter() - started,
        )

    step = max(len(outside) if chunk is None else chunk, 1)
    for start in range(0, len(outside), step):
        window = outside[start : start + step]
        # Never abandoned: the abandon threshold exists to skip a polish on a topology already
        # far off the pace of a *rival*, and here every screen is judged against the same
        # target on its own. An abandoned screen would return infinity and read as "not an
        # equivalent", which is the one answer this pass must not invent.
        costs = yield ExcludedBatch([ScreenTask(text, math.inf) for text in window], report())
        for cost, text in zip(costs, window, strict=True):
            screened += 1
            if float(cost) <= PERFECT_COST:
                found.append((float(cost), text))
    return report()


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

    This is the in-process driver of :func:`excluded_plan`, which holds every decision it makes.
    """
    target = excluded_target(candidate, spectrum)
    plan = excluded_plan(candidate, skeleton, spectrum, pool=pool)
    with _worker_pool(workers, target, weighting) as executor:
        try:
            batch = next(plan)
            while True:
                if executor is not None and len(batch.tasks) > 1:
                    costs = list(
                        executor.map(
                            _screen_worker,
                            [
                                (
                                    task.text,
                                    seed,
                                    task.abandon_above,
                                    budget.popsize,
                                    budget.maxiter,
                                    budget.restarts,
                                )
                                for task in batch.tasks
                            ],
                        )
                    )
                else:
                    costs = [
                        _screen_one(task, target, weighting=weighting, seed=seed, budget=budget)
                        for task in batch.tasks
                    ]
                batch = plan.send(costs)
        except StopIteration as done:
            return cast(ExcludedEquivalents, done.value)


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


def _best_runs_z(candidates: Sequence[Candidate]) -> float:
    """Runs z of the best fit's residuals; NaN when there is nothing to test.

    The residual vector is the real parts followed by the imaginary parts, so it is split
    before the runs test -- a sign pattern that alternates within each half but flips between
    them would otherwise read as random. The smaller half is taken, because structure in
    either one is structure.
    """
    if not candidates:
        return -math.inf
    best = min(candidates, key=lambda c: c.result.chi2_reduced)
    residuals = best.result.residuals
    if residuals.size < 4:
        return math.nan
    half = residuals.size // 2
    return min(_runs_z(residuals[:half]), _runs_z(residuals[half:]))


def _is_underfitted(candidates: Sequence[Candidate]) -> bool:
    """True when the best model leaves residuals that look like structure, not noise."""
    z = _best_runs_z(candidates)
    return False if math.isnan(z) else bool(z < RUNS_Z_LIMIT)


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
    warm_accept: float = WARM_ACCEPT_FACTOR,
    criterion: Criterion = DEFAULT_CRITERION,
    workers: int = 1,
) -> DiscoveryResult:
    """Regularised evolution over the topology grammar, warm-started from each parent.

    ``workers`` fans both tiers across processes exactly as :func:`_exhaustive` already does --
    [measured, docs/TOPOLOGY_6PLUS_PLAN.md section 5.11, X6] this search never had that option
    before: every evolve measurement in this repo before that section ran single-threaded, on
    194-798 core-seconds against the exhaustive control's six-way run, while all twelve of those
    runs were still bounded by ``generations`` rather than by ``time_limit``. Parallelism
    therefore was not what those runs were missing; it is wired in anyway because a search this
    document calls a *fallback* has no principled reason to run on one core when the search it
    falls back from does not, and because a wall-clock comparison between the two is not
    correctable after the fact -- only re-run under matching resources.
    """
    rng = np.random.default_rng(seed)
    evaluator = _Evaluator(
        spectrum,
        weighting,
        search_restarts,
        search_popsize,
        search_maxiter,
        search_tol,
        seed,
        warm_accept,
    )

    # The initial population has no parents: seeds come from the caller and the rest is random,
    # so every one of these is fitted by the global stage. That is also what fills
    # ``_Evaluator.best_cost``, which the warm starts are later judged against.
    trees: list[_Offspring] = []
    for text in seeds or ():
        trees.append((Circuit.parse(text).root, None))
    while len(trees) < population:
        n = int(rng.integers(min_elements, max_elements + 1))
        trees.append((random_topology(rng, pool, n), None))

    scored: list[Candidate] = []
    generation = 0
    with _worker_pool(workers, spectrum, weighting) as executor:
        for generation in range(generations):
            for candidate in evaluator.evaluate_all(trees, generation, executor):
                if candidate is not None:
                    scored.append(candidate)
            if time_limit is not None and time.perf_counter() - started > time_limit:
                break

            alive = _unique_best(scored, criterion)
            if not alive:
                trees = []
                for _ in range(population):
                    size = int(rng.integers(min_elements, max_elements + 1))
                    trees.append((random_topology(rng, pool, size), None))
                continue

            trees = _next_generation(
                _breeding_pool(alive, criterion=criterion),
                rng,
                pool,
                max_elements,
                population,
                criterion,
                # Crowding is a property of the whole archive, not of the front the pool is
                # (:func:`_complexity_frequencies`). Computed only when it can change something:
                # the default scaling is zero and the count would otherwise walk the archive once
                # per generation to be multiplied away.
                frequencies=(_complexity_frequencies(alive) if PARSIMONY_SCALING else None),
            )

        # Only refitted candidates are reported, which is the rule SCREEN_POPSIZE states and the
        # rule `_exhaustive` has always followed: every number that reaches the user comes from
        # the full-budget refit. [measured, docs/EVOLVE_SEARCH_PLAN.md section 1.4] This search
        # used to merge the unrefitted archive back in -- `_unique_best(refined + alive)` -- and
        # 82% of the Pareto rows it reported then carried screening-grade chi-squareds, standard
        # errors and therefore "free?" marks, with nothing in the report able to say which rows
        # those were. The archive is not lost: it selects the shortlist, and `n_evaluated` still
        # counts it.
        alive = _unique_best(scored, criterion)
        shortlist = _shortlist_candidates(alive, n_refine, criterion)
        refined, attempted = _refine(
            shortlist,
            spectrum,
            weighting,
            final_restarts,
            seed,
            deadline=None if time_limit is None else started + time_limit * REFIT_HEADROOM,
            criterion=criterion,
            executor=executor,
            workers=workers,
        )
    # Tier 2 is authoritative even when it scores worse than the reduced fit did: a full-budget
    # refit that lands in a different basin is the better estimate of that topology, and keeping
    # whichever number happened to be smaller would be picking the fit by its answer.
    refined = _unique_best(refined, criterion)
    refined.sort(key=lambda c: c.score(criterion))

    return DiscoveryResult(
        candidates=refined,
        pareto=pareto_front(refined, criterion),
        n_evaluated=len(evaluator.cache),
        generations=generation + 1,
        elapsed_s=time.perf_counter() - started,
        pool=pool,
        mode="evolve",
        complete_up_to=None,
        # Set only when the tier really was cut short. A finished refit that dropped a few
        # unfittable topologies is not a partial report, and saying so would cry wolf on the
        # one signal that means "these numbers are still moving".
        refit_progress=(None if attempted >= len(shortlist) else (len(refined), len(shortlist))),
        criterion=criterion,
    )


# -- Exhaustive search ---------------------------------------------------------------------


class Enumeration(NamedTuple):
    """The topologies an exhaustive stage will screen, and what coverage they can claim.

    The two halves belong together: ``boundaries`` records how many topologies had been
    queued once each element count was complete, and that is the only thing from which
    :meth:`coverage` can be derived. Splitting them would put the completeness rule somewhere
    that does not know where the levels ended.
    """

    texts: tuple[str, ...]
    """Every candidate to screen, in ascending element count."""
    boundaries: tuple[tuple[int, int], ...]
    """``(element count, topologies queued once that count was complete)`` per whole level."""
    floor: int
    """Smallest element count enumerated. Above 1 there is no completeness claim to make."""

    def coverage(self, n_scored: int) -> int | None:
        """Largest element count whose topologies were *all* screened, from a screen that got
        through ``n_scored`` of them.

        Topologies are screened in size order, so a truncated screen -- out of time, or
        cancelled from a browser -- still covers whole levels, and this is what says how many.
        Starting above one element forfeits the claim entirely: "all topologies up to N" is
        only true when the smaller sizes were looked at too. A skeleton is not such a start,
        even though its levels begin at its own size: no topology smaller than the skeleton
        can contain it, so the sizes below it are empty rather than skipped.
        """
        if self.floor != 1:
            return None
        return next((n for n, end in reversed(self.boundaries) if end <= n_scored), None)


def enumerate_candidates(
    spectrum: Spectrum,
    *,
    pool: tuple[str, ...],
    skeleton: Node | None,
    limit: int,
    floor: int,
    max_candidates: int,
    feasibility_filter: bool,
    feasibility_budget: int,
    extra: Sequence[str] | None = None,
) -> Enumeration:
    """Everything the exhaustive stage will screen, and nothing about how to screen it.

    Separated from :func:`_exhaustive` for the same reason :func:`screen_plan` and
    :func:`refit_plan` were: a browser drives the two tiers itself, and if it enumerated for
    itself there would be a second implementation of which topologies exist, where a level
    stops being affordable, and what may then be claimed -- the last of which is the whole
    point of exhaustive discovery. It takes a spectrum only to derive the endpoint behaviour
    the feasibility filter tests against.
    """
    behaviour = EndpointBehaviour.from_spectrum(spectrum) if feasibility_filter else None

    # Both level sources yield whole element counts in ascending order; the constrained one
    # grows the skeleton outwards and stops itself before materialising a level too large to
    # hold, which is the limit that binds first (docs/PARTIAL_TOPOLOGY_PLAN.md section 4.1).
    levels: Iterable[tuple[int, Iterable[Node]]]
    if skeleton is None:
        levels = ((n, enumerate_topologies(pool, n)) for n in range(floor, limit + 1))
    else:
        levels = grow_up_to(skeleton, pool, limit, max_frontier=max_candidates * FRONTIER_HEADROOM)

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

    return Enumeration(tuple(texts), tuple(boundaries), floor)


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
    criterion: Criterion = DEFAULT_CRITERION,
    grow_to: int | None = None,
    growth_width: int = GROWTH_DEFAULT,
    screen_restarts: int = SCREEN_RESTARTS,
) -> tuple[list[Candidate], int | None, int, int | None]:
    """Enumerate, screen, optionally grow past the limit, and refit.

    Returns ``(candidates, complete_up_to, topologies seen, grown_to)``, where ``grown_to`` is
    the largest element count the growth stage actually reached and ``None`` when it did not run.

    The growth stage sits **between** the two tiers rather than after them, and that placement is
    the point: it needs the tier-1 ranking of a completed level, which is exactly what
    :func:`_screen_all` has just produced and what the old code discarded on its way to the
    shortlist. Both stages' screens then feed one shortlist, so a six-element candidate competes
    with the five-element ones under the same per-size quota rather than in a report of its own.
    """
    plan = enumerate_candidates(
        spectrum,
        pool=pool,
        skeleton=skeleton,
        limit=limit,
        floor=floor,
        max_candidates=max_candidates,
        feasibility_filter=feasibility_filter,
        feasibility_budget=feasibility_budget,
        extra=extra,
    )
    texts = list(plan.texts)
    budget = ScreenBudget(SCREEN_POPSIZE, SCREEN_MAXITER, max(screen_restarts, 1))

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
            budget=budget,
        )
        complete_up_to = plan.coverage(len(scored))
        n_seen = len(scored)

        grown_to: int | None = None
        if (
            grow_to is not None
            and growth_width > 0
            and complete_up_to is not None
            and grow_to > complete_up_to
            and GROWTH_REACH > 0
            and (time_limit is None or time.perf_counter() - started < time_limit)
        ):
            grown = _grow_all(
                scored,
                spectrum,
                pool=pool,
                start_size=complete_up_to,
                # A reach past the completed level, never a walk to the absolute cap; see
                # GROWTH_REACH.
                max_elements=min(grow_to, complete_up_to + GROWTH_REACH),
                width=growth_width,
                weighting=weighting,
                seed=seed,
                executor=executor,
                on_progress=on_progress,
                time_limit=time_limit,
                started=started,
                criterion=criterion,
                budget=budget,
            )
            if grown:
                scored = list(scored) + grown
                n_seen += len(grown)
                grown_to = max(count_elements(Circuit.parse(text).root) for _cost, text in grown)

        candidates = _refit_shortlist(
            scored, spectrum, weighting, final_restarts, seed, n_refine, executor, criterion
        )
    return candidates, complete_up_to, n_seen, grown_to


#: What the screen ranks by when the chosen criterion cannot be computed from a cost alone.
#:
#: WAIC needs the leverage, which needs the Jacobian, which is the expensive half of a full fit
#: and is exactly what tier 1 does not do; ``ftest`` needs two models rather than one. Both fall
#: back here. That is a decision about *who gets refitted*, not about who wins -- every number
#: that reaches the user comes from tier 2, where the chosen criterion applies in full.
SCREENING_FALLBACK: Criterion = "aic"


def _screening_score(
    cost: float, n_params: int, n_data: int, criterion: Criterion = DEFAULT_CRITERION
) -> float:
    """A model-selection score from a screening cost alone, with no covariance.

    The same formulae :func:`stats.information_criteria` uses, fed the weighted sum of squared
    residuals and the parameter count. That is everything AIC, AICc, BIC, CAIC and HQC need; the
    expensive part of a full fit is the Jacobian, which only the uncertainties -- and WAIC --
    require. See :data:`SCREENING_FALLBACK` for the two that cannot be answered here.
    """
    if not math.isfinite(cost) or cost <= 0.0 or n_data - n_params - 1 <= 0:
        return math.inf
    name = criterion if criterion in ("aic", "aicc", "bic", "caic", "hqc") else SCREENING_FALLBACK
    value = information_criteria(cost, n_data, n_params)[name]
    return value if math.isfinite(value) else math.inf


class Ranked[T](NamedTuple):
    """One candidate for a full-budget refit, reduced to what the quota rule needs.

    ``payload`` is whatever the caller wants back -- a topology string for the exhaustive
    stage's screen, a :class:`Candidate` for the genetic search's archive.
    """

    n_elements: int
    score: float
    """Model-selection value, smaller better. Ranks *within* a size class."""
    cost: float
    """Weighted sum of squared residuals. Only the near-tie rule reads this."""
    tiebreak: str
    """Sorted on after score and cost, so that ties order the same way on every run.

    Not decoration. Two topologies scoring *exactly* alike is the normal case here rather than a
    rarity -- it is what an exact reparameterisation looks like, and surfacing those is what the
    equivalence-class report exists for -- so which of them the quota keeps would otherwise
    depend on the order the caller happened to build the list in.
    """
    payload: T


def _quota_by_size[T](items: Sequence[Ranked[T]], n_refine: int) -> list[T]:
    """Split ``n_refine`` into a per-element-count quota and take the best of each size.

    **The quota is per element count, and that is not a detail.** [measured] Ranking the whole
    pool by cost puts nothing but the largest circuits on the shortlist: raw residual always
    improves with parameters, so on the capacitor reference every one of the 60 best-scoring
    candidates had five elements and the four-element truth -- the circuit that generated the
    data -- never reached tier 2 at all. Two corrections, both needed:

    * rank *within* a size by an information criterion rather than raw cost, so an extra CPE has
      to earn its two parameters even against its own size class;
    * give every size its own quota, so the Pareto front has candidates at each complexity
      instead of a cluster at the top.

    Within a size the list is the score-best ``quota``, plus every candidate whose cost is
    within :data:`REFINE_COST_FACTOR` of that size's best -- the near-tie rule, which is what
    stops an exact equivalent from being dropped because a sloppy fit ranked it one place too
    low. [measured] That rule needs a ceiling: at 1% noise a factor 10 in cost is only a factor
    3.2 in relative error, so hundreds of candidates land inside it and refitting them all cost
    half an hour per run while surfacing nothing new.

    Shared by both searches on purpose. Gate G1 rests on this rule and gate EV2 on the genetic
    search making the same kind of claim as the exhaustive one; a second copy of it is a second
    thing that can drift (docs/EVOLVE_SEARCH_PLAN.md section 3.2).
    """
    by_size: dict[int, list[Ranked[T]]] = {}
    for item in items:
        by_size.setdefault(item.n_elements, []).append(item)
    if not by_size:
        return []

    quota = max(MIN_REFINE_PER_SIZE, n_refine // len(by_size))
    keep: list[T] = []
    for group in by_size.values():
        group.sort(key=lambda item: (item.score, item.cost, item.tiebreak))
        best_cost = min(item.cost for item in group)
        threshold = best_cost * REFINE_COST_FACTOR if best_cost > 0.0 else math.inf
        near_ties = sum(1 for item in group if item.cost <= threshold)
        take = min(max(quota, near_ties), quota * REFINE_CEILING_FACTOR)
        keep.extend(item.payload for item in group[:take])
    return keep


def _shortlist(
    scored: Sequence[tuple[float, str]],
    n_refine: int,
    n_data: int,
    criterion: Criterion = DEFAULT_CRITERION,
) -> list[str]:
    """The screened candidates worth a full-budget refit, as topology strings.

    Tier 1's half of :func:`_quota_by_size`, which holds the rule and the reasons for it. All
    this adds is what a *screen* has to rank by: the cost is a raw weighted SSR with no
    covariance behind it, so the score is :func:`_screening_score` rather than a fitted
    criterion.
    """
    ranked: list[Ranked[str]] = []
    for cost, text in scored:
        if not math.isfinite(cost):
            continue
        circuit = Circuit.parse(text)
        ranked.append(
            Ranked(
                len(circuit.leaves),
                _screening_score(cost, circuit.n_params, n_data, criterion),
                cost,
                text,
                text,
            )
        )
    return _quota_by_size(ranked, n_refine)


def _refit_order(
    candidates: Sequence[Candidate], criterion: Criterion = DEFAULT_CRITERION
) -> list[Candidate]:
    """The shortlist in the order a *bounded* tier 2 should walk it: best of every size first.

    :func:`_quota_by_size` chooses *which* candidates are worth a full-budget refit and says
    nothing about the order, because the exhaustive stage refits all of them. The genetic
    search's tier 2 does not: it answers to a deadline (:data:`REFIT_HEADROOM`) and stops
    wherever it has got to, so for that caller the order decides what is reported.

    [measured, docs/SEARCH_ALGORITHM_SCREENING.md section 4.6] Walking it in the order the
    quota happens to build -- grouped by element count, the groups in whatever order the
    archive first mentioned them -- lost the answer. At element cap 9, seed 0, the truth's
    equivalence class was ranked **1 of 270** in the archive and sat at position 53 of a
    73-candidate shortlist whose deadline cut fell at 40; sizes 6 and 8 were never attempted at
    all, and the report contained no six-element row while the best thing the search had found
    was one. Nothing was wrong with the search or with the shortlist. The report simply walked
    away from the answer.

    So the order is a round robin over the size groups, taking each group's best before any
    group's second, and ordering within a round by the score itself. Two properties follow, and
    they are the two the quota exists for: the archive's best-scoring candidate is always
    attempted first, and any cut that leaves room for one refit per size leaves a Pareto front
    that still spans the complexities -- rather than however many sizes fitted inside the clock.
    """
    by_size: dict[int, list[Candidate]] = {}
    for candidate in candidates:
        by_size.setdefault(len(candidate.circuit.leaves), []).append(candidate)

    def key(candidate: Candidate) -> tuple[float, float, str]:
        score = candidate.score(criterion)
        return (
            score if math.isfinite(score) else math.inf,
            candidate.result.statistics.ssr,
            candidate.circuit.canonical_form(),
        )

    ordered: list[tuple[int, tuple[float, float, str], Candidate]] = []
    for group in by_size.values():
        group.sort(key=key)
        ordered.extend((rank, key(candidate), candidate) for rank, candidate in enumerate(group))
    ordered.sort(key=lambda item: (item[0], item[1]))
    return [candidate for _rank, _key, candidate in ordered]


def _shortlist_candidates(
    alive: Sequence[Candidate], n_refine: int, criterion: Criterion = DEFAULT_CRITERION
) -> list[Candidate]:
    """The genetic search's archive reduced to what is worth a full-budget refit.

    The same rule as :func:`_shortlist` and deliberately so, but the inputs are better: these
    candidates were fitted, so the score is the chosen criterion computed from a real covariance
    rather than the cost-only approximation a screen has to make, and the cost the near-tie rule
    reads is the fit's own weighted SSR.

    The budget behind those numbers is still the reduced search budget, which is exactly why
    this selects rather than reports. What comes back gets refitted at full budget, and only
    that is published -- see :func:`_evolve`.
    """
    return _quota_by_size(
        [
            Ranked(
                len(candidate.circuit.leaves),
                candidate.score(criterion),
                candidate.result.statistics.ssr,
                candidate.circuit.canonical_form(),
                candidate,
            )
            for candidate in alive
            if math.isfinite(candidate.score(criterion))
        ],
        n_refine,
    )


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


def run_screen(
    task: ScreenTask,
    spectrum: Spectrum,
    *,
    weighting: Weighting,
    seed: int,
    budget: ScreenBudget = SCREEN_BUDGET,
) -> float:
    """One tier-1 screen, for a worker that was handed the task from somewhere else.

    The desktop's pool reaches :func:`_screen_one` through :func:`_screen_all`; a browser's
    pool has no such path, because the plan is driven from another worker entirely. This is
    that entry point, and it exists so the browser runs the same screening budget, the same
    early-abandon threshold and the same "a hopeless topology scores infinity rather than
    raising" rule as the command line, instead of a second version assembled in the bridge.
    """
    return _screen_one(task, spectrum, weighting=weighting, seed=seed, budget=budget)


def run_refit(task: RefitTask, spectrum: Spectrum, *, weighting: Weighting) -> FitResult | None:
    """One tier-2 refit, for the same kind of worker as :func:`run_screen`.

    Returns None when the topology cannot be fitted at all, which :func:`refit_plan` treats as
    an answer rather than an error.
    """
    return _full_fit(task.text, spectrum, weighting, task.restarts, task.seed)


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


class RefitBatch(NamedTuple):
    """One batch of tier-2 work, together with what the batches before it produced.

    ``done`` is here so that a driver can show a partial Pareto front while the rest is still
    running without rebuilding a :class:`Candidate` for itself -- which would mean a second
    copy of the decode and of the rule that a topology which cannot be fitted is dropped
    rather than reported. It is also what a cancelled run has to report from.
    """

    tasks: list[RefitTask]
    done: list[Candidate]
    """Candidates finished so far, best AICc first. Empty in the first batch."""
    total: int
    """Shortlist size, so a driver can say how far through the tier it is."""


def refit_plan(
    scored: Sequence[tuple[float, str]],
    *,
    n_refine: int,
    n_data: int,
    restarts: int,
    seed: int,
    chunk: int | None = None,
    criterion: Criterion = DEFAULT_CRITERION,
) -> Generator[RefitBatch, Sequence[RefitOutcome], list[Candidate]]:
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
    texts = _shortlist(scored, n_refine, n_data, criterion)
    results: list[FitResult] = []
    size = max(len(texts) if chunk is None else chunk, 1)
    for start in range(0, len(texts), size):
        window = texts[start : start + size]
        outcomes = yield RefitBatch(
            [RefitTask(text, restarts, seed) for text in window],
            _ranked(results, criterion),
            len(texts),
        )
        if len(outcomes) != len(window):
            raise ValueError(
                f"refit_plan was sent {len(outcomes)} outcomes for {len(window)} tasks"
            )
        results.extend(r for r in map(_as_fit_result, outcomes) if r is not None)
    return _ranked(results, criterion)


def _ranked(
    results: Sequence[FitResult], criterion: Criterion = DEFAULT_CRITERION
) -> list[Candidate]:
    """Fitted topologies as candidates, best first under ``criterion``."""
    out = [Candidate(r.circuit, r, 0) for r in results]
    out.sort(key=lambda c: c.score(criterion))
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
    criterion: Criterion = DEFAULT_CRITERION,
) -> list[Candidate]:
    """Tier 2: refit the shortlist at full budget. Only these numbers are ever reported.

    A thin driver over :func:`refit_plan`, exactly as :func:`_screen_parallel` is over
    :func:`screen_plan`: it runs the fits and holds no opinion about which ones to run.
    """
    plan = refit_plan(
        scored,
        n_refine=n_refine,
        n_data=2 * spectrum.n,
        restarts=restarts,
        seed=seed,
        criterion=criterion,
    )
    try:
        batch = next(plan)
        while True:
            outcomes: list[RefitOutcome]
            tasks = batch.tasks
            if executor is not None and len(tasks) > 1:
                outcomes = list(
                    executor.map(_refit_worker, [(t.text, t.restarts, t.seed) for t in tasks])
                )
            else:
                outcomes = [
                    _full_fit(t.text, spectrum, weighting, t.restarts, t.seed) for t in tasks
                ]
            batch = plan.send(outcomes)
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


def _grow_all(
    scored: Sequence[tuple[float, str]],
    spectrum: Spectrum,
    *,
    pool: tuple[str, ...],
    start_size: int,
    max_elements: int,
    width: int,
    weighting: Weighting,
    seed: int,
    executor: multiprocessing.pool.Pool | None,
    on_progress: Callable[[int, int, str | None], None] | None,
    time_limit: float | None,
    started: float,
    criterion: Criterion,
    budget: ScreenBudget = SCREEN_BUDGET,
) -> list[tuple[float, str]]:
    """Drive :func:`growth_plan`, screening each level's children.

    The counterpart of :func:`_screen_all` for the growth stage, and deliberately the same shape:
    the generator decides *what* to screen and this decides *how*, so a browser fanning batches
    across Web Workers can reuse the first half without reimplementing the second.
    """
    plan = growth_plan(
        scored,
        pool=pool,
        start_size=start_size,
        max_elements=max_elements,
        n_data=2 * spectrum.n,
        width=width,
        criterion=criterion,
    )
    produced: list[tuple[float, str]] = []
    try:
        tasks = next(plan)
        while True:
            if executor is not None and len(tasks) > 1:
                costs = list(
                    executor.map(
                        _screen_worker,
                        [
                            (
                                t.text,
                                seed,
                                t.abandon_above,
                                budget.popsize,
                                budget.maxiter,
                                budget.restarts,
                            )
                            for t in tasks
                        ],
                        chunksize=max(1, min(WORKER_CHUNK, len(tasks) // 8 or 1)),
                    )
                )
            else:
                costs = [
                    _screen_one(task, spectrum, weighting=weighting, seed=seed, budget=budget)
                    for task in tasks
                ]
            produced.extend(zip(costs, (t.text for t in tasks), strict=True))
            if on_progress is not None:
                on_progress(len(produced), len(produced), None)
            # A growth level is all-or-nothing, and the check is deliberately *after* the batch
            # rather than inside it: half a level is not "every one-element extension of the
            # best W", so a truncated level would leave :meth:`DiscoveryResult.completeness`
            # saying something false about the size it reached. ``growth_plan`` yields exactly
            # one batch per level, which is what makes that atomic.
            #
            # The price is that ``time_limit`` can be overshot by one level, and a level is
            # hundreds of screens. That is the right way round -- a run that goes over budget is
            # visible in the elapsed time, and a coverage sentence that over-claims is not.
            if time_limit is not None and time.perf_counter() - started > time_limit:
                return produced
            tasks = plan.send(costs)
    except StopIteration:
        return produced


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
            restarts=budget.restarts,
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


# -- Growth above the exhaustive limit -------------------------------------------------------


def growth_plan(
    scored: Sequence[tuple[float, str]],
    *,
    pool: tuple[str, ...],
    start_size: int,
    max_elements: int,
    n_data: int,
    width: int = GROWTH_WIDTH,
    criterion: Criterion = DEFAULT_CRITERION,
) -> Generator[list[ScreenTask], Sequence[float], list[tuple[float, str]]]:
    """Beam growth past the exhaustive limit, with the *running* of it left to the caller.

    Above :data:`DEFAULT_EXHAUSTIVE_LIMIT` the space stops being enumerable -- 21,057 topologies
    at six elements for the ``R,C,L,CPE`` pool against 2,976 at five -- and the genetic search
    that used to cover it is measured at 1/6 where the exhaustive stage is 30/30. This is the
    third option, and it exists because the exhaustive stage has *already produced the thing a
    growth search needs*: a complete, screened, ranked level. `_exhaustive` enumerates level 5
    and then throws that ranking away.

    So: take the best ``width`` topologies of the completed level, generate **every** one-element
    extension of each (:func:`~autocircuit.core.enumerate._insertions`, which includes the
    subset-grouping moves a plain attachment cannot reach), screen them, keep the best ``width``,
    and repeat up to ``max_elements``.

    [measured, docs/TOPOLOGY_6PLUS_PLAN.md section 5.5] The equivalent arm in
    ``benchmarks/screening_round/arms.py`` (``beams5w4``) reaches the six-element truth's
    equivalence class **three screening fits after the five-element enumeration ends** on the
    frozen ``R,C,L`` arena at ``n <= 7`` -- 452 charged fits against the 449 that level costs --
    where the genetic arms that beat the incumbent need 256-451 fits of their own and only
    stochastically. That is a measurement of the *strategy* against a frozen table and on one
    truth; whether this implementation changes what the **report** says, across shapes and
    sizes, is ``benchmarks/six_plus/recovery.py`` and is why :data:`GROWTH_DEFAULT` is zero.

    **What this may and may not claim.** It is *not* complete at six elements and the report must
    not imply it is: :attr:`DiscoveryResult.complete_up_to` stays at the exhaustive limit and
    :attr:`DiscoveryResult.grown_to` carries the narrower, true sentence -- every topology up to
    the exhaustive limit, and above it every one-element extension of the best ``width`` of them.
    That is the same obligation ``docs/PARTIAL_TOPOLOGY_PLAN.md`` section 3 places on a skeleton,
    and it is met the same way: in the coverage line, not in a footnote.

    Yields batches of :class:`ScreenTask` and expects their costs back through ``send``, exactly
    as :func:`screen_plan` does and for the same reason -- there is one implementation of the
    decisions, whoever runs the fits, in-process or across a browser's Web Workers.

    Args:
        scored: The tier-1 ``(cost, circuit)`` pairs the exhaustive stage produced. Used both to
            seed the beam and to avoid re-screening anything already seen.
        pool: Element codes the added elements may use.
        start_size: Element count of the completed level to grow from.
        max_elements: Largest element count to grow to.
        n_data: ``2 * spectrum.n``, for the screening score.
        width: How many topologies of each level are extended.
        criterion: Model-selection rule the per-level ranking uses.

    Returns:
        The ``(cost, circuit)`` pairs for every topology this stage screened. The caller merges
        them with the exhaustive stage's own before shortlisting, so both tiers see one list.
    """
    seen: dict[str, float] = {}
    sizes: dict[str, int] = {}
    for cost, text in scored:
        seen[text] = min(cost, seen.get(text, math.inf))

    def size_of(text: str) -> int:
        if text not in sizes:
            sizes[text] = count_elements(Circuit.parse(text).root)
        return sizes[text]

    def rank(items: Iterable[tuple[float, str]]) -> list[tuple[float, str]]:
        return sorted(
            items,
            key=lambda pair: _screening_score(
                pair[0], len(Circuit.parse(pair[1]).param_names), n_data, criterion
            ),
        )

    level = rank(
        (cost, text) for cost, text in scored if math.isfinite(cost) and size_of(text) == start_size
    )[:width]

    produced: list[tuple[float, str]] = []
    best_by_complexity: dict[float, float] = {}
    for cost, text in scored:
        complexity = Circuit.parse(text).complexity
        if cost < best_by_complexity.get(complexity, math.inf):
            best_by_complexity[complexity] = float(cost)

    for size in range(start_size + 1, max_elements + 1):
        fresh: list[str] = []
        for _cost, parent in level:
            for child in _insertions(Circuit.parse(parent).root, pool):
                try:
                    circuit = Circuit(simplify(child))
                except CircuitError:
                    continue
                # `simplify` can collapse an insertion back into its parent (two series
                # resistors become one), so the level is checked rather than assumed.
                if count_elements(circuit.root) != size or not is_plausible(circuit):
                    continue
                text = circuit.to_string()
                if text in seen:
                    continue
                seen[text] = math.inf
                sizes[text] = size
                fresh.append(text)
        if not fresh:
            break

        costs = yield [
            ScreenTask(text, _abandon_at(best_by_complexity, Circuit.parse(text).complexity))
            for text in fresh
        ]
        for cost, text in zip(costs, fresh, strict=True):
            seen[text] = float(cost)
            produced.append((float(cost), text))
            complexity = Circuit.parse(text).complexity
            if cost < best_by_complexity.get(complexity, math.inf):
                best_by_complexity[complexity] = float(cost)

        level = rank((c, t) for c, t in produced if size_of(t) == size and math.isfinite(c))[:width]
        if not level:
            break

    return produced


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


def _screen_worker(task: tuple[str, int, float, int, int, int]) -> float:
    """Screen one topology in a worker process; the task carries only strings and numbers."""
    text, seed, abandon, popsize, maxiter, restarts = task
    return _screen_one(
        ScreenTask(text, abandon),
        _WORKER["spectrum"],
        weighting=_WORKER["weighting"],
        seed=seed,
        budget=ScreenBudget(popsize, maxiter, restarts),
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
                        (
                            task.text,
                            seed,
                            task.abandon_above,
                            budget.popsize,
                            budget.maxiter,
                            budget.restarts,
                        )
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


def _unique_best(
    candidates: Sequence[Candidate], criterion: Criterion = DEFAULT_CRITERION
) -> list[Candidate]:
    """Keep the best-scoring instance of each distinct topology."""
    best: dict[str, Candidate] = {}
    for candidate in candidates:
        key = candidate.circuit.canonical_form()
        if key not in best or candidate.score(criterion) < best[key].score(criterion):
            best[key] = candidate
    return list(best.values())


def _breeding_pool(
    alive: Sequence[Candidate],
    extra: int = BREEDING_EXTRA,
    criterion: Criterion = DEFAULT_CRITERION,
) -> list[Candidate]:
    """The subset of the archive that may become a parent: the Pareto front.

    `_evolve` breeds from its *entire history*, and that is the mechanism behind
    docs/EVOLVE_SEARCH_PLAN.md section 1.2: `_tournament` draws 3 of N with N growing every
    generation, so the best-known candidate's chance of entering a tournament falls **8.2x over
    twelve generations**. The search does not lose the answer, it stops being able to breed from
    it.

    Bounding the set fixes N. [measured, docs/SEARCH_ALGORITHM_SCREENING.md section 5] On the
    frozen landscape of the three-block Maxwell-Wagner reference, over 120 seeds counted in fits
    rather than seconds, bounding it at all reaches the truth's equivalence class in **120/120
    [0.97,1.00] at a median of 308 fits**, against the unbounded incumbent's **87/120 [0.64,0.80]
    at 451**. Three arms cleared that bar and what they share is not their operators but that all
    three bound the set they breed from; this is the smallest of the three.

    **How tightly to bound it is `BREEDING_EXTRA`, and the answer is not a width.** The ladder in
    docs/EVOLVE_SEARCH_PLAN.md section 3.4.3 ran the extra members from forty down to none and
    the last two rungs are the same arm on every seed, so what ships is the front by itself. At
    an unsaturated budget that is 65/120 against the front-plus-forty rule's 7/120; ``extra``
    survives only so the benchmarks can re-walk the ladder.

    Two things it deliberately does not do:

    * **It does not truncate the archive.** The screening-round arm assigns its bounded pool back
      over the history, because a lookup-table walk has no report to produce. Here the full
      archive is what `_shortlist_candidates` selects tier 2 from and what `n_evaluated` counts,
      and throwing it away would narrow the report to pay for the search. [measured] Keeping it
      costs nothing: the arm was re-run against *this* rule and returned the same 120/120 at the
      same median of 308, so the two formulations search alike and only this one can still
      report from everything it fitted.
    * **It does not scale the tournament.** With ``len(pool)`` no longer growing, a fixed
      tournament of 3 is already a fixed pressure, and section 3.4's `TOURNAMENT_FRACTION` has
      no measurement behind it. One change, one measurement.
    """
    front = pareto_front(alive, criterion)
    if extra <= 0:
        # The shipped rule, and worth short-circuiting rather than letting the slice below
        # return nothing: the ranking calls `canonical_form()` on the whole archive, which grows
        # every generation, to choose members it would then discard.
        return front
    on_front = {id(candidate) for candidate in front}
    ranked = sorted(
        alive,
        key=lambda c: (
            c.score(criterion) if math.isfinite(c.score(criterion)) else math.inf,
            # Ties are the normal case rather than a rarity -- an exact reparameterisation is a
            # tie -- so which of two equal candidates gets to breed must not depend on the order
            # the archive happened to be built in (docs/EVOLVE_SEARCH_PLAN.md section 3.2.1).
            c.circuit.canonical_form(),
        ),
    )
    return front + [c for c in ranked[:extra] if id(c) not in on_front]


def _complexity_frequencies(archive: Sequence[Candidate]) -> dict[float, float]:
    """What fraction of the archive sits at each complexity level.

    The input is the whole archive rather than the breeding pool on purpose. The pool is the
    Pareto front (:data:`BREEDING_EXTRA`), which holds about *one* member per complexity by
    construction, so a crowding count taken over it is 1 everywhere and says nothing. What is
    unevenly populated is the history: where the search has actually spent its fits.
    """
    counts: dict[float, float] = {}
    for candidate in archive:
        counts[candidate.complexity] = counts.get(candidate.complexity, 0.0) + 1.0
    total = float(len(archive)) or 1.0
    return {key: value / total for key, value in counts.items()}


def _next_generation(
    alive: list[Candidate],
    rng: np.random.Generator,
    pool: tuple[str, ...],
    max_elements: int,
    population: int,
    criterion: Criterion = DEFAULT_CRITERION,
    *,
    frequencies: Mapping[float, float] | None = None,
    parsimony: float = PARSIMONY_SCALING,
    weights: Sequence[float] = MUTATION_WEIGHTS,
) -> list[_Offspring]:
    """Elitism over the Pareto front, then tournament selection with mutation/crossover.

    Breeding from the Pareto front rather than from the score ranking alone keeps simple
    topologies in play. Otherwise the population converges on whatever fits best regardless
    of size, and the trade-off curve -- the actual deliverable -- collapses to one point.

    Each child is returned **with the parent it was bred from**, which is what lets the
    evaluator start its fit from that parent's values rather than from nothing
    (:func:`_inherited_values`). For a crossover the parent named is the one whose tree was
    grafted onto, not the donor of the subtree: the child is a modification of that tree, so
    it is the one most of the inherited values will still belong to.
    """
    front = pareto_front(alive, criterion)
    elite = front[: max(2, population // 6)]
    trees: list[_Offspring] = [(candidate.circuit.root, candidate) for candidate in elite]

    while len(trees) < population:
        parent = _tournament(
            alive, rng, criterion=criterion, frequencies=frequencies, parsimony=parsimony
        )
        if rng.random() < 0.3 and len(alive) > 1:
            other = _tournament(
                alive, rng, criterion=criterion, frequencies=frequencies, parsimony=parsimony
            )
            child = crossover(parent.circuit.root, other.circuit.root, rng)
        else:
            child = parent.circuit.root
        child = mutate(child, rng, pool, max_elements, weights=weights)
        if count_elements(child) <= max_elements:
            trees.append((child, parent))
    return trees


def _tournament(
    alive: list[Candidate],
    rng: np.random.Generator,
    size: int = 3,
    criterion: Criterion = DEFAULT_CRITERION,
    *,
    frequencies: Mapping[float, float] | None = None,
    parsimony: float = 0.0,
) -> Candidate:
    """Draw three of the pool and keep the best, optionally discounted for crowding.

    The crowding term is PySR's adaptive parsimony, and it lives **here and nowhere else**.
    :meth:`Candidate.score` is what ranks the report under the criterion the user chose
    (:attr:`DiscoveryResult.criterion`); a breeding heuristic that reached it would change the
    published ranking for a reason the report cannot state. So the adjusted value is computed
    inside this call, used to pick a parent, and discarded.

    PySR multiplies the loss by ``exp(scaling * frequency)``. That is wrong for a criterion
    that can be negative -- AICc usually is here, and multiplying a negative loss by a number
    above one *rewards* the crowded level. The term is therefore additive, in units of the
    criterion, which is also the unit a scaling constant can be reasoned about in: a penalty of
    1 AICc is a penalty of one parameter's worth of evidence.
    """
    picks = rng.integers(0, len(alive), size=min(size, len(alive)))
    if not parsimony or frequencies is None:
        return min((alive[int(i)] for i in picks), key=lambda c: c.score(criterion))
    return min(
        (alive[int(i)] for i in picks),
        key=lambda c: c.score(criterion) + parsimony * frequencies.get(c.complexity, 0.0),
    )


def _refine(
    candidates: Sequence[Candidate],
    spectrum: Spectrum,
    weighting: Weighting,
    restarts: int,
    seed: int,
    deadline: float | None = None,
    criterion: Criterion = DEFAULT_CRITERION,
    executor: multiprocessing.pool.Pool | None = None,
    workers: int = 1,
) -> tuple[list[Candidate], int]:
    """Refit the shortlist at full budget, since the search used a reduced one.

    Returns the refitted candidates and **how many of the shortlist were attempted**, which is
    not the same number: a topology that cannot be fitted at all is dropped rather than
    reported, and that is an answer rather than an interruption. Only the second number can tell
    a caller whether the tier finished.

    ``deadline`` bounds this tier, which it has to now that the shortlist is a per-size quota
    rather than a fixed eight: [measured] the refit of a seven-size archive is 35-70 full fits,
    and a run given a 5 s budget spent 222 s in this function alone. See :data:`REFIT_HEADROOM`
    for why the deadline is not simply ``time_limit``. What a stopped tier may then claim
    already has an implementation -- :attr:`DiscoveryResult.refit_progress` and
    :meth:`DiscoveryResult._with_refit_note` -- so this reports into that rather than inventing
    a second way to say it.

    A tier that can stop early owes an order to stop *in*, which is :func:`_refit_order`: the
    shortlist arrives grouped by element count and is walked best-of-each-size first. Without
    it a deadline drops whichever sizes the archive happened to mention last, first-ranked
    candidate included.

    ``executor`` parallelises this tier exactly as :func:`_refit_shortlist` already does for the
    exhaustive stage's tier 2 -- unlike the generation loop in :meth:`_Evaluator.evaluate_all`,
    each candidate here is an independent full-budget fit with nothing cached between them, so
    there is no staleness to accept. The only thing that moves is the deadline check's
    granularity, from one candidate to one batch of ``workers``, the same trade
    :func:`_grow_all` already makes per level.
    """
    out: list[Candidate] = []
    attempted = 0
    ordered = _refit_order(candidates, criterion)
    step = max(1, workers) if executor is not None else 1
    i = 0
    while i < len(ordered):
        # The first batch is always attempted: a report with no rows in it cannot be read at
        # all, and one full-budget fit is the least that can honestly be published. Every batch
        # after it answers to the clock.
        if attempted and deadline is not None and time.perf_counter() > deadline:
            break
        batch = ordered[i : i + step]
        i += step
        attempted += len(batch)
        if executor is not None and len(batch) > 1:
            outcomes: list[FitResult | None] = [
                None if wire is None else FitResult.from_wire(wire)
                for wire in executor.map(
                    _refit_worker,
                    [(c.circuit.to_string(), restarts, seed) for c in batch],
                )
            ]
        else:
            outcomes = [
                _full_fit(c.circuit.to_string(), spectrum, weighting, restarts, seed) for c in batch
            ]
        for candidate, result in zip(batch, outcomes, strict=True):
            if result is not None:
                out.append(Candidate(candidate.circuit, result, candidate.generation))
    return out, attempted
