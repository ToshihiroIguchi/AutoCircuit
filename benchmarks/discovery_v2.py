"""Does exhaustive-first discovery actually work, and what does it cost?

Three measurements, selected by the first command-line argument:

``gate``
    Acceptance gate **G1** of ``docs/DISCOVERY_V2_PLAN.md``: on each reference spectrum,
    ``mode="exhaustive"`` must put the true topology (or an exact equivalent of it) into the
    reported equivalence classes, for every seed, within the time budget.

``filter``
    How much the structural feasibility filter of ``core/enumerate.py`` removes, and -- the
    part that matters -- whether the truth survives it. This is the number quoted in
    ``benchmarks/README.md``; section 3.2 of the plan guessed at it, so it is measured here
    rather than assumed.

``screen``
    Tuning evidence for the tier-1 screening budget: for a range of (popsize, maxiter)
    settings, how long the screen takes and whether it still ranks the truth highly enough to
    reach the tier-2 shortlist. A screen that is too cheap loses the answer; one that is too
    expensive defeats the point of screening.

``screen-rank``
    The same question asked properly, and the evidence a budget change has to rest on.
    ``screen`` samples ~60 topologies out of thousands and reports a global rank; that is not
    the quantity the pipeline uses. What decides whether the two-tier search keeps the answer
    is whether the truth -- and every known exact equivalent of it -- lands inside its
    **per-element-count quota**, ranked by screening AICc, in the *whole* filtered space. So
    this mode screens every candidate, at every budget in a grid, over several seeds, and
    records each tracked circuit's rank within its size, the quota it had to beat, and whether
    ``_shortlist`` in fact selected it. Cutting the budget on a 60-topology sample would repeat
    the mistake that cost gate G1 once already (ranking by raw cost looked fine on small cases
    and lost the truth on the real space).

Run with the package on the path (it is not pip-installed on the dev machine)::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/discovery_v2.py filter
    python benchmarks/discovery_v2.py screen
    python benchmarks/discovery_v2.py screen-rank --workers 8
    python benchmarks/discovery_v2.py gate --workers 8

``gate`` and ``screen-rank`` are the slow ones: both fit every plausible topology up to five
elements, several times over. Use ``--seeds 1`` and ``--limit 4`` for a sanity run.
"""

from __future__ import annotations

import argparse
import itertools
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import (
    MIN_REFINE_PER_SIZE,
    REFINE_DEFAULT,
    DiscoveryResult,
    ScreenBudget,
    # ``screen-rank`` measures the ranking the two-tier search actually performs, so it calls
    # that machinery rather than re-deriving it: a reimplementation here would measure the
    # benchmark. (This is the opposite choice from ``benchmarks/topology_space.py``, which
    # keeps its own enumerator on purpose so that gate G2 checks one implementation against
    # another.) The following four imports are private:
    _screen_all,
    _screening_aicc,
    _shortlist,
    _worker_pool,
    discover,
)
from autocircuit.core.enumerate import (
    EndpointBehaviour,
    enumerate_topologies,
    is_feasible,
)
from autocircuit.core.fit import screen
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum


@dataclass(frozen=True)
class Reference:
    """A synthetic spectrum whose true topology is known."""

    label: str
    circuit: str
    params: dict[str, float]
    pool: tuple[str, ...]
    f_min: float
    f_max: float
    noise: float = 0.01
    #: Same-size topologies known to fit this reference identically, measured by fitting every
    #: same-size topology to noise-free data and keeping those matching to 1e-9. The same list
    #: gate G3 uses (``tests/test_feasibility.py``): a screening budget that keeps the truth but
    #: drops its equivalents has quietly destroyed the equivalence-class report.
    equivalents: tuple[str, ...] = ()

    def spectrum(self, seed: int = 0, noise: float | None = None) -> Spectrum:
        return simulate(
            self.circuit,
            log_frequencies(self.f_min, self.f_max, 10),
            self.params,
            noise=self.noise if noise is None else noise,
            seed=seed,
        )

    @property
    def canonical(self) -> str:
        return Circuit.parse(self.circuit).canonical_form()

    @property
    def n_elements(self) -> int:
        return len(Circuit.parse(self.circuit).leaves)


REFERENCES = [
    Reference(
        "capacitor (C-R-L + skin effect)",
        "C1-R1-L1-SKINF1",
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
        ("R", "C", "L", "CPE", "SKINF"),
        1e2,
        1e9,
    ),
    Reference(
        "Maxwell-Wagner (two blocks)",
        "p(R1,C1)-p(R2,C2)",
        {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8},
        ("R", "C", "L", "CPE"),
        1e-1,
        1e7,
        equivalents=("p(R1-C1,R2,C2)", "p(p(R1,C1)-C2,R2)", "p(p(R1,C1)-R2,C2)"),
    ),
    Reference(
        "Randles (with Warburg)",
        "R1-p(C1,R2-W1)",
        {"R1.R": 20.0, "C1.C": 1e-5, "R2.R": 200.0, "W1.A": 50.0},
        ("R", "C", "CPE", "W"),
        1e-2,
        1e5,
    ),
]


@dataclass(frozen=True)
class Verdict:
    """What became of the true topology in one run.

    Gate G1 as written asks only for ``reported``: the truth, or an exact equivalent of it,
    present in the reported equivalence classes. ``on_front`` and ``recommended`` are stricter
    and are tracked separately because they are not the same question. A capacitor whose ESR
    is barely resolvable at 1% noise can legitimately be *recommended* as a three-element
    model even though the four-element truth is right there on the front beside it -- that is
    the parsimony rule working, not the search failing.
    """

    reported: bool
    on_front: bool
    is_recommendation: bool
    recommendation: str


def _truth_verdict(result: DiscoveryResult, reference: Reference) -> Verdict:
    truth = next(
        (c for c in result.candidates if c.circuit.canonical_form() == reference.canonical),
        None,
    )
    recommended = result.recommended
    name = "-" if recommended is None else recommended.circuit.to_string()
    if truth is None:
        return Verdict(False, False, False, name)
    equivalents = result.equivalents_of(truth)
    on_front = any(c is truth or c in equivalents for c in result.pareto)
    is_recommendation = recommended is not None and (
        truth is recommended or recommended in equivalents
    )
    return Verdict(True, on_front, is_recommendation, name)


def report_gate(seeds: int, limit: int, workers: int) -> None:
    print("=" * 92)
    print("G1: does exhaustive mode report the true topology (or an exact equivalent)?")
    print("=" * 92)
    for reference in REFERENCES:
        print(f"\n{reference.label}: {reference.circuit}   pool {','.join(reference.pool)}")
        passes = on_front = recommended_count = 0
        elapsed_total = 0.0
        for seed in range(seeds):
            data = reference.spectrum(seed)
            started = time.perf_counter()
            result = discover(
                data,
                pool=reference.pool,
                mode="exhaustive",
                exhaustive_limit=limit,
                workers=workers,
                seed=seed,
            )
            elapsed = time.perf_counter() - started
            elapsed_total += elapsed
            verdict = _truth_verdict(result, reference)
            passes += int(verdict.reported)
            on_front += int(verdict.on_front)
            recommended_count += int(verdict.is_recommendation)
            print(
                f"  seed {seed}: {'PASS' if verdict.reported else 'FAIL'}"
                f"  reported={verdict.reported} on-front={verdict.on_front}"
                f" recommended={verdict.is_recommendation}"
                f"  complete<={result.complete_up_to}"
                f"  screened={result.n_evaluated:,}  {elapsed / 60:.1f} min"
                f"  -> {verdict.recommendation}",
                flush=True,
            )
        print(
            f"  ==> G1 (truth reported): {passes}/{seeds};"
            f" on the Pareto front: {on_front}/{seeds};"
            f" it is the recommendation: {recommended_count}/{seeds};"
            f" mean {elapsed_total / max(seeds, 1) / 60:.1f} min"
        )


def report_filter() -> None:
    print("=" * 92)
    print("Feasibility filter: how much is removed, and does the truth survive?")
    print("=" * 92)
    print(f"{'reference':<40}{'n<=5':>10}{'kept':>10}{'reduction':>12}{'truth kept':>12}")
    for reference in REFERENCES:
        for noise in (0.0, reference.noise):
            data = reference.spectrum(0, noise=noise)
            behaviour = EndpointBehaviour.from_spectrum(data)
            total = kept = 0
            for n in range(1, 6):
                level = list(enumerate_topologies(reference.pool, n))
                total += len(level)
                kept += sum(1 for node in level if is_feasible(node, behaviour))
            survives = is_feasible(Circuit.parse(reference.circuit).root, behaviour)
            label = f"{reference.label} @ {noise:.0%}"
            print(
                f"{label:<40}{total:>10,}{kept:>10,}"
                f"{total / max(kept, 1):>11.2f}x{str(survives):>12}"
            )


def report_screen(sample: int) -> None:
    print("=" * 92)
    print("Tier-1 screening budget: cost per topology, and does the truth stay in the ranking?")
    print("=" * 92)
    reference = REFERENCES[0]
    data = reference.spectrum(0)
    behaviour = EndpointBehaviour.from_spectrum(data)
    nodes = [
        node
        for n in range(1, reference.n_elements + 1)
        for node in enumerate_topologies(reference.pool, n)
        if is_feasible(node, behaviour)
    ]
    step = max(len(nodes) // sample, 1)
    circuits = [Circuit(node) for node in itertools.islice(nodes, 0, len(nodes), step)]
    truth = Circuit.parse(reference.circuit)
    if all(c.canonical_form() != truth.canonical_form() for c in circuits):
        circuits.append(truth)

    print(f"{'popsize':>9}{'maxiter':>9}{'ms/topology':>14}{'truth rank':>12}  of sample")
    for popsize, maxiter in ((4, 20), (8, 40), (12, 60), (20, 100)):
        started = time.perf_counter()
        scored: list[tuple[float, str]] = []
        for circuit in circuits:
            try:
                cost = screen(circuit, data, seed=0, popsize=popsize, maxiter=maxiter)
            except Exception:  # noqa: BLE001 - an unfittable candidate is simply hopeless
                cost = float("inf")
            scored.append((cost, circuit.canonical_form()))
        elapsed = time.perf_counter() - started
        scored.sort()
        rank = next(
            i for i, (_, key) in enumerate(scored, start=1) if key == truth.canonical_form()
        )
        print(
            f"{popsize:>9}{maxiter:>9}{elapsed / len(circuits) * 1000:>14.1f}"
            f"{rank:>12}  of {len(circuits)}",
            flush=True,
        )


DEFAULT_BUDGETS = (
    ScreenBudget(8, 40),  # current default
    ScreenBudget(8, 20),
    ScreenBudget(4, 40),
    ScreenBudget(4, 20),
)


@dataclass(frozen=True)
class RankRow:
    """Where one tracked circuit landed in the screen it has to survive."""

    text: str
    size: int
    rank: int  #: position within its own element count, ranked by screening AICc
    of: int  #: how many candidates that element count held
    quota: int  #: how many of them ``_shortlist`` takes before the near-tie rule
    cost_ratio: float  #: its screening cost over the best cost at its size
    shortlisted: bool  #: what ``_shortlist`` actually did -- the only hard verdict here

    @property
    def margin(self) -> float:
        """Rank as a fraction of the quota. Below 1 is inside; well below 1 is safe."""
        return self.rank / self.quota


def _feasible_texts(reference: Reference, data: Spectrum, limit: int) -> list[str]:
    """The candidate list the exhaustive stage would build for this spectrum."""
    behaviour = EndpointBehaviour.from_spectrum(data)
    return [
        Circuit(node).to_string()
        for n in range(1, limit + 1)
        for node in enumerate_topologies(reference.pool, n)
        if is_feasible(node, behaviour)
    ]


def _rank_rows(
    scored: list[tuple[float, str]], tracked: dict[str, str], n_data: int, n_refine: int
) -> list[RankRow]:
    """Rank every screened candidate the way :func:`_shortlist` does, then find the tracked ones.

    Ranking is per element count and by screening AICc, because that is what the shortlist
    does; a global rank by raw cost -- what the ``screen`` mode reports -- answers a question
    the pipeline never asks.
    """
    by_size: dict[int, list[tuple[float, float, str]]] = {}
    for cost, text in scored:
        if not math.isfinite(cost):
            continue
        circuit = Circuit.parse(text)
        aicc = _screening_aicc(cost, circuit.n_params, n_data)
        by_size.setdefault(len(circuit.leaves), []).append((aicc, cost, text))
    for group in by_size.values():
        group.sort()

    quota = max(MIN_REFINE_PER_SIZE, n_refine // max(len(by_size), 1))
    chosen = {Circuit.parse(text).canonical_form() for text in _shortlist(scored, n_refine, n_data)}

    rows: list[RankRow] = []
    for canonical, label in tracked.items():
        for size, group in by_size.items():
            position = next(
                (
                    i
                    for i, (_, _, text) in enumerate(group, start=1)
                    if Circuit.parse(text).canonical_form() == canonical
                ),
                None,
            )
            if position is None:
                continue
            best_cost = min(cost for _, cost, _ in group)
            cost = group[position - 1][1]
            rows.append(
                RankRow(
                    label,
                    size,
                    position,
                    len(group),
                    quota,
                    cost / best_cost if best_cost > 0.0 else math.inf,
                    canonical in chosen,
                )
            )
            break
        else:
            # Screened but unfittable at every budget, or removed by the feasibility filter --
            # either way it never reached the ranking, which is a failure of this budget.
            rows.append(RankRow(label, 0, 0, 0, 1, math.inf, False))
    return rows


def report_screen_rank(
    seeds: int, limit: int, workers: int, budgets: Sequence[ScreenBudget]
) -> None:
    print("=" * 108)
    print("Tier-1 budget vs. the tier-2 shortlist: does the truth still make its per-size quota?")
    print("=" * 108)
    print(
        "rank/of = position within the same element count by screening AICc; quota = how many\n"
        "_shortlist takes per size before the near-tie rule; margin = rank/quota (< 1 is in).\n"
        "'kept' is the verdict that counts: _shortlist actually selected it.\n"
    )
    n_refine = REFINE_DEFAULT["exhaustive"]
    # budget -> (worst margin seen anywhere, tracked circuits kept, tracked circuits tested)
    overall: dict[ScreenBudget, list[float]] = {b: [0.0, 0.0, 0.0] for b in budgets}
    seconds: dict[ScreenBudget, float] = dict.fromkeys(budgets, 0.0)

    for reference in REFERENCES:
        print("-" * 108)
        print(f"{reference.label}: {reference.circuit}   pool {','.join(reference.pool)}")
        tracked = {
            Circuit.parse(text).canonical_form(): text
            for text in (reference.circuit, *reference.equivalents)
        }
        for seed in range(seeds):
            data = reference.spectrum(seed)
            texts = _feasible_texts(reference, data, limit)
            print(f"  seed {seed}: {len(texts):,} feasible candidates", flush=True)
            with _worker_pool(workers, data, "modulus") as executor:
                for budget in budgets:
                    started = time.perf_counter()
                    scored = _screen_all(
                        texts,
                        data,
                        weighting="modulus",
                        seed=seed,
                        executor=executor,
                        on_progress=None,
                        time_limit=None,
                        started=started,
                        budget=budget,
                    )
                    elapsed = time.perf_counter() - started
                    seconds[budget] += elapsed
                    rows = _rank_rows(scored, tracked, 2 * data.n, n_refine)
                    for row in rows:
                        overall[budget][1] += float(row.shortlisted)
                        overall[budget][2] += 1.0
                        overall[budget][0] = max(overall[budget][0], row.margin)
                        print(
                            f"    {budget.popsize:>2}x{budget.maxiter:<3}"
                            f" {elapsed / 60:>5.1f} min  {row.text:<26}"
                            f" n={row.size}  {row.rank:>4}/{row.of:<5}"
                            f" quota {row.quota:>2}  margin {row.margin:>5.2f}"
                            f"  cost/best {row.cost_ratio:>8.2f}"
                            f"  kept {'yes' if row.shortlisted else 'NO'}",
                            flush=True,
                        )

    print("-" * 108)
    print("summary (all references, all seeds, all tracked circuits):")
    print(f"{'budget':>10}{'total screen':>15}{'vs 8x40':>10}{'worst margin':>15}{'kept':>10}")
    baseline = seconds.get(budgets[0], 0.0)
    for budget in budgets:
        worst, kept, total = overall[budget]
        print(
            f"{f'{budget.popsize}x{budget.maxiter}':>10}{seconds[budget] / 60:>13.1f} m"
            f"{seconds[budget] / baseline if baseline else float('nan'):>9.2f}x"
            f"{worst:>15.2f}{f'{int(kept)}/{int(total)}':>10}"
        )
    print(
        "\nA budget is safe to adopt only if every tracked circuit is kept and the worst margin\n"
        "stays clear of 1 -- a margin at 0.9 means the next seed can push it out."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("what", choices=["gate", "filter", "screen", "screen-rank"])
    parser.add_argument(
        "--seeds", type=int, default=10, help="seeds per reference (gate, screen-rank)"
    )
    parser.add_argument(
        "--limit", type=int, default=5, help="exhaustive element limit (gate, screen-rank)"
    )
    parser.add_argument(
        "--workers", type=int, default=1, help="screening processes (gate, screen-rank)"
    )
    parser.add_argument("--sample", type=int, default=60, help="topologies sampled (screen)")
    parser.add_argument(
        "--only",
        help="run just the reference spectra whose label contains one of these comma-separated"
        " strings, e.g. 'Maxwell,Randles'. These runs are long enough that resuming one after"
        " an interruption beats repeating it.",
    )
    parser.add_argument(
        "--budgets",
        default=",".join(f"{b.popsize}x{b.maxiter}" for b in DEFAULT_BUDGETS),
        help="screen-rank budget grid as popsize x maxiter, e.g. 8x40,4x20. The first entry is"
        " the baseline the others are timed against.",
    )
    args = parser.parse_args()

    if args.only:
        wanted = [text.strip().lower() for text in args.only.split(",") if text.strip()]
        selected = [r for r in REFERENCES if any(w in r.label.lower() for w in wanted)]
        if not selected:
            raise SystemExit(f"error: --only {args.only!r} matched no reference spectrum")
        REFERENCES[:] = selected

    if args.what == "gate":
        report_gate(args.seeds, args.limit, args.workers)
    elif args.what == "filter":
        report_filter()
    elif args.what == "screen":
        report_screen(args.sample)
    else:
        budgets = [
            ScreenBudget(*(int(part) for part in text.split("x")))
            for text in args.budgets.split(",")
        ]
        report_screen_rank(args.seeds, args.limit, args.workers, budgets)


if __name__ == "__main__":
    main()
