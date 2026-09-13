"""PARAM_BUDGET_PLAN item 7, steps 7.2-7.4: does `Circuit.complexity`'s surcharge earn itself?

Arm A is today's table (W +0.5, CPE +0.5, SKINF +0.5, SKINW +1.0 over their own parameter count
-- docs/PARAM_BUDGET_PLAN.md section 7, F3). Arm B is `complexity = n_params` for every element,
patched via `complexity_confound._arm_b`. Step 7.1's 2x2 (this same module) already cleared the
`ABANDON_FACTOR`/`best_cost` confound on the three `REFERENCES` at `exhaustive_limit=4`, tied on
every reference (arm A and arm B recommend the identical circuit, with or without early abandon)
-- so any arm A/B difference below is read on the arenas that can actually separate them, and the
`REFERENCES` cell is reused rather than rerun.

Decision rule (section 7, written before this ran): arm A ships only if arm A's
`recommended_correct` is strictly better, or arm B's `by_criterion_overfits` is strictly worse. A
tie collapses `complexity` to `n_params`.

Three arenas, all reusing this project's own existing harnesses rather than a new fixture:

* `criterion_selection.py`'s negative controls (ref_capacitor, ref_mw, ref_randles, par5, ser5,
  mix5 at aic and bic) -- the only place `by_criterion_overfits` is defined.
* `six_plus/param_dense_truths.py`'s three CPE/SKINF-dense truths x 3 seeds via
  `param_dense_baseline.run_one` -- read against Phase 2's own basin-lottery baseline (1/3, 2/3,
  1/3 recommended on the element axis with the truth's own topology exhaustively enumerated), not
  against an assumed 100%.

Usage::

    python benchmarks/complexity_surcharge.py --out surcharge.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "six_plus"))

from complexity_confound import _arm_b  # noqa: E402
from criterion_selection import (  # noqa: E402
    REFERENCE_IDS,
    run_reference_cell,
    run_six_plus_cell,
)
from param_dense_baseline import run_one  # noqa: E402
from param_dense_truths import TRUTHS as PARAM_DENSE_TRUTHS  # noqa: E402
from truths import BY_ID as SIX_PLUS_BY_ID  # noqa: E402

_SIX_PLUS_NEGATIVE_CONTROLS = ("par5", "ser5", "mix5")
_CRITERIA = ("aic", "bic")
# One seed here, not two: each of these 24 cells costs the same as a full-cost discover() call
# (matching docs/PARAM_BUDGET_PLAN.md item 6's own Q1/Q3 slice, which measured ~53 min at 2
# seeds), and this script runs the whole slice twice (arm A, arm B). param_dense below keeps its
# own three seeds since that is what Phase 2's baseline already used and this arm run is read
# against that baseline directly.
_SEEDS = (0,)
_PARAM_DENSE_SEEDS = (1, 2, 3)


def _run_criterion_controls(workers: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ref_id, ref in REFERENCE_IDS.items():
        for criterion in _CRITERIA:
            for seed in _SEEDS:
                rows.append(run_reference_cell(ref, ref_id, seed, criterion, workers, grow=False))
    for truth_id in _SIX_PLUS_NEGATIVE_CONTROLS:
        truth = SIX_PLUS_BY_ID[truth_id]
        for criterion in _CRITERIA:
            for seed in _SEEDS:
                rows.append(run_six_plus_cell(truth, 0.01, 10, seed, criterion, workers))
    return rows


def _run_param_dense(workers: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for truth in PARAM_DENSE_TRUTHS:
        for seed in _PARAM_DENSE_SEEDS:
            rows.append(run_one(truth, seed, workers))
    return rows


def _run_arm(workers: int) -> dict[str, list[dict[str, Any]]]:
    return {
        "criterion_controls": _run_criterion_controls(workers),
        "param_dense": _run_param_dense(workers),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    print("running arm A (today's table) ...", flush=True)
    arm_a = _run_arm(args.workers)
    print("running arm B (complexity = n_params) ...", flush=True)
    with _arm_b():
        arm_b = _run_arm(args.workers)

    args.out.write_text(
        json.dumps({"A": arm_a, "B": arm_b}, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(f"wrote {args.out}")

    print("\n=== criterion_controls: by_criterion_overfits (negative controls only) ===")
    for criterion in _CRITERIA:
        for name, arm in (("A", arm_a), ("B", arm_b)):
            rows = [
                r
                for r in arm["criterion_controls"]
                if r["criterion"] == criterion and r["by_criterion_overfits"] is not None
            ]
            n_overfit = sum(1 for r in rows if r["by_criterion_overfits"])
            print(f"  {criterion} arm={name}: {n_overfit}/{len(rows)} overfit")

    print("\n=== criterion_controls: recommended_correct ===")
    for criterion in _CRITERIA:
        for name, arm in (("A", arm_a), ("B", arm_b)):
            rows = [r for r in arm["criterion_controls"] if r["criterion"] == criterion]
            n_correct = sum(1 for r in rows if r["recommended_correct"])
            print(f"  {criterion} arm={name}: {n_correct}/{len(rows)} recommended_correct")

    print("\n=== param_dense: reported/on_front/recommended ===")
    for name, arm in (("A", arm_a), ("B", arm_b)):
        for field in ("reported", "on_front", "recommended"):
            n = sum(1 for r in arm["param_dense"] if r[field])
            print(f"  arm={name} {field}: {n}/{len(arm['param_dense'])}")

    print("\n=== cell-by-cell diff, criterion_controls ===")

    def key(r: dict[str, Any]) -> tuple[Any, ...]:
        return (r["source"], r["truth"], r["seed"], r["criterion"])

    a_by_key = {key(r): r for r in arm_a["criterion_controls"]}
    b_by_key = {key(r): r for r in arm_b["criterion_controls"]}
    mismatches = 0
    for k in sorted(a_by_key):
        ra, rb = a_by_key[k], b_by_key[k]
        diffs = {
            f: (ra[f], rb[f])
            for f in ("recovered", "recommended_correct", "by_criterion_overfits")
            if ra[f] != rb[f]
        }
        if diffs:
            mismatches += 1
            print(f"  {k}: {diffs}")
    print(f"  {mismatches} of {len(a_by_key)} cells differ")

    print("\n=== cell-by-cell diff, param_dense ===")

    def pkey(r: dict[str, Any]) -> tuple[Any, ...]:
        return (r["truth"], r["seed"])

    a_by_pkey = {pkey(r): r for r in arm_a["param_dense"]}
    b_by_pkey = {pkey(r): r for r in arm_b["param_dense"]}
    p_mismatches = 0
    for k in sorted(a_by_pkey):
        ra, rb = a_by_pkey[k], b_by_pkey[k]
        diffs = {
            f: (ra[f], rb[f])
            for f in ("reported", "on_front", "recommended", "recommended_circuit")
            if ra[f] != rb[f]
        }
        if diffs:
            p_mismatches += 1
            print(f"  {k}: {diffs}")
    print(f"  {p_mismatches} of {len(a_by_pkey)} cells differ")


if __name__ == "__main__":
    main()
