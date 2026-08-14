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

import json
import math
from typing import Any

import pytest

from autocircuit.core.discover import RefitTask, ScreenTask, discover, run_refit, run_screen
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


@pytest.mark.parametrize("op", ["discover_screen", "discover_refit", "discover_report"])
def test_every_discovery_operation_answers_without_a_job(op: str) -> None:
    """The bridge never raises: a stale front end gets a message, not a dead worker."""
    job_module._CURRENT = None
    error = _error(op, job="job-does-not-exist")
    assert "no discovery job is running" in error["message"]
