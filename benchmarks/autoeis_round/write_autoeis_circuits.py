"""Translate an arena's truths into AutoEIS's grammar, for the AutoEIS environment to read.

Runs in the PROJECT environment. ``translate.py`` imports ``autocircuit`` and therefore cannot
run inside the AutoEIS environment, so the two exchange a file rather than a module -- the same
rule the two producers follow.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from translate import to_autoeis  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True)
    args = parser.parse_args()

    arena = json.loads((args.arena / "arena.json").read_text(encoding="utf-8"))
    mapping = {t["truth_id"]: to_autoeis(t["circuit"])[0] for t in arena["truths"]}
    (args.arena / "autoeis_circuits.json").write_text(
        json.dumps(mapping, indent=2), encoding="utf-8"
    )
    for truth_id, circuit in mapping.items():
        print(f"{truth_id:8} {circuit}")


if __name__ == "__main__":
    main()
