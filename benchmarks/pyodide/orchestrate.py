"""Orchestrator side of the browser discovery prototype (``docs/WEB_UI_PLAN.md`` step 1).

This runs in the Pyodide instance that owns the search. It keeps every decision that gate G1
depends on -- enumeration, the feasibility filter, the early-abandon thresholds, the per-size
shortlist quota, the tier-2 refit -- and hands out only batches of "screen these circuits".
JavaScript fans those across Web Workers and sends the costs back.

The point being proved is that no part of :func:`autocircuit.core.discover.screen_plan`,
:func:`refit_plan` or :func:`_shortlist` has to be reimplemented in JavaScript for the browser
to parallelise either tier. The alternative design would have moved the per-element-count quota
into JS, where nothing tests it.

**Tier 2 fans out as well, and that is the change this file records.** It used to run here,
serially, because a refit returns a whole ``FitResult`` -- covariance, restart spread and all --
and handing back only the fitted values is exactly the shortcut that loses the restart spread
(``docs/DISCOVERY_V2_PLAN.md`` 5.1). Measurement then showed that serial stage to be 80% of the
browser's run time (``docs/WEB_UI_PLAN.md`` 2.2), so the missing piece was built:
:meth:`FitResult.to_wire` carries every field across the boundary losslessly, and
:func:`refit_plan` hands out the fits the way ``screen_plan`` hands out the screens.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import (
    REFINE_DEFAULT,
    Candidate,
    DiscoveryResult,
    pareto_front,
    refit_plan,
    screen_plan,
)
from autocircuit.core.enumerate import EndpointBehaviour, enumerate_topologies, is_feasible
from autocircuit.core.simulate import log_frequencies, simulate

SPECTRUM = simulate(
    "C1-R1-L1-SKINF1",
    log_frequencies(1e2, 1e9, 10),
    {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
    noise=0.01,
    seed=0,
)
POOL = ("R", "C", "L", "CPE", "SKINF")
LIMIT = 4
CHUNK = 64

#: Refits handed out at a time. Unlike the screen, no decision here depends on an earlier
#: batch, so this only trades scheduling granularity against round trips -- and it is what the
#: UI will stream a partial Pareto front from. One batch would leave a worker idle at the tail,
#: since refit times vary by an order of magnitude across topologies.
REFIT_CHUNK = 8

_state: dict[str, Any] = {}


# JSON has no infinity, and JavaScript's JSON.parse rejects Python's bare ``Infinity`` while
# JSON.stringify silently turns its own ``Infinity`` into ``null``. So null *is* the wire
# representation of infinity in both directions -- which matters, because an infinite abandon
# threshold ("never abandon") and an infinite cost ("hopeless topology") are both routine here,
# not edge cases.


def _to_wire(value: float) -> float | None:
    return None if math.isinf(value) else float(value)


def _from_wire(value: float | None) -> float:
    return math.inf if value is None else float(value)


def start() -> str:
    """Enumerate, filter, and open the screen plan. Returns the candidate count as JSON."""
    behaviour = EndpointBehaviour.from_spectrum(SPECTRUM)
    texts = [
        Circuit(node).to_string()
        for n in range(1, LIMIT + 1)
        for node in enumerate_topologies(POOL, n)
        if is_feasible(node, behaviour)
    ]
    plan = screen_plan(texts, chunk=CHUNK)
    _state.update(texts=texts, plan=plan, scored=None, started=time.perf_counter())
    return json.dumps({"candidates": len(texts)})


def next_batch() -> str:
    """The next batch of screening work, or ``null`` once the plan is exhausted."""
    plan = _state["plan"]
    try:
        tasks = next(plan) if _state.get("pending") is None else plan.send(_state["pending"])
    except StopIteration as done:
        _state["scored"] = list(done.value)
        return json.dumps(None)
    _state["pending"] = None
    return json.dumps([[task.text, _to_wire(task.abandon_above)] for task in tasks])


def submit(costs_json: str) -> None:
    """Hand back the costs for the batch just issued."""
    _state["pending"] = [_from_wire(cost) for cost in json.loads(costs_json)]


def next_refit() -> str:
    """The next batch of tier-2 refits, or ``null`` once the shortlist is done.

    Same shape as :func:`next_batch`, and for the same reason: which topologies are worth a
    full-budget refit is :func:`_shortlist`'s decision, taken inside :func:`refit_plan`, and
    JavaScript never sees the rule -- only the list of fits to run.
    """
    if "refit_plan" not in _state:
        scored = [(float(cost), text) for cost, text in _state["scored"]]
        _state["refit_plan"] = refit_plan(
            scored,
            n_refine=REFINE_DEFAULT["exhaustive"],
            n_data=2 * SPECTRUM.n,
            restarts=5,
            seed=0,
            chunk=REFIT_CHUNK,
        )
        _state["refit_pending"] = None
    plan = _state["refit_plan"]
    try:
        if _state["refit_pending"] is None:
            batch = next(plan)
        else:
            batch = plan.send(_state["refit_pending"])
    except StopIteration as done:
        _state["candidates"] = list(done.value)
        return json.dumps(None)
    _state["refit_pending"] = None
    return json.dumps([[task.text, task.restarts, task.seed] for task in batch.tasks])


def submit_refit(results_json: str) -> None:
    """Hand back one wire-format ``FitResult`` (or ``null``) per task just issued.

    ``null`` means the topology could not be fitted at all, which is an answer rather than an
    error; anything else is :meth:`FitResult.to_wire`, which :func:`refit_plan` decodes.
    """
    _state["refit_pending"] = json.loads(results_json)


def finish() -> str:
    """The report, from the refitted candidates."""
    candidates: list[Candidate] = _state["candidates"]
    result = DiscoveryResult(
        candidates=candidates,
        pareto=pareto_front(candidates),
        n_evaluated=len(_state["scored"]),
        generations=0,
        elapsed_s=time.perf_counter() - _state["started"],
        pool=POOL,
        mode="exhaustive",
        complete_up_to=LIMIT,
    )
    return json.dumps(
        {
            "n_evaluated": result.n_evaluated,
            "complete_up_to": result.complete_up_to,
            "elapsed_s": result.elapsed_s,
            "candidates": [
                [c.circuit.canonical_form(), round(c.aicc, 9)] for c in result.candidates
            ],
            "pareto": [c.circuit.canonical_form() for c in result.pareto],
            "recommended": None
            if result.recommended is None
            else result.recommended.circuit.canonical_form(),
        }
    )
