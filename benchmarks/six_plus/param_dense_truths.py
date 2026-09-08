"""Parameter-dense negative-control truths (``docs/PARAM_BUDGET_PLAN.md`` section 8, item E.1).

**Why this module exists.** F7 of that plan measured that every truth defined anywhere in this
repository is parameter-lean: the nine truths in :mod:`truths`, the three ``REFERENCES`` and the
three ``LARGE_REFERENCES`` all sit at a params/elements ratio of 1.00-1.33, while the space a
parameter budget actually enumerates reaches 2.0. A budget change scored only against those
fifteen truths would pass for free -- a vacuous pass of the kind ``docs/HANDOFF.md`` section 3
already lists several of -- because none of them is *small in elements and large in parameters*,
which is exactly the class a parameter budget deletes relative to today's element budget. This
module builds that missing class before any budget is wired into ``discover()``, per Phase 2 of
``docs/PARAM_BUDGET_PLAN.md``.

**Two readings, and the second matters more than the first.** Given each truth's own admission
screen below and a run of ``discover()`` at both an element cap and a matching parameter budget:

1. *Recovery* -- how much is lost by switching axes, stated rather than avoided.
2. *Honesty* -- when a truth sits outside the parameter budget (by construction, every truth
   here is outside a same-*element*-cap budget once the budget's ``m``-per-element ceiling is
   below the truth's own ratio), does the report's coverage sentence correctly decline
   completeness, or does it confidently attach a completeness claim to a wrong in-budget
   recommendation? The plan's own pre-registered rule: a budget that fails the honesty reading
   does not ship at any default, regardless of every other gate.

**Reused machinery, one extension.** :class:`~truths.Truth`, :func:`~truths.spectrum_for`,
:func:`~truths.parameter_leverage`, :func:`~truths.survives_feasibility`, :func:`~truths.screen`
and :func:`~truths.check` are all generic over the circuit string and pool -- nothing in them
assumes R/C/L. Only :func:`~truths.tune` needed a hook (``ranges=``), added to that module rather
than duplicated here, so a CPE's ``Q`` and a SKINF's ``A``/``n`` get tuning bounds instead of the
R/C/L-shaped ``(1e-3, 1e3)`` fallback.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/param_dense_truths.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from truths import (  # noqa: E402
    EC_WINDOW,
    NOISE,
    Truth,
    check,
    tune_until_screened,
)

from autocircuit.core.circuit import Circuit, count_params  # noqa: E402

#: Tuning bounds for every field this module's truths use. R/C/L match ``truths.TUNE_RANGES``
#: exactly, so a truth built from those codes alone tunes identically either way; Q, A and n are
#: new. Q and A are the CPE/SKINF scale prefactors and span a physically plausible range for an
#: electrochemical-style spectrum (matching the EC_WINDOW truths below); n is the shared fractional
#: exponent, bounded a little inside the elements' own hard limits (0.02, 1.0) / (0.05, 0.95) so
#: the tuner does not sit the search boundary at a discontinuity in ``ConstantPhaseElement``'s or
#: ``SkinFractional``'s own clipping.
TUNE_RANGES: dict[str, tuple[float, float]] = {
    "R": (1e-2, 1e6),
    "C": (1e-12, 1e-2),
    "L": (1e-12, 1e-2),
    "Q": (1e-9, 1e-1),
    "A": (1e-6, 1e3),
    "n": (0.1, 0.9),
}

#: Values chosen by :func:`~truths.tune_until_screened` (``--tune``, ``TUNE_RANGES`` above), not
#: by hand -- ``truths.py``'s own docstring is why hand-picking is not attempted here. All three
#: passed the four-part screen on the tuner's first seed (0), at 8.79-9.90% weakest leverage.
TRUTHS: tuple[Truth, ...] = (
    # 5 elements, 8 parameters (ratio 1.6): every element but one is a CPE.
    Truth(
        "cpe_triple",
        "mixed",
        "p(R1,CPE1)-p(R2,CPE2)-CPE3",
        {
            "R1.R": 0.470506,
            "CPE1.Q": 2.47434e-06,
            "CPE1.n": 0.899557,
            "R2.R": 173.044,
            "CPE2.Q": 0.000132465,
            "CPE2.n": 0.9,
            "CPE3.Q": 0.0103155,
            "CPE3.n": 0.9,
        },
        *EC_WINDOW,
        pool=("R", "C", "L", "CPE"),
    ),
    # 5 elements, 7 parameters (ratio 1.4): one plain capacitor keeps this short of the others.
    Truth(
        "cpe_c_mix",
        "mixed",
        "p(R1,CPE1)-C1-p(R2,CPE2)",
        {
            "R1.R": 245824,
            "CPE1.Q": 2.43914e-07,
            "CPE1.n": 0.9,
            "C1.C": 1.42022e-05,
            "R2.R": 443.335,
            "CPE2.Q": 3.20994e-09,
            "CPE2.n": 0.899933,
        },
        *EC_WINDOW,
        pool=("R", "C", "L", "CPE"),
    ),
    # 5 elements, 8 parameters (ratio 1.6): exercises SKINF specifically, since F3's complexity
    # surcharge table names it as one of the four elements the surcharge question turns on.
    Truth(
        "skinf_cpe",
        "mixed",
        "p(R1,SKINF1)-p(R2,SKINF2)-CPE1",
        {
            "R1.R": 283483,
            "SKINF1.A": 0.584956,
            "SKINF1.n": 0.899987,
            "R2.R": 190.475,
            "SKINF2.A": 994.254,
            "SKINF2.n": 0.899903,
            "CPE1.Q": 0.0994258,
            "CPE1.n": 0.899769,
        },
        *EC_WINDOW,
        pool=("R", "C", "L", "CPE", "SKINF"),
    ),
)

BY_ID: dict[str, Truth] = {t.id: t for t in TRUTHS}

#: What had to move from the first guess, filled in once the tuner has run. Follows
#: ``truths.ADJUSTMENTS``'s convention: a truth that needed no adjustment is absent.
ADJUSTMENTS: dict[str, str] = {}


def ratio(truth: Truth) -> float:
    """Free parameters per element -- the axis this whole module exists to exercise."""
    node = Circuit.parse(truth.circuit).root
    return count_params(node) / truth.n_elements


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="run the identifiability screen")
    parser.add_argument(
        "--tune",
        action="store_true",
        help="search for parameter values maximising the weakest leverage, and print them",
    )
    parser.add_argument("--noise", type=float, default=NOISE)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    for truth in TRUTHS:
        print(
            f"{truth.id:12s} {truth.circuit:35s} {truth.n_elements} el, "
            f"{count_params(Circuit.parse(truth.circuit).root)} params, "
            f"ratio {ratio(truth):.2f}, pool={','.join(truth.pool)}"
        )

    if args.tune:
        for truth in TRUTHS:
            values, worst, used = tune_until_screened(truth, noise=args.noise, ranges=TUNE_RANGES)
            print(f"\n# {truth.id}: weakest leverage {worst * 100:.3f}% (tuner seed {used})")
            print(f'        "{truth.circuit}",')
            print("        {")
            for name, value in values.items():
                print(f'            "{name}": {value:.6g},')
            print("        },")
        return

    if not args.check:
        return

    verdicts = check(TRUTHS, noise=args.noise)
    failed = [v.truth_id for v in verdicts if not v.passed]
    print()
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    else:
        print("All truths pass the four-part screen.")

    if args.out is not None:
        payload: list[dict[str, Any]] = [
            {
                "truth_id": v.truth_id,
                "leverage": v.leverage,
                "min_leverage": v.min_leverage,
                "n_below_noise": v.n_below_noise,
                "n_unresolved": v.n_unresolved,
                "worst_deviation": v.worst_deviation,
                "feasible": v.feasible,
                "passed": v.passed,
            }
            for v in verdicts
        ]
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
