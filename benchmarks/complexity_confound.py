"""PARAM_BUDGET_PLAN item 7, step 7.1: clear the `best_cost`/`ABANDON_FACTOR` confound.

`Circuit.complexity` is read by two different mechanisms (docs/PARAM_BUDGET_PLAN.md section 7):

* the Pareto front's dominance/sort key and `recommended`'s first sort key -- the actual
  question item 7 asks;
* the `best_cost`/`abandon_above` dictionaries keyed by `complexity`, which decide whether a
  screened candidate's local polish is skipped (:data:`ABANDON_FACTOR`). A collapsed key (arm B:
  ``complexity = n_params``) shares that threshold across more candidates -- exactly the
  mechanism ``docs/SEARCH_TIME_PLAN.md`` section 3.2 measured and rejected a shipped
  optimisation over ("a stale threshold can never change a result" was disproved there).

So before arm A/B's numbers are trusted, this runs a 2x2 (arm x ABANDON_FACTOR) on the three
`REFERENCES` at a cheap `exhaustive_limit`: if the arm A/B verdict is the same whether or not
early abandon can fire (``ABANDON_FACTOR = math.inf`` disables it, since :func:`_abandon_at`
returns infinity whenever the reference is not itself abandoned), mechanism 3 is not driving
whatever arm A/B difference exists and the full arm run (arms.py's own, larger arenas) can trust
its numbers as answering the complexity question and not the abandon-threshold one.

Usage::

    python benchmarks/complexity_confound.py --limit 4 --out confound.txt
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discovery_v2 import REFERENCES  # noqa: E402

import autocircuit.core.discover as discover_module  # noqa: E402
from autocircuit.core import elements as E  # noqa: E402
from autocircuit.core.discover import discover  # noqa: E402
from autocircuit.core.simulate import log_frequencies, simulate  # noqa: E402

#: Only these four classes' complexity differs from their own parameter count
#: (docs/PARAM_BUDGET_PLAN.md section 7, F3): W +0.5, CPE +0.5, SKINF +0.5, SKINW +1.0.
_SURCHARGED = (E.Warburg, E.ConstantPhaseElement, E.SkinFractional, E.SkinRoundWire)


@contextlib.contextmanager
def _arm_b() -> Iterator[None]:
    """Patch every surcharged element's `complexity` to its own `n_params`, restore after."""
    originals = {cls: cls.complexity for cls in _SURCHARGED}
    for cls in _SURCHARGED:
        cls.complexity = float(len(cls.params))
    try:
        yield
    finally:
        for cls, value in originals.items():
            cls.complexity = value


@contextlib.contextmanager
def _abandon_factor(value: float) -> Iterator[None]:
    original = discover_module.ABANDON_FACTOR
    discover_module.ABANDON_FACTOR = value
    try:
        yield
    finally:
        discover_module.ABANDON_FACTOR = original


def _run(limit: int, workers: int) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for reference in REFERENCES:
        data = simulate(
            reference.circuit,
            log_frequencies(reference.f_min, reference.f_max, 10),
            reference.params,
            noise=reference.noise,
            seed=0,
        )
        result = discover(
            data,
            pool=reference.pool,
            mode="exhaustive",
            exhaustive_limit=limit,
            seed=0,
            workers=workers,
        )
        recommended = result.recommended
        rows[reference.label] = {
            "recommended": recommended.circuit.to_string() if recommended else None,
            "recommended_canonical": (
                recommended.circuit.canonical_form() if recommended else None
            ),
            "pareto": [c.circuit.to_string() for c in result.pareto],
            "n_evaluated": result.n_evaluated,
        }
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--limit", type=int, default=4)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    cells: dict[str, dict[str, Any]] = {}
    # A context manager built from a `@contextmanager` generator is single-use, so each cell
    # gets a fresh one from its factory rather than sharing one across the inner loop.
    arm_factories = (("A", contextlib.nullcontext), ("B", _arm_b))
    default_abandon = discover_module.ABANDON_FACTOR
    for arm_name, arm_factory in arm_factories:
        for abandon_name, abandon_value in (("finite", default_abandon), ("inf", math.inf)):
            key = f"arm={arm_name} abandon={abandon_name}"
            print(f"running {key} ...", flush=True)
            with arm_factory(), _abandon_factor(abandon_value):
                cells[key] = _run(args.limit, args.workers)
            print(f"  done: {json.dumps(cells[key], indent=1)}", flush=True)

    args.out.write_text(json.dumps(cells, indent=1, sort_keys=True), encoding="utf-8")
    print(f"\nwrote {args.out}")

    # Verdict per reference: does the arm A/B recommendation differ, and does that difference
    # depend on whether early abandon can fire?
    print("\n=== verdict ===")
    for reference in REFERENCES:
        label = reference.label
        a_finite = cells["arm=A abandon=finite"][label]["recommended_canonical"]
        a_inf = cells["arm=A abandon=inf"][label]["recommended_canonical"]
        b_finite = cells["arm=B abandon=finite"][label]["recommended_canonical"]
        b_inf = cells["arm=B abandon=inf"][label]["recommended_canonical"]
        arm_differs_finite = a_finite != b_finite
        arm_differs_inf = a_inf != b_inf
        abandon_changes_a = a_finite != a_inf
        abandon_changes_b = b_finite != b_inf
        print(
            f"{label}: A/B differ @finite={arm_differs_finite} @inf={arm_differs_inf}  "
            f"abandon changes A={abandon_changes_a} B={abandon_changes_b}"
        )
        if arm_differs_finite != arm_differs_inf:
            print(
                "  -> CONFOUNDED: the A/B verdict depends on whether early abandon can fire; "
                "take the @inf pair as the real answer, and record this as a second "
                "SEARCH_TIME_PLAN section 3.2 measurement."
            )


if __name__ == "__main__":
    main()
