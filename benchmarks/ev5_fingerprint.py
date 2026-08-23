"""Gate EV5: a byte fingerprint of the publication path, to compare across a change.

`docs/EVOLVE_SEARCH_PLAN.md` §4 states EV5 as *nothing else moved*: `mode="exhaustive"` and
`mode="auto"` below the fallback threshold produce identical results for a fixed seed before and
after every step of the genetic-search work. Until now the probe that measured it was ad hoc and
was thrown away after each run, which is why this file exists: the gate is only re-runnable if
the instrument is committed.

It is the instrument that caught the one bug in this area the test suite missed -- extracting the
per-size quota silently dropped the tiebreak between *exactly equal* scores, which is what an
exact reparameterisation looks like, and all 744 tests passed with it in place
(`docs/HANDOFF.md`, "Three things not to re-derive, from step 2"). Fingerprint the exhaustive
path before touching the shortlist.

Usage -- once against the unchanged sources, once against the changed ones, then `diff`:

    python benchmarks/ev5_fingerprint.py --out before.txt
    python benchmarks/ev5_fingerprint.py --out after.txt
    diff before.txt after.txt

Everything that is a clock rather than a number is dropped (see `_VOLATILE`); everything else is
printed to 17 significant figures, which is `repr` of a float and therefore lossless.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discovery_v2 import REFERENCES  # noqa: E402

from autocircuit.core.discover import discover  # noqa: E402
from autocircuit.core.simulate import log_frequencies, simulate  # noqa: E402

#: Keys whose value is a measurement of this machine rather than of the answer.
_VOLATILE = frozenset({"elapsed_s", "duration_s", "seconds"})


def _stable(value: Any) -> Any:
    """The report with every clock removed and every float in a lossless, sortable form."""
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in sorted(value.items()) if k not in _VOLATILE}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    if isinstance(value, float):
        return repr(value)
    return value


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=4, help="exhaustive element limit")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--mode", default="exhaustive,auto")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    lines: list[str] = [f"# limit={args.limit} seed={args.seed} modes={args.mode}"]
    for mode in args.mode.split(","):
        for reference in REFERENCES:
            data = simulate(
                reference.circuit,
                log_frequencies(reference.f_min, reference.f_max, 10),
                reference.params,
                noise=reference.noise,
                seed=0,
            )
            result = discover(
                data,
                pool=reference.pool,
                mode=mode,  # type: ignore[arg-type]
                exhaustive_limit=args.limit,
                seed=args.seed,
                workers=args.workers,
            )
            lines.append(f"\n## {mode} :: {reference.label}")
            lines.append(json.dumps(_stable(result.to_dict()), indent=1, sort_keys=True))
            print(f"{mode:11s} {reference.label:34s} "
                  f"{len(result.candidates):3d} rows, {len(result.pareto)} on the front",
                  flush=True)

    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
