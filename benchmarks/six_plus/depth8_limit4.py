"""Follow-up to X10 (``depth8.py``): does raising ``GROWTH_REACH`` from 3 to 4 let growth reach
an eight-element truth when the *exhaustive* stage is capped at four elements instead of the
production default of five?

This question exists because of a gap in X10's own coverage, not because of a new user-facing
knob. X10 measured reach 3 exclusively from an ``exhaustive_limit=5`` base (``complete_up_to=5``,
so ``5 + 3 = 8``). The web UI's Discover panel, independently, has shipped an ``exhaustiveLimit``
default of 4 since it was introduced -- never reconciled with the CLI/core default of 5, and never
covered by any growth benchmark. A user who wants to keep the browser's "Element limit" at 4 (for
its own, lower exhaustive-search cost) and still reach an eight-element truth by turning growth on
needs ``complete_up_to + GROWTH_REACH >= 8``, i.e. reach 4, not reach 3 -- and reach 4 has only
ever been tried once, in X10's over-growth control, from a ``complete_up_to=5`` base (testing
9-element over-growth, not 8-element recovery from a 4-element base). This file runs the
missing cell.

Two questions, mirroring X10's own structure:

* **Reach.** From ``exhaustive_limit=4``, does ``GROWTH_REACH=4`` (``max_elements=8``) actually
  recover ``par8`` and ``mix8``, and leave ``ser8`` exactly as unrecovered as every other reach has
  measured it (a search/identifiability property of that shape, not a reach one)?
* **Safety.** Does reaching four levels down from a *shallower* exhaustive base cause over-growth
  on truths smaller than eight elements -- ``par5``, ``par6``, ``par7`` -- that the shallower base
  no longer covers exhaustively by itself (``par6`` and ``par7`` are now grown into rather than
  enumerated directly, since the exhaustive stage stops at 4)?

A confirmation arm also checks the predicted negative result this whole file exists to get past:
at the *current* shipped ``GROWTH_REACH=3`` and ``exhaustive_limit=4``, ``par8`` should never be
reached at all (``4 + 3 = 7 < 8``), regardless of ``max_elements``.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/depth8_limit4.py --out benchmarks/six_plus/x10b_limit4.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from depth8 import MIX8, PAR8, SER8  # noqa: E402
from recovery import Referee  # noqa: E402
from truths import BY_ID, Truth, screen, spectrum_for  # noqa: E402

import autocircuit.core.discover as discover_mod  # noqa: E402
from autocircuit.core.circuit import count_elements  # noqa: E402
from autocircuit.core.discover import discover  # noqa: E402

NOISE = 0.01
WORKERS = 8

TARGET_TRUTHS: tuple[Truth, ...] = (PAR8, MIX8, SER8)
CONTROL_TRUTHS: tuple[Truth, ...] = (BY_ID["par5"], BY_ID["par6"], BY_ID["par7"])


@dataclass(frozen=True)
class Row:
    arm: str
    truth: str
    truth_n_elements: int
    reach: int
    exhaustive_limit: int
    max_elements: int
    seed: int
    seconds: float
    n_evaluated: int
    complete_up_to: int | None
    grown_to: int | None
    reported: bool
    on_front: bool
    recommended: bool
    recommended_n_elements: int | None
    over_grown: bool | None


def run_one(
    arm: str, truth: Truth, *, reach: int, exhaustive_limit: int, max_elements: int, seed: int
) -> Row:
    spectrum = spectrum_for(truth, noise=NOISE, seed=seed)
    referee = Referee(truth, spectrum)

    original_reach = discover_mod.GROWTH_REACH
    discover_mod.GROWTH_REACH = reach
    try:
        started = time.perf_counter()
        result = discover(
            spectrum,
            pool=truth.pool,
            mode="exhaustive",
            workers=WORKERS,
            growth_width=4,
            screen_restarts=1,
            exhaustive_limit=exhaustive_limit,
            max_elements=max_elements,
            seed=0,
        )
        elapsed = time.perf_counter() - started
    finally:
        discover_mod.GROWTH_REACH = original_reach

    reported = any(referee.matches(c) for c in result.candidates)
    on_front = any(referee.matches(c) for c in result.pareto)
    recommended = result.recommended is not None and referee.matches(result.recommended)
    rec_size = (
        None if result.recommended is None else count_elements(result.recommended.circuit.root)
    )
    return Row(
        arm=arm,
        truth=truth.id,
        truth_n_elements=truth.n_elements,
        reach=reach,
        exhaustive_limit=exhaustive_limit,
        max_elements=max_elements,
        seed=seed,
        seconds=round(elapsed, 1),
        n_evaluated=result.n_evaluated,
        complete_up_to=result.complete_up_to,
        grown_to=result.grown_to,
        reported=reported,
        on_front=on_front,
        recommended=recommended,
        recommended_n_elements=rec_size,
        over_grown=None if rec_size is None else rec_size > truth.n_elements,
    )


def check_admission() -> None:
    for truth in (*TARGET_TRUTHS, *CONTROL_TRUTHS):
        verdict = screen(truth, noise=NOISE)
        print(verdict.row())
        if not verdict.passed:
            raise SystemExit(f"{truth.id} fails the admission screen -- see truths.check()")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--confirm-seeds", type=int, default=2)
    parser.add_argument("--par8-seeds", type=int, default=8)
    parser.add_argument("--mix8-seeds", type=int, default=5)
    parser.add_argument("--ser8-seeds", type=int, default=3)
    parser.add_argument("--control-seeds", type=int, default=5)
    args = parser.parse_args()

    print("Admission screen (every truth used must pass before anything else runs):")
    check_admission()
    print()

    rows: list[dict[str, Any]] = []
    if args.out.exists():
        rows = json.loads(args.out.read_text(encoding="utf-8"))
        print(f"resuming with {len(rows)} rows already on disk")
    done = {(r["arm"], r["truth"], r["reach"], r["exhaustive_limit"], r["max_elements"], r["seed"])
            for r in rows}

    def maybe_run(
        arm: str, truth: Truth, *, reach: int, exhaustive_limit: int, max_elements: int, seed: int
    ) -> None:
        key = (arm, truth.id, reach, exhaustive_limit, max_elements, seed)
        if key in done:
            return
        row = run_one(
            arm, truth, reach=reach, exhaustive_limit=exhaustive_limit,
            max_elements=max_elements, seed=seed,
        )
        done.add(key)
        rows.append(vars(row))
        print(row)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print("== confirm: reach=3 (shipped), exhaustive_limit=4, max_elements=7 -- par8 predicted "
          "0/N (4+3=7 < 8) ==")
    for seed in range(1, args.confirm_seeds + 1):
        maybe_run("confirm_cap", PAR8, reach=3, exhaustive_limit=4, max_elements=7, seed=seed)

    print("\n== reach=4, exhaustive_limit=4, max_elements=8 -- target shapes ==")
    for seed in range(1, args.par8_seeds + 1):
        maybe_run("reach4_target", PAR8, reach=4, exhaustive_limit=4, max_elements=8, seed=seed)
    for seed in range(1, args.mix8_seeds + 1):
        maybe_run("reach4_target", MIX8, reach=4, exhaustive_limit=4, max_elements=8, seed=seed)
    for seed in range(1, args.ser8_seeds + 1):
        maybe_run("reach4_target", SER8, reach=4, exhaustive_limit=4, max_elements=8, seed=seed)

    print("\n== reach=4, exhaustive_limit=4, max_elements=8 -- over-growth control on smaller "
          "truths ==")
    for truth in CONTROL_TRUTHS:
        for seed in range(1, args.control_seeds + 1):
            maybe_run(
                "overgrowth_control", truth, reach=4, exhaustive_limit=4, max_elements=8,
                seed=seed,
            )

    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
