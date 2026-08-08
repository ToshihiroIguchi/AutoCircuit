"""Reader for Scribner ZView / ZPlot text exports (.z, .txt).

These files have a header block of "key: value" or "key,value" metadata lines followed by a
data table. The canonical ZPlot column order is::

    Freq(Hz), Ampl, Bias, Time(Sec), Z'(a), Z''(b), GD, Err, Range, ...

ZPlot already applies the sign to Z'' (i.e. the column IS Im(Z), negative for a capacitive
point), so it is used as-is by default; pass ``negate_imag=True`` to override for exports
that use the opposite convention.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from autocircuit.core.spectrum import Spectrum
from autocircuit.io.errors import ColumnMappingError
from autocircuit.io.generic_csv import _detect_delimiter, _split_line, _try_float


def _classify_zview_header(token: str) -> str | None:
    """Classify a ZPlot data-table column header, ignoring parenthetical annotations
    such as "(Hz)", "(a)", "(b)"."""
    t = re.sub(r"\(.*?\)", "", token.strip().lower()).strip()
    if "freq" in t:
        return "f"
    if t in ("z'", "zre", "z real", "zr"):
        return "re"
    if t in ("z''", "zim", "z imag", "zi"):
        return "im"
    return None


def _parse_meta_line(line: str) -> tuple[str | None, str]:
    s = line.strip()
    if ":" in s:
        key, _, value = s.partition(":")
    elif "," in s:
        key, _, value = s.partition(",")
    else:
        return None, s
    key_norm = re.sub(r"\s+", "_", key.strip().lower())
    key_norm = re.sub(r"[^a-z0-9_]", "", key_norm)
    if not key_norm:
        return None, s
    return key_norm, value.strip().strip('"')


def read(path: str | Path, **hints: Any) -> Spectrum:
    p = Path(path)
    with open(p, encoding="utf-8-sig", errors="replace") as fh:
        raw_lines = [ln.rstrip("\r\n") for ln in fh.readlines()]
    nonblank = [(i, ln) for i, ln in enumerate(raw_lines) if ln.strip()]
    if not nonblank:
        raise ColumnMappingError(f"No content found in ZView file {p}")

    delimiter = hints.get("delimiter")

    header_idx: int | None = None
    header_tokens: list[str] | None = None
    for i, ln in nonblank:
        low = ln.lower()
        if "freq" in low and "z'" in low:
            d = delimiter or _detect_delimiter([ln])
            tokens = _split_line(ln, d)
            if len(tokens) >= 2 and any("freq" in t.lower() for t in tokens):
                header_idx = i
                header_tokens = tokens
                if delimiter is None:
                    delimiter = d
                break

    if header_idx is not None and header_tokens is not None:
        meta_lines = [ln for i, ln in nonblank if i < header_idx]
        data_lines = [ln for i, ln in nonblank if i > header_idx]
        if delimiter is None:
            delimiter = _detect_delimiter(data_lines[:5]) if data_lines else " "
        col_roles = [_classify_zview_header(t) for t in header_tokens]
        idx_by_field: dict[str, int] = {}
        for idx, role in enumerate(col_roles):
            if role is not None and role not in idx_by_field:
                idx_by_field[role] = idx
        if not {"f", "re", "im"} <= idx_by_field.keys():
            raise ColumnMappingError(
                f"Could not map ZView columns from header {header_tokens!r} in {p}"
            )
        f_idx, re_idx, im_idx = idx_by_field["f"], idx_by_field["re"], idx_by_field["im"]
    else:
        # No column-header row found: locate the first fully-numeric, >= 6 column row,
        # trying each candidate delimiter per line rather than committing to one delimiter
        # from a (possibly non-representative) metadata line.
        data_start: int | None = None
        delim_candidates = [delimiter] if delimiter is not None else ["\t", ",", ";", " "]
        for i, ln in nonblank:
            for d in delim_candidates:
                tokens = _split_line(ln, d)
                if len(tokens) >= 6 and all(_try_float(t) is not None for t in tokens):
                    data_start = i
                    delimiter = d
                    break
            if data_start is not None:
                break
        if data_start is None:
            raise ColumnMappingError(
                f"Could not locate a data table in ZView file {p} (no header line with "
                "both a frequency and a Z' token, and no fully-numeric row with >= 6 columns)"
            )
        meta_lines = [ln for i, ln in nonblank if i < data_start]
        data_lines = [ln for i, ln in nonblank if i >= data_start]
        f_idx, re_idx, im_idx = 0, 4, 5

    metadata: dict[str, Any] = {}
    for ln in meta_lines:
        key, value = _parse_meta_line(ln)
        if key is not None:
            metadata[key] = value

    needed = max(f_idx, re_idx, im_idx)
    freqs: list[float] = []
    reals: list[float] = []
    imags: list[float] = []
    for ln in data_lines:
        tokens = _split_line(ln, delimiter)
        if len(tokens) <= needed:
            continue
        try:
            values = [float(t) for t in tokens]
        except ValueError:
            continue
        freqs.append(values[f_idx])
        reals.append(values[re_idx])
        imags.append(values[im_idx])

    if not freqs:
        raise ColumnMappingError(f"No parsable data rows found in ZView file {p}")

    negate_imag = bool(hints.get("negate_imag", False))
    im_arr: NDArray[np.float64] = np.asarray(imags, dtype=np.float64)
    if negate_imag:
        im_arr = -im_arr

    metadata["imag_sign_convention"] = (
        "negated by explicit hint (negate_imag=True)"
        if negate_imag
        else "as-is (ZPlot Z'' column already stores signed Im(Z))"
    )

    return Spectrum.from_parts(
        np.asarray(freqs, dtype=np.float64),
        np.asarray(reals, dtype=np.float64),
        im_arr,
        metadata,
    )


def read_many(path: str | Path, **hints: Any) -> list[Spectrum]:
    return [read(path, **hints)]
