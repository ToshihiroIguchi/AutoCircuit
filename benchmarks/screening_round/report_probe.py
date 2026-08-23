"""Which of the two reporting stages drops a first-ranked candidate?

`docs/SEARCH_ALGORITHM_SCREENING.md` section 4.6 records one row that is a defect rather than a
measurement: at element cap 9, seed 0, the truth's equivalence class was visited nine times,
ranked 1 of 270 fits by screening AICc, and **not one of the nine reached `candidates`**.
`evolve_probe.py` can see that the class was visited and that it was not reported; it cannot see
which stage between the two lost it.

This probe instruments both. It wraps `_shortlist_candidates` and `_refine` and prints, for the
archive of one real `_evolve` run:

* which class members reached the archive, and where they rank in it;
* which of them the shortlist kept, **and at what position in the list `_refine` walks**;
* how many of the shortlist `_refine` attempted before its deadline, and which class members
  fell after that cut.

The class is read from `targets_rcl7.json` -- canonical forms verified by the response test in
`targets.py`, not by cost proximity, which section 4.6's own README records as over-counting by
7.6x. That file covers the class only up to seven elements, so a nine-element equivalent would
go unrecognised here; this is a superset test for the *drop*, which is all the diagnosis needs.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

from autocircuit.core import discover as D
from autocircuit.core.simulate import log_frequencies, simulate

TRUTH = "p(R1,C1)-p(R2,C2)-p(R3,C3)"
PARAMS = {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8, "R3.R": 8e4, "C3.C": 5e-7}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--time-limit", type=float, default=300.0)
    ap.add_argument("--max-elements", type=int, default=9)
    ap.add_argument("--warm", type=float, default=0.0)
    ap.add_argument("--pool", default="R,C,L")
    ap.add_argument("--targets", default="targets_rcl7.json")
    args = ap.parse_args()

    targets = set(json.loads(Path(args.targets).read_text())["targets"])
    print(f"{len(targets)} verified class members (canonical forms, up to 7 elements)")

    spectrum = simulate(TRUTH, log_frequencies(1e-2, 1e7, 10), PARAMS, noise=0.01, seed=0)

    captured: dict[str, Any] = {}
    orig_shortlist = D._shortlist_candidates
    orig_refine = D._refine

    def spy_shortlist(alive, n_refine, criterion=D.DEFAULT_CRITERION):  # type: ignore[no-untyped-def]
        out = orig_shortlist(alive, n_refine, criterion)
        captured["alive"] = list(alive)
        captured["shortlist"] = list(out)
        captured["criterion"] = criterion
        captured["shortlist_t"] = time.perf_counter()
        return out

    def spy_refine(candidates, spectrum_, weighting, restarts, seed, deadline=None, criterion=D.DEFAULT_CRITERION):  # type: ignore[no-untyped-def] # noqa: E501
        started = time.perf_counter()
        out, attempted = orig_refine(
            candidates, spectrum_, weighting, restarts, seed, deadline=deadline,
            criterion=criterion,
        )
        captured["refine_s"] = time.perf_counter() - started
        captured["deadline_in"] = None if deadline is None else deadline - started
        captured["attempted"] = attempted
        captured["refined"] = list(out)
        return out, attempted

    D._shortlist_candidates = spy_shortlist  # type: ignore[assignment]
    D._refine = spy_refine  # type: ignore[assignment]
    try:
        for seed in range(args.seed, args.seed + args.seeds):
            captured.clear()
            started = time.perf_counter()
            result = D.discover(
                spectrum,
                pool=tuple(args.pool.split(",")),
                mode="evolve",
                max_elements=args.max_elements,
                seed=seed,
                time_limit=args.time_limit,
                warm_accept=args.warm,
            )
            elapsed = time.perf_counter() - started
            _report(seed, elapsed, result, captured, targets)
    finally:
        D._shortlist_candidates = orig_shortlist  # type: ignore[assignment]
        D._refine = orig_refine  # type: ignore[assignment]


def _report(
    seed: int,
    elapsed: float,
    result: D.DiscoveryResult,
    captured: dict[str, Any],
    targets: set[str],
) -> None:
    criterion = captured["criterion"]
    alive = captured["alive"]
    shortlist = captured["shortlist"]
    refined = captured["refined"]

    ranked = sorted(alive, key=lambda c: c.score(criterion))
    rank_of = {id(c): i + 1 for i, c in enumerate(ranked)}
    # The order `_refine` actually walks, which is not the order the shortlist was built in.
    walk = D._refit_order(shortlist, criterion)
    pos_in_shortlist = {id(c): i for i, c in enumerate(walk)}
    refined_forms = {c.circuit.canonical_form() for c in refined}
    reported = {c.circuit.canonical_form() for c in result.candidates}
    attempted = captured["attempted"]

    print(f"\n=== seed {seed}: {elapsed / 60:.1f} min, generations {result.generations}")
    print(f"  archive (alive) {len(alive)}, shortlist {len(shortlist)}, "
          f"attempted {attempted}, refined {len(refined)}, reported {len(result.candidates)}")
    print(f"  refine took {captured['refine_s']:.1f} s against a deadline "
          f"{captured['deadline_in']:.1f} s away when it started")
    print(f"  refit_progress {result.refit_progress}")

    sizes: dict[int, int] = {}
    for c in shortlist:
        sizes[len(c.circuit.leaves)] = sizes.get(len(c.circuit.leaves), 0) + 1
    print(f"  shortlist by size: {sorted(sizes.items())}")
    print("  shortlist sizes in the order _refine walks them: "
          + ",".join(str(len(c.circuit.leaves)) for c in walk))

    members = [c for c in alive if c.circuit.canonical_form() in targets]
    if not members:
        print("  class members in the archive: 0 -- nothing to diagnose on this seed")
        return
    print(f"  class members in the archive: {len(members)}")
    for c in sorted(members, key=lambda c: c.score(criterion)):
        form = c.circuit.canonical_form()
        pos = pos_in_shortlist.get(id(c))
        where = (
            f"shortlist position {pos} of {len(shortlist)}"
            + ("  -- PAST THE CUT" if pos is not None and pos >= attempted else "")
            if pos is not None
            else "NOT SHORTLISTED"
        )
        print(
            f"    rank {rank_of[id(c)]:>4} of {len(alive)}  size {len(c.circuit.leaves)}  "
            f"score {c.score(criterion):.2f}  {where}  "
            f"refined={form in refined_forms}  reported={form in reported}  {form}"
        )

    n_short = sum(1 for c in members if id(c) in pos_in_shortlist)
    n_cut = sum(
        1
        for c in members
        if id(c) in pos_in_shortlist and pos_in_shortlist[id(c)] >= attempted
    )
    best = min(members, key=lambda c: c.score(criterion))
    print(f"  VERDICT: {len(members)} visited, {n_short} shortlisted, "
          f"{n_cut} of those past the deadline cut, "
          f"{sum(1 for c in members if c.circuit.canonical_form() in reported)} reported. "
          f"Best member ranks {rank_of[id(best)]} of {len(alive)} in the archive.")
    unreported = best.circuit.canonical_form() not in reported
    if math.isfinite(best.score(criterion)) and rank_of[id(best)] == 1 and unreported:
        print("  ^ the first-ranked candidate in the archive was not reported.")


if __name__ == "__main__":
    main()
