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

Run with the package on the path (it is not pip-installed on the dev machine)::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/discovery_v2.py filter
    python benchmarks/discovery_v2.py screen
    python benchmarks/discovery_v2.py gate --workers 8

``gate`` is the slow one: it fits every plausible topology up to five elements, several times
over. Use ``--seeds 1`` and ``--limit 4`` for a sanity run.
"""

from __future__ import annotations

import argparse
import itertools
import time
from dataclasses import dataclass

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import DiscoveryResult, discover
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("what", choices=["gate", "filter", "screen"])
    parser.add_argument("--seeds", type=int, default=10, help="seeds per reference (gate)")
    parser.add_argument("--limit", type=int, default=5, help="exhaustive element limit (gate)")
    parser.add_argument("--workers", type=int, default=1, help="screening processes (gate)")
    parser.add_argument("--sample", type=int, default=60, help="topologies sampled (screen)")
    args = parser.parse_args()

    if args.what == "gate":
        report_gate(args.seeds, args.limit, args.workers)
    elif args.what == "filter":
        report_filter()
    else:
        report_screen(args.sample)


if __name__ == "__main__":
    main()
