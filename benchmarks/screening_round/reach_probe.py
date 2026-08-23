"""Did the real search reach the truth's equivalence class? Asked the cheap way.

`evolve_probe.py` answered this by refitting its forty best candidates at full budget and
comparing responses, which is faithful and — at a nine-element cap — costs more than the search
it is instrumenting. It does not have to. The class ties **exactly** on screening cost
(thirteen topologies at 0.0165602 on the R,C,L arena, next best 0.0339), so "the best screening
cost seen reached 0.01656" is the same signal for a hundredth of the price. The expensive probe
is what established that the two agree; this one is what can be run on every arm.
"""

from __future__ import annotations

import argparse
import math
import time

from autocircuit.core import discover as D
from autocircuit.core.simulate import log_frequencies, simulate

TRUTH = "p(R1,C1)-p(R2,C2)-p(R3,C3)"
PARAMS = {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8, "R3.R": 8e4, "C3.C": 5e-7}
#: The class's screening cost, measured by enumerating the whole R,C,L arena (`landscape.py`).
CLASS_COST = 0.0165602


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--time-limit", type=float, default=200.0)
    ap.add_argument("--max-elements", type=int, default=7)
    ap.add_argument("--pool", default="R,C,L")
    ap.add_argument("--warm", type=float, default=0.0)
    args = ap.parse_args()

    spectrum = simulate(TRUTH, log_frequencies(1e-2, 1e7, 10), PARAMS, noise=0.01, seed=0)
    pool = tuple(args.pool.split(","))

    seen: list[tuple[float, int]] = []
    original = D._Evaluator.evaluate

    def spy(self, node, generation, parent=None):  # type: ignore[no-untyped-def]
        out = original(self, node, generation, parent)
        if out is not None:
            seen.append((D._fit_cost(out.result), len(out.circuit.leaves)))
        return out

    D._Evaluator.evaluate = spy  # type: ignore[method-assign]
    hits = 0
    try:
        for seed in range(args.seeds):
            seen.clear()
            started = time.perf_counter()
            # The refit tier is what makes a large cap slow, and it is not what is being asked
            # about here, so the search is called directly rather than through `discover`.
            D._evolve(
                spectrum, pool=pool, generations=30, population=40,
                max_elements=args.max_elements, min_elements=2, seed=seed,
                weighting="modulus", search_restarts=1, search_popsize=8,
                search_maxiter=40, search_tol=1e-4, final_restarts=5, n_refine=1,
                time_limit=args.time_limit, seeds=None, started=started,
                warm_accept=args.warm,
            )
            elapsed = time.perf_counter() - started
            best = min((c for c, _n in seen), default=math.inf)
            reached = best <= CLASS_COST * 1.02
            hits += int(reached)
            sizes: dict[int, int] = {}
            for _c, n in seen:
                sizes[n] = sizes.get(n, 0) + 1
            share = " ".join(f"n{k}:{v / len(seen):.0%}" for k, v in sorted(sizes.items()))
            print(f"  seed {seed}: {'REACHED' if reached else 'missed '} "
                  f"best cost {best:.6g} (class {CLASS_COST:.6g})  "
                  f"fits {len(seen):,}  {elapsed:.0f} s  "
                  f"{elapsed / max(len(seen), 1):.2f} s/fit  {share}", flush=True)
    finally:
        D._Evaluator.evaluate = original  # type: ignore[method-assign]
    print(f"  ==> reached the class in {hits}/{args.seeds} seeds  "
          f"[pool={pool} max_elements={args.max_elements} warm={args.warm}]")


if __name__ == "__main__":
    main()
