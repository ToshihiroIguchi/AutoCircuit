"""Build the source archive that ``run_pyodide.mjs`` unpacks into the Pyodide filesystem.

Not a job for PowerShell's ``Compress-Archive``: it writes backslash separators into the entry
names, and Python's ``zipfile`` then treats them as part of the filename, so the archive
unpacks to files literally called ``autocircuit\\__init__.py`` and there is no package to
import. That failure is silent until the import.
"""

from __future__ import annotations

import argparse
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
OUT = pathlib.Path(__file__).with_name("src.zip")


def build(out: pathlib.Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SRC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            archive.write(path, path.relative_to(SRC).as_posix())
    with zipfile.ZipFile(out) as archive:
        count = len(archive.namelist())
    print(f"{out} -> {count} files, {out.stat().st_size:,} bytes")


def main() -> None:
    # The web build calls this too, with its own output path: one archive builder rather than a
    # second copy under web/ that could drift from this one and ship a different core.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=pathlib.Path, default=OUT)
    build(parser.parse_args().output)


if __name__ == "__main__":
    main()
