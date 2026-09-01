"""Experiment X3 (``docs/TOPOLOGY_6PLUS_PLAN.md`` sections 4.3 and 5.12): a decision rule that
fires when, and only when, the next element is real.

Growth (section 6, ``discover.growth_width``) ships **off by default** because the search half is
measured and the report half is not: the search reliably reaches a genuinely six- or seven-element
truth's class (X4, section 5.9), but nothing decides *whether to trust what it grew to* against a
truth that only needed five. The current runs test (``discover._is_underfitted``) is the wrong
instrument for that job -- ``docs/AUTOEIS_COMPARISON.md`` section 2.2 measured it reading z in
[-0.45, 0.67] on five- and six-element truths that plainly needed a sixth element, so the genetic
fallback it is supposed to arm never fired once in forty scored comparisons.

Four candidates, scored on one labelled set built from ``truths.py``'s nine pre-registered truths
over the same (noise, points-per-decade) grid X2 (``identifiability.py``) already used:

  (a) **the current runs test** -- the control. Applied exactly as ``discover._is_underfitted``
      applies it: to the residuals of the best-fitting model at the smaller size.
  (b) **a nested F-test** between the best model at the smaller size and its own one-element
      extensions. Nested *by construction* -- the larger model is built by inserting one element
      into the smaller one's own parsed tree (``enumerate._insertions``), not by taking the
      independently-best topology of the larger size, which need not extend anything. This is the
      one place in this project ``core/stats.f_test``'s nesting assumption is actually licensed.
  (c) **a parametric bootstrap** of (b)'s statistic. The inserted element's parameter sits at a
      *boundary* of its own range at the null (shorted or opened reduces it to its parent), which
      makes the asymptotic F-distribution's regularity conditions not apply -- resimulating from
      the smaller model at its own fitted values and refitting both models on each draw reads the
      null off the data instead of off a table.
  (d) **X9's pole count** (``order.stabilisation_order``, the one estimator of the three built
      that needs no user-supplied noise level). Applied as a margin rather than an absolute count,
      because no exact element-count-to-pole-order map exists for a circuit containing a series
      inductor (``order.py``'s ``rcl_relax`` note): the raw spectrum's estimated order is compared
      against the order the *same* estimator reports on a clean, noise-free simulation of the
      smaller model's own fitted circuit -- "does the actual data show more structure than the
      smaller model alone would, even without noise?"

**The labelled set, and why it has nine rows per grid cell and not six.** X2's own grid only
carries the six- and seven-element truths -- every cell there is a case where growing one element
*is* correct, so it can only ever measure a recovery rate. Section 4.7's negative control is what
this experiment adds: for ``par5``/``ser5``/``mix5`` the boundary tested is (5 -> 6), the same
move the pipeline would consider after finishing the exhaustive stage at the production default
``exhaustive_limit=5``, and the correct answer there is "no, do not grow" -- fitting a sixth
element to five-element data can only be explaining noise. The six two- and seven-element truths
test the mirror boundary: (5 -> 6) for ``par6``/``ser6``/``mix6``, (6 -> 7) for
``par7``/``ser7``/``mix7``, where growing *is* correct. 9 truths x 12 grid cells (4 noise levels x
3 points-per-decade) = 108 rows, each carrying all four candidates' verdicts plus the ground truth,
so a single script produces the whole ROC pair (recovery rate, false-positive rate) per candidate
without repeating the expensive part four times.

**What "the best model at the smaller size" means here, and the simplification this makes.**
Production's ``_is_underfitted`` reads the runs test off the single best-fitting member of the
*whole* refit shortlist, which can be any size the per-size AICc quota kept. This script uses the
best-scoring topology at *exactly* the smaller size instead -- the boundary case that matters for
a growth decision taken right after the exhaustive stage completes that size, and the one that
keeps the F-test's parent well-defined. That is a stated simplification, not an oversight.

Cost, and why the grid is the same size as X2's rather than larger: enumerating the smaller level
is one level cheaper than X2's own per-cell enumeration (level 5 for the six truths and the
five-element negative controls, level 6 for the seven-element truths, both a strict subset of what
X2 already enumerated one level up), one-element insertions of a *single* parent topology are far
cheaper than a full extra level, and the two publish-grade refits plus the bootstrap's screening
pairs are the dominant added cost. Run ``--dry-run`` first; use ``--only`` and a small
``--boot-reps`` to pilot before committing machine time to the full grid.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/trigger.py --dry-run
    python benchmarks/six_plus/trigger.py --out benchmarks/six_plus/x3_trigger.json `
        --only par5,par6 --boot-reps 20 --workers 8
    python benchmarks/six_plus/trigger.py --out benchmarks/six_plus/x3_trigger.json `
        --boot-reps 100 --workers 8
    python benchmarks/six_plus/trigger.py --summarize benchmarks/six_plus/x3_trigger.json
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from order import estimate_stabilisation  # noqa: E402
from truths import BY_ID, Truth  # noqa: E402

from autocircuit.core.circuit import Circuit, CircuitError, count_elements, simplify  # noqa: E402
from autocircuit.core.enumerate import _insertions, enumerate_up_to, is_plausible  # noqa: E402
from autocircuit.core.fit import fit, screen  # noqa: E402
from autocircuit.core.simulate import log_frequencies, simulate  # noqa: E402
from autocircuit.core.spectrum import Spectrum  # noqa: E402
from autocircuit.core.stats import FTEST_ALPHA, f_test  # noqa: E402
from autocircuit.core.validate import RUNS_Z_LIMIT, _runs_z  # noqa: E402

#: (from_size, to_size, is the extra element real?) per truth. The five-element truths test the
#: negative-control boundary (5 -> 6, never real); the six- and seven-element truths test their
#: own last boundary (5 -> 6, 6 -> 7 respectively, always real). See the module docstring.
TRUTH_BOUNDARIES: dict[str, tuple[int, int, bool]] = {
    "par5": (5, 6, False),
    "ser5": (5, 6, False),
    "mix5": (5, 6, False),
    "par6": (5, 6, True),
    "ser6": (5, 6, True),
    "mix6": (5, 6, True),
    "par7": (6, 7, True),
    "ser7": (6, 7, True),
    "mix7": (6, 7, True),
}

#: Matches ``identifiability.py`` exactly, so the two grids are directly comparable.
NOISE_LEVELS: tuple[float, ...] = (0.001, 0.003, 0.01, 0.03)
POINTS_PER_DECADE: tuple[int, ...] = (5, 10, 20)
DATA_SEED = 1

DEFAULT_BOOT_REPS = 100

_WORKER: dict[str, Any] = {}


def _init(f: Any, z: Any) -> None:
    _WORKER["spectrum"] = Spectrum(f, z)


def _screen_one(text: str) -> float:
    try:
        return float(screen(text, _WORKER["spectrum"], seed=0))
    except Exception:
        return float("inf")


def _boot_worker(
    args: tuple[int, str, dict[str, float], Any, float, str, str],
) -> tuple[float, float]:
    """One bootstrap replicate: resimulate from the smaller model, screen both models on it."""
    seed, base_text, base_values, freqs, noise, lower_text, ext_text = args
    spectrum = simulate(base_text, freqs, base_values, noise=noise, seed=seed)
    try:
        cost_lower = float(screen(lower_text, spectrum, seed=0))
    except Exception:
        cost_lower = float("inf")
    try:
        cost_ext = float(screen(ext_text, spectrum, seed=0))
    except Exception:
        cost_ext = float("inf")
    return cost_lower, cost_ext


def _enumerate_texts(pool: tuple[str, ...], n_max: int) -> list[str]:
    return [Circuit(node).to_string() for node in enumerate_up_to(pool, n_max)]


def _one_element_extensions(parent_text: str, pool: tuple[str, ...], target_size: int) -> list[str]:
    """Every distinct, plausible one-element extension of ``parent_text`` at ``target_size``."""
    parent_node = Circuit.parse(parent_text).root
    out: list[str] = []
    seen: set[str] = set()
    for child in _insertions(parent_node, pool):
        try:
            circuit = Circuit(simplify(child))
        except CircuitError:
            continue
        if count_elements(circuit.root) != target_size or not is_plausible(circuit):
            continue
        text = circuit.to_string()
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def run_cell(
    truth: Truth, noise: float, ppd: int, *, workers: int, boot_reps: int, boot_seed_base: int
) -> dict[str, Any]:
    from_size, to_size, real = TRUTH_BOUNDARIES[truth.id]
    freqs = log_frequencies(truth.f_min, truth.f_max, ppd)
    spectrum = simulate(truth.circuit, freqs, truth.params, noise=noise, seed=DATA_SEED)

    lower_texts = _enumerate_texts(truth.pool, from_size)
    # Only the level exactly at ``from_size`` is needed here, not everything below it.
    lower_texts = [t for t in lower_texts if count_elements(Circuit.parse(t).root) == from_size]

    started = time.perf_counter()
    with multiprocessing.Pool(
        max(1, workers), initializer=_init, initargs=(spectrum.f, spectrum.z)
    ) as pool_exec:
        lower_costs = list(pool_exec.imap(_screen_one, lower_texts, chunksize=32))
        best_lower_text = lower_texts[
            int(min(range(len(lower_costs)), key=lambda i: lower_costs[i]))
        ]

        ext_texts = _one_element_extensions(best_lower_text, truth.pool, to_size)
        ext_costs = list(pool_exec.imap(_screen_one, ext_texts, chunksize=32))
        best_ext_text = ext_texts[int(min(range(len(ext_costs)), key=lambda i: ext_costs[i]))]

        # Publish-grade refits of the nested pair -- what every candidate below is computed from.
        fit_lower = fit(best_lower_text, spectrum, seed=0)
        fit_ext = fit(best_ext_text, spectrum, seed=0)

        # (a) the current runs test, applied to the smaller model's own residuals.
        runs_z = _runs_z(fit_lower.residuals)
        a_fires = bool(not math.isnan(runs_z) and runs_z < RUNS_Z_LIMIT)

        # (b) the asymptotic nested F-test.
        n_data = fit_lower.statistics.n_data
        k_lower = fit_lower.statistics.n_params
        k_ext = fit_ext.statistics.n_params
        ft = f_test(fit_lower.statistics.ssr, k_lower, fit_ext.statistics.ssr, k_ext, n_data)
        b_stat = ft.f if ft is not None else 0.0
        b_p = ft.p if ft is not None else 1.0
        b_fires = bool(ft is not None and ft.significant)

        # (c) parametric bootstrap of the same statistic under the smaller model's own null.
        boot_tasks = [
            (
                boot_seed_base + i,
                best_lower_text,
                fit_lower.params,
                spectrum.f,
                noise,
                best_lower_text,
                best_ext_text,
            )
            for i in range(boot_reps)
        ]
        boot_pairs = (
            list(pool_exec.imap(_boot_worker, boot_tasks, chunksize=4)) if boot_reps else []
        )

    boot_f: list[float] = []
    for cost_lower, cost_ext in boot_pairs:
        boot_ft = f_test(cost_lower, k_lower, cost_ext, k_ext, 2 * spectrum.n)
        boot_f.append(boot_ft.f if boot_ft is not None else 0.0)
    c_p = (
        (sum(1 for x in boot_f if x >= b_stat) + 1) / (len(boot_f) + 1) if boot_f else float("nan")
    )
    c_fires = bool(not math.isnan(c_p) and c_p < FTEST_ALPHA)

    # (d) X9's pole count, as a margin over the smaller model's own clean self-order.
    self_spectrum = simulate(fit_lower.circuit, spectrum.f, fit_lower.params, noise=0.0)
    observed_order, _detail = estimate_stabilisation(spectrum, noise)
    self_order, _detail2 = estimate_stabilisation(self_spectrum, 0.0)
    d_margin = observed_order - self_order
    d_fires = bool(d_margin >= 1)

    elapsed = time.perf_counter() - started
    return {
        "truth": truth.id,
        "from_size": from_size,
        "to_size": to_size,
        "real": real,
        "noise": noise,
        "points_per_decade": ppd,
        "n_points": int(2 * spectrum.n),
        "n_lower_topologies": len(lower_texts),
        "n_extensions": len(ext_texts),
        "best_lower": best_lower_text,
        "best_extension": best_ext_text,
        "runs_z": runs_z,
        "a_fires": a_fires,
        "f_stat": b_stat,
        "f_p": b_p,
        "b_fires": b_fires,
        "boot_reps": len(boot_f),
        "boot_p": c_p,
        "c_fires": c_fires,
        "observed_order": observed_order,
        "self_order": self_order,
        "d_margin": d_margin,
        "d_fires": d_fires,
        "elapsed_s": round(elapsed, 1),
    }


def plan(only: set[str] | None) -> list[tuple[str, float, int]]:
    ids = [t for t in TRUTH_BOUNDARIES if only is None or t in only]
    # Cheapest boundaries first (from_size=5 truths) so an interrupted run keeps the cheap half.
    ids.sort(key=lambda t: TRUTH_BOUNDARIES[t][0])
    return [(t, noise, ppd) for t in ids for noise in NOISE_LEVELS for ppd in POINTS_PER_DECADE]


def summarize(rows: list[dict[str, Any]]) -> str:
    """ROC pair per candidate: recovery rate on real boundaries, false-positive rate on the rest."""
    lines = ["| candidate | recovery (real=True) | false-positive rate (real=False) | n |"]
    lines.append("|---|---:|---:|---:|")
    positives = [r for r in rows if r["real"]]
    negatives = [r for r in rows if not r["real"]]
    for label, key in (
        ("(a) runs test", "a_fires"),
        ("(b) F-test", "b_fires"),
        ("(c) bootstrap", "c_fires"),
        ("(d) pole margin", "d_fires"),
    ):
        recovery = (
            sum(1 for r in positives if r[key]) / len(positives) if positives else float("nan")
        )
        fpr = sum(1 for r in negatives if r[key]) / len(negatives) if negatives else float("nan")
        lines.append(
            f"| {label} | {recovery:.2%} ({sum(1 for r in positives if r[key])}/{len(positives)}) "
            f"| {fpr:.2%} ({sum(1 for r in negatives if r[key])}/{len(negatives)}) | {len(rows)} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--boot-reps", type=int, default=DEFAULT_BOOT_REPS)
    parser.add_argument("--only", default=None, help="comma-separated truth ids")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--summarize",
        type=Path,
        default=None,
        help="print ROC pairs from an existing JSON file and exit",
    )
    args = parser.parse_args()

    if args.summarize is not None:
        saved_rows = json.loads(args.summarize.read_text(encoding="utf-8"))
        print(summarize(saved_rows))
        return

    only = None if args.only is None else {s.strip() for s in args.only.split(",")}
    todo_all = plan(only)
    if not todo_all:
        raise SystemExit("no truth selected")

    print(f"{len(todo_all)} cells planned across {len({t for t, _, _ in todo_all})} truth(s)")
    if args.dry_run:
        seen_ids = {t for t, _, _ in todo_all}
        for truth_id in (t for t in TRUTH_BOUNDARIES if t in seen_ids):
            from_size, to_size, real = TRUTH_BOUNDARIES[truth_id]
            n_topo = sum(
                1
                for node in enumerate_up_to(BY_ID[truth_id].pool, from_size)
                if count_elements(node) == from_size
            )
            print(
                f"  {truth_id}: {from_size} -> {to_size} (real={real}), "
                f"~{n_topo} topologies at size {from_size}"
            )
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
        row = run_cell(
            BY_ID[truth_id],
            noise,
            ppd,
            workers=args.workers,
            boot_reps=args.boot_reps,
            boot_seed_base=1000 * index,
        )
        rows.append(row)
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(
            f"[{index}/{len(todo)}] {truth_id} noise={noise:.3%} ppd={ppd} real={row['real']}"
            f"  a={row['a_fires']} b={row['b_fires']}(p={row['f_p']:.3g})"
            f" c={row['c_fires']}(p={row['boot_p']:.3g})"
            f" d={row['d_fires']}(margin={row['d_margin']})"
            f"  {row['elapsed_s']:.0f}s",
            flush=True,
        )
    print(f"\nall done in {(time.perf_counter() - started_all) / 60:.1f} min")
    print()
    print(summarize(rows))


if __name__ == "__main__":
    main()
