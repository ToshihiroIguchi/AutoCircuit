"""Idea 2a: successive halving for tier-1 screening -- probe a cheap fraction of the budget on
every candidate, keep only the top half, double the budget, repeat.

**The hypothesis this directly collides with.** `docs/TOPOLOGY_6PLUS_PLAN.md`'s basin-lottery
finding: "the tier-1 screen's verdict is a basin lottery for a minority of topologies and budget
does not fix it -- one circuit screens at 0.0141 or 33.78 on the seed alone." Successive halving's
entire premise is that a *cheap* probe's ranking predicts the *full-budget* ranking well enough to
discard the bottom half safely. If a topology's screening cost can swing >1000x from the RNG seed
alone at a *fixed* budget, a cheaper probe (fewer DE iterations, same seed-sensitivity mechanism)
should be *at least* as unreliable a ranking signal, and successive halving would then be discarding
good candidates at the very first, cheapest round -- before a doubled budget ever gets a chance to
correct it.

**Method.** Enumerate every 4-element (R,C)-pool topology (a manageable, exhaustive-stage-sized
set), screen each one at a quarter tier-1 budget and at the full tier-1 budget (one seed each,
matching how the production screen actually runs -- one seed, not averaged), and measure: (a)
Spearman rank correlation between the two cost rankings, and (b) what fraction of the *actual*
top-K (full-budget) candidates would have survived being in the top-2K at the cheap quarter-budget
round (the concrete quantity successive halving needs to be safe first-round pruning).

Decision rule, fixed before running: worth prototyping into `discover.py` only if the quarter-budget
round preserves at least 90% of the true top-K in its own top-2K, and Spearman rho > 0.8.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

_SPEEDUP_DIR = Path(__file__).resolve().parent
_BENCH_DIR = _SPEEDUP_DIR.parent
sys.path.insert(0, str(_SPEEDUP_DIR))

from truths import MW5, spectrum_for  # noqa: E402

from autocircuit.core.circuit import Circuit  # noqa: E402
from autocircuit.core.enumerate import enumerate_topologies  # noqa: E402
from autocircuit.core.fit import screen  # noqa: E402

N_ELEMENTS = 5
POOL = ("R", "C", "L", "CPE")
FULL_POPSIZE, FULL_MAXITER = 8, 40
QUARTER_POPSIZE, QUARTER_MAXITER = 8, 10  # 1/4 the iterations, same population
TOP_K = 20


def main() -> None:
    spectrum = spectrum_for(MW5, seed=0)

    texts = [Circuit(node).to_string() for node in enumerate_topologies(POOL, N_ELEMENTS)]
    print(f"{len(texts)} distinct {N_ELEMENTS}-element topologies from pool {POOL}")

    full_costs = []
    quarter_costs = []
    for text in texts:
        full_costs.append(
            screen(text, spectrum, seed=0, popsize=FULL_POPSIZE, maxiter=FULL_MAXITER)
        )
        quarter_costs.append(
            screen(text, spectrum, seed=0, popsize=QUARTER_POPSIZE, maxiter=QUARTER_MAXITER)
        )

    full_costs = np.array(full_costs)
    quarter_costs = np.array(quarter_costs)

    rho, pval = spearmanr(full_costs, quarter_costs)
    print(f"Spearman rank correlation (full vs quarter budget): rho={rho:.4f}, p={pval:.2e}")

    full_rank = np.argsort(full_costs)
    quarter_rank = np.argsort(quarter_costs)
    true_top_k = set(full_rank[:TOP_K].tolist())
    cheap_top_2k = set(quarter_rank[: 2 * TOP_K].tolist())
    preserved = len(true_top_k & cheap_top_2k) / len(true_top_k)
    print(f"fraction of true top-{TOP_K} preserved in cheap top-{2*TOP_K}: {preserved * 100:.1f}%")

    print(
        f"\ndecision rule (preserved>=90% AND rho>0.8): "
        f"{'PASS' if preserved >= 0.9 and rho > 0.8 else 'FAIL'}"
    )


if __name__ == "__main__":
    main()
