"""Which frequencies survive AutoEIS's preprocessing, per truth. Runs in the AutoEIS env."""
import json
from pathlib import Path

import autoeis as ae
import numpy as np

ARENA = Path(r"C:\Users\toshi\python\AutoCircuit\benchmarks\autoeis_round\arena_c")
arena = json.loads((ARENA / "arena.json").read_text())
out = {}
for t in arena["truths"]:
    table = np.loadtxt(ARENA / "spectra" / f"{t['truth_id']}_s1.csv", delimiter=",", skiprows=1)
    f, z = table[:, 0], table[:, 1] + 1j * table[:, 2]
    f2, _ = ae.utils.preprocess_impedance_data(f, z)
    out[t["truth_id"]] = sorted(float(x) for x in f2)
    print(f"{t['truth_id']}: {len(f)} -> {len(f2)}", flush=True)
(ARENA / "kept_frequencies.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
