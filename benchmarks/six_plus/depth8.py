"""Experiment X10 of ``docs/TOPOLOGY_6PLUS_PLAN.md`` section 5.13: does growth reach eight
elements, and does raising :data:`~autocircuit.core.discover.GROWTH_REACH` past its old value of
2 stay safe across shapes?

The old value caps growth at ``complete_up_to + 2`` regardless of ``max_elements``, which with
the production exhaustive limit of 5 is a hard ceiling of seven elements -- exactly the largest
size ``benchmarks/six_plus/recovery.py`` (X4) ever measured. An eight-element topology can never
be screened under the old value no matter how the caller sets ``max_elements`` or
``growth_width``. This file asks the two questions that follow from that:

* **Reach.** With the reach raised to 3, does the pipeline actually recover an eight-element
  truth, and how much does it cost?
* **Safety across shapes.** Does raising the shared reach constant help or hurt the *other* two
  shapes this project already tracks (``docs/TOPOLOGY_6PLUS_PLAN.md``'s parallel/series/mixed
  taxonomy, `truths.py`), or does it only work for the one shape it was motivated by?

Three eight-element truths, one per shape, each first passing the same four-part admission screen
`truths.py` requires (leverage, unresolved, deviation, feasibility) before being used to measure
anything:

* ``par8`` -- ``p(R1,C1)-p(R2,C2)-p(R3,C3)-p(R4,C4)``, a four-block Maxwell-Wagner chain (the
  motivating case: a user asked to fit exactly this shape, "4 series Maxwell-Wagner blocks",
  reliably and automatically). Parallel shape by `truths.shape_of` -- every element sits inside a
  parallel block, none is a direct child of the top-level Series node.
* ``mix8`` -- ``p(p(R1,C1)-R2,C2)-p(R3,C3)-p(R4,C4)``, extending ``mix7`` by replacing its
  trailing series R4 with a fourth parallel block, keeping the parallel-inside-parallel shape.
* ``ser8`` -- ``C1-R1-L1-p(R2,C2-L2,C3-R3)``, extending ``ser7``'s pattern. **The first attempt,**
  ``C1-R1-L1-p(R2,C2-L2,C3,R3)`` (``R3`` as a fourth bare parallel branch alongside ``R2``),
  failed identically at 4.762% weakest leverage on all five tuner seeds -- not a lottery but a
  structural degeneracy, two plain-resistor branches in parallel are only ever seen through their
  combined value. Putting ``R3`` in series with ``C3`` instead (so no branch is a bare resistor
  paired with another bare resistor) passed at 9.780% on the second tuner seed.

**[measured] Reach 3 recovers par8 (10/10 seeds: reported, on the front, and recommended) and
mix8 (5/5, same three) at a median ~35-45 s and ~700 topologies fitted -- roughly the same
1.5-1.7x cost `docs/TOPOLOGY_6PLUS_PLAN.md` section 5.5 already measured for growth reaching six
elements. Reach 2 recovers neither (0/13 combined, structurally: no eight-element candidate is
ever screened).** ``ser8`` stays at 0/5 under reach 3 -- unchanged from the already-documented
``ser6``/``ser7`` failure at reach 2 (section 5.9's X4), not a new regression reach 3 introduces.
The admission screen already says this is not an identifiability gap (9.780% weakest leverage,
comfortably above the 1% noise floor): the beam's insertion moves do not reach a series-shaped
eight-element topology from the five-element level, the same search-side failure already on
record for six and seven elements. A separate, pre-existing measurement
(``benchmarks/six_plus/x8_oracle.json``, case ``8el/8par`` -- exactly ``par8``'s topology) already
shows the *parameter* side is not a concern here either: the tier-1 screening budget alone
(``restarts=1, popsize=8, maxiter=40``) reaches the global optimum 12/12.

**Over-growth control.** Giving ``par8`` a further element of headroom (``max_elements=9`` with
reach raised to 4, so growth *can* reach nine) does not cause the report to prefer a spurious
nine-element candidate: 10/10 seeds still recommend the true eight-element topology. Parsimony
holds at this depth the same way it is already measured to hold at five through seven elements.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/depth8.py --out benchmarks/six_plus/x10_depth8.json
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

from recovery import Referee  # noqa: E402
from truths import COMPONENT_WINDOW, EC_WINDOW, Truth, screen, shape_of, spectrum_for  # noqa: E402

import autocircuit.core.discover as discover_mod  # noqa: E402
from autocircuit.core.circuit import count_elements  # noqa: E402
from autocircuit.core.discover import discover  # noqa: E402

#: Tuned by `truths.tune_until_screened` (maximise the weakest parameter leverage, then require
#: the full four-part screen to pass) at the module's own noise level and window. Values are
#: literals for the same reason `truths.py`'s own entries are: tuning is a one-off search, not
#: something every run should redo.
PAR8 = Truth(
    "par8",
    "parallel",
    "p(R1,C1)-p(R2,C2)-p(R3,C3)-p(R4,C4)",
    {
        "R1.R": 365986.0,
        "C1.C": 2.25497e-05,
        "R2.R": 14.4613,
        "C2.C": 3.89417e-09,
        "R3.R": 532.849,
        "C3.C": 5.81793e-08,
        "R4.R": 19225.3,
        "C4.C": 1.15177e-06,
    },
    *EC_WINDOW,
)  # weakest leverage 8.224% (C3.C), tuner seed 0

MIX8 = Truth(
    "mix8",
    "mixed",
    "p(p(R1,C1)-R2,C2)-p(R3,C3)-p(R4,C4)",
    {
        "R1.R": 56.6182,
        "C1.C": 0.000305254,
        "R2.R": 1.04057,
        "C2.C": 1.24993e-05,
        "R3.R": 0.0575924,
        "C3.C": 9.39956e-07,
        "R4.R": 993.471,
        "C4.C": 0.00846825,
    },
    *EC_WINDOW,
)  # weakest leverage 8.166% (C3.C), tuner seed 0

SER8 = Truth(
    "ser8",
    "series",
    "C1-R1-L1-p(R2,C2-L2,C3-R3)",
    {
        "C1.C": 1.38701e-07,
        "R1.R": 0.0921907,
        "L1.L": 1.53918e-09,
        "R2.R": 7260.87,
        "C2.C": 1.45945e-09,
        "L2.L": 1.73991e-07,
        "C3.C": 1.44112e-11,
        "R3.R": 14.5316,
    },
    *COMPONENT_WINDOW,
)  # weakest leverage 9.780% (R2.R), tuner seed 1 -- see module docstring for the first,
# structurally degenerate attempt this replaced.

TRUTHS: tuple[Truth, ...] = (PAR8, MIX8, SER8)

for _truth in TRUTHS:
    _seen = shape_of(_truth.circuit)
    if _seen != _truth.shape:
        raise AssertionError(f"{_truth.id}: labelled {_truth.shape!r} but the tree says {_seen!r}")
    if _truth.n_elements != 8:
        raise AssertionError(f"{_truth.id}: expected 8 elements, circuit has {_truth.n_elements}")
del _truth, _seen

NOISE = 0.01
WORKERS = 8


@dataclass(frozen=True)
class Row:
    truth: str
    reach: int
    max_elements: int
    seed: int
    seconds: float
    n_evaluated: int
    grown_to: int | None
    reported: bool
    on_front: bool
    recommended: bool
    recommended_n_elements: int | None
    over_grown: bool | None


def run_one(truth: Truth, reach: int, max_elements: int, seed: int) -> Row:
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
        truth=truth.id,
        reach=reach,
        max_elements=max_elements,
        seed=seed,
        seconds=round(elapsed, 1),
        n_evaluated=result.n_evaluated,
        grown_to=result.grown_to,
        reported=reported,
        on_front=on_front,
        recommended=recommended,
        recommended_n_elements=rec_size,
        over_grown=None if rec_size is None else rec_size > truth.n_elements,
    )


def check_admission() -> None:
    """The same four-part screen `truths.py` requires before a truth measures anything."""
    for truth in TRUTHS:
        verdict = screen(truth, noise=NOISE)
        print(verdict.row())
        if not verdict.passed:
            raise SystemExit(f"{truth.id} fails the admission screen -- see truths.check()")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--sanity-seeds", type=int, default=1, help="seeds at the old reach=2, per truth"
    )
    parser.add_argument(
        "--reach3-seeds",
        type=int,
        default=5,
        help="seeds at reach=3, max_elements=8, per truth (par8 gets 10 regardless, per the "
        "module docstring's own claim)",
    )
    parser.add_argument(
        "--overgrow-seeds", type=int, default=10, help="seeds for the par8 over-growth control"
    )
    args = parser.parse_args()

    print("Admission screen (all three truths must pass before anything else runs):")
    check_admission()
    print()

    # Resume: each run costs 30-110s, so a chunked invocation (one shape or one arm per call)
    # must not redo work an earlier call already wrote.
    rows: list[dict[str, Any]] = []
    if args.out.exists():
        rows = json.loads(args.out.read_text(encoding="utf-8"))
        print(f"resuming with {len(rows)} rows already on disk")
    done = {(r["truth"], r["reach"], r["max_elements"], r["seed"]) for r in rows}

    def maybe_run(truth: Truth, reach: int, max_elements: int, seed: int) -> None:
        key = (truth.id, reach, max_elements, seed)
        if key in done:
            return
        row = run_one(truth, reach=reach, max_elements=max_elements, seed=seed)
        done.add(key)
        rows.append(vars(row))
        print(row)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print(f"== reach=2 sanity, seeds 1-{args.sanity_seeds}, all three shapes ==")
    for truth in TRUTHS:
        for seed in range(1, args.sanity_seeds + 1):
            maybe_run(truth, reach=2, max_elements=8, seed=seed)

    par8_seeds = max(args.reach3_seeds, 10)
    print("\n== reach=3, max_elements=8 ==")
    for truth in TRUTHS:
        n_seeds = par8_seeds if truth.id == "par8" else args.reach3_seeds
        for seed in range(1, n_seeds + 1):
            maybe_run(truth, reach=3, max_elements=8, seed=seed)

    print(
        f"\n== over-growth control: par8, reach=4, max_elements=9, seeds 1-{args.overgrow_seeds} =="
    )
    for seed in range(1, args.overgrow_seeds + 1):
        maybe_run(PAR8, reach=4, max_elements=9, seed=seed)

    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
