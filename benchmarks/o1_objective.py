"""Gate O1: the objective changes the report and never a number.

``CLAUDE.md`` states it as *the full pipeline run under both objectives on the same spectrum
and seed produces a byte-identical* ``DiscoveryResult`` *wire payload; only the rendered report
differs*. This is that, fingerprinted the way ``benchmarks/ev5_fingerprint.py`` fingerprints the
publication path.

The gate has two halves and both are needed.

* **Structural.** ``discover()`` and ``fit()` do not take an objective, and neither module
  imports :mod:`autocircuit.core.objective`. This is the half that actually holds the property
  -- a value that cannot reach the search cannot change it -- and it is checked first, because
  a byte comparison passing while the parameter exists would only mean the two runs happened to
  agree on these spectra.
* **Measured.** The command line is driven end to end once per objective, on the same file with
  the same seed, and the two ``--json`` payloads are compared byte for byte with the objective's
  own section removed and every clock dropped (see ``_VOLATILE``; two runs differ in elapsed
  time and that is not a number about the answer). The rendered reports must *differ*, or the
  objective is decoration and the comparison above is vacuous.

Usage:

    python benchmarks/o1_objective.py --limit 3 --out o1.txt

Exit status is 1 if any half fails, so this is runnable as a gate and not only as a report.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discovery_v2 import REFERENCES  # noqa: E402

from autocircuit.cli.main import main as cli_main  # noqa: E402
from autocircuit.core.discover import discover  # noqa: E402
from autocircuit.core.fit import fit  # noqa: E402
from autocircuit.core.objective import OBJECTIVES  # noqa: E402
from autocircuit.io import write_csv  # noqa: E402

#: Keys whose value is a measurement of this machine rather than of the answer.
_VOLATILE = frozenset({"elapsed_s", "duration_s", "seconds"})

#: The key the report writes its objective-specific section under. The one key allowed to differ.
_OBJECTIVE_KEY = "objective"


def _stable(value: Any) -> Any:
    """The payload with every clock removed and every float in a lossless, sortable form."""
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in sorted(value.items()) if k not in _VOLATILE}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    if isinstance(value, float):
        return repr(value)
    return value


def _payload_fingerprint(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop(_OBJECTIVE_KEY, None)
    return json.dumps(_stable(payload), indent=1, sort_keys=True)


def _imports_of(module: Any) -> set[str]:
    """Every module name imported by ``module``'s source, however it is spelled."""
    tree = ast.parse(Path(inspect.getsourcefile(module) or "").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module or ''}.{alias.name}" for alias in node.names)
    return names


def structural() -> list[str]:
    """The half that holds the property. Returns the failures, empty when it passes."""
    failures: list[str] = []
    for function in (discover, fit):
        parameters = inspect.signature(function).parameters
        if "objective" in parameters:
            failures.append(f"{function.__module__}.{function.__name__} takes an objective")
    from autocircuit.core import discover as discover_module
    from autocircuit.core import fit as fit_module

    for module in (discover_module, fit_module):
        imported = _imports_of(module)
        if any(name.endswith("objective") or name.endswith(".objective") for name in imported):
            failures.append(f"{module.__name__} imports the objective module")
    return failures


def _run_cli(argv: list[str]) -> str:
    """The command line, end to end, with its report captured instead of printed."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli_main(argv)
    if code != 0:
        raise SystemExit(f"error: {' '.join(argv)} exited {code}")
    return buffer.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3, help="exhaustive element limit")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", type=Path, help="write the fingerprints here")
    args = ap.parse_args()

    failures = structural()
    for failure in failures:
        print(f"FAIL (structural): {failure}")
    if not failures:
        print("pass (structural): neither discover() nor fit() can see an objective")

    lines: list[str] = [f"# limit={args.limit} seed={args.seed}"]
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        for reference in REFERENCES:
            data = workspace / "spectrum.csv"
            write_csv(reference.spectrum(seed=0), data)
            fingerprints: dict[str, str] = {}
            reports: dict[str, str] = {}
            for objective in OBJECTIVES:
                report_path = workspace / f"report_{objective}.json"
                reports[objective] = _run_cli(
                    [
                        "discover",
                        str(data),
                        "--mode",
                        "exhaustive",
                        "--exhaustive-limit",
                        str(args.limit),
                        "--pool",
                        ",".join(reference.pool),
                        "--seed",
                        str(args.seed),
                        "--workers",
                        str(args.workers),
                        "--no-validate",
                        "--objective",
                        objective,
                        "--json",
                        str(report_path),
                    ]
                )
                fingerprints[objective] = _payload_fingerprint(report_path)

            distinct = set(fingerprints.values())
            same_report = len(set(reports.values())) == 1
            verdict = "pass"
            if len(distinct) != 1:
                verdict = "FAIL: the payload moved"
                failures.append(f"{reference.label}: payload differs between objectives")
            elif same_report:
                verdict = "FAIL: the report did not move"
                failures.append(f"{reference.label}: both objectives rendered the same report")
            print(
                f"{reference.label:34s} payload {'identical' if len(distinct) == 1 else 'DIFFERS'}"
                f", report {'identical' if same_report else 'differs'}  -- {verdict}",
                flush=True,
            )
            lines.append(f"\n## {reference.label}")
            lines.append(fingerprints[OBJECTIVES[0]])

    if args.out is not None:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {args.out} ({args.out.stat().st_size:,} bytes)")
    if failures:
        raise SystemExit(1)
    print("O1: pass")


if __name__ == "__main__":
    main()
