"""KPI-0: is the truth even at the top of the frozen landscape?

This is the gatekeeper of the whole shortlisting round. Every topology-search candidate in
`docs/SEARCH_ALGORITHM_SURVEY.md` section 3.1 assumes the scoring function points at the truth
and only the *search* fails to reach it. If the truth is not near rank 1 under the tier-1
screening score, then no search algorithm can fix EV1's 1/9 and the shortlist has to be drawn
from the parameter side instead. One second of arithmetic decides which half of the survey is
worth measuring.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import _screening_score


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("landscape", type=Path)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    data = json.loads(args.landscape.read_text(encoding="utf-8"))
    rows = data["rows"]
    n_data = data["n_data"]
    truth_key = data["truth_canonical"]

    for r in rows:
        r["canonical"] = Circuit.parse(r["text"]).canonical_form()
        r["aicc"] = _screening_score(r["cost"], r["n_params"], n_data, "aicc")

    truth = next(r for r in rows if r["canonical"] == truth_key)
    costs = np.array([r["cost"] for r in rows])
    aiccs = np.array([r["aicc"] for r in rows])

    print(f"landscape: {args.landscape.name}  pool={data['pool']}  n<={data['n_max']}")
    print(f"topologies: {len(rows)}   built in {data['elapsed_s'] / 60:.1f} min")
    print(f"truth: {data['truth']}  ({truth['n_elements']} elem, {truth['n_params']} params)")
    print()

    rank_cost = int((costs < truth["cost"]).sum()) + 1
    rank_aicc = int((aiccs < truth["aicc"]).sum()) + 1
    print(f"KPI-0  rank of the truth by screening cost : {rank_cost} / {len(rows)}")
    print(f"KPI-0  rank of the truth by screening AICc : {rank_aicc} / {len(rows)}")
    same = [r for r in rows if r["n_elements"] == truth["n_elements"]]
    r_same = int(sum(1 for r in same if r["aicc"] < truth["aicc"])) + 1
    print(f"       rank within its own element count   : {r_same} / {len(same)}")
    print()

    order = np.argsort(aiccs)
    print(f"top {args.top} by screening AICc:")
    for i in order[: args.top]:
        r = rows[int(i)]
        mark = "  <-- TRUTH" if r["canonical"] == truth_key else ""
        print(
            f"  {r['aicc']:11.3f}  cost={r['cost']:.5g}  n={r['n_elements']} "
            f"p={r['n_params']}  {r['text']}{mark}"
        )
    if rank_aicc > args.top:
        print(f"  ... truth at rank {rank_aicc}: aicc={truth['aicc']:.3f} cost={truth['cost']:.5g}")

    # How many topologies fit at least as well as the truth does? That is the size of the
    # needle-equivalent set a search has to land in, and it bounds what any search can achieve.
    tol = truth["cost"] * 1.05
    near = [r for r in rows if r["cost"] <= tol]
    print()
    print(f"topologies within 5% of the truth's screening cost: {len(near)}")
    for r in sorted(near, key=lambda r: r["aicc"])[:10]:
        mark = "  <-- TRUTH" if r["canonical"] == truth_key else ""
        print(f"  aicc={r['aicc']:11.3f} n={r['n_elements']} {r['text']}{mark}")


if __name__ == "__main__":
    main()
