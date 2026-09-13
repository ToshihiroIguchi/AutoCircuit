"""docs/DE_KERNEL_PLAN.md Step 4, DE5 clause 2: a T5-style ``DiscoveryResult.summary()``
comparison between the unpatched pipeline (scipy's ``differential_evolution``) and the same
pipeline run through the relaxed vectorized DE kernel (``benchmarks/speedup/de_kernel_patch.py``),
on all three ``REFERENCES`` (exhaustive mode, reachable in five elements) and all three
``LARGE_REFERENCES`` (auto mode, six-to-seven elements, triggers the genetic fallback).

**No ``time_limit`` is passed.** A first version of this script bounded both runs at the same
wall-clock budget (180 s) and found all 6/6 references "differ" -- but `discover()`'s own
docstring says `time_limit` is "a wall-clock budget ... the search stops cleanly when exceeded",
which bounds the exhaustive stage's own screening loop directly (`discover.py` checks
`time.perf_counter() - started > time_limit` inside the per-size driver), not merely the genetic
fallback. Under a shared wall-clock cap, the relaxed kernel -- faster per fit, which is the whole
point of building it -- simply gets through more topologies in the same window, so the two runs
compare different amounts of search rather than the same search under two kernels: exactly the
"a wall-clock budget measures the machine" trap `docs/SEARCH_ALGORITHM_SCREENING.md` sections 2.1
and 2.2 already name. The fix is to bound *effort*, not *time*: the exhaustive stage runs to its
own natural, deterministic completion (enumeration is combinatorial and kernel-independent), and
the genetic fallback is bounded by `generations` (a fixed count, default 30) rather than by a
clock, so both kernels do the same fixed amount of work.

Usage (PYTHONPATH needs both ``src`` and the repo root)::

    $env:PYTHONPATH = "...\\AutoCircuit\\src;...\\AutoCircuit"
    python benchmarks/speedup/de5_pipeline.py [--generations 30] [--workers 1]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.speedup.de_kernel_patch import use_relaxed_de  # noqa: E402
from discovery_v2 import LARGE_REFERENCES, REFERENCES, Reference  # noqa: E402

from autocircuit.core.discover import discover  # noqa: E402

#: `DiscoveryResult.summary()`'s own line: "Evaluated {n} distinct topologies in {s} s (mode:
#: {mode})" (discover.py's `summary()`, `scope = f"in {self.elapsed_s:.1f} s"`). Normalized
#: rather than dropped, so the topology *count* -- which should be identical for the exhaustive
#: stage regardless of kernel, since enumeration is combinatorial -- is still compared, and only
#: the kernel-speed-dependent seconds are excluded.
_ELAPSED = re.compile(r"in \d+\.\d+ s \(mode:")


def _normalize(text: str) -> list[str]:
    return [_ELAPSED.sub("in TIME s (mode:", line) for line in text.splitlines()]


def _run(reference: Reference, *, mode: str, generations: int, workers: int) -> str:
    data = reference.spectrum(seed=0)
    kwargs: dict[str, object] = dict(pool=reference.pool, mode=mode, seed=0, workers=workers)
    if mode == "exhaustive":
        kwargs["exhaustive_limit"] = 5
    else:
        kwargs["generations"] = generations
    result = discover(data, **kwargs)  # type: ignore[arg-type]
    return result.summary()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generations", type=int, default=30)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    cases = [(ref, "exhaustive") for ref in REFERENCES] + [
        (ref, "auto") for ref in LARGE_REFERENCES
    ]

    mismatches = 0
    for reference, mode in cases:
        print(f"--- {reference.label} ({mode}) ---")
        t0 = time.perf_counter()
        baseline = _run(reference, mode=mode, generations=args.generations, workers=args.workers)
        t_baseline = time.perf_counter() - t0

        t0 = time.perf_counter()
        with use_relaxed_de():
            patched = _run(reference, mode=mode, generations=args.generations, workers=args.workers)
        t_patched = time.perf_counter() - t0

        base_lines = _normalize(baseline)
        patch_lines = _normalize(patched)

        if base_lines == patch_lines:
            print(f"  IDENTICAL (baseline {t_baseline:.1f}s, patched {t_patched:.1f}s)")
        else:
            mismatches += 1
            print(f"  DIFFERS (baseline {t_baseline:.1f}s, patched {t_patched:.1f}s)")
            print("  --- baseline ---")
            print("  " + "\n  ".join(base_lines))
            print("  --- patched ---")
            print("  " + "\n  ".join(patch_lines))
        print(flush=True)

    print("=" * 88)
    print(f"{6 - mismatches}/6 references identical (wall-clock lines excluded)")
    print("=" * 88)


if __name__ == "__main__":
    main()
