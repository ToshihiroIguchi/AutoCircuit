"""Generic delimited-text reader (CSV/TSV/whitespace) for impedance spectra.

Handles comma-, semicolon-, tab-, and whitespace-separated files, with or without a header
row. Column roles (frequency, real/imag or magnitude/phase) are inferred from header text
using case/space/punctuation-insensitive alias matching; when no header is present the
caller must supply positional hints (``col_f``, ``col_re``, ``col_im``, ``col_mag``,
``col_phase``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from autocircuit.core.spectrum import Spectrum
from autocircuit.io.errors import ColumnMappingError

# --------------------------------------------------------------------------------------
# Low-level text helpers (also reused by autocircuit.io.zview).
# --------------------------------------------------------------------------------------

_COMMENT_CHARS = ("#", "%", "!")


def _read_raw_lines(path: Path) -> list[str]:
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        return [line.rstrip("\r\n") for line in fh.readlines()]


def _is_comment_or_blank(line: str) -> bool:
    s = line.strip()
    return not s or s[0] in _COMMENT_CHARS


def _detect_delimiter(sample_lines: list[str]) -> str:
    """Guess the field delimiter from a handful of representative lines.

    Tries tab, comma, and semicolon (in that order) and accepts the first one that yields a
    consistent, nonzero column count across all sampled lines. Falls back to "whitespace
    splitting" (returned as a single space, handled specially by :func:`_split_line`).
    """
    non_empty = [line for line in sample_lines if line.strip()]
    for delim in ("\t", ",", ";"):
        counts = {line.count(delim) for line in non_empty}
        counts.discard(0)
        if len(counts) == 1:
            return delim
    return " "


def _split_line(line: str, delimiter: str) -> list[str]:
    s = line.strip()
    if delimiter == " ":
        return re.split(r"\s+", s) if s else []
    return [tok.strip() for tok in s.split(delimiter)]


def _try_float(tok: str) -> float | None:
    try:
        return float(tok)
    except ValueError:
        return None


# --------------------------------------------------------------------------------------
# Header alias tables.
# --------------------------------------------------------------------------------------

_PRIME_MAP = {
    "′": "'",  # prime
    "″": "''",  # double prime
    "‘": "'",
    "’": "'",
    "“": "''",
    "”": "''",
    "`": "'",
    '"': "''",
}


def _canon(raw: str) -> str:
    """Canonicalize a header token for alias matching: lowercase, unify quote/prime glyphs,
    then strip everything but letters, digits, apostrophes, and a leading minus sign."""
    s = raw.strip().lower()
    for src, dst in _PRIME_MAP.items():
        s = s.replace(src, dst)
    s = re.sub(r"[^a-z0-9'\-]", "", s)
    return s


_FREQ_ALIASES = ["freq", "frequency", "f", "hz", "f(hz)", "frequency (hz)", "frequency_hz"]
_OMEGA_ALIASES = ["omega", "w", "rad/s"]
_REAL_ALIASES = ["re(z)", "z'", "zre", "real", "zr", "resistance", "r", "re_z_ohm"]
_IMAG_ALIASES = ["im(z)", "z''", "-z''", "zim", "imag", "zi", "reactance", "x", "im_z_ohm"]
_MAG_ALIASES = ["|z|", "z", "zmod", "mag", "magnitude", "abs(z)"]
_PHASE_ALIASES = ["phase", "theta", "phi", "ang", "angle", "deg"]

# Only the bare "Z''" header (no explicit leading minus) means the column stores the
# positive-up -Im(Z) convention and must be negated to recover Im(Z).
_IMAG_NEGATE_RAW = {"z''"}

_FREQ_SET = {_canon(a) for a in _FREQ_ALIASES}
_OMEGA_SET = {_canon(a) for a in _OMEGA_ALIASES}
_REAL_SET = {_canon(a) for a in _REAL_ALIASES}
_IMAG_SET = {_canon(a) for a in _IMAG_ALIASES}
_IMAG_NEGATE_SET = {_canon(a) for a in _IMAG_NEGATE_RAW}
_MAG_SET = {_canon(a) for a in _MAG_ALIASES}
_PHASE_SET = {_canon(a) for a in _PHASE_ALIASES}


def _classify_header(raw: str) -> tuple[str, bool] | None:
    """Map a header token to (field, negate_imag), or None if unrecognized."""
    c = _canon(raw)
    if c in _FREQ_SET:
        return ("f", False)
    if c in _OMEGA_SET:
        return ("omega", False)
    if c in _IMAG_SET:
        return ("im", c in _IMAG_NEGATE_SET)
    if c in _REAL_SET:
        return ("re", False)
    if c in _MAG_SET:
        return ("mag", False)
    if c in _PHASE_SET:
        return ("phase", False)
    return None


# --------------------------------------------------------------------------------------
# Public reader.
# --------------------------------------------------------------------------------------


def read(path: str | Path, **hints: Any) -> Spectrum:
    """Read a generic delimited text file into a :class:`Spectrum`.

    Recognized hints:
        delimiter: explicit field delimiter override.
        has_header: force header detection on/off.
        col_f, col_re, col_im, col_mag, col_phase: 0-based positional column indices, used
            when there is no header row (or to override header-based detection).
        negate_imag: force negation of the parsed imaginary/reactance column.
        phase_unit: "deg" or "rad", overrides the automatic degrees-vs-radians heuristic.
    """
    p = Path(path)
    raw_lines = _read_raw_lines(p)
    return _parse_lines(raw_lines, p, **hints)


def read_many(path: str | Path, **hints: Any) -> list[Spectrum]:
    """Read a file that may hold several sweeps, separated by blank-line runs.

    If the file contains only a single block of data, this is equivalent to ``[read(path)]``.
    """
    p = Path(path)
    raw_lines = _read_raw_lines(p)
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in raw_lines:
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    if len(blocks) <= 1:
        return [_parse_lines(raw_lines, p, **hints)]
    return [_parse_lines(block, p, **hints) for block in blocks]


def _parse_lines(raw_lines: list[str], p: Path, **hints: Any) -> Spectrum:
    data_lines = [ln for ln in raw_lines if not _is_comment_or_blank(ln)]
    if not data_lines:
        raise ColumnMappingError(f"No data found in {p}")

    delimiter = hints.get("delimiter")
    if delimiter is None:
        delimiter = _detect_delimiter(data_lines[:20])

    first_tokens = _split_line(data_lines[0], delimiter)
    has_header = hints.get("has_header")
    if has_header is None:
        has_header = not all(_try_float(t) is not None for t in first_tokens)

    negate_imag_hint = hints.get("negate_imag")
    column_roles: list[tuple[str, bool] | None]

    if has_header:
        header_tokens = first_tokens
        column_roles = [_classify_header(t) for t in header_tokens]
        body_lines = data_lines[1:]
        detected_headers: list[str] = header_tokens
    else:
        body_lines = data_lines
        detected_headers = first_tokens
        n_cols = len(first_tokens)
        col_f = hints.get("col_f", 0)
        col_re = hints.get("col_re")
        col_im = hints.get("col_im")
        col_mag = hints.get("col_mag")
        col_phase = hints.get("col_phase")
        column_roles = [None] * n_cols

        if col_mag is not None or col_phase is not None:
            if col_mag is None or col_phase is None:
                raise ColumnMappingError(
                    "Both col_mag and col_phase must be given together for positional "
                    f"magnitude/phase mode (file {p} has no header row)."
                )
            positional_roles = (
                (col_f, ("f", False)),
                (col_mag, ("mag", False)),
                (col_phase, ("phase", False)),
            )
            for idx, pos_role in positional_roles:
                if idx >= n_cols:
                    raise ColumnMappingError(
                        f"Column index {idx} out of range for a {n_cols}-column file {p}"
                    )
                column_roles[idx] = pos_role
        else:
            if col_re is None:
                col_re = 1
            if col_im is None:
                col_im = 2
            if n_cols <= max(col_f, col_re, col_im):
                raise ColumnMappingError(
                    f"Positional column indices out of range for a {n_cols}-column file {p} "
                    f"(col_f={col_f}, col_re={col_re}, col_im={col_im}); this file has no "
                    "header row, so pass col_f/col_re/col_im or col_mag/col_phase hints "
                    "explicitly."
                )
            column_roles[col_f] = ("f", False)
            column_roles[col_re] = ("re", False)
            column_roles[col_im] = ("im", bool(negate_imag_hint))

    idx_by_field: dict[str, int] = {}
    imag_negate = False
    for idx, role in enumerate(column_roles):
        if role is None:
            continue
        field, negate = role
        if field not in idx_by_field:
            idx_by_field[field] = idx
            if field == "im":
                imag_negate = negate
    if negate_imag_hint is not None:
        imag_negate = bool(negate_imag_hint)

    if "f" in idx_by_field:
        freq_idx = idx_by_field["f"]
        freq_is_omega = False
    elif "omega" in idx_by_field:
        freq_idx = idx_by_field["omega"]
        freq_is_omega = True
    else:
        raise ColumnMappingError(
            f"Could not find a frequency column in {p}. Detected headers: {detected_headers!r}"
        )

    has_re_im = "re" in idx_by_field and "im" in idx_by_field
    has_mag_phase = "mag" in idx_by_field and "phase" in idx_by_field
    if not has_re_im and not has_mag_phase:
        raise ColumnMappingError(
            "Could not map impedance columns (need both real+imag or magnitude+phase "
            f"columns). Detected headers: {detected_headers!r}"
        )

    needed = max(idx_by_field.values())
    freqs: list[float] = []
    col_a: list[float] = []
    col_b: list[float] = []
    for line in body_lines:
        tokens = _split_line(line, delimiter)
        if len(tokens) <= needed:
            continue
        try:
            values = [float(t) for t in tokens]
        except ValueError:
            continue
        f_val = values[freq_idx]
        if freq_is_omega:
            f_val = f_val / (2.0 * np.pi)
        if has_re_im:
            a = values[idx_by_field["re"]]
            b = values[idx_by_field["im"]]
            if imag_negate:
                b = -b
        else:
            a = values[idx_by_field["mag"]]
            b = values[idx_by_field["phase"]]
        freqs.append(f_val)
        col_a.append(a)
        col_b.append(b)

    if not freqs:
        raise ColumnMappingError(f"No parsable data rows found in {p}")

    f_arr: NDArray[np.float64] = np.asarray(freqs, dtype=np.float64)
    a_arr: NDArray[np.float64] = np.asarray(col_a, dtype=np.float64)
    b_arr: NDArray[np.float64] = np.asarray(col_b, dtype=np.float64)

    metadata: dict[str, Any] = {
        "delimiter": "whitespace" if delimiter == " " else delimiter,
        "header_detected": bool(has_header),
    }

    if has_re_im:
        metadata["imag_sign_convention"] = (
            "negated (header indicated the Z'' positive-up convention)"
            if imag_negate
            else "as-is (column already gives signed Im(Z))"
        )
        return Spectrum.from_parts(f_arr, a_arr, b_arr, metadata)

    phase_unit = hints.get("phase_unit")
    if phase_unit is not None:
        degrees = str(phase_unit).lower().startswith("deg")
    else:
        degrees = bool(np.any(np.abs(b_arr) > 3.2))
    phase_deg = b_arr if degrees else np.rad2deg(b_arr)
    metadata["imag_sign_convention"] = "derived from magnitude and phase"
    metadata["phase_unit_detected"] = "deg" if degrees else "rad"
    return Spectrum.from_polar(f_arr, a_arr, phase_deg, metadata)
