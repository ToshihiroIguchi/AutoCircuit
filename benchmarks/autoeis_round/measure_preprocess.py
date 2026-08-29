"""How much of each arena-C spectrum survives AutoEIS's default preprocessing?

Reads the arena's own CSVs and puts them through preprocess_impedance_data at its defaults.
No search, no fitting -- this is only about what the other tool's search is given.
"""
import json
from pathlib import Path

import numpy as np

import autoeis as ae

ARENA = Path(r"C:\Users\toshi\python\AutoCircuit\benchmarks\autoeis_round\arena_c")
arena = json.loads((ARENA / "arena.json").read_text())
truths = {t["truth_id"]: t for t in arena["truths"]}

print(f"{'truth':8} {'L?':4} {'circuit':34} {'in':>4} {'out':>4} {'kept':>6}  {'Im>0 pts':>8}")
rows = []
for tid, t in truths.items():
    keep_fracs = []
    for seed in (1, 2, 3):
        path = ARENA / "spectra" / f"{tid}_s{seed}.csv"
        table = np.loadtxt(path, delimiter=",", skiprows=1)
        f, z = table[:, 0], table[:, 1] + 1j * table[:, 2]
        n_positive_im = int(np.count_nonzero(z.imag > 0))
        try:
            f2, z2 = ae.utils.preprocess_impedance_data(f, z)
            n_out = len(f2)
        except Exception as exc:  # noqa: BLE001
            n_out = -1
            print(f"  {tid} s{seed}: preprocessing raised {type(exc).__name__}: {exc}")
        keep_fracs.append(n_out / len(f))
        if seed == 1:
            print(f"{tid:8} {'yes' if t['has_inductor'] else 'no':4} {t['circuit']:34} "
                  f"{len(f):4} {n_out:4} {n_out / len(f):6.1%}  {n_positive_im:8}")
    rows.append((tid, t["has_inductor"], float(np.mean(keep_fracs))))

print()
with_l = [r[2] for r in rows if r[1]]
without_l = [r[2] for r in rows if not r[1]]
print(f"mean kept, truths WITH an inductor    ({len(with_l)}): {np.mean(with_l):.1%}")
print(f"mean kept, truths WITHOUT an inductor ({len(without_l)}): {np.mean(without_l):.1%}")
