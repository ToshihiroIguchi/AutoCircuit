"""Arena C of ``docs/AUTOEIS_COMPARISON_PLAN.md``: truths authored by neither tool.

**Everything in the "pre-registered" block below is fixed before any tool is run, and the file
that records it is written before the first spectrum is scored.** Arenas A and B use fixtures one
side or the other wrote; this one exists because a comparison run only on those measures who
wrote the fixtures. Step 0 then made it the only arena in which a recovery rate exists at all
(``docs/AUTOEIS_COMPARISON.md`` section 0.4), so the choices here carry the whole round and are
listed rather than buried.

Why each choice is what it is:

``POOL``
    The intersection of the two vocabularies, minus what the other tool's *default* would throw
    away. AutoEIS has ``R``, ``C``, ``L``, ``P`` and no Warburg; its default ``terminals`` is
    ``"RLP"``, and ``capacitance_filter`` deletes any circuit that keeps an ideal ``C`` anyway.
    So an ideal capacitor cannot appear in a truth that AutoEIS is able to return, and ``CPE``
    carries the capacitive behaviour for both sides. This is a narrowing the other tool's
    defaults impose, not one chosen here.

``SIZES``
    3 to 6 elements. Five is where this project's exhaustive stage stops being complete and the
    genetic fallback takes over, and that fallback is measured at 5/9 truths reported against the
    exhaustive stage's 30/30 (``docs/EVOLVE_SEARCH_PLAN.md``). Stopping at five would therefore
    hand this side its strongest configuration and call the result a comparison. Six is included
    for that reason, and **results are reported per size**, so neither the strong nor the weak
    half is averaged away.

``requires a top-level series resistance`` and ``requires a parallel block``
    ``ohmic_resistance_filter`` and ``series_filter`` are two of AutoEIS's four default
    post-filters, and a truth that fails either can never be returned by it. Sampling such truths
    anyway would fill the arena with ``filtered`` events that say nothing about either search.
    **The count of draws these two constraints rejected is reported**, because an arena that
    silently discards most of its sample is a different arena from the one described here.

``L`` is kept, deliberately
    AutoEIS's default preprocessing deletes the inductive tail before its search ever sees it
    (``docs/AUTOEIS_COMPARISON.md`` section 0.5). Dropping ``L`` from the sampler would design the
    arena around that; keeping it silently would design it the other way. So ``L`` stays and the
    scorer splits the report into ``L``-containing and ``L``-free truths.

``SEEDS`` and ``STAGES``
    The seed list is fixed here, in full, before any run. Extending the round means running more
    of an already-written list, never choosing seeds after seeing a result. **The round stops when
    the machine time runs out or ``SEEDS`` is exhausted -- never because a result looked
    significant.** A stopping rule that depends on the data is not a stopping rule, and this one
    is written down so that it can be checked rather than promised.

The identifiability screen is the one ``LARGE_REFERENCES`` applied to itself by hand: fit the
truth to its own noisy data and require that no parameter comes back with a standard error
exceeding its own value. Asking either search for a circuit the data cannot confirm measures
neither search. It is applied here **before any tool is run** and identically to every draw,
rather than by hand to the ones that looked wrong.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from autocircuit.core import elements
from autocircuit.core.circuit import Circuit, ElementNode, Node, Parallel, Series
from autocircuit.core.enumerate import enumerate_topologies
from autocircuit.core.fit import fit
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.stats import unresolved_mask

# ==============================================================================================
# Pre-registered. Do not edit these after the first run of the round; add a new arena instead.
# ==============================================================================================

#: The shared vocabulary, after the other tool's default filters (see the module docstring).
POOL: tuple[str, ...] = ("R", "L", "CPE")

#: Element counts sampled, and how many truths are drawn at each.
SIZES: tuple[int, ...] = (3, 4, 5, 6)
TRUTHS_PER_SIZE: int = 2

#: Noise realisations, fixed in full before the first run. Stage boundaries are the prefixes of
#: this list at which the paired test is reported; the round may stop at any of them, but only
#: because the machine time ran out.
SEEDS: tuple[int, ...] = tuple(range(1, 21))
STAGES: tuple[int, ...] = (5, 10, 20)

#: The sweep. Ten points per decade over eight decades is 81 points, which is a realistic
#: instrument sweep and wide enough that a 6-element truth is not under-determined by the window.
F_MIN: float = 1e-2
F_MAX: float = 1e6
POINTS_PER_DECADE: int = 10

#: Proportional noise, matching the level every reference in ``benchmarks/discovery_v2.py`` uses.
NOISE: float = 0.01

#: Log-uniform parameter ranges, except the CPE exponent which is uniform. Chosen so that the
#: characteristic frequencies of the blocks land inside the sweep window rather than outside it.
PARAM_RANGES: dict[str, tuple[float, float]] = {
    "R.R": (1e0, 1e6),
    "L.L": (1e-9, 1e-3),
    "CPE.Q": (1e-9, 1e-3),
    "CPE.n": (0.5, 1.0),
}

#: The sampler's own RNG seed, so the arena is reproducible even though AutoEIS is not.
ARENA_SEED: int = 20260829

#: How many parameter draws to try per topology before giving up on it. A topology whose
#: parameters cannot be made identifiable in this many attempts is discarded, and the count of
#: such discards is reported.
PARAM_ATTEMPTS: int = 12


@dataclass(frozen=True)
class Truth:
    """One sampled truth: a topology, its parameters, and what it is made of."""

    truth_id: str
    circuit: str
    params: dict[str, float]
    n_elements: int
    has_inductor: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "truth_id": self.truth_id,
            "circuit": self.circuit,
            "params": self.params,
            "n_elements": self.n_elements,
            "has_inductor": self.has_inductor,
        }


@dataclass
class SamplerCensus:
    """What the sampler threw away, and why. Reported: an arena that silently discards most of
    its draws is not the arena its description claims."""

    topologies_enumerated: dict[int, int] = field(default_factory=dict)
    rejected_no_series_resistance: int = 0
    rejected_no_parallel_block: int = 0
    rejected_unidentifiable: int = 0
    accepted: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "topologies_enumerated": {str(k): v for k, v in self.topologies_enumerated.items()},
            "rejected_no_series_resistance": self.rejected_no_series_resistance,
            "rejected_no_parallel_block": self.rejected_no_parallel_block,
            "rejected_unidentifiable": self.rejected_unidentifiable,
            "accepted": self.accepted,
        }


def has_top_level_series_resistance(node: Node) -> bool:
    """True when a bare ``R`` sits in the top-level series chain.

    This is what AutoEIS's ``ohmic_resistance_filter`` requires (via
    ``parser.find_ohmic_resistors``): a resistor in series with everything else, not one buried
    inside a parallel block.
    """
    if isinstance(node, ElementNode):
        return node.code == "R"
    if isinstance(node, Series):
        return any(isinstance(c, ElementNode) and c.code == "R" for c in node.children)
    return False


def has_parallel_block(node: Node) -> bool:
    """True when the circuit contains a parallel route anywhere.

    AutoEIS's ``series_filter`` drops any circuit whose string has no ``[``.
    """
    if isinstance(node, Parallel):
        return True
    if isinstance(node, Series):
        return any(has_parallel_block(c) for c in node.children)
    return False


def _draw_params(circuit: Circuit, rng: np.random.Generator) -> dict[str, float]:
    """One log-uniform draw for every parameter of ``circuit``."""
    values: dict[str, float] = {}
    for leaf in circuit.leaves:
        for spec in elements.get(leaf.code).params:
            lo, hi = PARAM_RANGES[f"{leaf.code}.{spec.name}"]
            name = f"{leaf.label}.{spec.name}"
            if spec.log_scale:
                values[name] = float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
            else:
                values[name] = float(rng.uniform(lo, hi))
    return values


def is_identifiable(circuit: str, params: dict[str, float]) -> bool:
    """Fit the truth to its own noisy data and require every parameter to be resolved.

    The same screen ``LARGE_REFERENCES`` applied to itself, applied here before any tool has run
    and identically to every draw. A truth failing it would ask both searches for a circuit the
    data does not contain.
    """
    spectrum = simulate(
        circuit,
        log_frequencies(F_MIN, F_MAX, POINTS_PER_DECADE),
        params,
        noise=NOISE,
        seed=0,
    )
    result = fit(circuit, spectrum, seed=0)
    stderr = result.statistics.stderr
    return not bool(np.any(unresolved_mask(result.values, stderr)))


def candidate_stream(size: int, rng: np.random.Generator) -> list[tuple[str, dict[str, float]]]:
    """Every (topology, parameter draw) this arena would try at ``size``, in order.

    **No fitting happens here**, which is what makes the sampler resumable without becoming
    non-deterministic: the whole candidate sequence is a pure function of :data:`ARENA_SEED`, so
    a restart regenerates exactly the same sequence and only the expensive verdicts -- which are
    cached on disk -- have to survive. Drawing candidates and screening them in one interleaved
    RNG stream, which is the obvious way to write this, could not be resumed without either
    replaying every fit or advancing the RNG differently the second time.
    """
    admissible: list[Node] = []
    for node in enumerate_topologies(POOL, size):
        if not has_top_level_series_resistance(node):
            continue
        if not has_parallel_block(node):
            continue
        admissible.append(node)
    if not admissible:
        raise RuntimeError(f"no admissible topology of size {size}")

    order = rng.permutation(len(admissible))
    out: list[tuple[str, dict[str, float]]] = []
    for index in order:
        circuit = Circuit(admissible[int(index)])
        text = circuit.to_string()
        for _ in range(PARAM_ATTEMPTS):
            out.append((text, _draw_params(circuit, rng)))
    return out


def _census_counts(size: int) -> tuple[int, int, int]:
    """(admissible, rejected for no series R, rejected for no parallel block) at ``size``."""
    admissible = no_series_r = no_parallel = 0
    for node in enumerate_topologies(POOL, size):
        if not has_top_level_series_resistance(node):
            no_series_r += 1
        elif not has_parallel_block(node):
            no_parallel += 1
        else:
            admissible += 1
    return admissible, no_series_r, no_parallel


def sample_truths(
    cache_path: Path | None = None, verbose: bool = True
) -> tuple[list[Truth], SamplerCensus]:
    """Draw the arena. Deterministic given :data:`ARENA_SEED`, and resumable.

    ``cache_path`` is a JSONL of identifiability verdicts already computed. Screening one draw
    is a full fit, so a machine that stops partway would otherwise lose the whole sampling run;
    with the cache it loses at most the draw in flight.
    """
    rng = np.random.default_rng(ARENA_SEED)
    census = SamplerCensus()
    truths: list[Truth] = []

    cache: dict[str, bool] = {}
    if cache_path is not None and cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                cache[record["key"]] = bool(record["identifiable"])
        if verbose:
            print(f"resuming with {len(cache)} cached identifiability verdicts", flush=True)

    for size in SIZES:
        admissible, no_series_r, no_parallel = _census_counts(size)
        census.topologies_enumerated[size] = admissible
        census.rejected_no_series_resistance += no_series_r
        census.rejected_no_parallel_block += no_parallel

        taken = 0
        for text, params in candidate_stream(size, rng):
            if taken == TRUTHS_PER_SIZE:
                break
            key = json.dumps([text, params], sort_keys=True)
            if key in cache:
                verdict = cache[key]
            else:
                verdict = is_identifiable(text, params)
                if cache_path is not None:
                    with cache_path.open("a", encoding="utf-8") as handle:
                        handle.write(
                            json.dumps({"key": key, "identifiable": verdict}) + "\n"
                        )
                cache[key] = verdict
            if not verdict:
                census.rejected_unidentifiable += 1
                continue
            circuit = Circuit.parse(text)
            truth = Truth(
                truth_id=f"c{size}_{taken}",
                circuit=text,
                params=params,
                n_elements=size,
                has_inductor=any(leaf.code == "L" for leaf in circuit.leaves),
            )
            truths.append(truth)
            census.accepted += 1
            taken += 1
            if verbose:
                print(f"  accepted {truth.truth_id}: {text}", flush=True)
        if taken < TRUTHS_PER_SIZE:
            raise RuntimeError(f"only {taken} identifiable truths found at size {size}")

    return truths, census


def write_arena(out_dir: Path, verbose: bool = True) -> None:
    """Write the truths, the spectra both tools will read, and the sampler's census."""
    out_dir.mkdir(parents=True, exist_ok=True)
    truths, census = sample_truths(cache_path=out_dir / "screen_cache.jsonl", verbose=verbose)
    spectra_dir = out_dir / "spectra"
    spectra_dir.mkdir(parents=True, exist_ok=True)

    frequencies = log_frequencies(F_MIN, F_MAX, POINTS_PER_DECADE)
    for truth in truths:
        for seed in SEEDS:
            spectrum = simulate(
                truth.circuit, frequencies, truth.params, noise=NOISE, seed=seed
            )
            path = spectra_dir / f"{truth.truth_id}_s{seed}.csv"
            table = np.column_stack([spectrum.f, spectrum.z.real, spectrum.z.imag])
            np.savetxt(
                path,
                table,
                delimiter=",",
                header="frequency_hz,z_real_ohm,z_imag_ohm",
                comments="",
                fmt="%.17g",
            )

    (out_dir / "arena.json").write_text(
        json.dumps(
            {
                "pool": list(POOL),
                "sizes": list(SIZES),
                "truths_per_size": TRUTHS_PER_SIZE,
                "seeds": list(SEEDS),
                "stages": list(STAGES),
                "f_min": F_MIN,
                "f_max": F_MAX,
                "points_per_decade": POINTS_PER_DECADE,
                "n_points": int(frequencies.size),
                "noise": NOISE,
                "param_ranges": {k: list(v) for k, v in PARAM_RANGES.items()},
                "arena_seed": ARENA_SEED,
                "census": census.to_json(),
                "truths": [t.to_json() for t in truths],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if verbose:
        print(f"\nwrote {len(truths)} truths x {len(SEEDS)} seeds to {out_dir}")
        print(json.dumps(census.to_json(), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "arena_c",
        help="directory to write the arena into",
    )
    args = parser.parse_args()
    write_arena(args.out)


if __name__ == "__main__":
    main()
