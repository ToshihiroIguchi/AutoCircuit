"""Resumable version of `landscape.py`.

The first build was killed twice by something outside this process after twenty minutes of
work, with no error on either stream, so the shape of the job has to change rather than the
patience: results are appended to a JSONL file and flushed as they arrive, and a restart skips
whatever is already there. A kill now costs one chunk instead of the run.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import time
from pathlib import Path
from typing import Any

from autocircuit.core.circuit import Circuit
from autocircuit.core.enumerate import enumerate_up_to
from autocircuit.core.fit import screen
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum

TRUTH = "p(R1,C1)-p(R2,C2)-p(R3,C3)"
PARAMS = {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8, "R3.R": 8e4, "C3.C": 5e-7}
F_MIN, F_MAX, NOISE = 1e-2, 1e7, 0.01

_WORKER: dict[str, Any] = {}


def _init(f: Any, z: Any) -> None:
    _WORKER["spectrum"] = Spectrum(f, z)


def _job(task: tuple[str, int, int]) -> str:
    text, n_elements, n_params = task
    try:
        cost = float(screen(text, _WORKER["spectrum"], seed=0))
    except Exception:
        cost = float("inf")
    return json.dumps(
        {"text": text, "n_elements": n_elements, "n_params": n_params, "cost": cost}
    )


def reference_spectrum(seed: int = 0) -> Spectrum:
    return simulate(
        TRUTH, log_frequencies(F_MIN, F_MAX, 10), PARAMS, noise=NOISE, seed=seed
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="R,C,L")
    ap.add_argument("--n-max", type=int, default=7)
    ap.add_argument("--n-min", type=int, default=1)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--jsonl", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--chunk-seconds", type=float, default=0.0,
                    help="stop cleanly after this long, so a restart resumes rather than loses")
    args = ap.parse_args()

    pool = tuple(args.pool.split(","))
    spectrum = reference_spectrum(args.seed)

    done: set[str] = set()
    if args.jsonl.exists():
        for line in args.jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["text"])

    tasks: list[tuple[str, int, int]] = []
    for node in enumerate_up_to(pool, args.n_max, args.n_min):
        circuit = Circuit(node)
        text = circuit.to_string()
        if text in done:
            continue
        tasks.append((text, len(circuit.leaves), len(circuit.param_names)))
    print(f"pool={pool} n={args.n_min}..{args.n_max}  todo={len(tasks)} done={len(done)}",
          flush=True)

    started = time.perf_counter()
    if tasks:
        with args.jsonl.open("a", encoding="utf-8") as sink:
            with multiprocessing.Pool(
                args.workers, initializer=_init, initargs=(spectrum.f, spectrum.z)
            ) as executor:
                for i, line in enumerate(executor.imap(_job, tasks, chunksize=8), 1):
                    sink.write(line + "\n")
                    if i % 100 == 0:
                        sink.flush()
                        rate = (time.perf_counter() - started) / i
                        print(f"  {i}/{len(tasks)} {rate * 1000:.0f} ms/topo "
                              f"eta {(len(tasks) - i) * rate / 60:.1f} min", flush=True)
                    if args.chunk_seconds and time.perf_counter() - started > args.chunk_seconds:
                        print("  chunk budget reached, stopping cleanly", flush=True)
                        executor.terminate()
                        break
            sink.flush()

    if args.out:
        rows = [json.loads(line) for line in
                args.jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        seen: dict[str, dict] = {r["text"]: r for r in rows}
        payload = {
            "truth": TRUTH,
            "truth_canonical": Circuit.parse(TRUTH).canonical_form(),
            "pool": list(pool),
            "n_max": args.n_max,
            "data_seed": args.seed,
            "n_data": int(2 * len(spectrum.f)),
            "elapsed_s": time.perf_counter() - started,
            "rows": list(seen.values()),
        }
        args.out.write_text(json.dumps(payload), encoding="utf-8")
        print(f"wrote {args.out} with {len(seen)} rows", flush=True)


if __name__ == "__main__":
    main()
