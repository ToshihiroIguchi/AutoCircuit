"""Orchestrator side of the browser discovery prototype (``docs/WEB_UI_PLAN.md`` step 1).

This runs in the Pyodide instance that owns the search. It keeps every decision that gate G1
depends on -- enumeration, the feasibility filter, the early-abandon thresholds, the per-size
shortlist quota, the tier-2 refit -- and hands out only batches of "screen these circuits".
JavaScript fans those across Web Workers and sends the costs back.

The point being proved is that no part of :func:`autocircuit.core.discover.screen_plan` or
:func:`_shortlist` has to be reimplemented in JavaScript for the browser to parallelise the
screen. The alternative design would have moved the per-element-count quota into JS, where
nothing tests it.

Tier 2 deliberately stays here rather than being fanned out too. A refit returns a whole
``FitResult`` -- covariance, restart spread and all -- which is a Python object that cannot
cross a structured-clone boundary without a serialisation format nobody has needed yet, and
handing back only the fitted values is exactly the shortcut that loses the restart spread
(``docs/DISCOVERY_V2_PLAN.md`` 5.1). It is also the cheaper tier.
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
    _refit_shortlist,
    pareto_front,
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


def finish() -> str:
    """Tier 2 and the report, from the scored screen."""
    scored = [(float(cost), text) for cost, text in _state["scored"]]
    candidates: list[Candidate] = _refit_shortlist(
        scored, SPECTRUM, "modulus", 5, 0, REFINE_DEFAULT["exhaustive"], None
    )
    candidates.sort(key=lambda c: c.aicc)
    result = DiscoveryResult(
        candidates=candidates,
        pareto=pareto_front(candidates),
        n_evaluated=len(scored),
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
