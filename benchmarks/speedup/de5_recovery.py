"""docs/DE_KERNEL_PLAN.md Step 4, DE5 clause 4: end-to-end recovery on the nine
``six_plus`` truths, ``grow`` arm (the one that actually reaches the six- and seven-element
truths -- ``docs/TOPOLOGY_6PLUS_PLAN.md``'s own X4 baseline), 3 seeds each, once unpatched
(scipy) and once through the relaxed vectorized DE kernel. Reuses ``recovery.py``'s own
``run_one``/``Referee`` machinery directly rather than reimplementing it.

Bar (pre-registered): no truth moves from ``reported`` to not-``reported``.

Usage (PYTHONPATH needs both ``src`` and the repo root)::

    $env:PYTHONPATH = "...\\AutoCircuit\\src;...\\AutoCircuit"
    python benchmarks/speedup/de5_recovery.py [--workers 1] [--seeds 1,2,3]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SIX_PLUS = Path(__file__).resolve().parents[1] / "six_plus"
sys.path.insert(0, str(_SIX_PLUS))

from benchmarks.speedup.de_kernel_patch import use_relaxed_de  # noqa: E402
from recovery import ARMS, run_one  # noqa: E402
from truths import TRUTHS  # noqa: E402

GROW_ARM = next(a for a in ARMS if a.name == "grow")


def _run_all(seeds: list[int], workers: int) -> dict[tuple[str, int], bool]:
    out: dict[tuple[str, int], bool] = {}
    for truth in TRUTHS:
        for seed in seeds:
            row = run_one(truth, GROW_ARM, seed, workers)
            out[(truth.id, seed)] = row["reported"]
            print(
                f"  {truth.id:8s} seed={seed}  reported={row['reported']}  "
                f"on_front={row['on_front']}  recommended={row['recommended']}  "
                f"{row['seconds']:.0f}s",
                flush=True,
            )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seeds", default="1,2,3")
    args = parser.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]

    print(f"grow arm, {len(TRUTHS)} truths x {len(seeds)} seeds")
    print("--- baseline (scipy) ---")
    baseline = _run_all(seeds, args.workers)
    print("--- patched (relaxed vectorized DE) ---")
    with use_relaxed_de():
        patched = _run_all(seeds, args.workers)

    print()
    print("=" * 88)
    regressions = [k for k in baseline if baseline[k] and not patched[k]]
    improvements = [k for k in baseline if not baseline[k] and patched[k]]
    n_base = sum(baseline.values())
    n_patch = sum(patched.values())
    print(
        f"baseline reported: {n_base}/{len(baseline)}   "
        f"patched reported: {n_patch}/{len(patched)}"
    )
    if regressions:
        print(f"REGRESSIONS (reported -> not reported): {regressions}")
    else:
        print("no truth moved from reported to not-reported")
    if improvements:
        print(f"improvements (not reported -> reported): {improvements}")
    print(f"DE5 clause 4: {'PASSED' if not regressions else 'FAILED'}")
    print("=" * 88)


if __name__ == "__main__":
    main()
