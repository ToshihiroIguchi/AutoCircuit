"""Freeze the tier-1 fitness landscape of one reference so topology search is measurable.

Why this exists. `benchmarks/discovery_v2.py evolve-gate` costs hours per arm because its
budget is wall-clock and every topology it looks at is fitted on the spot. That is the right
instrument for a gate and the wrong one for *shortlisting algorithms*, because it fuses three
independent quantities: how many topologies a search must visit, how much one visit costs, and
whether a visit scores the topology correctly.

This script separates them. It screens **every** plausible topology in the space `_evolve`
actually searches, once, and writes the result to disk. After that a topology-search algorithm
is a pure combinatorial search over a lookup table: milliseconds per run, hundreds of seeds
free, and the KPI (distinct evaluations until the truth is first visited) is immune to what
else the machine is doing -- which is the confound `benchmarks/README.md` warns about three
times.

Limitations, stated rather than discovered later:

* The landscape is **screen-grade** (`fit.screen`, the exhaustive stage's tier 1), while
  `_evolve`'s `_Evaluator` runs `fit(restarts=1, ..., local=PUBLISH_LOCAL)` -- about 4x dearer
  per topology. Rankings are expected to agree; that is an assumption of this round.
* A frozen table cannot express **parameter inheritance** (`WARM_ACCEPT_FACTOR`), where a
  topology's score depends on the parent that proposed it. So every arm here is measured in the
  `warm_accept=0` world, which is the control arm gate EV3 uses.
* Early abandon is switched off (`abandon_above=inf`) so that every entry is comparable.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from autocircuit.core.circuit import Circuit
from autocircuit.core.enumerate import enumerate_up_to
from autocircuit.core.fit import screen
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum

#: The three-block Maxwell-Wagner reference of `docs/EVOLVE_SEARCH_PLAN.md` section 3.1, copied
#: verbatim from `benchmarks/discovery_v2.py::LARGE_REFERENCES[0]`. It is the one reference on
#: which the genetic search recovers anything at all (EV1: 1/3, and 6/10 with warm start), which
#: is what makes it the reference a *shortlisting* round can resolve differences on.
#:
#: The module-level names stay bound to it so that every arena built before this file grew a
#: `--reference` option rebuilds byte-for-byte from the same command.
TRUTH = "p(R1,C1)-p(R2,C2)-p(R3,C3)"
PARAMS = {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8, "R3.R": 8e4, "C3.C": 5e-7}
F_MIN, F_MAX, NOISE = 1e-2, 1e7, 0.01


@dataclass(frozen=True)
class Reference:
    """A truth to freeze a landscape around."""

    truth: str
    params: dict[str, float]
    f_min: float
    f_max: float
    noise: float = 0.01


#: Why there is more than one.
#:
#: Every arena this round built before step 5 -- `land_rcl6`, `land_rcl7`, `land_rclcpe6` --
#: freezes the **same** truth in a different space, so the round has never once varied the shape
#: of the circuit it is looking for. Step 5's mutation sweep is where that stopped being
#: harmless: the operator weights are a prior over *structure*, and the arm that moves weight
#: from insert-series to insert-parallel wins on a truth that is three parallel blocks in
#: series. A prior tuned on one truth's shape is not a search improvement, it is the answer
#: written into the question, and only a second truth of the opposite shape can tell the two
#: apart.
#:
#: `series` is that second truth: a capacitor with its ESR and ESL and one interfacial RC
#: block, which is `LARGE_REFERENCES[1]` with the CPE and the skin-effect element replaced by
#: their plain counterparts -- the same physics, in a pool small enough to enumerate. Four of
#: its five elements are in series where five of the Maxwell-Wagner's six are in parallel.
#: [measured] Fitting it to its own 1% data leaves 0/5 parameters unresolved on seeds 0-2, worst
#: parameter deviation 0.7%, so a search that fails here fails at finding the topology rather
#: than at a truth the data cannot support.
REFERENCES: dict[str, Reference] = {
    "maxwell": Reference(TRUTH, PARAMS, F_MIN, F_MAX, NOISE),
    "series": Reference(
        "C1-R1-L1-p(R2,C2)",
        {"C1.C": 1e-6, "R1.R": 0.05, "L1.L": 5e-10, "R2.R": 5.0, "C2.C": 1e-7},
        1e2,
        1e9,
    ),
}

_WORKER: dict[str, Any] = {}


def _init(f: Any, z: Any) -> None:
    _WORKER["spectrum"] = Spectrum(f, z)


def _screen_one(text: str) -> float:
    try:
        return float(screen(text, _WORKER["spectrum"], seed=0))
    except Exception:
        return float("inf")


def reference_spectrum(seed: int = 0, reference: Reference | None = None) -> Spectrum:
    ref = reference or REFERENCES["maxwell"]
    return simulate(
        ref.truth,
        log_frequencies(ref.f_min, ref.f_max, 10),
        ref.params,
        noise=ref.noise,
        seed=seed,
    )


def truth_reference(truth_id: str) -> Reference:
    """A :class:`Reference` for one of the pre-registered truths of ``six_plus/truths.py``.

    Kept behind its own CLI flag rather than added to :data:`REFERENCES`, because the arenas
    already committed here must keep rebuilding byte-for-byte from the command lines in the
    README -- which means neither the choices of ``--reference`` nor the payload's key set may
    move for them. ``truth_id`` is written into the payload only when this path is used.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "six_plus"))
    from truths import BY_ID  # noqa: PLC0415  (optional dependency of one CLI flag)

    truth = BY_ID[truth_id]
    return Reference(truth.circuit, truth.params, truth.f_min, truth.f_max, 0.01)


def build(
    pool: tuple[str, ...],
    n_max: int,
    workers: int,
    out: Path,
    seed: int,
    reference: Reference | None = None,
    truth_id: str | None = None,
) -> None:
    ref = reference or REFERENCES["maxwell"]
    spectrum = reference_spectrum(seed, ref)
    texts: list[str] = []
    meta: list[tuple[int, int]] = []
    for node in enumerate_up_to(pool, n_max):
        circuit = Circuit(node)
        texts.append(circuit.to_string())
        meta.append((len(circuit.leaves), len(circuit.param_names)))
    print(f"pool={pool} n<={n_max} topologies={len(texts)} points={len(spectrum.f)}", flush=True)

    started = time.perf_counter()
    if workers > 1:
        with multiprocessing.Pool(
            workers, initializer=_init, initargs=(spectrum.f, spectrum.z)
        ) as executor:
            costs: list[float] = []
            for i, cost in enumerate(executor.imap(_screen_one, texts, chunksize=16), 1):
                costs.append(cost)
                if i % 500 == 0:
                    rate = (time.perf_counter() - started) / i
                    print(
                        f"  {i}/{len(texts)} {rate * 1000:.0f} ms/topo "
                        f"eta {(len(texts) - i) * rate / 60:.1f} min",
                        flush=True,
                    )
    else:
        _init(spectrum.f, spectrum.z)
        costs = [_screen_one(t) for t in texts]
    elapsed = time.perf_counter() - started

    payload = {
        "truth": ref.truth,
        "truth_canonical": Circuit.parse(ref.truth).canonical_form(),
        # Written so that `targets.py` can rebuild the spectrum from the file rather than from
        # this module's constants. The arenas built before these keys existed do not carry
        # them, and that is what the fallback in `targets.py` is for.
        "params": ref.params,
        "f_min": ref.f_min,
        "f_max": ref.f_max,
        "noise": ref.noise,
        "pool": list(pool),
        "n_max": n_max,
        "data_seed": seed,
        "n_data": int(2 * len(spectrum.f)),
        "elapsed_s": elapsed,
        "rows": [
            {"text": t, "n_elements": m[0], "n_params": m[1], "cost": c}
            for t, m, c in zip(texts, meta, costs, strict=True)
        ],
    }
    # Added only on the `--truth` path: the arenas committed before this flag existed must
    # keep rebuilding byte-for-byte, and an unconditional key would change every one of them.
    if truth_id is not None:
        payload["truth_id"] = truth_id
    out.write_text(json.dumps(payload), encoding="utf-8")
    finite = np.isfinite(costs).sum()
    print(f"wrote {out} in {elapsed / 60:.1f} min, {finite}/{len(costs)} finite", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="R,C,L")
    ap.add_argument("--n-max", type=int, default=6)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--reference", default="maxwell", choices=sorted(REFERENCES))
    ap.add_argument(
        "--truth",
        default=None,
        help=(
            "freeze the landscape around a pre-registered truth from six_plus/truths.py "
            "(par5, ser5, mix5, par6, ser6, mix6, par7, ser7, mix7, par6_incumbent) "
            "instead of a named --reference"
        ),
    )
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    reference = (
        REFERENCES[args.reference] if args.truth is None else truth_reference(args.truth)
    )
    build(
        tuple(args.pool.split(",")),
        args.n_max,
        args.workers,
        args.out,
        args.seed,
        reference,
        args.truth,
    )


if __name__ == "__main__":
    main()
