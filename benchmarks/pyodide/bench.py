"""The same measurements under CPython and under Pyodide, so the ratio means something.

Run this file directly for the CPython baseline; ``run_pyodide.mjs`` execs the very same file
inside Pyodide under Node. Sharing one script is the point -- a browser-versus-desktop number
is only worth having if both sides did identical work.

Prints one JSON object of median seconds per operation::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/pyodide/bench.py

Everything here runs single-threaded, because a browser has no ``multiprocessing``. That is
also why the headline number is a whole ``discover`` run at ``exhaustive_limit=4``: it is the
web default the plan proposes, and the only figure that settles whether it is usable.
"""

from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from collections.abc import Callable
from typing import Any


def _median(fn: Callable[[int], Any], repeats: int) -> float:
    samples = []
    for i in range(repeats):
        started = time.perf_counter()
        fn(i)
        samples.append(time.perf_counter() - started)
    return statistics.median(samples)


def main() -> dict[str, Any]:
    started = time.perf_counter()
    from autocircuit.core.circuit import Circuit
    from autocircuit.core.discover import discover
    from autocircuit.core.enumerate import (
        EndpointBehaviour,
        enumerate_topologies,
        is_feasible,
    )
    from autocircuit.core.fit import fit, screen
    from autocircuit.core.simulate import log_frequencies, simulate
    from autocircuit.core.validate import lin_kk

    import_s = time.perf_counter() - started

    small = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 10),
        {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-5},
        noise=0.01,
        seed=0,
    )
    large = simulate(
        "C1-R1-L1-SKINF1",
        log_frequencies(1e2, 1e9, 10),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
        noise=0.01,
        seed=0,
    )

    out: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "import_s": import_s,
    }

    out["fit_3param_s"] = _median(
        lambda i: fit(Circuit.parse("R1-p(R2,C1)"), small, seed=i), 3
    )
    out["fit_6param_s"] = _median(
        lambda i: fit(Circuit.parse("C1-R1-L1-SKINF1"), large, seed=i), 3
    )
    out["screen_3elem_s"] = _median(
        lambda i: screen(Circuit.parse("R1-p(R2,C1)"), small, seed=i, popsize=8, maxiter=40),
        5,
    )
    out["screen_4elem_s"] = _median(
        lambda i: screen(
            Circuit.parse("C1-R1-L1-SKINF1"), large, seed=i, popsize=8, maxiter=40
        ),
        5,
    )
    out["lin_kk_s"] = _median(lambda i: lin_kk(small), 3)

    pool = ("R", "C", "L", "CPE", "SKINF")

    def _enumerate(_i: int) -> int:
        behaviour = EndpointBehaviour.from_spectrum(large)
        return sum(
            1
            for n in range(1, 6)
            for node in enumerate_topologies(pool, n)
            if is_feasible(node, behaviour)
        )

    # Warm the enumerator's per-(pool, n) memoisation first: what the browser pays for
    # enumeration is the filtering, and a cold first call would fold in a one-off.
    out["enumerate_n5_candidates"] = _enumerate(0)
    out["enumerate_n5_cached_s"] = _median(_enumerate, 3)

    started = time.perf_counter()
    result = discover(
        small, pool=("R", "C"), mode="exhaustive", exhaustive_limit=4, workers=1, seed=0
    )
    out["discover_rc_n4_s"] = time.perf_counter() - started
    out["discover_rc_n4_screened"] = result.n_evaluated

    # The number the web phase has to live with: the flagship capacitor search at the proposed
    # browser default, single-threaded. Reported apart from the toy run above because this one
    # is the decision.
    started = time.perf_counter()
    result = discover(
        large, pool=pool, mode="exhaustive", exhaustive_limit=4, workers=1, seed=0
    )
    out["discover_capacitor_n4_s"] = time.perf_counter() - started
    out["discover_capacitor_n4_screened"] = result.n_evaluated
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
