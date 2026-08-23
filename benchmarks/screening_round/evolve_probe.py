"""Where does the real search lose the answer -- before the shortlist, or after it?

The frozen landscape says this reference's topology search is easy: every arm reaches the
truth's exact-equivalence class inside ~150 evaluations, on both arena sizes, at both element
caps, and the class is ~1% of the space on the realistic pool too. EV1 measures 1/3 on the same
reference. Those two cannot both be a complete description, and the difference is whatever the
frozen model abstracts away.

Three candidates, and this probe separates them by instrumenting the real `_evolve`:

1. **Never visited.** No topology in the class was ever evaluated -- then the frozen model's
   proposal accounting is wrong and the search really is the problem.
2. **Visited and mis-scored.** A class member was evaluated but its tier-1 fit landed in a
   basin far from the one the frozen table holds, so it scored badly and was discarded. Then the
   problem is the *screening fit's reliability at restarts=1*, not the topology search.
3. **Visited, scored, and dropped anyway.** It reached the archive with a good score and still
   did not reach `candidates` -- then the loss is in `_shortlist_candidates` or `_refine`.

`n_evaluated` is `len(cache)` and counts entries that were never fitted, so the probe also
reports how many of the "topologies evaluated" EV1 quotes were real fits.
"""

from __future__ import annotations

import argparse
import math
import time

import numpy as np

from autocircuit.core import discover as D
from autocircuit.core.fit import fit
from autocircuit.core.simulate import log_frequencies, simulate

TRUTH = "p(R1,C1)-p(R2,C2)-p(R3,C3)"
PARAMS = {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8, "R3.R": 8e4, "C3.C": 5e-7}
POOL = ("R", "C", "L", "CPE")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--time-limit", type=float, default=300.0)
    ap.add_argument("--max-elements", type=int, default=7)
    ap.add_argument("--warm", type=float, default=math.inf)
    ap.add_argument("--pool", default="R,C,L,CPE")
    args = ap.parse_args()

    spectrum = simulate(TRUTH, log_frequencies(1e-2, 1e7, 10), PARAMS, noise=0.01, seed=0)
    truth_fit = fit(TRUTH, spectrum, seed=0)
    z_truth = truth_fit.z_model
    magnitude = np.abs(z_truth)
    print(f"truth full-budget cost {truth_fit.statistics.chi2_reduced:.6g} "
          f"rel err {truth_fit.relative_error:.4%}")

    seen: list[tuple[str, float, float, int]] = []
    original = D._Evaluator.evaluate

    def spy(self, node, generation, parent=None):  # type: ignore[no-untyped-def]
        before = len(self.cache)
        out = original(self, node, generation, parent)
        if out is not None and len(self.cache) >= before:
            seen.append(
                (out.circuit.canonical_form(), D._fit_cost(out.result),
                 out.score("aicc"), out.circuit.to_string())
            )
        return out

    D._Evaluator.evaluate = spy  # type: ignore[method-assign]
    try:
        for seed in range(args.seeds):
            seen.clear()
            started = time.perf_counter()
            result = D.discover(
                spectrum, pool=tuple(args.pool.split(",")), mode="evolve",
                max_elements=args.max_elements,
                seed=seed, time_limit=args.time_limit, warm_accept=args.warm,
            )
            elapsed = time.perf_counter() - started

            # A class member is one whose *own* response, refitted at full budget, matches the
            # truth's -- the rule `_large_truth_verdict` uses. Only topologies that already
            # screened near the truth's cost can qualify, so only those are refitted.
            best = {}
            for key, cost, score, text in seen:
                if key not in best or cost < best[key][0]:
                    best[key] = (cost, score, text)
            truth_cost = min((c for c, _s, _t in best.values()), default=math.inf)
            near = sorted(best.items(), key=lambda kv: kv[1][0])[:40]
            members: list[tuple[str, float, float]] = []
            failures = 0
            # The canonical form is NOT a parseable circuit string -- it is a normalised label
            # with brackets and no element numbers -- and the first version of this probe fed it
            # straight to `fit`, so every refit raised, every raise was swallowed by the `except`
            # below, and the probe reported "class members visited: 0" on a run whose best
            # screening AICc was the class's own value to two decimals. An empty result that
            # looks like an answer is this project's characteristic failure; the failure counter
            # is here so it cannot happen silently a second time.
            for key, (cost, score, text) in near:
                try:
                    refit = fit(text, spectrum, seed=0)
                except Exception:
                    failures += 1
                    continue
                z = refit.z_model
                if z.shape == z_truth.shape and float(
                    np.max(np.abs(z - z_truth) / magnitude)
                ) <= D.EQUIVALENCE_RTOL:
                    members.append((key, cost, score))

            reported = {c.circuit.canonical_form() for c in result.candidates}
            on_front = {c.circuit.canonical_form() for c in result.pareto}
            member_keys = {k for k, _c, _s in members}
            best_score = min((s for _c, s, _t in best.values()), default=math.inf)
            member_best = min((s for _k, _c, s in members), default=math.inf)

            print(f"\nseed {seed}: {elapsed / 60:.1f} min, generations {result.generations}")
            print(f"  n_evaluated (len cache) {result.n_evaluated:,}; "
                  f"real fits recorded {len(best):,}")
            print(f"  best screening cost seen {truth_cost:.6g}; "
                  f"best screening AICc {best_score:.2f}")
            print(f"  class members VISITED: {len(members)}"
                  f"{'  <-- none, so the search never got there' if not members else ''}")
            if members:
                print(f"  best class member's screening AICc {member_best:.2f} "
                      f"(rank {sum(1 for _c, s, _t in best.values() if s < member_best) + 1} "
                      f"of {len(best)})")
                print(f"  class members REPORTED: {len(member_keys & reported)}; "
                      f"on the front: {len(member_keys & on_front)}")
            print(f"  reported rows {len(result.candidates)}, front {len(result.pareto)}, "
                  f"best front rel err "
                  f"{min((c.relative_error for c in result.pareto), default=math.nan):.2%}")
    finally:
        D._Evaluator.evaluate = original  # type: ignore[method-assign]


if __name__ == "__main__":
    main()
