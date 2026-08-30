"""Score ``run_evolve_arms.py`` against the same referee the AutoEIS round used.

Nothing about the verdict is re-implemented here: ``Referee`` and ``score_autocircuit`` are
imported from ``score.py``, so a candidate counts as the truth in this table for exactly the
reasons it would have counted in ``docs/AUTOEIS_COMPARISON.md`` -- canonical-form identity, or a
response within ``EQUIVALENCE_RTOL`` of the truth's after refitting the topology with our fitter.

The ``auto`` row is the control from ``results_autocircuit.jsonl``, scored by the same call. It
is expected to be zero and the reason is structural, printed with the table: those runs stopped
at ``complete_up_to = 5`` and a six-element truth cannot be in a five-element candidate list.

Usage::

    python benchmarks/autoeis_round/score_evolve_arms.py --arena benchmarks/autoeis_round/arena_c
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from score import Referee, load_jsonl, read_spectrum, score_autocircuit

CONTROL_ARM = "auto"


def _relative_error(report: dict[str, Any] | None) -> float:
    """The best relative error on the reported front, the quantity EV1's table carries."""
    if not report:
        return math.nan
    # ``relative_error`` lives inside each candidate's ``statistics`` block, not at its top
    # level: reading it from the wrong place produced a column of NaN on the first scoring run.
    values = [
        (c.get("statistics") or {}).get("relative_error") for c in (report.get("candidates") or [])
    ]
    present = [v for v in values if v is not None]
    return min(present) if present else math.nan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True)
    parser.add_argument("--results", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None, help="write the table as JSON here")
    args = parser.parse_args()

    arena = json.loads((args.arena / "arena.json").read_text(encoding="utf-8"))
    truths = {t["truth_id"]: t for t in arena["truths"]}

    probe = [
        r
        for r in load_jsonl(args.results or (args.arena / "results_evolve_arms.jsonl"))
        if not r.get("smoke")
    ]
    if not probe:
        raise SystemExit("no non-smoke probe records yet")
    keys = sorted({(r["truth_id"], r["seed"]) for r in probe})
    control = {
        (r["truth_id"], r["seed"]): r for r in load_jsonl(args.arena / "results_autocircuit.jsonl")
    }

    rows: list[dict[str, Any]] = []
    for truth_id, seed in keys:
        truth = truths[truth_id]
        spectrum = read_spectrum(args.arena / "spectra" / f"{truth_id}_s{seed}.csv")
        referee = Referee(truth["circuit"], spectrum)
        here = [(CONTROL_ARM, control[(truth_id, seed)])] if (truth_id, seed) in control else []
        here += [(r["arm"], r) for r in probe if (r["truth_id"], r["seed"]) == (truth_id, seed)]
        for arm, record in here:
            outcome = score_autocircuit(record, referee, truth)
            report = record.get("report") or {}
            rows.append(
                {
                    "arm": arm,
                    "truth_id": truth_id,
                    "seed": seed,
                    "status": outcome.status,
                    "reported": outcome.reported_refitted,
                    "on_front": outcome.on_front,
                    "recommended": outcome.recommended,
                    "recommended_circuit": outcome.recommended_circuit,
                    "generations": report.get("generations"),
                    "n_evaluated": report.get("n_evaluated"),
                    "n_candidates": outcome.n_candidates,
                    "wall_seconds": record.get("wall_seconds"),
                    "cpu_seconds": record.get("cpu_seconds"),
                    "best_relative_error": _relative_error(report),
                }
            )
            print(
                f"  {arm:<15} {truth_id} s{seed}"
                f"  reported={int(outcome.reported_refitted)}"
                f" front={int(outcome.on_front)} rec={int(outcome.recommended)}"
                f"  gen={report.get('generations')} n={report.get('n_evaluated')}"
                f"  err={_relative_error(report) * 100:.2f}%"
                f"  {outcome.recommended_circuit}",
                flush=True,
            )

    arms = [CONTROL_ARM] + sorted({r["arm"] for r in rows if r["arm"] != CONTROL_ARM})
    print("\n| arm | runs | truth reported | on the front | is the recommendation |")
    print("|---|---:|---:|---:|---:|")
    for arm in arms:
        subset = [r for r in rows if r["arm"] == arm]
        if not subset:
            continue
        total = len(subset)
        print(
            f"| {arm} | {total} "
            f"| {sum(r['reported'] for r in subset)}/{total} "
            f"| {sum(r['on_front'] for r in subset)}/{total} "
            f"| {sum(r['recommended'] for r in subset)}/{total} |"
        )

    print("\nper arm: wall / cpu seconds, generations, topologies evaluated, best relative error")
    for arm in arms:
        subset = [r for r in rows if r["arm"] == arm]
        if not subset:
            continue
        walls = [r["wall_seconds"] for r in subset if r["wall_seconds"]]
        cpus = [r["cpu_seconds"] for r in subset if r["cpu_seconds"]]
        gens = [r["generations"] for r in subset if r["generations"] is not None]
        evals = [r["n_evaluated"] for r in subset if r["n_evaluated"] is not None]
        errs = [
            r["best_relative_error"] for r in subset if not math.isnan(r["best_relative_error"])
        ]
        cpu_text = f"{min(cpus):.0f}-{max(cpus):.0f}" if cpus else "not recorded"
        print(
            f"  {arm:<15} wall {min(walls):.0f}-{max(walls):.0f} s, cpu {cpu_text} s, "
            f"gen {min(gens)}-{max(gens)}, topologies {min(evals)}-{max(evals)}, "
            f"err {min(errs) * 100:.2f}-{max(errs) * 100:.2f}%"
        )

    print(
        "\nThe control's zero is structural, not stochastic: its runs stopped at "
        "complete_up_to = 5,\nso a six-element truth could not appear in the candidate list at "
        "all. Any recovery by an\nevolve arm is therefore a strict improvement, and no paired "
        "test is owed. Six runs per arm\ncannot measure a rate."
    )

    if args.out:
        args.out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
