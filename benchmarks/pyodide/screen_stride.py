"""Screening work for one worker of the Pyodide worker-pool measurement.

Kept in its own file rather than embedded in the JavaScript: a Python docstring using the
project's usual double-backtick markup silently terminates a JS template literal, and the
resulting parse error points somewhere else entirely.

``run_workers.mjs`` sets ``WORKER_INDEX``, ``WORKER_TOTAL``, ``POOL_CSV`` and ``LIMIT`` in the
Pyodide globals before running this, then calls :func:`screen_stride`.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Any

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import SCREEN_BUDGET, SCREEN_TOL
from autocircuit.core.enumerate import EndpointBehaviour, enumerate_topologies, is_feasible
from autocircuit.core.fit import screen
from autocircuit.core.simulate import log_frequencies, simulate

SPECTRUM = simulate(
    "C1-R1-L1-SKINF1",
    log_frequencies(1e2, 1e9, 10),
    {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
    noise=0.01,
    seed=0,
)

_behaviour = EndpointBehaviour.from_spectrum(SPECTRUM)
_pool = tuple(POOL_CSV.split(","))  # type: ignore[name-defined]  # noqa: F821 - set by the harness
TEXTS = [
    Circuit(node).to_string()
    for n in range(1, LIMIT + 1)  # type: ignore[name-defined]  # noqa: F821 - set by the harness
    for node in enumerate_topologies(_pool, n)
    if is_feasible(node, _behaviour)
]


def screen_stride(index: int, total: int) -> str:
    """Screen every ``total``-th candidate, starting at ``index``.

    Early abandon is switched off here on purpose. It is shared state -- the best cost seen so
    far at each complexity -- and a worker pool would have to gossip about it; what is being
    measured is raw screening throughput against worker count, which that would only muddy.
    """
    mine = TEXTS[index::total]
    started = time.perf_counter()
    for text in mine:
        # An unfittable candidate still costs its screen, which is what is being timed.
        with contextlib.suppress(Exception):
            screen(
                text,
                SPECTRUM,
                seed=0,
                popsize=SCREEN_BUDGET.popsize,
                maxiter=SCREEN_BUDGET.maxiter,
                tol=SCREEN_TOL,
            )
    out: dict[str, Any] = {
        "n": len(mine),
        "seconds": time.perf_counter() - started,
        "total": len(TEXTS),
    }
    return json.dumps(out)
