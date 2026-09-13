"""Idea 2c, measured as planned (not citation-only): does removing the generation-boundary
barrier (batch dispatch -> continuous as-completed dispatch) improve worker throughput at
workers=8 on heterogeneous-cost fits, the way it should if idle time comes from waiting for the
slowest member of a batch?

This targets the *dispatch mechanism* directly with the production `screen()` cost function,
rather than re-running the full genetic loop (which `docs/SEARCH_TIME_PLAN.md` section 4.3's T4
already improved once, by merging two sequential per-generation dispatches into one). Build a
batch of topologies with genuinely heterogeneous cost (mixing CPE-bearing and CPE-free candidates,
since `docs/SEARCH_ALGORITHM_SCREENING.md` already measured a 2x per-fit cost gap between them --
exactly the kind of heterogeneity that makes a synchronous batch only as fast as its slowest
member). Compare wall-clock time to complete the same total set of `screen()` calls at
`workers=8` under (a) `ProcessPoolExecutor.map` in fixed-size batches (mirrors the production
per-generation barrier) and (b) `as_completed`-driven continuous dispatch (a worker is handed a
new task the moment it frees, never waiting for a whole batch).

Decision rule, fixed before running: worth prototyping into `_evolve` only if continuous dispatch
is faster by a clear, repeatable margin (>15%) at workers=8.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

_SPEEDUP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SPEEDUP_DIR))

from truths import MW5, spectrum_for  # noqa: E402

from autocircuit.core.circuit import Circuit  # noqa: E402
from autocircuit.core.enumerate import enumerate_topologies  # noqa: E402
from autocircuit.core.fit import screen  # noqa: E402
from autocircuit.core.spectrum import Spectrum  # noqa: E402

WORKERS = 8
BATCH_SIZE = 8  # mirrors a small population's per-generation chunk


def _screen_task(args: tuple[str, Spectrum]) -> float:
    text, spectrum = args
    return screen(text, spectrum, seed=0)


def build_heterogeneous_batch(n: int) -> list[str]:
    """Mix CPE-bearing (slow) and CPE-free (fast) topologies for real cost heterogeneity."""
    cpe_texts = [
        Circuit(node).to_string() for node in enumerate_topologies(("R", "C", "L", "CPE"), 5)
    ]
    cpe_only = [t for t in cpe_texts if "CPE" in t][: n // 2]
    plain_texts = [
        Circuit(node).to_string() for node in enumerate_topologies(("R", "C", "L"), 5)
    ][: n // 2]
    return (cpe_only + plain_texts)[:n]


def run_batched(tasks: list[tuple[str, Spectrum]]) -> float:
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        for i in range(0, len(tasks), BATCH_SIZE):
            chunk = tasks[i : i + BATCH_SIZE]
            list(ex.map(_screen_task, chunk))
    return time.time() - t0


def run_continuous(tasks: list[tuple[str, Spectrum]]) -> float:
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(_screen_task, task): task for task in tasks}
        for fut in as_completed(futures):
            fut.result()
    return time.time() - t0


def main() -> None:
    spectrum = spectrum_for(MW5, seed=0)
    n = 64
    texts = build_heterogeneous_batch(n)
    print(f"{len(texts)} topologies ({sum('CPE' in t for t in texts)} CPE-bearing)")
    tasks = [(t, spectrum) for t in texts]

    t_batched = run_batched(tasks)
    t_continuous = run_continuous(tasks)

    speedup = (t_batched - t_continuous) / t_batched * 100 if t_batched > 0 else 0.0
    print(f"batched (barrier every {BATCH_SIZE}): {t_batched:.2f}s")
    print(f"continuous (as-completed):            {t_continuous:.2f}s")
    print(f"speedup: {speedup:.1f}%")
    print(f"decision rule (>15% faster): {'PASS' if speedup > 15.0 else 'FAIL'}")


if __name__ == "__main__":
    main()
