"""Build the source archive that ``run_pyodide.mjs`` unpacks into the Pyodide filesystem.

Not a job for PowerShell's ``Compress-Archive``: it writes backslash separators into the entry
names, and Python's ``zipfile`` then treats them as part of the filename, so the archive
unpacks to files literally called ``autocircuit\\__init__.py`` and there is no package to
import. That failure is silent until the import.
"""

from __future__ import annotations

import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
OUT = pathlib.Path(__file__).with_name("src.zip")


def main() -> None:
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SRC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            archive.write(path, path.relative_to(SRC).as_posix())
    with zipfile.ZipFile(OUT) as archive:
        count = len(archive.namelist())
    print(f"{OUT} -> {count} files, {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
