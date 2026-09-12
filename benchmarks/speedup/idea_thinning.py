"""docs/SEARCH_TIME_PLAN.md section 3.5, run (pilot scale): does thinning the frequency points
fed to the DE global stage help tier-1 screening hit rate at all, on a topology hard enough that
the joint-combinatorics bottleneck `docs/SEARCH_SPEEDUP_PLAN.md` ideas C/D already found (10-12
free parameters) is actually present?

Method: fit the SAME 10-element, 5-block Maxwell-Wagner-style topology at the production tier-1
screen budget (`SCREEN_POPSIZE=8, SCREEN_MAXITER=40, SCREEN_RESTARTS=1`, and -- caught only after
an initial run ran far slower than expected -- `local=SCREEN_LOCAL`, since `fit()`'s own default
local-polish budget is `PUBLISH_LOCAL`, not the cheap tier-1 one, regardless of the DE popsize/
maxiter passed) three ways -- full spectrum, uniform 2x decimation, uniform 4x decimation --
using `fit()` rather than `screen()` because `screen()` returns only a cost (no parameter
vector), and the whole point here is to re-evaluate the *fitted parameters* against the FULL,
untouched spectrum via `relative_error` (weighting-independent) so costs computed on
different-sized data are comparable on one scale.

This is a **pilot at 30-60 seeds**, explicitly short of the 480-seed convention this project's
own gates use elsewhere in this document -- flagged as such in the write-up, not presented as a
final verdict either way.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from autocircuit.core.circuit import Circuit  # noqa: E402
from autocircuit.core.fit import SCREEN_LOCAL, fit, relative_error  # noqa: E402
from autocircuit.core.simulate import log_frequencies, simulate  # noqa: E402
from autocircuit.core.spectrum import Spectrum  # noqa: E402

TEXT = "p(R1,C1)-p(R2,C2)-p(R3,C3)-p(R4,C4)-p(R5,C5)"
VALUES = {
    "R1.R": 10.0,
    "C1.C": 1.0e-8,
    "R2.R": 50.0,
    "C2.C": 1.0e-6,
    "R3.R": 200.0,
    "C3.C": 1.0e-4,
    "R4.R": 800.0,
    "C4.C": 1.0e-2,
    "R5.R": 3000.0,
    "C5.C": 1.0,
}
F_MIN, F_MAX, PPD = 1e-1, 1e7, 10

SCREEN_POPSIZE = 8
SCREEN_MAXITER = 40
SCREEN_RESTARTS = 1


def thin(spectrum: Spectrum, stride: int) -> Spectrum:
    return Spectrum(f=spectrum.f[::stride], z=spectrum.z[::stride])


def main() -> None:
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    full = simulate(TEXT, log_frequencies(F_MIN, F_MAX, PPD), VALUES, noise=0.01, seed=0)
    circuit = Circuit.parse(TEXT)
    print(f"reference: {TEXT}  {len(full.f)} points  {n_seeds} seeds per condition")

    conditions = {
        "full (1x)": thin(full, 1),
        "half (2x)": thin(full, 2),
        "quarter (4x)": thin(full, 4),
    }
    for name, spectrum in conditions.items():
        print(f"  {name}: {len(spectrum.f)} points")
    print()

    results: dict[str, list[float]] = {name: [] for name in conditions}
    times: dict[str, list[float]] = {name: [] for name in conditions}
    for seed in range(n_seeds):
        for name, spectrum in conditions.items():
            t0 = time.perf_counter()
            result = fit(
                circuit,
                spectrum,
                weighting="modulus",
                seed=seed,
                restarts=SCREEN_RESTARTS,
                popsize=SCREEN_POPSIZE,
                maxiter=SCREEN_MAXITER,
                local=SCREEN_LOCAL,
            )
            elapsed = time.perf_counter() - t0
            z_model = circuit.impedance(full.omega, result.values)
            err = relative_error(z_model, full)
            results[name].append(err)
            times[name].append(elapsed)

    print(f"{'condition':14s} {'median err%':>12s} {'mean time':>10s} {'hits (err<5%)':>14s}")
    print("-" * 55)
    for name in conditions:
        errs = np.array(results[name]) * 100
        hits = int(np.sum(errs < 5.0))
        print(
            f"{name:14s} {np.median(errs):12.3f} {np.mean(times[name]):10.3f} {hits:6d}/{n_seeds}"
        )

    print()
    full_hits = np.array(results["full (1x)"]) * 100 < 5.0
    for name in ("half (2x)", "quarter (4x)"):
        cond_hits = np.array(results[name]) * 100 < 5.0
        both = int(np.sum(full_hits & cond_hits))
        only_full = int(np.sum(full_hits & ~cond_hits))
        only_cond = int(np.sum(~full_hits & cond_hits))
        neither = int(np.sum(~full_hits & ~cond_hits))
        print(
            f"{name} vs full: both={both} only_full={only_full} only_{name.split()[0]}={only_cond} "
            f"neither={neither}"
        )


if __name__ == "__main__":
    main()
