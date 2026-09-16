"""Real-fit throughput/recovery gate for the two-element insertion operator, `motif_rate`.

`docs/EVOLVE_SEARCH_PLAN.md` section 3.8 measured a two-element insertion step for the genetic
search (`mutate` places `series(A,B)`/`parallel(A,B)` instead of one fresh element, with
probability `motif_rate`) against a pre-registered symmetry rule on **frozen cost tables** --
`motif_rate=0.30` passed (wins on a parallel/CPE-dense arena, does not lose on two series
arenas), but that round explicitly deferred "an EV3-style two-sided real-fit
throughput/recovery gate" before anything ships, because a frozen-table win says nothing about
real fitting cost (section 3.3, 3.3.1's own caution). This file is that gate.

**`discover.py` is not edited.** `mutate` has exactly one call site
(`_propose_child`, `discover.py`), resolved as a module global at call time, so a
`discover.mutate` rebinding reaches both `_next_generation` and the `_SteadyState` proposer, and
survives `workers > 1` because mutation happens in the parent process (workers only fit).

**Two corrections relative to `benchmarks/screening_round/motif_probe.py`'s `mutate_motif`,
both required before any number here is trusted:**

1. The `rng.random()` draw for the motif decision now short-circuits on `motif_rate` (`if
   motif_rate and rng.random() < motif_rate and ...`). The frozen-table probe drew
   unconditionally, which cost it nothing (a fresh RNG per seed, nothing to stay bit-identical
   against); shipped that way, a `motif_rate=0.0` default would still consume one extra draw per
   insertion and shift every existing evolve RNG stream, breaking `ev5_fingerprint.py`'s
   byte-identity gate for a parameter that is supposed to do nothing at its default.
2. The control arm is the **patched** operator at `motif_rate=0.0`, not the unpatched
   `discover.mutate` -- otherwise the two arms' RNG streams diverge from the first insertion for
   a reason unrelated to the operator being tested. This is what the frozen round already did;
   restated here so a future edit does not "simplify" it away.

**Arenas** (both `max_elements=6`, matching the frozen arenas' own `n_max` exactly -- the
operator's decline rule is `count_elements(node) + 2 <= max_elements`, so a different cap is a
different operator, and section 3.8 already voided one sweep over exactly this mismatch):

* `par6` (`p(R1,C1)-p(R2,C2)-p(R3,C3)`) with `pool=("R","C","L","CPE")` -- the real-fit analogue
  of the frozen `land_rclcpe6`, the only §3.8 arena that carried information (`land_rcl6`
  saturated at 100% both ways). Deliberately **not** `INCUMBENT_PAR6`'s values -- `truths.py`
  documents those as failing the module's own four-part identifiability screen (`C3.C` at
  0.700% leverage against 1% noise); a recovery gate built on a truth the data does not contain
  would measure the fitter, not the operator.
* `ser6` (`C1-R1-L1-p(R2,C2-L2)`) with `pool=("R","C","L")` -- mirrors `land_series_rcl6`.

A frozen "hit" (18 accepted canonical classes in `targets_rclcpe6.json`) and this file's
`reported` (one class, via `Referee`) are **different events** -- the two rounds' rates are not
comparable to each other, only each round's own paired contrast is.

**The gate is two-sided and non-inferiority-shaped, not the frozen round's win/no-loss shape.**
At n in the tens of seeds an exact McNemar needs roughly a 10:1 discordant split to clear 0.05,
and the frozen effect (107 vs 71 of 480, ~1.5:1) would land near p=0.7 at n=30 -- keeping the
frozen round's *win* as a ship condition here would guarantee a fail-by-no-power, the exact
failure `docs/EVOLVE_SEARCH_PLAN.md` section 3.3.1 names in words ("a gate that fails on a
statistic with no resolving power has not been failed; it has not been measured"). So the win
is recorded as a secondary reading only; the ship clauses are throughput-not-worse and
recovery-not-worse.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/motif_gate.py pilot --out benchmarks/six_plus/motif_pilot.json
    python benchmarks/six_plus/motif_gate.py score --seeds 30 --time-limit 300 \\
        --out benchmarks/six_plus/motif_gate_300.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

from paired_stats import mcnemar_exact  # noqa: E402
from recovery import Referee  # noqa: E402
from truths import BY_ID, spectrum_for  # noqa: E402

import autocircuit.core.discover as discover_module  # noqa: E402
from autocircuit.core.circuit import (  # noqa: E402
    ElementNode,
    Node,
    count_elements,
    parallel,
    replace_subtree,
    series,
    subtree_at,
    subtree_paths,
)
from autocircuit.core.discover import (  # noqa: E402
    MUTATION_WEIGHTS,
    _delete,
    _element_paths,
    discover,
)


def mutate_motif(
    node: Node,
    rng: np.random.Generator,
    pool: Sequence[str],
    max_elements: int,
    *,
    weights: Sequence[float] = MUTATION_WEIGHTS,
    motif_rate: float = 0.0,
) -> Node:
    """`discover.mutate`, with a `motif_rate` chance that an insertion places two fresh
    elements (`series(A,B)`/`parallel(A,B)`, an even coin, both drawn from `pool`) instead of
    one. See the module docstring for the short-circuit correction relative to
    `benchmarks/screening_round/motif_probe.py`'s version of this function.
    """
    operations = ["retype", "insert_series", "insert_parallel", "delete"]
    active = np.array(weights, dtype=float)
    if count_elements(node) >= max_elements:
        active[1] = active[2] = 0.0
    if count_elements(node) <= 1:
        active[3] = 0.0
    active = active / active.sum()
    operation = str(rng.choice(operations, p=active))

    if operation == "retype":
        paths = _element_paths(node)
        path = paths[int(rng.integers(len(paths)))]
        return replace_subtree(node, path, ElementNode(str(rng.choice(pool))))

    if operation == "delete":
        paths = _element_paths(node)
        path = paths[int(rng.integers(len(paths)))]
        result = _delete(node, path)
        return result if result is not None else node

    paths = subtree_paths(node)
    path = paths[int(rng.integers(len(paths)))]
    subtree = subtree_at(node, path)

    if motif_rate and rng.random() < motif_rate and count_elements(node) + 2 <= max_elements:
        a = ElementNode(str(rng.choice(pool)))
        b = ElementNode(str(rng.choice(pool)))
        fresh: Node = series(a, b) if rng.random() < 0.5 else parallel(a, b)
    else:
        fresh = ElementNode(str(rng.choice(pool)))

    combined = series(subtree, fresh) if operation == "insert_series" else parallel(subtree, fresh)
    return replace_subtree(node, path, combined)


@dataclass
class MotifStats:
    """Free instrumentation for section 3.8's own open question: does a two-element move land
    in already-visited territory more often than a one-element move? `calls` is every
    invocation of the patched `mutate`, from any retry inside `_propose_child`'s loop
    (`PROPOSE_RETRY_CAP`) or `_SteadyState`'s proposer; there is no hook on `_propose_child`
    itself (this file does not edit or wrap it), so `calls / n_evaluated` is a proxy for the
    mean retry rate, not an exact count of retries per accepted child. Recorded, not gated.
    """

    calls: int = 0


@contextmanager
def _patched_mutate(
    motif_rate: float, weights: Sequence[float], stats: MotifStats
) -> Iterator[None]:
    """Monkeypatch `discover.mutate` for the duration of one `discover()` call, then restore."""
    original = discover_module.mutate

    def wrapped(
        node: Node,
        rng: np.random.Generator,
        pool: Sequence[str],
        max_elements: int,
        *,
        weights: Sequence[float] = weights,
    ) -> Node:
        stats.calls += 1
        return mutate_motif(node, rng, pool, max_elements, weights=weights, motif_rate=motif_rate)

    discover_module.mutate = wrapped  # type: ignore[assignment]
    try:
        yield
    finally:
        discover_module.mutate = original  # type: ignore[assignment]


@dataclass(frozen=True)
class Arena:
    truth_id: str
    pool: tuple[str, ...]
    max_elements: int = 6


ARENAS: tuple[Arena, ...] = (
    Arena("par6", ("R", "C", "L", "CPE")),
    Arena("ser6", ("R", "C", "L")),
)

NOISE = 0.01
WORKERS = 8
GENERATIONS = 10_000  # so `time_limit` binds, not the iteration cap (X6, TOPOLOGY_6PLUS_PLAN §5.11)


def run_one(arena: Arena, motif_rate: float, seed: int, time_limit: float) -> dict[str, Any]:
    truth = BY_ID[arena.truth_id]
    spectrum = spectrum_for(truth, noise=NOISE, seed=seed)
    referee = Referee(truth, spectrum)
    stats = MotifStats()

    started = time.perf_counter()
    with _patched_mutate(motif_rate, MUTATION_WEIGHTS, stats):
        result = discover(
            spectrum,
            pool=arena.pool,
            mode="evolve",
            workers=WORKERS,
            seed=seed,
            time_limit=time_limit,
            generations=GENERATIONS,
            max_elements=arena.max_elements,
        )
    elapsed = time.perf_counter() - started

    best = result.best
    return {
        "arena": arena.truth_id,
        "motif_rate": motif_rate,
        "seed": seed,
        "time_limit": time_limit,
        "seconds": round(elapsed, 1),
        "n_evaluated": result.n_evaluated,
        "generations": result.generations,
        "mutate_calls": stats.calls,
        "best_score": None if best is None else best.score(result.criterion),
        "reported": any(referee.matches(c) for c in result.candidates),
        "on_front": any(referee.matches(c) for c in result.pareto),
        "recommended": result.recommended is not None and referee.matches(result.recommended),
    }


def run_pilot(time_limit: float, seeds: int, out: Path) -> None:
    """Base arm only (`motif_rate=0.0`, patched), to size the scored job's `time_limit` before
    it runs -- see the module docstring's escalation rule.
    """
    rows: list[dict[str, Any]] = []
    for arena in ARENAS:
        for seed in range(seeds):
            row = run_one(arena, 0.0, seed, time_limit)
            rows.append(row)
            print(json.dumps(row), flush=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    for arena in ARENAS:
        subset = [r for r in rows if r["arena"] == arena.truth_id]
        n_reported = sum(r["reported"] for r in subset)
        print(f"{arena.truth_id}: {n_reported}/{len(subset)} reported at time_limit={time_limit}")


def run_scored(time_limit: float, seeds: int, out: Path) -> None:
    """The scored job: both arms, interleaved seed by seed, both arenas."""
    rows: list[dict[str, Any]] = []
    if out.exists():
        rows = json.loads(out.read_text(encoding="utf-8"))
        print(f"resuming with {len(rows)} rows already on disk", flush=True)
    done = {(r["arena"], r["motif_rate"], r["seed"]) for r in rows}

    for arena in ARENAS:
        for seed in range(seeds):
            for motif_rate in (0.0, 0.30):
                if (arena.truth_id, motif_rate, seed) in done:
                    continue
                row = run_one(arena, motif_rate, seed, time_limit)
                rows.append(row)
                print(json.dumps(row), flush=True)
                out.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print()
    print(summarise(rows))
    out.with_suffix(".md").write_text(summarise(rows), encoding="utf-8")


def summarise(rows: Sequence[dict[str, Any]]) -> str:
    lines: list[str] = ["# Real-fit gate for `motif_rate = 0.30`", ""]
    #: Per arena: (throughput_pass, score_pass, recovery_pass_or_None). The ship decision is
    #: computed from this after the loop, per the pre-registered fallback rule: an unresolved
    #: recovery clause (fewer than 10 discordant pairs) defers the arena's verdict to
    #: throughput and score alone rather than blocking on it.
    per_arena: dict[str, tuple[bool, bool, bool | None]] = {}

    for arena in ARENAS:
        base = {
            r["seed"]: r
            for r in rows
            if r["arena"] == arena.truth_id and r["motif_rate"] == 0.0
        }
        motif = {
            r["seed"]: r
            for r in rows
            if r["arena"] == arena.truth_id and r["motif_rate"] == 0.30
        }
        seeds = sorted(set(base) & set(motif))
        if not seeds:
            continue

        lines.append(f"## {arena.truth_id} (pool={arena.pool}, n={len(seeds)} seeds)")
        lines.append("")

        # Throughput: rate = n_evaluated / seconds, paired ratio motif/base.
        ratios = [
            (motif[s]["n_evaluated"] / motif[s]["seconds"])
            / (base[s]["n_evaluated"] / base[s]["seconds"])
            for s in seeds
        ]
        median_ratio = float(np.median(ratios))
        higher = sum(1 for r in ratios if r > 1.0)  # motif faster than base
        lower = sum(1 for r in ratios if r < 1.0)  # motif slower than base
        p_throughput = mcnemar_exact(lower, higher)
        # Non-inferiority, not equivalence: the sign test only fails this clause when it is
        # both significant AND in the direction unfavourable to motif (lower > higher) --
        # a significant *improvement* (motif faster) must not fail a "does not get worse"
        # clause. An earlier version of this function used `p_throughput > 0.05` unconditionally,
        # which failed the clause on a significant *speed-up* the first time this ran; caught
        # before any verdict was drawn from it, fixed here rather than reworded after the fact.
        significantly_worse = p_throughput <= 0.05 and lower > higher
        throughput_pass = median_ratio >= 0.90 and not significantly_worse
        lines.append(
            f"- throughput: median rate ratio (motif/base) = {median_ratio:.3f}, "
            f"paired sign test p={p_throughput:.4f} ({higher} higher / {lower} lower) "
            f"-> {'PASS' if throughput_pass else 'FAIL'}"
        )

        # Search quality: best score, smaller is better -- same non-inferiority shape as
        # throughput (fails only on a significant swing *against* motif), since a criterion
        # score has no natural "at least 0.90 of" ratio the way a rate does.
        score_diffs = [motif[s]["best_score"] - base[s]["best_score"] for s in seeds]
        motif_better = sum(1 for d in score_diffs if d < 0)
        base_better = sum(1 for d in score_diffs if d > 0)
        p_score = mcnemar_exact(motif_better, base_better)
        score_significantly_worse = p_score <= 0.05 and base_better > motif_better
        score_pass = not score_significantly_worse
        lines.append(
            f"- best score (lower better): motif better on {motif_better}/{len(seeds)}, "
            f"base better on {base_better}/{len(seeds)}, median delta "
            f"{float(np.median(score_diffs)):+.3f}, p={p_score:.4f} "
            f"-> {'PASS' if score_pass else 'FAIL'}"
        )

        # Recovery: reported/on_front/recommended, paired exact McNemar. `reported` is the one
        # read into the ship decision; on_front/recommended are printed for context only.
        recovery_pass: bool | None = None
        for field_name in ("reported", "on_front", "recommended"):
            only_base = sum(1 for s in seeds if base[s][field_name] and not motif[s][field_name])
            only_motif = sum(1 for s in seeds if not base[s][field_name] and motif[s][field_name])
            discordant = only_base + only_motif
            p = mcnemar_exact(only_motif, only_base)
            base_n = sum(base[s][field_name] for s in seeds)
            motif_n = sum(motif[s][field_name] for s in seeds)
            resolvable = discordant >= 10
            not_worse = (not resolvable) or p > 0.05 or only_motif >= only_base
            lines.append(
                f"- {field_name}: base {base_n}/{len(seeds)}, motif {motif_n}/{len(seeds)}, "
                f"discordant={discordant} (only-base={only_base}/only-motif={only_motif}), "
                f"p={p:.4f}"
                + ("" if resolvable else " -- fewer than 10 discordant pairs, not resolvable")
            )
            if field_name == "reported":
                recovery_pass = None if not resolvable else not_worse

        per_arena[arena.truth_id] = (throughput_pass, score_pass, recovery_pass)

        # Retry/duplicate-territory instrumentation -- recorded, not gated.
        base_calls_per_eval = float(
            np.mean([base[s]["mutate_calls"] / max(base[s]["n_evaluated"], 1) for s in seeds])
        )
        motif_calls_per_eval = float(
            np.mean([motif[s]["mutate_calls"] / max(motif[s]["n_evaluated"], 1) for s in seeds])
        )
        lines.append(
            f"- mutate calls per evaluated candidate (proxy for retry rate): "
            f"base {base_calls_per_eval:.2f}, motif {motif_calls_per_eval:.2f}"
        )
        lines.append("")

    lines.append("## Verdict")
    lines.append("")
    lines.append(
        "Per the pre-registered rule: an unresolved recovery clause (fewer than 10 discordant "
        "pairs) is not read as a failure -- it defers that arena's verdict to throughput and "
        "score alone."
    )
    lines.append("")
    arena_ships: dict[str, bool] = {}
    for truth_id, (throughput_pass, score_pass, recovery_pass) in per_arena.items():
        if recovery_pass is False:
            arena_ships[truth_id] = False
            basis = "recovery clause failed"
        elif not (throughput_pass and score_pass):
            arena_ships[truth_id] = False
            basis = "throughput or score clause failed"
        elif recovery_pass is None:
            arena_ships[truth_id] = True
            basis = "recovery unresolved at this n -- deferred to throughput+score, both PASS"
        else:
            arena_ships[truth_id] = True
            basis = "throughput, score and recovery all PASS"
        recovery_label = (
            "PASS" if recovery_pass else ("UNRESOLVED" if recovery_pass is None else "FAIL")
        )
        lines.append(
            f"- {truth_id}: throughput={'PASS' if throughput_pass else 'FAIL'}, "
            f"score={'PASS' if score_pass else 'FAIL'}, recovery={recovery_label} "
            f"-> {'SHIP-ELIGIBLE' if arena_ships[truth_id] else 'DO NOT SHIP'} ({basis})"
        )

    lines.append("")
    if not arena_ships or not all(arena_ships.values()):
        lines.append(
            "**Do not ship.** At least one arena's non-inferiority clauses failed; "
            "`discover.py` stays untouched."
        )
    else:
        any_unresolved = any(r is None for _, _, r in per_arena.values())
        lines.append(
            "**Ships**"
            + (
                ", on the throughput+score fallback basis for at least one arena -- "
                "the recovery clause could not resolve at this n and is not part of the basis "
                "(pre-registered)."
                if any_unresolved
                else " (throughput, score and recovery all support it on every arena)."
            )
        )
        lines.append(
            "Pending the win reading and the `PROPOSE_RETRY_CAP`/duplicate-rate check named as "
            "secondary in the module docstring."
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    pilot = sub.add_parser("pilot")
    pilot.add_argument("--time-limit", type=float, required=True)
    pilot.add_argument("--seeds", type=int, default=3)
    pilot.add_argument("--out", type=Path, required=True)

    scored = sub.add_parser("score")
    scored.add_argument("--time-limit", type=float, required=True)
    scored.add_argument("--seeds", type=int, required=True)
    scored.add_argument("--out", type=Path, required=True)

    summarise_cmd = sub.add_parser("summarise")
    summarise_cmd.add_argument("--in", dest="in_path", type=Path, required=True)

    args = parser.parse_args()
    if args.cmd == "pilot":
        run_pilot(args.time_limit, args.seeds, args.out)
    elif args.cmd == "score":
        run_scored(args.time_limit, args.seeds, args.out)
    elif args.cmd == "summarise":
        rows = json.loads(args.in_path.read_text(encoding="utf-8"))
        print(summarise(rows))


if __name__ == "__main__":
    main()
