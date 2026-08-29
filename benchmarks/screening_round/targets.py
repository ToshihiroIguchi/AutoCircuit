"""Which topologies in the frozen landscape count as "the truth or an exact equivalent".

Mirrors `benchmarks/discovery_v2.py::_large_truth_verdict`: the truth is fitted once at full
budget and every candidate is compared to *its* response under `EQUIVALENCE_RTOL`, because at
six elements an exact reparameterisation is the expected outcome of a correct search rather
than a bug in it. Only landscape rows that already screen at or below the truth's own cost can
possibly be equivalents, so the response check is asked of those alone.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from landscape import Reference, reference_spectrum

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import EQUIVALENCE_RTOL
from autocircuit.core.fit import fit


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("landscape", type=Path)
    ap.add_argument("--band", type=float, default=1.05)
    ap.add_argument("--max-checks", type=int, default=400)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    data = json.loads(args.landscape.read_text(encoding="utf-8"))
    rows = data["rows"]
    # An arena built before `landscape.py` grew a `--reference` option carries no parameters of
    # its own, and for those the module default *is* the truth they were built from. Falling
    # back rather than requiring the keys is what keeps `targets_rcl6/7` and `targets_rclcpe6`
    # rebuildable from the files already on disk.
    spectrum = reference_spectrum(
        data["data_seed"],
        None
        if "params" not in data
        else Reference(
            data["truth"], data["params"], data["f_min"], data["f_max"], data["noise"]
        ),
    )
    truth_key = data["truth_canonical"]

    for r in rows:
        r["canonical"] = Circuit.parse(r["text"]).canonical_form()
    truth_row = next(r for r in rows if r["canonical"] == truth_key)

    truth_fit = fit(data["truth"], spectrum, seed=0)
    z_truth = truth_fit.z_model
    magnitude = np.abs(z_truth)

    band = [r for r in rows if r["cost"] <= truth_row["cost"] * args.band]
    band.sort(key=lambda r: r["cost"])
    print(f"truth screening cost {truth_row['cost']:.6g}; {len(band)} rows within {args.band}x")
    checked = band[: args.max_checks]
    # `--max-checks` truncates from the *cheap* end, and the truth sits at the expensive end of
    # its own band by construction -- so a band longer than the cap drops the truth itself and
    # the run reports a target set that does not contain the answer, with nothing on either
    # stream to say so. [measured] The five-element series truth at n <= 7 has a band of 761 and
    # the default cap is 400: 250 rows in, the count was still zero. Put the truth back and say
    # what was cut; a silent 0/N here would be read as "this arena has no equivalents".
    if truth_row not in checked:
        checked.append(truth_row)
    if len(band) > args.max_checks:
        print(
            f"  WARNING: band truncated to {args.max_checks} of {len(band)} rows; "
            f"{len(band) - args.max_checks} possible equivalents were not checked. "
            f"Raise --max-checks to count them all.",
            flush=True,
        )

    targets: list[str] = []
    for i, r in enumerate(checked, 1):
        if r["canonical"] == truth_key:
            targets.append(r["canonical"])
            continue
        try:
            result = fit(r["text"], spectrum, seed=0)
        except Exception:
            continue
        z = result.z_model
        if z.shape == z_truth.shape and (
            float(np.max(np.abs(z - z_truth) / magnitude)) <= EQUIVALENCE_RTOL
        ):
            targets.append(r["canonical"])
        if i % 25 == 0:
            print(f"  checked {i}/{len(checked)}, {len(targets)} targets", flush=True)

    print(f"targets: {len(targets)} of {len(rows)} topologies "
          f"({len(targets) / len(rows):.3%} of the space)")
    args.out.write_text(
        json.dumps({"landscape": args.landscape.name, "targets": targets}), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
