"""Tests for `autocircuit.web.job`: a topology search driven one batch at a time.

The browser runs `discover()`'s two tiers itself, across Web Workers, so what has to be true
is that driving them from outside produces the search the command line produces -- not a
similar one. These tests drive the whole thing through `bridge.handle`, exactly as JavaScript
will, and compare against `discover()` on the same data:

* the same topologies screened, the same coverage claimed, the same candidates with the same
  AICc, and the same recommendation;
* a run stopped part-way claims *less*, and says so in the sentence the UI renders verbatim --
  a screen cut short lowers `complete_up_to`, and a refit cut short leaves a partial front
  which `refit_progress` announces rather than presenting as a finished ranking;
* every response is JSON `JSON.parse` would accept, with the non-finite values that are
  routine here (an infinite abandon threshold, an infinite screening cost, the `-inf` AICc of
  an exact fit) surviving the trip.

Exact equality throughout, following `tests/test_web_bridge.py`.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

import pytest

from autocircuit.core.discover import (
    RefitTask,
    ScreenTask,
    discover,
    excluded_equivalents,
    run_refit,
    run_screen,
)
from autocircuit.core.interpret import interpret_class
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum
from autocircuit.web import job as job_module
from autocircuit.web.bridge import handle

POOL = ("R", "C")
LIMIT = 3


def _semicircle(noise: float = 0.005, points: int = 8) -> Spectrum:
    return simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e0, 1e6, points),
        {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=noise,
        seed=0,
    )


def _call(op: str, **kwargs: Any) -> dict[str, Any]:
    """One bridge request, checked for wire safety, unwrapped on success."""
    parsed = json.loads(handle(json.dumps({"op": op, **kwargs})))
    json.dumps(parsed, allow_nan=False)  # what JSON.parse will accept, not what Python emits
    assert parsed["ok"], parsed.get("error")
    return parsed["result"]


def _error(op: str, **kwargs: Any) -> dict[str, Any]:
    """One bridge request that is expected to fail, returning the error response."""
    parsed = json.loads(handle(json.dumps({"op": op, **kwargs})))
    json.dumps(parsed, allow_nan=False)
    assert not parsed["ok"], parsed
    return dict(parsed["error"])


class Driver:
    """The JavaScript side, in Python: it moves batches and results and decides nothing."""

    def __init__(self, spectrum: Spectrum, **options: Any) -> None:
        self.wire = spectrum.to_wire()
        self.plan = _call("discover_start", spectrum=self.wire, **options)
        self.id = self.plan["job"]
        self.screen_steps: list[dict[str, Any]] = []
        self.refit_steps: list[dict[str, Any]] = []

    def screen(self, batches: int | None = None) -> None:
        """Run the tier-1 screen, or only ``batches`` of it."""
        costs = None
        while batches is None or len(self.screen_steps) < batches:
            step = _call("discover_screen", job=self.id, costs=costs)
            self.screen_steps.append(step)
            if step["tasks"] is None:
                return
            costs = [
                _call(
                    "screen_task", spectrum=self.wire, circuit=text, abandon_above=abandon
                )["cost"]
                for text, abandon in step["tasks"]
            ]

    def refit(self, batches: int | None = None) -> None:
        """Run the tier-2 refit, or only ``batches`` of it."""
        results = None
        while batches is None or len(self.refit_steps) < batches:
            step = _call("discover_refit", job=self.id, results=results)
            self.refit_steps.append(step)
            if step["tasks"] is None:
                return
            results = [
                _call(
                    "refit_task",
                    spectrum=self.wire,
                    circuit=text,
                    restarts=restarts,
                    seed=seed,
                )["fit"]
                for text, restarts, seed in step["tasks"]
            ]

    def run(self) -> None:
        """Both tiers, and again for every further pass the search asks for.

        The loop is what a derived pool needs: tier 2 running out is no longer the end of the
        search, because the completed fit is the evidence `choose_pool` reads. How many passes
        there are is the core's decision, so the driver asks (`more`) rather than counting.
        """
        for _ in range(4):  # a bound, so a driver bug cannot hang the suite
            self.screen()
            self.refit()
            if not self.refit_steps[-1]["more"]:
                return
        raise AssertionError("the search asked for more passes than it can have")

    def cancel(self) -> dict[str, Any]:
        return _call("discover_cancel", job=self.id)

    def report(self) -> dict[str, Any]:
        return _call("discover_report", job=self.id)


# =============================================================================================
# 1. The whole search, driven from outside, is the search discover() runs
# =============================================================================================


def test_a_driven_search_reproduces_discover_exactly() -> None:
    """Gate W2's result half, in-process: same coverage, same candidates, same AICc.

    The screening batch is one candidate at a time here to match ``discover``'s in-process
    driver, because the batch size is the one thing a driver chooses that the search can see:
    within a batch the early-abandon threshold is one batch stale. That cannot change which
    topology fits best -- abandoning only ever skips a polish already a hundredfold off the
    pace -- but it can change a screening cost, and these assertions are exact.
    """
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT, screen_chunk=1)
    driver.screen()
    driver.refit()
    report = driver.report()

    reference = discover(spectrum, pool=POOL, mode="exhaustive", exhaustive_limit=LIMIT, seed=0)

    assert report["n_evaluated"] == reference.n_evaluated
    assert report["complete_up_to"] == reference.complete_up_to
    assert report["completeness"] == reference.completeness()
    assert report["refit_progress"] is None
    assert [row["circuit"] for row in report["candidates"]] == [
        c.circuit.to_string() for c in reference.candidates
    ]
    assert [row["aicc"] for row in report["candidates"]] == [
        c.aicc for c in reference.candidates
    ]
    assert [row["circuit"] for row in report["pareto"]] == [
        c.circuit.to_string() for c in reference.pareto
    ]
    assert reference.recommended is not None
    assert report["recommended"] == reference.recommended.circuit.to_string()


def test_a_batched_screen_finds_the_same_candidates() -> None:
    """The browser's batch size changes the order of exact ties, and nothing else.

    A batch of 64 is what both the desktop's process pool and the browser's worker pool use,
    so this is the arrangement gate W2 is measured in. Two topologies that are exact
    reparameterisations of one another score the same AICc to the last digit, and which of
    them a stable sort puts first is not a result -- it is why the report shows equivalence
    classes rather than a ranking with a winner.
    """
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT, screen_chunk=64)
    driver.screen()
    driver.refit()
    report = driver.report()

    reference = discover(spectrum, pool=POOL, mode="exhaustive", exhaustive_limit=LIMIT, seed=0)

    assert report["complete_up_to"] == reference.complete_up_to
    assert {row["circuit"] for row in report["candidates"]} == {
        c.circuit.to_string() for c in reference.candidates
    }
    assert sorted(row["aicc"] for row in report["candidates"]) == sorted(
        c.aicc for c in reference.candidates
    )
    assert reference.recommended is not None
    assert report["recommended"] == reference.recommended.circuit.to_string()


def test_the_plan_says_how_much_work_it_committed_to() -> None:
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT)
    assert driver.plan["mode"] == "exhaustive"
    assert driver.plan["limit"] == LIMIT
    assert driver.plan["candidates"] == sum(
        level["candidates"] for level in driver.plan["levels"]
    )
    assert [level["n_elements"] for level in driver.plan["levels"]] == [1, 2, 3]

    driver.screen()
    assert driver.screen_steps[-1]["screened"] == driver.plan["candidates"]
    assert driver.screen_steps[-1]["total"] == driver.plan["candidates"]


def test_the_front_is_streamed_while_the_refit_is_still_running() -> None:
    """Every refit batch carries the front so far, which is what the job screen draws."""
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT, refit_chunk=1)
    driver.screen()
    driver.refit()

    refitted = [step["refitted"] for step in driver.refit_steps]
    assert refitted == sorted(refitted)
    assert refitted[0] == 0
    assert refitted[-1] == len(driver.report()["candidates"])
    # The front only ever grows or reshuffles; it never claims more than has been fitted.
    for step in driver.refit_steps:
        assert len(step["front"]) <= step["refitted"]
        assert step["shortlisted"] >= step["refitted"]


# =============================================================================================
# 2. A search that was stopped claims less
# =============================================================================================


def test_cancelling_the_screen_lowers_the_coverage_claim() -> None:
    """The coverage of a screen cut short is the levels it finished, never the level it was in."""
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=4, screen_chunk=1)
    driver.screen(batches=3)
    stopped = driver.cancel()
    report = driver.report()

    assert stopped["screened"] < driver.plan["candidates"]
    assert report["stopped"] is True
    assert report["n_evaluated"] == stopped["screened"]
    full = discover(spectrum, pool=POOL, mode="exhaustive", exhaustive_limit=4, seed=0)
    assert full.complete_up_to == 4
    assert report["complete_up_to"] is None or report["complete_up_to"] < 4


def test_a_screen_stopped_before_any_fit_says_nothing_was_fitted() -> None:
    """Nothing to report is still a report: the shortlist size is knowable without fitting."""
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT, screen_chunk=1)
    driver.screen(batches=2)
    driver.cancel()
    report = driver.report()

    assert report["candidates"] == []
    assert report["recommended"] is None
    done, total = report["refit_progress"]
    assert done == 0
    assert total > 0
    assert f"only 0 of the {total} shortlisted" in report["completeness"]


def test_a_search_cancelled_immediately_reports_only_its_coverage() -> None:
    """The button a user presses when they realise the limit was too high."""
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT)
    driver.cancel()
    report = driver.report()

    assert report["candidates"] == []
    assert report["refit_progress"] == [0, 0]
    assert "no fitted parameters to report" in report["completeness"]
    # A search that screened nothing can still cover an element count -- but only one the
    # feasibility filter emptied, where "all of them were evaluated" is a statement about
    # nothing. Any claim beyond that would be a claim about work that never happened.
    levels = {level["n_elements"]: level["candidates"] for level in driver.plan["levels"]}
    claimed = report["complete_up_to"]
    assert claimed is None or levels[claimed] == 0


def test_cancelling_the_refit_reports_a_partial_front_as_partial() -> None:
    """A complete screen with a half-refitted shortlist must not look like a finished report."""
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT, refit_chunk=1)
    driver.screen()
    driver.refit(batches=2)
    driver.cancel()
    report = driver.report()

    done, total = report["refit_progress"]
    assert 0 < done < total
    assert report["candidates"] != []
    # The screen finished, so its claim stands; the ranking underneath it does not.
    assert report["complete_up_to"] == LIMIT
    assert f"up to {LIMIT} elements" in report["completeness"]
    assert f"only {done} of the {total} shortlisted" in report["completeness"]
    assert "partial" in report["completeness"]
    assert report["completeness"] in report["summary"]


def test_a_finished_search_makes_no_partial_claim() -> None:
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT)
    driver.screen()
    driver.refit()
    report = driver.report()
    assert report["refit_progress"] is None
    assert report["stopped"] is False
    assert "partial" not in report["completeness"]


def test_a_cancelled_search_hands_out_no_more_work() -> None:
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT, screen_chunk=1)
    driver.screen(batches=1)
    driver.cancel()
    assert _call("discover_screen", job=driver.id)["tasks"] is None
    assert _call("discover_refit", job=driver.id)["tasks"] is None


# =============================================================================================
# 3. What a skeleton does to the claim
# =============================================================================================


def test_a_skeleton_narrows_the_space_and_the_sentence() -> None:
    """Mode 2 through the browser: the space is narrowed, and the report says whose doing."""
    spectrum = _semicircle()
    driver = Driver(
        spectrum, pool=list(POOL), skeleton="R1-C1", exhaustive_limit=3, screen_chunk=1
    )
    driver.screen()
    driver.refit()
    report = driver.report()

    reference = discover(
        spectrum, pool=POOL, skeleton="R1-C1", mode="exhaustive", exhaustive_limit=3, seed=0
    )
    assert report["skeleton"] == "R1-C1"
    assert report["n_evaluated"] == reference.n_evaluated
    assert report["completeness"] == reference.completeness()
    assert "contains R1-C1" in report["completeness"]
    assert "not evidence against them" in report["completeness"]


# =============================================================================================
# 4. The wire: infinities, and requests that should fail rather than mislead
# =============================================================================================


def test_an_infinite_abandon_threshold_travels_as_null_in_both_directions() -> None:
    """Null is the wire's infinity for a cost, and both directions are routine values here."""
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=2, screen_chunk=1)
    step = _call("discover_screen", job=driver.id)
    assert step["tasks"][0][1] is None  # nothing screened yet: never abandon

    assert job_module.from_wire_cost(None) == math.inf
    assert job_module.to_wire_cost(math.inf) is None
    assert job_module.to_wire_cost(2.5) == 2.5


def test_a_cost_of_null_means_hopeless_and_removes_the_topology() -> None:
    """The other direction of the same convention: a worker's infinity reaches the shortlist.

    A topology that cannot be fitted at all scores infinity rather than raising, which is an
    answer; here every one of them does, so the shortlist is empty and the search finishes
    with a coverage claim and nothing to rank.
    """
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT)
    step = _call("discover_screen", job=driver.id)
    assert step["tasks"] is not None
    hopeless = [None] * len(step["tasks"])
    assert _call("discover_screen", job=driver.id, costs=hopeless)["tasks"] is None
    assert _call("discover_refit", job=driver.id)["tasks"] is None

    report = driver.report()
    assert report["candidates"] == []
    assert report["recommended"] is None
    assert report["complete_up_to"] == LIMIT
    assert report["refit_progress"] is None


def test_a_screen_task_answers_with_the_cost_the_command_line_would_get() -> None:
    """The pool worker's operation is `run_screen` and nothing else."""
    spectrum = _semicircle()
    text = "R1-p(R2,C1)"
    through_bridge = _call(
        "screen_task", spectrum=spectrum.to_wire(), circuit=text, abandon_above=None
    )["cost"]
    direct = run_screen(
        ScreenTask(text, math.inf), spectrum, weighting="modulus", seed=0
    )
    assert through_bridge == direct


def test_a_refit_task_answers_with_the_fit_the_command_line_would_get() -> None:
    spectrum = _semicircle()
    text = "R1-p(R2,C1)"
    through_bridge = _call(
        "refit_task", spectrum=spectrum.to_wire(), circuit=text, restarts=1, seed=0
    )["fit"]
    direct = run_refit(RefitTask(text, 1, 0), spectrum, weighting="modulus")
    assert direct is not None
    expected = direct.to_wire()
    # Everything but the clock: how long the fit took is not part of the fit.
    assert through_bridge.keys() == expected.keys()
    assert {k: v for k, v in through_bridge.items() if k != "elapsed_s"} == {
        k: v for k, v in expected.items() if k != "elapsed_s"
    }


def test_a_request_for_a_job_that_is_gone_is_an_error_not_the_wrong_job() -> None:
    spectrum = _semicircle()
    first = Driver(spectrum, pool=list(POOL), exhaustive_limit=2)
    second = Driver(spectrum, pool=list(POOL), exhaustive_limit=2)
    assert first.id != second.id
    error = _error("discover_screen", job=first.id)
    assert "no longer running" in error["message"]


def test_the_wrong_number_of_costs_is_refused() -> None:
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=3, screen_chunk=4)
    step = _call("discover_screen", job=driver.id)
    error = _error("discover_screen", job=driver.id, costs=[1.0] * (len(step["tasks"]) - 1))
    assert "screening tasks" in error["message"]


def test_an_unknown_element_in_the_pool_is_refused_before_anything_runs() -> None:
    spectrum = _semicircle()
    error = _error(
        "discover_start", spectrum=spectrum.to_wire(), pool=["R", "Q"], exhaustive_limit=2
    )
    assert "unknown element codes" in error["message"]


# =============================================================================================
# 4b. The fit behind a results row, so the screen that ran the search can plot what it found
# =============================================================================================


def test_a_reported_row_hands_back_the_fit_it_was_ranked_on() -> None:
    """`discover_candidate` returns the search's own fit, not a new one.

    The check that matters is the last two: the curve and the residuals come from the
    `FitResult` the job has held since its tier-2 refit, so the picture the Discover screen
    draws is the fit the ranking was computed from rather than a re-run that might land
    somewhere else (docs/SCREEN_STATE_PLAN.md section 4).
    """
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT)
    driver.screen()
    driver.refit()
    report = driver.report()
    row = report["pareto"][0]

    answer = _call("discover_candidate", job=driver.id, circuit=row["circuit"])

    assert answer["fit"]["circuit"] == row["circuit"]
    assert answer["fit"]["statistics"]["aicc"] == row["aicc"]
    assert answer["fit"]["statistics"]["chi2_reduced"] == row["chi2_reduced"]
    # As many residual points as data points, split real-then-imaginary by Python so no front
    # end has to know the objective function's concatenation order.
    assert len(answer["residual_real"]["data"]) == len(answer["residual_imag"]["data"])
    assert answer["summary"] != ""


def test_the_recommended_row_is_the_default_candidate() -> None:
    """Omitting the circuit asks for the row the report recommends, as the exports do."""
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT)
    driver.screen()
    driver.refit()
    report = driver.report()

    answer = _call("discover_candidate", job=driver.id)

    assert answer["fit"]["circuit"] == report["recommended"]


def test_a_topology_this_search_never_fitted_is_refused() -> None:
    """A stale front end asking about a row from another search gets a message, not a fit."""
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT)
    driver.screen()
    driver.refit()

    error = _error("discover_candidate", job=driver.id, circuit="R1-R2-R3-R4")

    assert "not one of the topologies this search fitted" in error["message"]


@pytest.mark.parametrize(
    "op", ["discover_screen", "discover_refit", "discover_report", "discover_candidate"]
)
def test_every_discovery_operation_answers_without_a_job(op: str) -> None:
    """The bridge never raises: a stale front end gets a message, not a dead worker."""
    job_module._CURRENT = None
    error = _error(op, job="job-does-not-exist")
    assert "no discovery job is running" in error["message"]


# =============================================================================================
# 5. What the skeleton excluded, driven the same way
# =============================================================================================


class ExcludedDriver:
    """The JavaScript side of the excluded-equivalents pass, in Python.

    Note which spectrum the screens go against: the ``target`` the orchestrator handed back,
    which is the reported candidate's *fitted* response and not the measured data. A driver that
    reached for the data instead would be answering a different question, which is why the
    target is something it is given rather than something it picks.
    """

    def __init__(self, search: Driver, **options: Any) -> None:
        self.start = _call("excluded_start", job=search.id, **options)
        self.id = self.start["job"]
        self.target = self.start["target"]
        self.steps: list[dict[str, Any]] = []

    def run(self, batches: int | None = None) -> None:
        costs = None
        while batches is None or len(self.steps) < batches:
            step = _call("excluded_screen", job=self.id, costs=costs)
            self.steps.append(step)
            if step["tasks"] is None:
                return
            costs = [
                _call(
                    "screen_task", spectrum=self.target, circuit=text, abandon_above=abandon
                )["cost"]
                for text, abandon in step["tasks"]
            ]

    def cancel(self) -> dict[str, Any]:
        return _call("excluded_cancel", job=self.id)

    def report(self) -> dict[str, Any]:
        return _call("excluded_report", job=self.id)


def _skeleton_search() -> tuple[Spectrum, Driver]:
    """A finished constrained search, which is the only thing this pass can be run on."""
    spectrum = _semicircle()
    driver = Driver(
        spectrum, pool=list(POOL), skeleton="R1-p(R2,C1)", exhaustive_limit=3, screen_chunk=1
    )
    driver.screen()
    driver.refit()
    return spectrum, driver


def test_the_driven_excluded_pass_reproduces_the_command_lines() -> None:
    """Section 3.3 through the browser's transport: same counts, same equivalents.

    The list is the point. `R1-p(R2,C1)` and `p(R1-C1,R2)` describe exactly the same
    semicircles, so asserting the first excludes the second outright -- and the browser has to
    name it for the same reason the command line does: the survivor is a choice the user made,
    not something the data preferred.
    """
    spectrum, search = _skeleton_search()
    driver = ExcludedDriver(search, chunk=1)
    driver.run()
    report = driver.report()

    reference_search = discover(
        spectrum, pool=POOL, skeleton="R1-p(R2,C1)", mode="exhaustive", exhaustive_limit=3,
        seed=0,
    )
    assert reference_search.recommended is not None
    assert reference_search.skeleton is not None
    reference = excluded_equivalents(
        reference_search.recommended, reference_search.skeleton, spectrum, pool=POOL, seed=0
    )

    assert report["equivalents"] == list(reference.equivalents)
    assert report["excluded"] == reference.excluded
    assert report["kept"] == reference.kept
    assert report["screened"] == reference.screened == reference.excluded
    assert report["partial"] is False
    assert report["finished"] is True
    assert report["summary"] == reference.summary()
    assert "choosing between them is something you did" in report["summary"]


def test_the_pass_screens_against_the_fitted_model_not_the_measured_data() -> None:
    """The target crosses the wire because choosing it is a decision, not plumbing.

    An exact reparameterisation reaches a noise-free target to machine precision; against the
    sample's own noise it would look no better than a topology that merely fits well, and the
    pass would answer a question nobody asked.
    """
    spectrum, search = _skeleton_search()
    driver = ExcludedDriver(search, chunk=1)
    candidate = job_module.current(search.id).candidate()

    target = Spectrum.from_wire(driver.target)
    assert list(target.z) == list(candidate.result.z_model)
    assert list(target.f) == list(spectrum.f)
    assert list(target.z) != list(spectrum.z)


def test_the_pass_says_how_much_work_it_is_before_screening_any_of_it() -> None:
    """The counts are known from the enumeration alone, and this pass costs about as much as
    the search that preceded it -- so the number to decline is available before the waiting."""
    _, search = _skeleton_search()
    driver = ExcludedDriver(search, chunk=1)
    assert driver.start["screened"] == 0
    assert driver.start["excluded"] > 0
    assert driver.start["kept"] > 0
    assert driver.start["circuit"] == search.report()["recommended"]
    assert driver.start["skeleton"] == "R1-p(R2,C1)"


def test_a_stopped_pass_reports_what_it_checked_and_not_what_it_did_not() -> None:
    _, search = _skeleton_search()
    driver = ExcludedDriver(search, chunk=1)
    driver.run(batches=2)
    stopped = driver.cancel()
    report = driver.report()

    assert 0 < stopped["screened"] < stopped["total"]
    assert report["partial"] is True
    assert report["finished"] is False
    assert report["stopped"] is True
    assert report["screened"] == stopped["screened"]
    assert f"Only {report['screened']} of them have been checked" in report["summary"]
    assert "Nothing the data could not already distinguish was lost" not in report["summary"]
    assert _call("excluded_screen", job=driver.id)["tasks"] is None


def test_the_pass_is_refused_for_a_search_that_had_no_skeleton() -> None:
    """Nothing was excluded from an unconstrained search, and answering "none" would be a
    different claim -- one that reads as an assurance rather than as "you asserted nothing"."""
    spectrum = _semicircle()
    search = Driver(spectrum, pool=list(POOL), exhaustive_limit=2, screen_chunk=1)
    search.screen()
    search.refit()
    error = _error("excluded_start", job=search.id)
    assert "no skeleton" in error["message"]


def test_the_pass_is_refused_for_a_topology_the_search_never_fitted() -> None:
    _, search = _skeleton_search()
    error = _error("excluded_start", job=search.id, circuit="R1-C1-L1")
    assert "not one of the topologies this search fitted" in error["message"]


def test_the_excluded_pass_is_a_slot_of_its_own_and_leaves_the_search_readable() -> None:
    """The report screen asks the same worker for both, after the search has finished."""
    _, search = _skeleton_search()
    driver = ExcludedDriver(search, chunk=1)
    driver.run()
    assert search.report()["recommended"] is not None
    assert driver.report()["search"] == search.id


# =============================================================================================
# 6. The report screen: classes as classes, and files that match the command line's
# =============================================================================================


def _without_clocks(payload: Any) -> Any:
    """The same structure with every elapsed time removed.

    Two runs of the same search agree on every number that is a *result*; how long each took is
    not one. Everything else here is compared exactly.
    """
    if isinstance(payload, dict):
        return {k: _without_clocks(v) for k, v in payload.items() if k != "elapsed_s"}
    if isinstance(payload, list):
        return [_without_clocks(item) for item in payload]
    return payload


def _finished_search() -> tuple[Spectrum, Driver]:
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT, screen_chunk=1)
    driver.screen()
    driver.refit()
    return spectrum, driver


def test_the_report_carries_the_equivalence_classes_as_classes() -> None:
    """The one thing this report is not allowed to be is a ranking with a winner.

    Different topologies are routinely exact reparameterisations of each other, so the grouping
    is the structure of the answer rather than an annotation on it -- and it travels as a
    grouping instead of being reconstructed in JavaScript from rows that happen to score alike.
    """
    spectrum, driver = _finished_search()
    report = driver.report()
    reference = discover(spectrum, pool=POOL, mode="exhaustive", exhaustive_limit=LIMIT, seed=0)

    assert report["equivalence_classes"] == [
        [c.circuit.to_string() for c in group] for group in reference.equivalence_classes()
    ]
    # Every candidate appears in exactly one class, singletons included.
    members = [text for group in report["equivalence_classes"] for text in group]
    assert sorted(members) == sorted(row["circuit"] for row in report["candidates"])
    assert len(set(members)) == len(members)
    assert any(len(group) > 1 for group in report["equivalence_classes"])


def test_an_unconstrained_report_says_null_rather_than_empty_for_the_skeleton_findings() -> None:
    """Absent and empty mean different things: "nothing was asserted" is not "the assertion
    was tested and held"."""
    _, driver = _finished_search()
    report = driver.report()
    assert report["skeleton"] is None
    assert report["unsupported_assertion"] is None
    assert report["skeleton_placements"] is None


def test_a_constrained_report_names_what_the_data_could_not_test() -> None:
    """The measured signature of a wrong skeleton (docs/PARTIAL_TOPOLOGY_PLAN.md §3.2), and
    where the skeleton sits ambiguously -- both structured, because the report screen has to
    show them beside the candidate they belong to rather than only inside a paragraph."""
    spectrum, search = _skeleton_search()
    report = search.report()
    reference = discover(
        spectrum, pool=POOL, skeleton="R1-p(R2,C1)", mode="exhaustive", exhaustive_limit=3,
        seed=0,
    )
    assert reference.recommended is not None

    assert report["unsupported_assertion"] == list(
        reference.unsupported_assertion(reference.recommended)
    )
    assert report["skeleton_placements"] == {
        c.circuit.to_string(): reference.placements_of(c) for c in reference.pareto
    }
    assert set(report["skeleton_placements"]) == {row["circuit"] for row in report["pareto"]}


def test_the_json_export_is_the_file_the_command_line_writes() -> None:
    """A download outlives the session and gets read by someone who was never at the screen, so
    it is the CLI's own ``--json`` payload rather than a browser rendering of the same idea."""
    spectrum, driver = _finished_search()
    artifact = _call("export", kind="json", job=driver.id)
    reference = discover(spectrum, pool=POOL, mode="exhaustive", exhaustive_limit=LIMIT, seed=0)

    assert artifact["filename"].endswith(".json")
    assert artifact["mime"] == "application/json"
    assert _without_clocks(json.loads(artifact["content"])) == _without_clocks(
        reference.to_dict()
    )
    written = json.loads(artifact["content"])
    assert written["coverage"] == reference.completeness()
    assert written["equivalence_classes"] == [
        [c.circuit.to_string() for c in group]
        for group in reference.equivalence_classes()
        if len(group) > 1
    ]


def test_the_json_export_of_a_stopped_search_carries_the_partial_claim() -> None:
    """The coverage sentence is in the file, so a report read a year later still says that the
    ranking in it was only part of the shortlist."""
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT, refit_chunk=1)
    driver.screen()
    driver.refit(batches=2)
    driver.cancel()

    written = json.loads(_call("export", kind="json", job=driver.id)["content"])
    done, total = written["refit_progress"]
    assert 0 < done < total
    assert f"only {done} of the {total} shortlisted" in written["coverage"]


def test_the_csv_export_names_the_rows_that_cannot_be_told_apart() -> None:
    """A flat table is the least honest of the three exports, so the ambiguity is a column:
    someone sorting by AICc in a spreadsheet still meets it."""
    spectrum, driver = _finished_search()
    artifact = _call("export", kind="csv", job=driver.id)
    reference = discover(spectrum, pool=POOL, mode="exhaustive", exhaustive_limit=LIMIT, seed=0)

    assert artifact["mime"] == "text/csv"
    assert artifact["content"] == reference.to_csv()
    rows = list(csv.DictReader(io.StringIO(artifact["content"])))
    assert [row["circuit"] for row in rows] == [
        row["circuit"] for row in driver.report()["candidates"]
    ]
    assert any(row["equivalents"] for row in rows)
    assert sum(int(row["recommended"]) for row in rows) == 1


def test_the_netlist_export_is_of_the_recommended_candidate_by_default() -> None:
    """The same candidate ``discover --spice`` writes, which is the parsimonious one and not
    the lowest AICc."""
    _, driver = _finished_search()
    report = driver.report()
    artifact = _call("export", kind="netlist", job=driver.id)

    assert artifact["filename"] == "autocircuit-discovery.cir"
    assert f"Circuit: {report['recommended']}" in artifact["content"]
    assert "Topology discovered automatically by AutoCircuit" in artifact["content"]

    named = _call("export", kind="netlist", job=driver.id, circuit=report["pareto"][0]["circuit"])
    assert f"Circuit: {report['pareto'][0]['circuit']}" in named["content"]


def test_the_json_export_includes_the_excluded_pass_only_when_one_was_run() -> None:
    """An absent key and an empty result mean different things wherever a skeleton is
    involved: "not asked" is not "asked, and nothing was lost"."""
    _, search = _skeleton_search()
    before = json.loads(_call("export", kind="json", job=search.id)["content"])
    assert before["excluded_equivalents"] is None

    driver = ExcludedDriver(search, chunk=1)
    driver.run()
    after = json.loads(
        _call("export", kind="json", job=search.id, excluded=driver.id)["content"]
    )
    assert after["excluded_equivalents"]["summary"] == driver.report()["summary"]
    assert after["excluded_equivalents"]["screened"] == driver.report()["screened"]


# =============================================================================================
# 8. The pool the spectrum chose
# =============================================================================================
#
# `CLAUDE.md`: the automatic path takes the spectrum and nothing else, and the software must not
# ask what kind of part this is. The browser used to require a pool and default to `DEFAULT_POOL`
# -- so its search could never widen, whatever the residuals said -- while the CLI had defaulted
# to `--pool auto` since docs/POOL_FROM_SPECTRUM_PLAN.md. These are that difference closed, and
# they assert it the only way that means anything: the two paths produce the same report.


def test_the_browser_can_read_a_reported_circuit_as_internal_structure() -> None:
    """`discover_interpret`, and the thing that makes it honest: it carries the class.

    The same rule the CLI follows (`docs/HANDOFF.md` §27) -- interpret the recommendation *and*
    every topology the data cannot tell it apart from, so the report can say which numbers the
    class agreed on. Asserted against `interpret_class` on the same fits rather than against a
    transcription of what it should say.
    """
    spectrum = _semicircle()
    driver = Driver(spectrum, pool=list(POOL), exhaustive_limit=LIMIT, screen_chunk=1)
    driver.run()
    answer = _call("discover_interpret", job=driver.id)

    running = job_module.current(driver.id)
    chosen = running.candidate(None)
    family = [chosen, *running.report().equivalents_of(chosen)]
    expected = interpret_class([c.result for c in family], spectrum)

    assert answer["summary"] == expected.summary()
    assert answer["interpretation"] == expected.to_dict()
    assert answer["interpretation"]["class_members"][0] == chosen.circuit.to_string()
    invariant = [
        row for row in answer["interpretation"]["class_spread"] if row["invariant"]
    ]
    assert invariant, "nothing marked invariant, so the answer asserts nothing"


def _diffusion() -> Spectrum:
    """A finite-length diffusion spectrum: a transmission line no R/C/L/CPE tree reproduces.

    Swept down to 0.01 Hz because `tau = 1 s` puts the transition near 0.16 Hz and it is the DC
    limit below it that tells `Ws` from `Wo` (docs/POOL_FROM_SPECTRUM_PLAN.md).
    """
    return simulate(
        "R1-Ws1",
        log_frequencies(1e-2, 1e3, 6),
        {"R1.R": 10.0, "Ws1.R": 100.0, "Ws1.tau": 1.0},
        noise=0.01,
        seed=0,
    )


def test_a_derived_pool_widens_in_the_browser_exactly_as_it_does_on_the_command_line() -> None:
    """The whole point of the wiring, asserted against `discover(pool=None)` row for row.

    Not "the browser also widens": the same widened pool, the same lost completeness level, the
    same candidates at the same AICc, and the same sentence -- which is the one the UI renders
    verbatim rather than paraphrasing.
    """
    spectrum = _diffusion()
    driver = Driver(spectrum, exhaustive_limit=3, screen_chunk=1)
    assert driver.plan["derive_pool"] is True
    driver.run()
    report = driver.report()

    reference = discover(spectrum, pool=None, mode="exhaustive", exhaustive_limit=3, seed=0)

    # Not a vacuous pass: this spectrum has to be one that actually asks for a wider pool.
    assert reference.pool_choice is not None
    assert reference.pool_choice.added
    assert report["pool_choice"] == reference.pool_choice.to_dict()
    assert report["pool"] == list(reference.pool)
    assert report["complete_up_to"] == reference.complete_up_to
    assert report["base_complete_up_to"] == reference.base_complete_up_to
    assert report["completeness"] == reference.completeness()
    assert report["n_evaluated"] == reference.n_evaluated
    assert [row["circuit"] for row in report["candidates"]] == [
        c.circuit.to_string() for c in reference.candidates
    ]
    assert [row["aicc"] for row in report["candidates"]] == [
        c.aicc for c in reference.candidates
    ]
    assert reference.recommended is not None
    assert report["recommended"] == reference.recommended.circuit.to_string()
    assert report["refit_progress"] is None


def test_the_widening_is_a_second_pass_and_the_progress_says_so() -> None:
    """A driver that stopped at the first `tasks: null` would report the narrow pool.

    That is the failure this wiring has to avoid, so it is asserted directly: tier 2 ends with
    `more`, screening starts again over a larger space, and the second pass is marked as one.
    """
    driver = Driver(_diffusion(), exhaustive_limit=3, screen_chunk=1)
    driver.screen()
    driver.refit()

    assert driver.refit_steps[-1]["more"] is True
    assert driver.screen_steps[0]["widened"] is False
    first_total = driver.screen_steps[0]["total"]

    driver.screen()
    driver.refit()

    assert driver.screen_steps[-1]["widened"] is True
    assert driver.screen_steps[-1]["total"] > first_total
    assert driver.refit_steps[-1]["more"] is False
    assert driver.report()["pool"] != list(driver.plan["pool"])


def test_a_named_pool_is_an_assertion_and_is_never_widened() -> None:
    """`pool_choice` is null when the caller named one, which is not the same as "not triggered".

    The distinction is the report's, not a nicety: a derived pool that found nothing to add
    still says the data was asked, and a pool the user named says the user chose. A browser that
    silently derived on top of a named pool would take that choice back.
    """
    driver = Driver(_diffusion(), pool=["R", "C"], exhaustive_limit=3, screen_chunk=1)
    assert driver.plan["derive_pool"] is False
    driver.run()
    report = driver.report()

    assert report["pool"] == ["R", "C"]
    assert report["pool_choice"] is None
    assert report["base_complete_up_to"] is None
    assert len(driver.screen_steps) == len(
        [step for step in driver.screen_steps if step["widened"] is False]
    )
