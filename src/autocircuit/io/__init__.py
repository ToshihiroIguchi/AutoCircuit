"""Data I/O for AutoCircuit: readers/writers translating instrument file formats to/from the
common :class:`autocircuit.core.spectrum.Spectrum` contract.

Public API:
    read(path, *, format=None, **hints) -> Spectrum
    read_many(path, *, format=None, **hints) -> list[Spectrum]
    write_csv(spectrum, path) -> None
    write_zview(spectrum, path) -> None
    REGISTRY: dict[str, module] mapping format name -> reader module.

When ``format`` is not given, :func:`read` sniffs it: first from the file extension, then by
inspecting the first ~40 lines of content. If no candidate reader succeeds, it raises
:class:`autocircuit.io.errors.UnsupportedFormatError` listing every format that was tried and
why it failed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from autocircuit.core.spectrum import Spectrum
from autocircuit.io import generic_csv, keysight, touchstone, zview
from autocircuit.io.errors import UnsupportedFormatError
from autocircuit.io.writers import write_csv, write_zview

__all__ = [
    "REGISTRY",
    "read",
    "read_many",
    "write_csv",
    "write_zview",
]

REGISTRY: dict[str, Any] = {
    "generic_csv": generic_csv,
    "zview": zview,
    "touchstone": touchstone,
    "keysight": keysight,
}

_TOUCHSTONE_EXT_RE = re.compile(r"\.[syz]\d+p$", re.IGNORECASE)


def _read_head(path: Path, n_lines: int = 40) -> str:
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            lines = []
            for _ in range(n_lines):
                line = fh.readline()
                if not line:
                    break
                lines.append(line)
        return "".join(lines)
    except OSError:
        return ""


def _sniff_candidates(path: Path) -> list[str]:
    """Order candidate format names to try: extension-based hints first, then content."""
    ext = path.suffix.lower()
    candidates: list[str] = []

    def add(name: str) -> None:
        if name not in candidates:
            candidates.append(name)

    if _TOUCHSTONE_EXT_RE.match(ext):
        add("touchstone")
    if ext == ".z":
        add("zview")

    head = _read_head(path)
    lower_no_space = head.lower().replace(" ", "")

    if re.search(r"^\s*#.*\b(s|z|y)\b.*\b(ri|ma|db)\b", head, re.IGNORECASE | re.MULTILINE):
        add("touchstone")
    if "freq(hz)" in lower_no_space and "z'" in lower_no_space:
        add("zview")
    if re.search(r'^"?(title|date|trace\s*\d+)"?\s*[,:]', head, re.IGNORECASE | re.MULTILINE):
        add("keysight")
    add("generic_csv")  # always the last-resort, most permissive candidate
    return candidates


def _finalize(spectrum: Spectrum, path: Path, format_name: str) -> Spectrum:
    spectrum.metadata.setdefault("source_path", str(path))
    spectrum.metadata.setdefault("format", format_name)
    return spectrum


def read(path: str | Path, *, format: str | None = None, **hints: Any) -> Spectrum:
    """Read a single impedance spectrum from ``path``.

    If ``format`` is None, the format is sniffed from the file extension and then, if that is
    ambiguous, from the first ~40 lines of content. Extra keyword arguments are forwarded as
    column-mapping/parsing hints to the selected reader module.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    if format is not None:
        if format not in REGISTRY:
            raise UnsupportedFormatError(
                f"Unknown format {format!r}; known formats: {sorted(REGISTRY)}"
            )
        spectrum = REGISTRY[format].read(p, **hints)
        return _finalize(spectrum, p, format)

    candidates = _sniff_candidates(p)
    attempts: list[str] = []
    for name in candidates:
        try:
            spectrum = REGISTRY[name].read(p, **hints)
        except Exception as exc:  # noqa: BLE001 - collected for the diagnostic message below
            attempts.append(f"{name}: {exc}")
            continue
        return _finalize(spectrum, p, name)

    tried = "; ".join(attempts)
    raise UnsupportedFormatError(
        f"Could not determine the file format of {p}. Tried: {tried}"
    )


def read_many(path: str | Path, *, format: str | None = None, **hints: Any) -> list[Spectrum]:
    """Read all sweeps from ``path`` into a list of :class:`Spectrum` objects.

    Most formats hold a single sweep, in which case this is equivalent to ``[read(path)]``.
    Formats that support multiple sweeps per file (e.g. concatenated generic CSV blocks)
    expose their own ``read_many`` in the reader module, used automatically here.
    """
    p = Path(path)
    candidates = [format] if format is not None else _sniff_candidates(p)

    attempts: list[str] = []
    for name in candidates:
        module = REGISTRY.get(name)
        if module is None:
            attempts.append(f"{name}: unknown format")
            continue
        reader = getattr(module, "read_many", None)
        try:
            spectra = reader(p, **hints) if reader is not None else [module.read(p, **hints)]
        except Exception as exc:  # noqa: BLE001 - collected for the diagnostic message below
            attempts.append(f"{name}: {exc}")
            continue
        for spectrum in spectra:
            spectrum.metadata.setdefault("source_path", str(p))
            spectrum.metadata.setdefault("format", name)
        return spectra

    tried = "; ".join(attempts)
    raise UnsupportedFormatError(
        f"Could not determine the file format of {p}. Tried: {tried}"
    )
