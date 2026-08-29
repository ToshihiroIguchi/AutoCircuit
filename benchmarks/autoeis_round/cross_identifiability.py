"""Does the OTHER tool also think arena C's truths are identifiable?

The arena's identifiability screen is this project's own fitter deciding whether a truth's
parameters come back resolved (``arena.py``). That is a defensible screen -- asking either search
for a circuit the data cannot confirm measures neither search -- but it is *our* verdict, so the
arena is shaped by what our fitter handles well, and a truth that AutoEIS's inference could not
resolve either would be invisible.

This asks AutoEIS the same question about the same eight truths, using its own instrument: fit the
TRUE circuit with ``perform_bayesian_inference`` at its defaults and read the posterior
coefficient of variation of each parameter. AutoEIS's own convention (``docs`` and
``METRICS_AND_UX_PLAN.md`` section 2.3's note on mapping the two) treats CV >= 1 as unresolved.

**This does not change the arena.** It is a diagnostic reported beside the result, because
changing a pre-registered sampler after seeing its draw is the move the plan forbids. Runs in the
AutoEIS environment; never imports autocircuit.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1, help="which noise realisation to use")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--no-preprocess",
        action="store_true",
        help="skip AutoEIS's own preprocessing, to separate an instrument disagreement "
        "from the effect of the points that preprocessing deletes",
    )
    args = parser.parse_args()

    import autoeis as ae

    arena = json.loads((args.arena / "arena.json").read_text(encoding="utf-8"))
    # The circuits in AutoEIS's own grammar, translated in the PROJECT environment by
    # ``write_autoeis_circuits.py`` -- ``translate.py`` imports autocircuit and so cannot run
    # here. The two environments never meet; they exchange files.
    mapping_path = args.arena / "autoeis_circuits.json"
    if not mapping_path.exists():
        raise SystemExit(
            f"{mapping_path} is missing. Run, in the project environment:\n"
            "  python benchmarks/autoeis_round/write_autoeis_circuits.py --arena <arena>"
        )
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))

    rows = []
    for truth in arena["truths"]:
        tid = truth["truth_id"]
        table = np.loadtxt(
            args.arena / "spectra" / f"{tid}_s{args.seed}.csv", delimiter=",", skiprows=1
        )
        freq, Z = table[:, 0], table[:, 1] + 1j * table[:, 2]
        n_raw = len(freq)
        if not args.no_preprocess:
            freq, Z = ae.utils.preprocess_impedance_data(freq, Z)

        circuit = mapping[tid]
        t0 = time.perf_counter()
        try:
            results = ae.perform_bayesian_inference(
                circuit, freq, Z, seed=args.seed, progress_bar=False
            )
            elapsed = time.perf_counter() - t0
            result = results[0]
            samples = {k: np.asarray(v) for k, v in result.samples.items()}
            cvs = {
                name: float(np.std(values) / abs(np.mean(values)))
                for name, values in samples.items()
                if not name.startswith("sigma")
            }
            unresolved = sorted(n for n, cv in cvs.items() if cv >= 1.0)
            row = {
                "truth_id": tid,
                "circuit": truth["circuit"],
                "autoeis_circuit": circuit,
                "n_points": int(len(freq)),
                "n_points_raw": int(n_raw),
                "preprocessed": not args.no_preprocess,
                "converged": bool(result.converged),
                "divergences": int(result.num_divergences),
                "cv": cvs,
                "unresolved": unresolved,
                "identifiable_by_autoeis": not unresolved,
                "seconds": elapsed,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            row = {
                "truth_id": tid,
                "circuit": truth["circuit"],
                "autoeis_circuit": circuit,
                "error": f"{type(exc).__name__}: {exc}",
                "identifiable_by_autoeis": None,
            }
        rows.append(row)
        print(
            f"{tid:8} {truth['circuit']:34} "
            f"identifiable={row.get('identifiable_by_autoeis')} "
            f"unresolved={row.get('unresolved')} err={row.get('error')}",
            flush=True,
        )

    agree = sum(1 for r in rows if r.get("identifiable_by_autoeis") is True)
    print(f"\nAutoEIS also finds {agree} of {len(rows)} truths identifiable.")
    print("Truths where the two instruments disagree carry a caveat; the arena is NOT re-drawn.")
    if args.out is not None:
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
