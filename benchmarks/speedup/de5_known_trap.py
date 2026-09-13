"""docs/DE_KERNEL_PLAN.md Step 4, DE5 clause 3: the exact reference and method that took
``docs/PARAM_OPTIMIZER_PLAN.md``'s L-SHADE from 5/12 to 0/12 seeds reaching the noise floor --
``R1-L1-p(CPE1,R2-Wo1)-p(R3,C1)`` (``discovery_v2.LARGE_REFERENCES[2]``), one fixed 1%-noise
data realization (seed 0, the same one a `.summary()` comparison uses), 12 **optimizer** seeds,
``fit(restarts=1)``, pass = ``chi2_reduced < 2e-4``.

**This measures the global search's own reliability against one real, noisy, multi-modal
landscape** -- not data-noise sensitivity -- mirroring ``docs/TOPOLOGY_6PLUS_PLAN.md`` item
(b)'s method (noise-free data, the true topology given, 12/20 restarts varying only the
optimizer's own seed). A first version of this script varied the *data* seed instead and held
the optimizer seed fixed at 0; that measured a different, much less favorable statistic (mostly
data-noise-realization difficulty) and its own baseline read 1/12 against the 5/12 this plan's
own citation of PARAM_OPTIMIZER_PLAN's number, which is the tell that gave away the mistake.

Run once unpatched (scipy) and once through the relaxed vectorized DE kernel
(``benchmarks/speedup/de_kernel_patch.py``); the pre-registered bar (DE_KERNEL_PLAN.md Step 4
clause 3) is >=5/12 seeds passing under the kernel -- a fixed threshold mirroring
PARAM_OPTIMIZER_PLAN's own L-SHADE check exactly, not a statistical test. At n=12 the observed
5/12 vs 2/12 has only 3 discordant pairs, and exact McNemar on those returns p=0.25 -- not
significant at the conventional 0.05 level, per this repository's own "the response to a bar
that cannot resolve its own question is more seeds, never a reworded bar" rule
(``EVOLVE_SEARCH_PLAN.md``). ``--seeds`` raises the optimizer-seed count for exactly that reason;
the pre-registered >=5/12 pass/fail line does not move with it, but the McNemar p-value reported
at the end does gain the power to actually answer the question at a larger n.

Usage (PYTHONPATH needs both ``src`` and the repo root)::

    $env:PYTHONPATH = "...\\AutoCircuit\\src;...\\AutoCircuit"
    python benchmarks/speedup/de5_known_trap.py [--seeds 120]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.speedup.de_kernel_patch import use_relaxed_de  # noqa: E402
from discovery_v2 import LARGE_REFERENCES  # noqa: E402

from autocircuit.core.fit import fit  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "autoeis_round"))
from score import mcnemar_exact  # noqa: E402

REFERENCE = LARGE_REFERENCES[2]
NOISE_FLOOR = 2e-4


def _sweep(label: str, spectrum: object, n_seeds: int) -> list[float]:
    print(f"--- {label} ---")
    chi2s = []
    for seed in range(n_seeds):
        result = fit(REFERENCE.circuit, spectrum, restarts=1, seed=seed)  # type: ignore[arg-type]
        chi2s.append(result.chi2_reduced)
        ok = result.chi2_reduced < NOISE_FLOOR
        status = "OK" if ok else "over floor"
        print(f"  seed {seed}: chi2_reduced={result.chi2_reduced:.6g}  {status}")
    n_pass = sum(1 for c in chi2s if c < NOISE_FLOOR)
    print(f"  ==> {n_pass}/{n_seeds} reach the noise floor (< {NOISE_FLOOR:g})")
    print(flush=True)
    return chi2s


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=12, help="optimizer seed count")
    args = parser.parse_args()
    n_seeds = args.seeds

    spectrum = REFERENCE.spectrum(seed=0, noise=0.01)
    print(f"reference: {REFERENCE.label}  {REFERENCE.circuit}")
    print(f"one fixed 1%-noise data realization (seed 0); {n_seeds} optimizer seeds")
    print(f"noise floor bar: chi2_reduced < {NOISE_FLOOR:g}, pre-registered pass: >=5/12")
    print("(the pre-registered pass/fail line is fixed at n=12 and does not scale with --seeds;")
    print(" a larger n only sharpens the McNemar p-value reported at the end)")
    print()
    baseline = _sweep("scipy (baseline)", spectrum, n_seeds)
    with use_relaxed_de():
        patched = _sweep("relaxed vectorized DE (patched)", spectrum, n_seeds)

    base_ok = [c < NOISE_FLOOR for c in baseline]
    patch_ok = [c < NOISE_FLOOR for c in patched]
    n_base = sum(base_ok)
    n_patch = sum(patch_ok)
    only_base = sum(b and not p for b, p in zip(base_ok, patch_ok, strict=True))
    only_patch = sum((not b) and p for b, p in zip(base_ok, patch_ok, strict=True))
    both = sum(b and p for b, p in zip(base_ok, patch_ok, strict=True))
    neither = sum((not b) and (not p) for b, p in zip(base_ok, patch_ok, strict=True))
    p_value = mcnemar_exact(only_base, only_patch)

    print("=" * 88)
    print(f"baseline: {n_base}/{n_seeds}   patched: {n_patch}/{n_seeds}")
    print(
        f"paired: both pass {both}, only baseline {only_base}, only patched {only_patch}, "
        f"neither {neither}"
    )
    print(f"McNemar exact two-sided p = {p_value:.4f}")
    if n_seeds == 12:
        print(f"pre-registered bar (n=12 only): >=5/12 -- {'PASSED' if n_patch >= 5 else 'FAILED'}")
    print("=" * 88)


if __name__ == "__main__":
    main()
