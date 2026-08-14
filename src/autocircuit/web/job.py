"""One in-progress topology search, driven a batch at a time from JavaScript.

:mod:`autocircuit.web.bridge` is stateless because a spectrum should not have to live in a
worker under a handle. A *search* is the exception, and it has to be: it is a generator that
holds the enumeration, the abandon thresholds and the shortlist quota between batches, and it
runs for minutes. So the state lives here, in the orchestrator worker, and the pool workers
that do the actual fitting stay stateless -- they are handed a topology and a spectrum and
answer with a number.

What this module deliberately does **not** contain is any decision. Which topologies exist,
where a level stops being affordable, what may then be claimed, which candidates earn a
full-budget refit, and what each screen's early-abandon threshold is all come from
:mod:`autocircuit.core.discover` -- from :func:`~autocircuit.core.discover.enumerate_candidates`,
:func:`~autocircuit.core.discover.screen_plan` and
:func:`~autocircuit.core.discover.refit_plan`, the same three the command line drives. This is
a fourth driver of them, not a second search.

Two consequences are worth stating because they are what a stopped run reports from:

* **A screen that stopped part-way still covers whole element counts.** That is
  :meth:`~autocircuit.core.discover.Enumeration.coverage`, and it is the same arithmetic the
  CLI does when a ``time_limit`` cuts a run short.
* **A refit that stopped part-way does not.** The shortlist is not ordered by size, so what
  came back is a partial ranking, and :attr:`DiscoveryResult.refit_progress` is what makes the
  report say so instead of looking finished.
"""

from __future__ import annotations

import itertools
import math
import time
from collections.abc import Generator, Sequence
from typing import Any, cast

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import (
    REFINE_DEFAULT,
    WORKER_CHUNK,
    Candidate,
    DiscoveryResult,
    Enumeration,
    RefitBatch,
    RefitOutcome,
    ScreenTask,
    enumerate_candidates,
    exhaustive_limit_for,
    pareto_front,
    refit_plan,
    screen_plan,
)
from autocircuit.core.elements import DEFAULT_POOL, REGISTRY
from autocircuit.core.enumerate import DEFAULT_DEGENERACY_BUDGET
from autocircuit.core.fit import Weighting
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.wire import encode_float

#: Screens handed out per round trip. The same figure the desktop pool uses, because the batch
#: size is the one thing a driver chooses that touches the search at all: within a batch the
#: abandon threshold is one batch stale, which can waste time but cannot change a result. The
#: browser's progress bar does not need this smaller -- the driver fans a batch across its
#: workers task by task, so it counts finished tasks without asking Python anything.
SCREEN_CHUNK = WORKER_CHUNK

#: Refits handed out per round trip. Nothing here depends on an earlier batch, so this only
#: trades scheduling granularity against round trips -- and it is how often the partial Pareto
#: front can be redrawn. One batch would also leave workers idle at the tail, since refit times
#: vary by an order of magnitude across topologies.
REFIT_CHUNK = 8

_COUNTER = itertools.count(1)

#: The two plans as this module holds them: yielded work out, results in, the report's raw
#: material at the end.
type ScreenGenerator = Generator[list[ScreenTask], Sequence[float], list[tuple[float, str]]]
type RefitGenerator = Generator[RefitBatch, Sequence[RefitOutcome], list[Candidate]]


class DiscoveryJob:
    """An exhaustive search, in the middle of being run by someone else.

    The caller alternates ``next_*`` and the matching ``submit_*`` until the stage is done.
    Nothing is fitted here; every task goes out to a worker and comes back as a number or a
    wire-format :class:`~autocircuit.core.fit.FitResult`.
    """

    def __init__(
        self,
        spectrum: Spectrum,
        *,
        pool: tuple[str, ...] = tuple(DEFAULT_POOL),
        skeleton: str | None = None,
        exhaustive_limit: int | None = None,
        exhaustive_min: int = 1,
        max_candidates: int = 20_000,
        feasibility_filter: bool = True,
        feasibility_budget: int = DEFAULT_DEGENERACY_BUDGET,
        weighting: Weighting = "modulus",
        seed: int = 0,
        final_restarts: int = 5,
        n_refine: int | None = None,
        screen_chunk: int = SCREEN_CHUNK,
        refit_chunk: int = REFIT_CHUNK,
    ) -> None:
        unknown = [code for code in pool if code not in REGISTRY]
        if unknown:
            raise ValueError(f"unknown element codes in pool: {', '.join(unknown)}")
        self.id = f"job-{next(_COUNTER)}"
        self.spectrum = spectrum
        self.pool = tuple(pool)
        self.weighting: Weighting = weighting
        self.seed = seed
        self.final_restarts = final_restarts
        self.n_refine = REFINE_DEFAULT["exhaustive"] if n_refine is None else n_refine
        self.frame = None if skeleton is None else Circuit.parse(skeleton)
        self.floor = max(1, exhaustive_min)
        self.limit = exhaustive_limit_for(
            None if self.frame is None else len(self.frame.leaves), exhaustive_limit
        )
        self.enumeration: Enumeration = enumerate_candidates(
            spectrum,
            pool=self.pool,
            skeleton=None if self.frame is None else self.frame.root,
            limit=self.limit,
            floor=self.floor,
            max_candidates=max_candidates,
            feasibility_filter=feasibility_filter,
            feasibility_budget=feasibility_budget,
        )
        self.started = time.perf_counter()
        self.stopped = False
        self.screen_chunk = max(1, screen_chunk)
        self.refit_chunk = max(1, refit_chunk)

        self._screen: ScreenGenerator = screen_plan(
            self.enumeration.texts, chunk=self.screen_chunk
        )
        self._screen_open = True
        # "Open" is about whether the generator can still be driven, which cancelling also
        # ends; "done" is about whether it ran out of work, which is what the report's claims
        # rest on. Collapsing the two is how a cancelled run comes to look finished.
        self._screen_done = False
        self._refit_done = False
        self._issued: list[str] | None = None
        self._costs: list[float] | None = None
        self._scored: list[tuple[float, str]] = []
        self._best: tuple[float, str] | None = None
        self._refit: RefitGenerator | None = None
        self._refit_open = False
        self._batch: RefitBatch | None = None
        self._issued_refits = 0
        self._outcomes: list[RefitOutcome] | None = None
        self._candidates: list[Candidate] = []
        self._shortlisted = 0

    # -- Tier 1 ------------------------------------------------------------------------------

    def next_screen(self) -> list[tuple[str, float]] | None:
        """The next batch of ``(circuit, abandon above)``, or None when the screen is done."""
        if self.stopped or not self._screen_open:
            return None
        try:
            if self._issued is None:
                tasks = next(self._screen)
            elif self._costs is None:
                raise ValueError("the previous screening batch has not been submitted")
            else:
                costs, self._costs = self._costs, None
                tasks = self._screen.send(costs)
        except StopIteration as done:
            self._screen_open = False
            self._screen_done = True
            self._scored = list(done.value)
            return None
        self._issued = [task.text for task in tasks]
        return [(task.text, task.abandon_above) for task in tasks]

    def submit_screen(self, costs: list[float]) -> None:
        """Hand back one cost per task in the batch just issued."""
        if self._issued is None:
            raise ValueError("no screening batch is outstanding")
        if len(costs) != len(self._issued):
            raise ValueError(f"{len(costs)} costs for {len(self._issued)} screening tasks")
        self._costs = [float(cost) for cost in costs]
        for cost, text in zip(self._costs, self._issued, strict=True):
            self._scored.append((cost, text))
            if self._best is None or cost < self._best[0]:
                self._best = (cost, text)

    @property
    def screened(self) -> int:
        """Topologies screened so far. Also the number the coverage claim is derived from."""
        return len(self._scored)

    @property
    def best_screened(self) -> str | None:
        """Best-scoring topology so far, for the progress line and nothing else.

        A screening cost is not a publishable number -- only the tier-2 refit produces those --
        so this is the circuit text without its score, which is what ``--progress`` shows on
        the command line.
        """
        return None if self._best is None else self._best[1]

    # -- Tier 2 ------------------------------------------------------------------------------

    def next_refit(self) -> list[tuple[str, int, int]] | None:
        """The next batch of ``(circuit, restarts, seed)``, or None when the tier is done.

        Opening the plan is free -- it computes the shortlist and yields, without fitting
        anything -- which is why :meth:`report` can open it purely to learn how long the
        shortlist was for a run that never got to fit any of it.
        """
        if self.stopped:
            return None
        if self._refit is None:
            self._open_refit()
        if not self._refit_open or self._refit is None:
            return None
        if self._batch is None:
            if self._outcomes is None:
                raise ValueError("the previous refit batch has not been submitted")
            try:
                self._batch = self._refit.send(self._outcomes)
            except StopIteration as done:
                self._refit_open = False
                self._refit_done = True
                self._candidates = list(done.value)
                return None
            self._outcomes = None
            self._absorb(self._batch)
        batch, self._batch = self._batch, None
        self._issued_refits = len(batch.tasks)
        return [(task.text, task.restarts, task.seed) for task in batch.tasks]

    def submit_refit(self, outcomes: list[RefitOutcome]) -> None:
        """Hand back one wire-format fit, or None, per task in the batch just issued."""
        if len(outcomes) != self._issued_refits:
            raise ValueError(f"{len(outcomes)} outcomes for {self._issued_refits} refit tasks")
        self._outcomes = list(outcomes)

    def _open_refit(self) -> None:
        """Start the tier-2 plan on whatever the screen produced, cut short or not.

        A screen that was stopped part-way leaves a shortlist of the topologies it reached,
        which is exactly what a time-limited run on the command line refits.
        """
        self._refit = refit_plan(
            self._scored,
            n_refine=self.n_refine,
            n_data=2 * self.spectrum.n,
            restarts=self.final_restarts,
            seed=self.seed,
            chunk=self.refit_chunk,
        )
        try:
            self._batch = next(self._refit)
        except StopIteration as done:
            self._refit_open = False
            self._refit_done = True
            self._candidates = list(done.value)
            return
        self._refit_open = True
        self._absorb(self._batch)

    def _absorb(self, batch: RefitBatch) -> None:
        """Take the candidates a batch reports as finished, and the shortlist's size."""
        self._candidates = list(batch.done)
        self._shortlisted = batch.total

    @property
    def refitted(self) -> int:
        return len(self._candidates)

    @property
    def shortlisted(self) -> int:
        return self._shortlisted

    @property
    def front(self) -> list[Candidate]:
        """The Pareto front of what has been refitted so far."""
        return pareto_front(self._candidates)

    # -- Finishing ---------------------------------------------------------------------------

    def cancel(self) -> None:
        """Stop the search here and release the generators holding its state.

        The tasks already dispatched are the caller's problem -- a Web Worker in the middle of
        a differential evolution stops when it is terminated and not before -- but nothing
        further is handed out, and :meth:`report` describes what was actually reached.
        """
        self.stopped = True
        if self._screen_open:
            self._screen.close()
            self._screen_open = False
        if self._refit_open and self._refit is not None:
            self._refit.close()
            self._refit_open = False

    @property
    def finished(self) -> bool:
        """True once both tiers ran out of work of their own accord.

        Not the same as "no longer running": cancelling also closes both generators, and a
        report that could not tell the difference would present a stopped search as a
        finished one.
        """
        return self._screen_done and self._refit_done

    def report(self) -> DiscoveryResult:
        """What the run is entitled to claim, whether it finished or was stopped.

        A stopped run is not a failed one: the coverage it reached is a real result, and the
        candidates it refitted are real fits. What it may not do is look complete, which is
        what :attr:`DiscoveryResult.refit_progress` prevents.
        """
        if self._refit is None:
            # Nothing was refitted, not even opened -- but the shortlist size is knowable
            # without fitting, and "0 of 37" is a far more useful thing to report than "0".
            self._open_refit()
        candidates = sorted(self._candidates, key=lambda c: c.aicc)
        return DiscoveryResult(
            candidates=candidates,
            pareto=pareto_front(candidates),
            n_evaluated=len(self._scored),
            generations=0,
            elapsed_s=time.perf_counter() - self.started,
            pool=self.pool,
            mode="exhaustive",
            complete_up_to=self.enumeration.coverage(len(self._scored)),
            skeleton=None if self.frame is None else self.frame.to_string(),
            refit_progress=(
                None if self.finished else (len(candidates), self._shortlisted)
            ),
        )


_CURRENT: DiscoveryJob | None = None


def install(job: DiscoveryJob) -> DiscoveryJob:
    """Make ``job`` the worker's search, cancelling whatever it was running before.

    One at a time, because there is one screening pool and a second search would be competing
    with the first for it. Starting a new search is therefore how a user abandons the old one,
    and the old one is stopped rather than left holding its generators.
    """
    global _CURRENT
    if _CURRENT is not None and _CURRENT is not job:
        _CURRENT.cancel()
    _CURRENT = job
    return job


def current(job_id: str) -> DiscoveryJob:
    """The running search, if it is the one the caller thinks it is.

    A request naming a job that has been replaced is answered with an error rather than
    silently applied to the new one -- costs from a search the user abandoned would otherwise
    be fed into the plan of the search they started instead.
    """
    if _CURRENT is None:
        raise ValueError("no discovery job is running")
    if _CURRENT.id != job_id:
        raise ValueError(f"job {job_id} is no longer running; {_CURRENT.id} is")
    return _CURRENT


def candidate_row(candidate: Candidate) -> dict[str, Any]:
    """One line of a results table: what it is, how well it fits, and what it cannot pin down.

    ``n_unresolved`` travels beside the scores rather than behind a details view because a
    lower AICc bought with a parameter the data cannot resolve is the trap this whole project
    is built to avoid presenting as a win.
    """
    circuit = candidate.circuit
    return {
        "circuit": circuit.to_string(),
        "canonical": circuit.canonical_form(),
        "n_elements": len(circuit.leaves),
        "n_params": circuit.n_params,
        "complexity": encode_float(candidate.complexity),
        "aicc": encode_float(candidate.aicc),
        "chi2_reduced": encode_float(candidate.result.chi2_reduced),
        "n_unresolved": candidate.n_unresolved,
        "unresolved": [
            name
            for name, bad in zip(circuit.param_names, candidate.unresolved, strict=True)
            if bad
        ],
    }


def plan_summary(job: DiscoveryJob) -> dict[str, Any]:
    """What the search is about to do, before a single topology is fitted.

    The per-level counts are here so the user can see the size of what they asked for -- a
    limit one higher can be forty times the work -- and lower the limit before waiting rather
    than after.
    """
    levels: list[dict[str, int]] = []
    previous = 0
    for n, end in job.enumeration.boundaries:
        levels.append({"n_elements": n, "candidates": end - previous})
        previous = end
    return {
        "job": job.id,
        "candidates": len(job.enumeration.texts),
        "levels": levels,
        "limit": job.limit,
        "floor": job.floor,
        "pool": list(job.pool),
        "skeleton": None if job.frame is None else job.frame.to_string(),
        "mode": "exhaustive",
        "screen_chunk": job.screen_chunk,
        "refit_chunk": job.refit_chunk,
    }


def report_payload(job: DiscoveryJob) -> dict[str, Any]:
    """The finished (or stopped) search as JSON.

    ``completeness`` and ``summary`` are rendered verbatim by the browser rather than
    paraphrased, for the same reason the Lin-KK verdict is: the sentence that says what the
    search is allowed to claim is the part a second implementation would get subtly wrong.
    """
    result = job.report()
    return {
        "n_evaluated": result.n_evaluated,
        "complete_up_to": result.complete_up_to,
        "elapsed_s": encode_float(result.elapsed_s),
        "pool": list(result.pool),
        "mode": result.mode,
        "skeleton": result.skeleton,
        "refit_progress": (
            None if result.refit_progress is None else list(result.refit_progress)
        ),
        "stopped": job.stopped,
        "completeness": result.completeness(),
        "summary": result.summary(job.spectrum),
        "candidates": [candidate_row(c) for c in result.candidates],
        "pareto": [candidate_row(c) for c in result.pareto],
        "recommended": (
            None if result.recommended is None else result.recommended.circuit.to_string()
        ),
        "unresolved_everywhere": result.unresolved_everywhere,
    }


def to_wire_cost(cost: float) -> float | None:
    """Infinity travels as null: JSON has no infinity and JavaScript rejects the Python token.

    A screening cost is one-sided -- there is no such thing as a negatively infinite one -- so
    null is unambiguous here, unlike in a fit's standard errors where both an infinity and a
    NaN are meaningful and travel as string sentinels instead (``core/wire.py``).
    """
    return None if math.isinf(cost) else float(cost)


def from_wire_cost(cost: float | None) -> float:
    """The other half of :func:`to_wire_cost`. Both directions are routine, not defensive:
    an abandon threshold of infinity means "nothing to compare against yet", and a cost of
    infinity means "this topology cannot be fitted at all", which is an answer."""
    return math.inf if cost is None else float(cost)


def cast_weighting(value: Any) -> Weighting:
    """A weighting from the wire, checked before it reaches the fitter."""
    if value not in ("modulus", "unit", "proportional"):
        raise ValueError(f"unknown weighting {value!r}")
    return cast(Weighting, value)
