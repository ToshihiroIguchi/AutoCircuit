"""Exceptions raised by the autocircuit.io package."""

from __future__ import annotations


class IOFormatError(Exception):
    """Base class for errors raised while reading or writing spectrum data files."""


class UnsupportedFormatError(IOFormatError):
    """Raised when a file's format cannot be determined or is not supported.

    The error message lists the formats that were attempted (and why each failed) so the
    caller can decide whether to pass an explicit ``format=`` or column-mapping hints.
    """


class ColumnMappingError(IOFormatError):
    """Raised when the columns of a delimited text file cannot be mapped to known fields.

    The error message includes the headers (or column indices) that were detected, so the
    caller can supply explicit hints (e.g. ``col_f``, ``col_re``, ``col_im``) to resolve it.
    """
