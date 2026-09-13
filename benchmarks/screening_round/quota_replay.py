"""PARAM_BUDGET_PLAN item 6, step 6.1: replay the tier-2 quota over a frozen landscape.

No fitting. `_shortlist` takes exactly `[(cost, text)]` plus `n_refine`/`n_data`, and a frozen
landscape (`land_rclcpe6.json`, 21,057 screened topologies, pool R,C,L,CPE) already has that —
so both the element-count key `discover.py` ships today and the parameter-count key
`docs/PARAM_BUDGET_PLAN.md` §5 proposes can be replayed offline, at n = 21,057, for the cost of a
few seconds. This is not a gate; it is what the pre-registered constant decision (§6.2 of the
plan) is read off before any production code changes.

Only `land_rclcpe6.json` has a mixed-cost pool. `land_rcl6.json`/`land_rcl7.json`/
`land_series_rcl6.json`/`land_series_rcl7.json` are R,C,L only, where element count and parameter
count coincide -- replaying them would be vacuous under this change, so they are not read here.

Usage (from this directory, or anywhere with `benchmarks/screening_round` importable)::

    python quota_replay.py                       # default settings, both keys
    python quota_replay.py --n-refine 30 --min-per-size 5,3,2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from autocircuit.core.circuit import Circuit  # noqa: E402
from autocircuit.core.discover import (  # noqa: E402
    REFINE_CEILING_FACTOR,
    REFINE_COST_FACTOR,
    Ranked,
    _quota_by_size,
    _screening_score,
)

LANDSCAPE = Path(__file__).resolve().parent / "land_rclcpe6.json"
TARGETS = Path(__file__).resolve().parent / "targets_rclcpe6.json"


class Row(NamedTuple):
    text: str
    n_elements: int
    n_params: int
    cost: float
    canonical: str


def _load() -> tuple[list[Row], set[str], int]:
    landscape = json.loads(LANDSCAPE.read_text(encoding="utf-8"))
    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    if targets["landscape"] != LANDSCAPE.name:
        raise SystemExit(
            f"{TARGETS.name} was built from {targets['landscape']!r}, not {LANDSCAPE.name!r}"
        )
    truth_class = set(targets["targets"])
    rows = [
        Row(
            r["text"],
            r["n_elements"],
            r["n_params"],
            r["cost"],
            Circuit.parse(r["text"]).canonical_form(),
        )
        for r in landscape["rows"]
    ]
    # The truth's own canonical form is not itself listed among its equivalents in
    # targets_rclcpe6.json (see targets.py), so it is recovered from the landscape's own
    # truth_canonical field and added -- otherwise "does the truth class survive" would silently
    # never ask about the truth itself.
    truth_class.add(landscape["truth_canonical"])
    return rows, truth_class, landscape["n_data"]


def _quota_by(
    rows: list[Row], key: str, n_refine: int, min_per_size: int, n_data: int, criterion: str
) -> tuple[list[str], dict[int, int]]:
    """Replay `_quota_by_size` at a given bucket key and MIN_REFINE_PER_SIZE, no fitting."""
    ranked: list[Ranked[str]] = []
    by_bucket_all: dict[int, int] = {}
    for row in rows:
        bucket = row.n_elements if key == "elements" else row.n_params
        by_bucket_all[bucket] = by_bucket_all.get(bucket, 0) + 1
        score = _screening_score(row.cost, row.n_params, n_data, criterion)  # type: ignore[arg-type]
        ranked.append(Ranked(bucket, score, row.cost, row.text, row.text))

    # _quota_by_size hard-codes MIN_REFINE_PER_SIZE as a module constant; replay it locally so
    # different floors can be swept without monkeypatching the module for every setting.
    import autocircuit.core.discover as discover_module

    original = discover_module.MIN_REFINE_PER_SIZE
    discover_module.MIN_REFINE_PER_SIZE = min_per_size
    try:
        keep = _quota_by_size(ranked, n_refine)
    finally:
        discover_module.MIN_REFINE_PER_SIZE = original
    return keep, by_bucket_all


def _rank_of(rows: list[Row], keep: list[str], truth_class: set[str]) -> int | None:
    """1-based rank (by screening cost) of the best surviving truth-class member, or None."""
    by_text = {r.text: r for r in rows}
    hits = [by_text[t] for t in keep if by_text[t].canonical in truth_class]
    if not hits:
        return None
    best = min(h.cost for h in hits)
    return 1 + sum(1 for r in rows if r.cost < best)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--n-refine", type=int, default=30, help="REFINE_DEFAULT to replay")
    ap.add_argument(
        "--min-per-size",
        default="5,4,3,2,1",
        help="comma-separated MIN_REFINE_PER_SIZE settings to sweep",
    )
    ap.add_argument("--criterion", default="bic")
    args = ap.parse_args()

    rows, truth_class, n_data = _load()
    print(f"{len(rows)} rows, n_data={n_data}, truth class has {len(truth_class)} members")
    print(f"REFINE_COST_FACTOR={REFINE_COST_FACTOR} REFINE_CEILING_FACTOR={REFINE_CEILING_FACTOR}")
    print()

    for key in ("elements", "params"):
        n_buckets = len({(r.n_elements if key == "elements" else r.n_params) for r in rows})
        print(f"=== key={key} ({n_buckets} buckets) ===")
        for min_per_size in (int(x) for x in args.min_per_size.split(",")):
            keep, by_bucket = _quota_by(
                rows, key, args.n_refine, min_per_size, n_data, args.criterion
            )
            quota = max(min_per_size, args.n_refine // n_buckets)
            rank = _rank_of(rows, keep, truth_class)
            rank_str = "MISSING" if rank is None else f"rank {rank} of {len(rows)}"
            print(
                f"  MIN_REFINE_PER_SIZE={min_per_size:>2d}  "
                f"quota/bucket={quota:>3d}  shortlist={len(keep):>5d}  "
                f"truth class: {rank_str}"
            )
        print()


if __name__ == "__main__":
    main()
