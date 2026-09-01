"""Experiment X2: the identifiability ladder.

``docs/TOPOLOGY_6PLUS_PLAN.md`` section 4.3 asks a question no published curve answers (section
3.4): over (noise) x (points per decade) x (truth), where does a six- or seven-element truth stop
being distinguishable from every smaller circuit the same pool can build? Section 5.2 already
answers one point on this grid by reading two frozen landscapes at a fixed 1% noise, 10
points/decade: adding the sixth element cuts the best screening cost 2.74x on one truth and 1.29x
on another, and a genuinely five-element truth shows 1.007x -- "nothing". This script is that
single point turned into the grid, so the report can state a domain of applicability instead of
one anecdote.

**Method, matched to section 5.2's on purpose.** For each (truth, noise, points_per_decade) cell:
simulate the truth's own circuit at that noise and density, enumerate *every* topology the R,C,L
pool can build up to the truth's own element count (``enumerate_up_to``, the same space
``land_rcl6``/``land_rcl7`` freeze), screen all of them (``fit.screen``, tier-1, seed=0 -- the
same instrument section 5.2 and every ``screening_round`` arm uses), and take the best cost at
each size. ``gain = best(n-1) / best(n)`` is section 5.2's column, generalised. This deliberately
does *not* ask whether the truth's own topology is the best fit at its own size -- a different
topology of the same size beating the truth's own fit is itself part of what "not identifiable"
looks like at high noise or low density, and folding that into ``best(n)`` rather than reading the
truth's own screen cost is what makes this the same measurement as section 5.2, not a new one.

**Cost, why the six- and seven-element truths are not run at the same ``n_max``, and why the
pool is fixed at R, C, L.** All three are inherited from ``build_arenas.py``: R,C,L is what
section 5.2 measured (CPE alone cuts a truth's own 2.74x to 1.29x, section 5.2's second row, so
mixing it in here would confound pool with the noise/density axis this script exists to isolate).
``n_max`` is the truth's own element count -- 6 for ``par6``/``ser6``/``mix6`` (2174 topologies),
7 for ``par7``/``ser7``/``mix7`` (11033) -- because only ``best(n-1)`` and ``best(n)`` are read;
enumerating one level past the truth answers a question (does the search overshoot) this script is
not asking. **12 grid cells per truth, 6 truths.** At the per-topology screening rate this
machine's other landscapes were built at, the six-element truths cost minutes each and the
seven-element ones cost roughly 5x that -- run ``--dry-run`` before committing machine time, and
use ``--only`` to pilot on one truth of each size before the full grid.

Resumable and idempotent, like every other driver in this package: results already on disk for a
(truth, noise, points_per_decade) triple are skipped, so an interrupted run keeps its hours.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/identifiability.py --dry-run
    python benchmarks/six_plus/identifiability.py --out benchmarks/six_plus/x2_ladder.json `
        --only par6,ser6 --workers 8
    python benchmarks/six_plus/identifiability.py --out benchmarks/six_plus/x2_ladder.json `
        --workers 8
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from truths import BY_ID, Truth  # noqa: E402

from autocircuit.core.circuit import Circuit  # noqa: E402
from autocircuit.core.enumerate import enumerate_up_to  # noqa: E402
from autocircuit.core.fit import screen  # noqa: E402
from autocircuit.core.simulate import log_frequencies, simulate  # noqa: E402
from autocircuit.core.spectrum import Spectrum  # noqa: E402

#: The six pre-registered truths section 4.3 names -- the three five-element rows are the
#: negative control for a different experiment (section 4.7) and are not part of this grid.
TRUTH_IDS: tuple[str, ...] = ("par6", "ser6", "mix6", "par7", "ser7", "mix7")
NOISE_LEVELS: tuple[float, ...] = (0.001, 0.003, 0.01, 0.03)
POINTS_PER_DECADE: tuple[int, ...] = (5, 10, 20)
#: Distinct from the arenas' data_seed=0 (``build_arenas.py``/``landscape.py``) so this grid's
#: draws are not the same noise realisation the existing 1%/10-ppd point was read from.
DATA_SEED = 1

_WORKER: dict[str, Any] = {}


def _init(f: Any, z: Any) -> None:
    _WORKER["spectrum"] = Spectrum(f, z)


def _screen_one(text: str) -> float:
    try:
        return float(screen(text, _WORKER["spectrum"], seed=0))
    except Exception:
        return float("inf")


def _enumerate_texts(pool: tuple[str, ...], n_max: int) -> tuple[list[str], list[int]]:
    texts: list[str] = []
    sizes: list[int] = []
    for node in enumerate_up_to(pool, n_max):
        circuit = Circuit(node)
        texts.append(circuit.to_string())
        sizes.append(len(circuit.leaves))
    return texts, sizes


def run_cell(truth: Truth, noise: float, ppd: int, workers: int) -> dict[str, Any]:
    freqs = log_frequencies(truth.f_min, truth.f_max, ppd)
    spectrum = simulate(truth.circuit, freqs, truth.params, noise=noise, seed=DATA_SEED)
    texts, sizes = _enumerate_texts(truth.pool, truth.n_elements)

    started = time.perf_counter()
    if workers > 1:
        with multiprocessing.Pool(
            workers, initializer=_init, initargs=(spectrum.f, spectrum.z)
        ) as executor:
            costs = list(executor.imap(_screen_one, texts, chunksize=32))
    else:
        _init(spectrum.f, spectrum.z)
        costs = [_screen_one(t) for t in texts]
    elapsed = time.perf_counter() - started

    best_by_size: dict[int, float] = {}
    for size, cost in zip(sizes, costs, strict=True):
        if cost < best_by_size.get(size, float("inf")):
            best_by_size[size] = cost
    n = truth.n_elements
    best_below = best_by_size.get(n - 1, float("inf"))
    best_at = best_by_size.get(n, float("inf"))
    gain = float("inf") if best_at == 0 else best_below / best_at

    return {
        "truth": truth.id,
        "n_elements": n,
        "noise": noise,
        "points_per_decade": ppd,
        "n_points": int(2 * len(spectrum.f)),
        "n_topologies": len(texts),
        "data_seed": DATA_SEED,
        f"best_at_{n - 1}": best_below,
        f"best_at_{n}": best_at,
        "gain": gain,
        "elapsed_s": round(elapsed, 1),
    }


def plan(only: set[str] | None) -> list[tuple[str, float, int]]:
    ids = [t for t in TRUTH_IDS if only is None or t in only]
    # Six-element truths first: cheaper (n_max=6, 2174 topologies) than the seven-element ones
    # (n_max=7, 11033), so an interrupted run keeps the cheaper half complete.
    ids.sort(key=lambda t: BY_ID[t].n_elements)
    return [(t, noise, ppd) for t in ids for noise in NOISE_LEVELS for ppd in POINTS_PER_DECADE]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--only", default=None, help="comma-separated truth ids")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    only = None if args.only is None else {s.strip() for s in args.only.split(",")}
    todo_all = plan(only)
    if not todo_all:
        raise SystemExit("no truth selected")

    by_size: dict[int, int] = {}
    for t, _, _ in todo_all:
        by_size[BY_ID[t].n_elements] = by_size.get(BY_ID[t].n_elements, 0) + 1
    print(f"{len(todo_all)} cells planned across {len(by_size)} truth size(s)")
    for n_max, count in sorted(by_size.items()):
        n_topo = sum(1 for _ in enumerate_up_to(("R", "C", "L"), n_max))
        print(f"  n={n_max}: {count} cells x {n_topo} topologies = {count * n_topo} screens")
    if args.dry_run:
        return
    if args.out is None:
        raise SystemExit("--out is required unless --dry-run")

    rows: list[dict[str, Any]] = []
    if args.out.exists():
        rows = json.loads(args.out.read_text(encoding="utf-8"))
        print(f"resuming with {len(rows)} rows already on disk", flush=True)
    done = {(r["truth"], r["noise"], r["points_per_decade"]) for r in rows}
    todo = [cell for cell in todo_all if cell not in done]
    print(f"{len(todo)} cells to go", flush=True)

    started_all = time.perf_counter()
    for index, (truth_id, noise, ppd) in enumerate(todo, start=1):
        row = run_cell(BY_ID[truth_id], noise, ppd, args.workers)
        rows.append(row)
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(
            f"[{index}/{len(todo)}] {truth_id} noise={noise:.3%} ppd={ppd}"
            f"  gain={row['gain']:.3f}  {row['elapsed_s']:.0f}s",
            flush=True,
        )
    print(f"\nall done in {(time.perf_counter() - started_all) / 60:.1f} min")


if __name__ == "__main__":
    main()
