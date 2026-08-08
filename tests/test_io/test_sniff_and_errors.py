from __future__ import annotations

from pathlib import Path

import pytest

from autocircuit.io import REGISTRY, read
from autocircuit.io.errors import ColumnMappingError, UnsupportedFormatError

DATA = Path(__file__).parent / "data"


def test_registry_lists_all_formats() -> None:
    assert set(REGISTRY) == {"generic_csv", "zview", "touchstone", "keysight"}


def test_unmappable_columns_raise_column_mapping_error_directly() -> None:
    from autocircuit.io import generic_csv

    with pytest.raises(ColumnMappingError):
        generic_csv.read(DATA / "generic_bad_columns.csv")


def test_unsniffable_file_raises_unsupported_format_error() -> None:
    with pytest.raises(UnsupportedFormatError) as excinfo:
        read(DATA / "generic_bad_columns.csv")
    message = str(excinfo.value)
    assert "generic_csv" in message


def test_unknown_explicit_format_raises_unsupported_format_error() -> None:
    with pytest.raises(UnsupportedFormatError):
        read(DATA / "generic_re_im.csv", format="not_a_real_format")


def test_missing_file_raises_file_not_found() -> None:
    with pytest.raises(FileNotFoundError):
        read(DATA / "does_not_exist.csv")


def test_explicit_format_bypasses_sniffing() -> None:
    spec = read(DATA / "generic_re_im.csv", format="generic_csv")
    assert spec.metadata["format"] == "generic_csv"


@pytest.mark.parametrize(
    ("filename", "expected_format", "hints"),
    [
        ("generic_re_im.csv", "generic_csv", {}),
        ("sample_header.z", "zview", {}),
        ("cap_series_thru.s2p", "touchstone", {"port_config": "series_thru"}),
        ("kv_r_x.csv", "keysight", {}),
    ],
)
def test_sniff_selects_expected_reader(
    filename: str, expected_format: str, hints: dict[str, object]
) -> None:
    spec = read(DATA / filename, **hints)
    assert spec.metadata["format"] == expected_format
    assert spec.metadata["source_path"] == str(DATA / filename)
