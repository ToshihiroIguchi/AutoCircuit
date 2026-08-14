"""CPython side of gate W1: the reference the browser has to reproduce.

Gate W1 (``docs/WEB_UI_PLAN.md`` section 6) asks whether the browser and the command line
produce the same fitted parameters for the nine-circuit synthetic corpus. This writes the
command line's half of that comparison, and ``run_fit_parity.mjs`` runs the other half inside
Pyodide and diffs the two.

**The corpus is not copied here.** It is imported from ``tests/test_fit.py``, which is where the
nine circuits are defined and maintained; a benchmark that kept its own copy would drift and
then measure the wrong thing. The *spectra* travel in the output file as well, rather than being
regenerated on the far side, so the two interpreters are demonstrably fitting the same numbers
and not merely the same recipe for numbers.

    python benchmarks/pyodide/fit_parity.py [restarts]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from autocircuit.core.fit import fit  # noqa: E402
from autocircuit.core.simulate import log_frequencies, simulate  # noqa: E402
from test_fit import SYNTHETIC_SUITE  # noqa: E402

#: Restarts used on both sides. Parity does not depend on the number, but it has to be the same
#: number, and a smaller one keeps the WASM half of the comparison to a few minutes.
RESTARTS = 3
SEED = 0
POINTS_PER_DECADE = 8
NOISE = 0.01


def main() -> int:
    restarts = int(sys.argv[1]) if len(sys.argv) > 1 else RESTARTS
    cases = []
    for label, dsl, truth, f_min, f_max in SYNTHETIC_SUITE:
        frequencies = log_frequencies(f_min, f_max, POINTS_PER_DECADE)
        spectrum = simulate(dsl, frequencies, truth, noise=NOISE, seed=7)
        started = time.perf_counter()
        result = fit(dsl, spectrum, restarts=restarts, seed=SEED)
        cases.append(
            {
                "label": label,
                "circuit": dsl,
                "restarts": restarts,
                "seed": SEED,
                "spectrum": spectrum.to_wire(),
                "fit": result.to_wire(),
                "elapsed_s": time.perf_counter() - started,
            }
        )
        print(f"{label:<28} {time.perf_counter() - started:6.1f} s  {result.message}")

    out = Path(__file__).with_name("fit_parity_ref.json")
    out.write_text(json.dumps({"cases": cases}, allow_nan=False), encoding="utf-8")
    print(f"\nwrote {out} ({out.stat().st_size / 1024:.0f} kB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
