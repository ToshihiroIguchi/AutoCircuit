"""Tests for `autocircuit.web.bridge`: the JSON-in/JSON-out dispatcher a Pyodide worker calls.

Three properties from the module docstring of `autocircuit.web.bridge` are what these tests
pin down, not just "it works":

* `handle` never raises -- every failure a caller can trigger (a missing file, a file no reader
  can parse, an unknown operation, invalid JSON, a request with no `op`, a trim window that
  selects nothing) must come back as an `{"ok": false, ...}` response instead of an exception.
* The wire is strictly JSON: every response must parse with `json.loads` and then re-serialize
  with `json.dumps(..., allow_nan=False)`, because Python's default `json.dumps` emits bare
  `Infinity`/`NaN` tokens that `JSON.parse` rejects (see docs/HANDOFF.md section 3).
* `read`, `trim` and `validate` must agree exactly -- bit for bit, not approximately -- with
  calling `autocircuit.io.read_many`, `Spectrum.select` and `lin_kk` directly, since the bridge
  is only a JSON envelope around those calls.

Follows the conventions of `tests/test_wire.py`: exact equality throughout, no `np.allclose`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from autocircuit import io
from autocircuit.core.circuit import (
    Circuit,
    ElementNode,
    Parallel,
    Series,
    parallel,
    remove_subtree,
    replace_subtree,
    series,
    subtree_at,
    subtree_paths,
)
from autocircuit.core.elements import POOLS, REGISTRY
from autocircuit.core.fit import fit as core_fit
from autocircuit.core.fit import relative_error, search_space
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import WIRE_VERSION as SPECTRUM_WIRE_VERSION
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.validate import WIRE_VERSION as VALIDATE_WIRE_VERSION
from autocircuit.core.validate import lin_kk
from autocircuit.core.wire import decode_array, decode_complex_array, decode_float
from autocircuit.web.bridge import BRIDGE_VERSION, handle

DATA = Path(__file__).parent / "test_io" / "data"


def _assert_wire_safe(obj: Any) -> None:
    """Confirm an already-parsed JSON structure satisfies the real wire contract.

    The contract is re-serializing with ``allow_nan=False`` without raising -- the default
    ``json.dumps`` accepts bare ``Infinity``/``NaN`` tokens that ``JSON.parse`` rejects, so
    proving a payload dumps under the default settings proves nothing (docs/HANDOFF.md
    section 3). Every test below funnels its response through this or through :func:`_call`.
    """
    json.dumps(obj, allow_nan=False)


def _call(op: str, **kwargs: Any) -> dict[str, Any]:
    """Send one request to the bridge; return the parsed response after checking wire safety."""
    response = handle(json.dumps({"op": op, **kwargs}))
    parsed = json.loads(response)  # must parse as JSON on its own
    _assert_wire_safe(parsed)
    return parsed


# =================================================================================================
# 1. Spectrum wire round trip is exact
# =================================================================================================


def test_spectrum_wire_round_trip_is_bit_identical() -> None:
    circuit = "R1-p(R2,C1)"
    frequencies = log_frequencies(1e1, 1e5, points_per_decade=6)
    spectrum = simulate(
        circuit, frequencies, {"R1.R": 12.0, "R2.R": 800.0, "C1.C": 5e-8}, noise=0.01, seed=4
    )

    wire = spectrum.to_wire()
    parsed = json.loads(json.dumps(wire, allow_nan=False))
    back = Spectrum.from_wire(parsed)

    np.testing.assert_array_equal(back.f, spectrum.f)
    np.testing.assert_array_equal(back.z, spectrum.z)


def test_spectrum_wire_round_trip_survives_extreme_magnitudes() -> None:
    """A spectrum whose |Z| spans huge and tiny values, to actually exercise the
    shortest-repr round trip rather than a range where any encoding would look correct.
    """
    frequencies = log_frequencies(1e-3, 1e15, points_per_decade=2)
    spectrum = simulate("R1-C1", frequencies, {"R1.R": 1e-6, "C1.C": 1e-9}, noise=0.02, seed=3)
    magnitude = np.abs(spectrum.z)
    assert magnitude.max() > 1e6, "test construction did not reach a large |Z|; widen the sweep"
    assert magnitude.min() < 1e-3, "test construction did not reach a small |Z|; widen the sweep"

    wire = spectrum.to_wire()
    parsed = json.loads(json.dumps(wire, allow_nan=False))
    back = Spectrum.from_wire(parsed)

    np.testing.assert_array_equal(back.f, spectrum.f)
    np.testing.assert_array_equal(back.z, spectrum.z)


# =================================================================================================
# 2. A wrong version field is refused
# =================================================================================================


def test_spectrum_from_wire_rejects_a_wrong_version() -> None:
    spectrum = simulate("R1-C1", log_frequencies(1e0, 1e5, 5), {"R1.R": 25.0, "C1.C": 4.7e-6})
    wire = spectrum.to_wire()

    wrong_version = dict(wire)
    wrong_version["version"] = SPECTRUM_WIRE_VERSION + 1
    with pytest.raises(ValueError, match=str(SPECTRUM_WIRE_VERSION + 1)):
        Spectrum.from_wire(wrong_version)

    missing_version = dict(wire)
    del missing_version["version"]
    # A payload with no version at all reads as version 0, which is what a build predating the
    # format would send; it has to be refused just as loudly as a newer one.
    with pytest.raises(ValueError, match=f"version 0 is not {SPECTRUM_WIRE_VERSION}"):
        Spectrum.from_wire(missing_version)


# =================================================================================================
# 3. Metadata survives, and unencodable metadata degrades instead of exploding
# =================================================================================================


def test_json_safe_metadata_round_trips_unchanged() -> None:
    metadata: dict[str, Any] = {
        "note": "a string value",
        "passed": True,
        "n_points": 7,
        "gain": 3.5,
        "tags": ["a", "b", "c"],
        "nested": {"x": 1, "y": [1, 2, 3], "flag": False},
    }
    spectrum = simulate("R1", log_frequencies(1e2, 1e4, 3), {"R1.R": 10.0}, metadata=metadata)

    parsed = json.loads(json.dumps(spectrum.to_wire(), allow_nan=False))
    back = Spectrum.from_wire(parsed)

    for key, value in metadata.items():
        assert back.metadata[key] == value


def test_unencodable_metadata_degrades_to_a_json_safe_payload() -> None:
    """Metadata JSON cannot express is not reconstructed -- ``_json_safe`` documents this as a
    deliberately lossy ``repr()`` rendering, so only the "does not explode" half is asserted.
    """
    metadata: dict[str, Any] = {
        "array": np.array([1.0, 2.0, 3.0]),
        "path": Path("some/file.csv"),
        "not_finite": math.inf,
        "numpy_scalar": np.float64(2.5),
    }
    spectrum = simulate("R1", log_frequencies(1e2, 1e4, 3), {"R1.R": 10.0}, metadata=metadata)

    wire = spectrum.to_wire()
    text = json.dumps(wire, allow_nan=False)  # must not raise
    parsed = json.loads(text)

    assert parsed["metadata"]["numpy_scalar"] == 2.5  # np.generic unwraps via .item()
    assert parsed["metadata"]["not_finite"] == repr(math.inf)
    assert parsed["metadata"]["array"] == repr(metadata["array"])
    assert parsed["metadata"]["path"] == repr(metadata["path"])


# =================================================================================================
# 4. `read` matches `autocircuit.io.read_many` exactly
# =================================================================================================


def _assert_spectra_equal(got: list[Spectrum], expected: list[Spectrum]) -> None:
    assert len(got) == len(expected)
    for g, e in zip(got, expected, strict=True):
        np.testing.assert_array_equal(g.f, e.f)
        np.testing.assert_array_equal(g.z, e.z)
        assert g.metadata["format"] == e.metadata["format"]


def test_read_matches_read_many_for_generic_csv(tmp_path: Path) -> None:
    spectrum = simulate(
        "R1-C1", log_frequencies(1e2, 1e5, 3), {"R1.R": 12.0, "C1.C": 2e-6}, noise=0.01, seed=1
    )
    path = tmp_path / "spectrum.csv"
    io.write_csv(spectrum, path)

    expected = io.read_many(path)
    response = _call("read", path=str(path))
    assert response["ok"] is True
    got = [Spectrum.from_wire(s) for s in response["result"]["spectra"]]

    _assert_spectra_equal(got, expected)
    assert got[0].metadata["format"] == "generic_csv"


def test_read_matches_read_many_for_zview(tmp_path: Path) -> None:
    spectrum = simulate(
        "R1-C1", log_frequencies(1e2, 1e5, 3), {"R1.R": 12.0, "C1.C": 2e-6}, noise=0.01, seed=2
    )
    path = tmp_path / "spectrum.z"
    io.write_zview(spectrum, path)

    expected = io.read_many(path)
    response = _call("read", path=str(path))
    assert response["ok"] is True
    got = [Spectrum.from_wire(s) for s in response["result"]["spectra"]]

    _assert_spectra_equal(got, expected)
    assert got[0].metadata["format"] == "zview"


def test_read_matches_read_many_for_touchstone() -> None:
    path = DATA / "cap_1port.s1p"
    expected = io.read_many(path)
    response = _call("read", path=str(path))
    assert response["ok"] is True
    got = [Spectrum.from_wire(s) for s in response["result"]["spectra"]]

    _assert_spectra_equal(got, expected)
    assert got[0].metadata["format"] == "touchstone"


def test_read_matches_read_many_for_keysight() -> None:
    path = DATA / "kv_z_theta.csv"
    expected = io.read_many(path)
    response = _call("read", path=str(path))
    assert response["ok"] is True
    got = [Spectrum.from_wire(s) for s in response["result"]["spectra"]]

    _assert_spectra_equal(got, expected)
    assert got[0].metadata["format"] == "keysight"


# =================================================================================================
# 5. Errors come back as responses, never as exceptions
# =================================================================================================


def test_read_missing_file_returns_an_error_response() -> None:
    response = _call("read", path=str(DATA / "does_not_exist.csv"))
    assert response["ok"] is False
    assert response["error"]["type"] == "FileNotFoundError"
    assert response["error"]["message"]


def test_read_unparseable_file_returns_an_error_response() -> None:
    response = _call("read", path=str(DATA / "generic_bad_columns.csv"))
    assert response["ok"] is False
    assert response["error"]["type"] == "UnsupportedFormatError"
    assert response["error"]["message"]
    # UnsupportedFormatError.__str__ lists every candidate reader tried, as documented in
    # autocircuit.io.errors -- confirm it is not an empty or unrelated message.
    assert "generic_csv" in response["error"]["message"]


def test_unknown_operation_returns_an_error_response() -> None:
    response = _call("not_a_real_operation")
    assert response["ok"] is False
    assert response["error"]["type"] == "ValueError"
    assert "not_a_real_operation" in response["error"]["message"]


def test_invalid_json_request_returns_an_error_response() -> None:
    response_text = handle("this is not { valid json")
    parsed = json.loads(response_text)  # the response itself must still be valid JSON
    _assert_wire_safe(parsed)
    assert parsed["ok"] is False
    assert parsed["error"]["type"] == "JSONDecodeError"
    assert parsed["error"]["message"]


def test_request_with_no_op_key_returns_an_error_response() -> None:
    response_text = handle(json.dumps({"path": "irrelevant.csv"}))
    parsed = json.loads(response_text)
    _assert_wire_safe(parsed)
    assert parsed["ok"] is False
    assert parsed["error"]["type"] == "KeyError"
    assert parsed["error"]["message"]


def test_trim_with_a_window_selecting_no_points_returns_an_error_response() -> None:
    spectrum = simulate("R1", log_frequencies(1e2, 1e4, 3), {"R1.R": 10.0})
    out_of_range = float(spectrum.f[-1] + 1.0)
    response = _call("trim", spectrum=spectrum.to_wire(), f_min=out_of_range)
    assert response["ok"] is False
    assert response["error"]["type"] == "ValueError"
    assert "no points" in response["error"]["message"]


def test_handle_never_raises_for_any_of_the_above() -> None:
    """The requirement in one place: every bad input above is handled by calling `handle`
    itself, with no `pytest.raises` around it anywhere in this section.
    """
    bad_requests = [
        json.dumps({"op": "read", "path": str(DATA / "does_not_exist.csv")}),
        json.dumps({"op": "read", "path": str(DATA / "generic_bad_columns.csv")}),
        json.dumps({"op": "not_a_real_operation"}),
        "this is not { valid json",
        json.dumps({"path": "irrelevant.csv"}),
        # A circuit string that does not parse.
        json.dumps({"op": "circuit", "circuit": "Q1"}),
        # An unknown element code in an edit.
        json.dumps(
            {"op": "edit", "circuit": "R1-C1", "path": [1], "action": "series", "code": "ZZ"}
        ),
        # A path that addresses nothing.
        json.dumps({"op": "edit", "circuit": "R1-C1", "path": [5], "action": "remove"}),
        # `remove` on a single-element circuit.
        json.dumps({"op": "edit", "circuit": "R1", "path": [], "action": "remove"}),
        # `replace` aimed at a parallel block rather than an element.
        json.dumps(
            {"op": "edit", "circuit": "R1-p(R2,C1)", "path": [1], "action": "replace", "code": "L"}
        ),
    ]
    for request in bad_requests:
        response_text = handle(request)  # must not raise
        parsed = json.loads(response_text)
        _assert_wire_safe(parsed)
        assert parsed["ok"] is False


# =================================================================================================
# 6. `trim` agrees with `Spectrum.select`
# =================================================================================================


@pytest.mark.parametrize(
    ("f_min", "f_max"),
    [(1e3, None), (None, 1e5), (1e3, 1e5)],
    ids=["f_min_only", "f_max_only", "both_bounds"],
)
def test_trim_matches_spectrum_select_bit_identical(
    f_min: float | None, f_max: float | None
) -> None:
    spectrum = simulate(
        "R1-C1", log_frequencies(1e1, 1e6, 5), {"R1.R": 15.0, "C1.C": 3e-6}, noise=0.01, seed=7
    )
    expected = spectrum.select(f_min, f_max)

    kwargs: dict[str, Any] = {"spectrum": spectrum.to_wire()}
    if f_min is not None:
        kwargs["f_min"] = f_min
    if f_max is not None:
        kwargs["f_max"] = f_max
    response = _call("trim", **kwargs)
    assert response["ok"] is True
    got = Spectrum.from_wire(response["result"]["spectrum"])

    np.testing.assert_array_equal(got.f, expected.f)
    np.testing.assert_array_equal(got.z, expected.z)


# =================================================================================================
# 7. `validate` agrees with calling `lin_kk` directly
# =================================================================================================


def test_validate_matches_lin_kk_directly() -> None:
    spectrum = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e1, 1e5, 6),
        {"R1.R": 12.0, "R2.R": 800.0, "C1.C": 5e-8},
        noise=0.01,
        seed=4,
    )
    expected = lin_kk(spectrum)

    response = _call("validate", spectrum=spectrum.to_wire())
    assert response["ok"] is True
    payload = response["result"]["validation"]

    assert payload["passed"] == expected.passed
    assert payload["systematic"] == expected.systematic
    assert payload["n_elements"] == expected.n_elements
    assert payload["summary"] == expected.summary(spectrum)

    assert decode_float(payload["mu"]) == expected.mu
    assert decode_float(payload["r_ohm"]) == expected.r_ohm
    assert decode_float(payload["inductance"]) == expected.inductance
    assert decode_float(payload["capacitance"]) == expected.capacitance
    assert decode_float(payload["max_residual"]) == expected.max_residual
    assert decode_float(payload["rms_residual"]) == expected.rms_residual
    assert decode_float(payload["runs_z"]) == expected.runs_z
    assert decode_float(payload["residual_limit"]) == expected.residual_limit

    np.testing.assert_array_equal(decode_array(payload["tau"]), expected.tau)
    np.testing.assert_array_equal(decode_array(payload["resistances"]), expected.resistances)
    np.testing.assert_array_equal(decode_array(payload["residual_real"]), expected.residual_real)
    np.testing.assert_array_equal(decode_array(payload["residual_imag"]), expected.residual_imag)
    np.testing.assert_array_equal(decode_complex_array(payload["z_fit"]), expected.z_fit)


# =================================================================================================
# 9. `elements` matches the registry and the pools exactly
# =================================================================================================


def test_elements_lists_every_registry_code_with_matching_metadata() -> None:
    response = _call("elements")
    assert response["ok"] is True
    payload = response["result"]["elements"]
    assert [entry["code"] for entry in payload] == sorted(REGISTRY)

    by_code = {entry["code"]: entry for entry in payload}
    for code, element in REGISTRY.items():
        entry = by_code[code]
        assert entry["name"] == element.name
        assert entry["spice_form"] == element.spice_form
        assert decode_float(entry["complexity"]) == element.complexity
        assert [p["name"] for p in entry["params"]] == [spec.name for spec in element.params]
        assert [p["unit"] for p in entry["params"]] == [spec.unit for spec in element.params]
        assert [p["log_scale"] for p in entry["params"]] == [
            spec.log_scale for spec in element.params
        ]
        for p, spec in zip(entry["params"], element.params, strict=True):
            assert decode_float(p["hard_lo"]) == spec.hard_lo
            assert decode_float(p["hard_hi"]) == spec.hard_hi


def test_elements_reports_the_same_pools_as_the_registry() -> None:
    response = _call("elements")
    assert response["ok"] is True
    assert response["result"]["pools"] == {name: list(codes) for name, codes in POOLS.items()}


# =================================================================================================
# 10. `circuit` reproduces `Circuit.parse` and its tree addresses the same subtrees as
#     `subtree_paths`
# =================================================================================================


def test_circuit_reproduces_circuit_parse() -> None:
    text = "R2-R"
    circuit = Circuit.parse(text)
    response = _call("circuit", circuit=text)
    assert response["ok"] is True
    result = response["result"]

    assert result["circuit"] == circuit.to_string()
    assert result["canonical"] == circuit.canonical_form()
    assert result["n_elements"] == len(circuit.leaves)
    assert result["n_params"] == circuit.n_params
    assert decode_float(result["complexity"]) == circuit.complexity

    params = result["params"]
    assert [p["name"] for p in params] == list(circuit.param_names)
    assert [p["unit"] for p in params] == [spec.unit for spec in circuit.param_specs()]


def test_circuit_rejects_a_string_that_does_not_parse() -> None:
    response = _call("circuit", circuit="Q1")
    assert response["ok"] is False
    assert response["error"]["type"] == "CircuitSyntaxError"
    assert response["error"]["message"]


def test_circuit_tree_addresses_the_same_subtrees_as_subtree_paths() -> None:
    text = "R1-p(R2,C1-L1)"
    circuit = Circuit.parse(text)
    response = _call("circuit", circuit=text)
    assert response["ok"] is True
    tree = response["result"]["tree"]

    seen_paths: set[tuple[int, ...]] = set()

    def _walk(node: dict) -> None:
        path = tuple(node["path"])
        seen_paths.add(path)
        target = subtree_at(circuit.root, path)
        if node["kind"] == "element":
            assert isinstance(target, ElementNode)
        elif node["kind"] == "series":
            assert isinstance(target, Series)
        else:
            assert isinstance(target, Parallel)
        for child in node.get("children", []):
            _walk(child)

    _walk(tree)
    assert seen_paths == set(subtree_paths(circuit.root))


# =================================================================================================
# 11. With a spectrum, `circuit`'s per-parameter lower/upper/start equal `search_space` exactly
# =================================================================================================


def test_circuit_params_carry_search_space_bounds_with_a_spectrum() -> None:
    text = "C1-R1-L1"
    circuit = Circuit.parse(text)
    spectrum = simulate(
        text,
        log_frequencies(10.0, 1e6, 8),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        noise=0.01,
        seed=1,
    )
    lower, upper, start = search_space(circuit, spectrum)

    response = _call("circuit", circuit=text, spectrum=spectrum.to_wire())
    assert response["ok"] is True
    params = response["result"]["params"]
    assert [p["name"] for p in params] == list(circuit.param_names)
    for i, p in enumerate(params):
        assert decode_float(p["lower"]) == lower[i]
        assert decode_float(p["upper"]) == upper[i]
        assert decode_float(p["start"]) == start[i]


def test_circuit_params_start_at_the_fixed_value() -> None:
    text = "C1-R1-L1"
    circuit = Circuit.parse(text)
    spectrum = simulate(
        text,
        log_frequencies(10.0, 1e6, 8),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        noise=0.01,
        seed=2,
    )
    fixed = {"L1.L": 5e-10}
    lower, upper, start = search_space(circuit, spectrum, fixed=fixed)

    response = _call("circuit", circuit=text, spectrum=spectrum.to_wire(), fixed=fixed)
    assert response["ok"] is True
    params = response["result"]["params"]
    for i, p in enumerate(params):
        assert decode_float(p["lower"]) == lower[i]
        assert decode_float(p["upper"]) == upper[i]
        assert decode_float(p["start"]) == start[i]
    l1_index = circuit.param_names.index("L1.L")
    assert decode_float(params[l1_index]["start"]) == 5e-10


def test_circuit_params_respect_a_bounds_override() -> None:
    text = "R1-C1"
    circuit = Circuit.parse(text)
    spectrum = simulate(
        text,
        log_frequencies(10.0, 1e6, 8),
        {"R1.R": 25.0, "C1.C": 4.7e-6},
        noise=0.01,
        seed=3,
    )
    bounds = {"R1.R": (100.0, 200.0)}
    lower, upper, start = search_space(circuit, spectrum, bounds=bounds)

    response = _call(
        "circuit", circuit=text, spectrum=spectrum.to_wire(), bounds={"R1.R": [100.0, 200.0]}
    )
    assert response["ok"] is True
    params = response["result"]["params"]
    for i, p in enumerate(params):
        assert decode_float(p["lower"]) == lower[i]
        assert decode_float(p["upper"]) == upper[i]
        assert decode_float(p["start"]) == start[i]


# =================================================================================================
# 12. `edit` matches the core circuit-surgery helpers, and preserves surviving labels
# =================================================================================================


def test_edit_series_after_inserts_following_the_target() -> None:
    circuit = Circuit.parse("C1-R1")
    target = subtree_at(circuit.root, (1,))
    expected_root = replace_subtree(circuit.root, (1,), series(target, ElementNode("L")))
    expected = Circuit(expected_root).to_string()

    response = _call("edit", circuit="C1-R1", path=[1], action="series", code="L")
    assert response["ok"] is True
    assert response["result"]["circuit"] == expected


def test_edit_series_before_inserts_ahead_of_the_target() -> None:
    circuit = Circuit.parse("C1-R1")
    target = subtree_at(circuit.root, (1,))
    expected_root = replace_subtree(circuit.root, (1,), series(ElementNode("L"), target))
    expected = Circuit(expected_root).to_string()

    response = _call(
        "edit", circuit="C1-R1", path=[1], action="series", code="L", position="before"
    )
    assert response["ok"] is True
    assert response["result"]["circuit"] == expected


def test_edit_parallel_adds_a_branch_beside_the_target() -> None:
    circuit = Circuit.parse("C1-R1")
    target = subtree_at(circuit.root, (1,))
    expected_root = replace_subtree(circuit.root, (1,), parallel(target, ElementNode("C")))
    expected = Circuit(expected_root).to_string()

    response = _call("edit", circuit="C1-R1", path=[1], action="parallel", code="C")
    assert response["ok"] is True
    assert response["result"]["circuit"] == expected


def test_edit_replace_swaps_one_element_for_another() -> None:
    circuit = Circuit.parse("C1-R1")
    expected_root = replace_subtree(circuit.root, (1,), ElementNode("L"))
    expected = Circuit(expected_root).to_string()

    response = _call("edit", circuit="C1-R1", path=[1], action="replace", code="L")
    assert response["ok"] is True
    assert response["result"]["circuit"] == expected


def test_edit_remove_collapses_a_two_branch_parallel_into_the_surviving_branch() -> None:
    text = "C1-R1-p(R2,C2)"
    circuit = Circuit.parse(text)
    expected = Circuit(remove_subtree(circuit.root, (2, 1))).to_string()
    assert expected == "C1-R1-R2"

    response = _call("edit", circuit=text, path=[2, 1], action="remove")
    assert response["ok"] is True
    assert response["result"]["circuit"] == expected


def test_edit_remove_an_element_from_inside_a_branch() -> None:
    text = "R1-p(R2-C1,L1)"
    circuit = Circuit.parse(text)
    expected = Circuit(remove_subtree(circuit.root, (1, 0, 1))).to_string()
    assert expected == "R1-p(R2,L1)"

    response = _call("edit", circuit=text, path=[1, 0, 1], action="remove")
    assert response["ok"] is True
    assert response["result"]["circuit"] == expected


def test_edit_preserves_labels_of_elements_that_survive_it() -> None:
    """Editing "C1-R1" must go on calling the resistor "R1" so that its previous parameter
    values (or a fixed override keyed by that name) stay valid after the edit.
    """
    response = _call(
        "edit", circuit="C1-R1", path=[1], action="series", code="L", position="after"
    )
    assert response["ok"] is True
    result = response["result"]
    assert result["circuit"] == "C1-R1-L1"
    param_names = [p["name"] for p in result["params"]]
    assert "R1.R" in param_names
    assert "C1.C" in param_names


# =================================================================================================
# 13. `preview` matches `circuit.impedance` at `search_space`'s start, bit for bit
# =================================================================================================


def test_preview_with_no_values_matches_search_space_start_bit_for_bit() -> None:
    text = "C1-R1-L1"
    circuit = Circuit.parse(text)
    spectrum = simulate(
        text,
        log_frequencies(10.0, 1e6, 8),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        noise=0.01,
        seed=5,
    )
    _, _, start = search_space(circuit, spectrum)
    expected_z = circuit.impedance(spectrum.omega, start)

    response = _call("preview", circuit=text, spectrum=spectrum.to_wire())
    assert response["ok"] is True
    z_model = decode_complex_array(response["result"]["z_model"])
    assert np.array_equal(z_model, expected_z)
    assert decode_float(response["result"]["relative_error"]) == relative_error(
        expected_z, spectrum
    )


def test_preview_with_explicit_values_overrides_only_the_named_parameter() -> None:
    text = "C1-R1-L1"
    circuit = Circuit.parse(text)
    spectrum = simulate(
        text,
        log_frequencies(10.0, 1e6, 8),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        noise=0.01,
        seed=6,
    )
    _, _, start = search_space(circuit, spectrum)
    override = start.copy()
    override[circuit.param_names.index("R1.R")] = 0.5
    expected_z = circuit.impedance(spectrum.omega, override)

    response = _call("preview", circuit=text, spectrum=spectrum.to_wire(), values={"R1.R": 0.5})
    assert response["ok"] is True
    z_model = decode_complex_array(response["result"]["z_model"])
    assert np.array_equal(z_model, expected_z)
    # Only R1.R was overridden; C1.C and L1.L still show the search_space start.
    assert decode_float(response["result"]["values"]["C1.C"]) == start[
        circuit.param_names.index("C1.C")
    ]
    assert decode_float(response["result"]["values"]["L1.L"]) == start[
        circuit.param_names.index("L1.L")
    ]
    assert decode_float(response["result"]["values"]["R1.R"]) == 0.5


# =================================================================================================
# 14. `fit` matches `autocircuit.core.fit.fit` called directly, bit for bit
# =================================================================================================


def test_fit_matches_direct_fit_call_bit_for_bit() -> None:
    text = "R1-C1"
    truth = {"R1.R": 25.0, "C1.C": 4.7e-6}
    spectrum = simulate(text, log_frequencies(1.0, 1e6, 8), truth, noise=0.01, seed=9)
    expected = core_fit(text, spectrum, seed=3, restarts=2)

    response = _call("fit", circuit=text, spectrum=spectrum.to_wire(), seed=3, restarts=2)
    assert response["ok"] is True
    result = response["result"]
    np.testing.assert_array_equal(decode_array(result["fit"]["values"]), expected.values)
    assert result["summary"] == expected.summary(spectrum)
    assert result["warnings"] == list(expected.warnings)
    assert decode_float(result["relative_error"]) == expected.relative_error(spectrum)


# =================================================================================================
# 15. The new operations answer with errors, never exceptions, for bad input
# =================================================================================================


def test_edit_with_an_unknown_element_code_returns_an_error_response() -> None:
    response = _call("edit", circuit="R1-C1", path=[1], action="series", code="ZZ")
    assert response["ok"] is False
    assert response["error"]["type"] == "ValueError"
    assert "ZZ" in response["error"]["message"]


def test_edit_with_a_path_that_addresses_nothing_returns_an_error_response() -> None:
    response = _call("edit", circuit="R1-C1", path=[5], action="remove")
    assert response["ok"] is False
    assert response["error"]["type"] == "ValueError"


def test_edit_remove_on_a_single_element_circuit_returns_an_error_response() -> None:
    response = _call("edit", circuit="R1", path=[], action="remove")
    assert response["ok"] is False
    assert response["error"]["type"] == "CircuitError"


def test_edit_replace_aimed_at_a_parallel_block_returns_an_error_response() -> None:
    response = _call("edit", circuit="R1-p(R2,C1)", path=[1], action="replace", code="L")
    assert response["ok"] is False
    assert response["error"]["type"] == "ValueError"
    assert "element" in response["error"]["message"]


def test_preview_with_a_value_for_an_unknown_parameter_returns_an_error_response() -> None:
    spectrum = simulate("R1-C1", log_frequencies(1.0, 1e6, 5), {"R1.R": 10.0, "C1.C": 1e-6})
    response = _call(
        "preview", circuit="R1-C1", spectrum=spectrum.to_wire(), values={"R9.R": 1.0}
    )
    assert response["ok"] is False
    assert response["error"]["type"] == "ValueError"
    assert "R9.R" in response["error"]["message"]


# =================================================================================================
# 16. Every response satisfies the real wire contract
# =================================================================================================


def test_version_operation_reports_versions_and_formats() -> None:
    """Exercises the one operation not otherwise covered above, through the same `_call`
    helper that checks wire safety on every other operation's response.
    """
    response = _call("version")
    assert response["ok"] is True
    result = response["result"]
    assert result["bridge"] == BRIDGE_VERSION
    assert result["spectrum"] == SPECTRUM_WIRE_VERSION
    assert result["validate"] == VALIDATE_WIRE_VERSION
    assert result["formats"] == sorted(io.REGISTRY)


def test_bridge_version_is_bumped_for_the_new_operations() -> None:
    """Pins the value rather than just its presence: a worker checks this at start-up and a
    stale cached bundle must fail loudly instead of answering with the old protocol.
    """
    assert BRIDGE_VERSION == 2


def test_every_response_above_parses_as_json_and_re_dumps_without_allow_nan() -> None:
    """The wire contract stated explicitly: `json.loads` succeeds, and re-dumping the parsed
    object with `json.dumps(obj, allow_nan=False)` succeeds too -- the point of the latter is
    that Python's default `json.dumps` would accept bare `Infinity`/`NaN` tokens that
    `JSON.parse` cannot (docs/HANDOFF.md section 3), so proving the default dump works proves
    nothing. `_call` and the direct `handle()` calls throughout this module already funnel every
    response through `_assert_wire_safe`; this test collects a few of each kind again as a
    single, explicit checkpoint.
    """
    spectrum = simulate("R1-C1", log_frequencies(1e1, 1e5, 4), {"R1.R": 10.0, "C1.C": 1e-6})
    responses = [
        handle(json.dumps({"op": "version"})),
        handle(json.dumps({"op": "trim", "spectrum": spectrum.to_wire(), "f_min": 1e2})),
        handle(json.dumps({"op": "validate", "spectrum": spectrum.to_wire()})),
        handle(json.dumps({"op": "read", "path": str(DATA / "does_not_exist.csv")})),
        handle("not valid json"),
        handle(json.dumps({"op": "elements"})),
        handle(json.dumps({"op": "circuit", "circuit": "R1-p(R2,C1)"})),
        handle(
            json.dumps(
                {
                    "op": "circuit",
                    "circuit": "R1-p(R2,C1)",
                    "spectrum": spectrum.to_wire(),
                }
            )
        ),
        handle(
            json.dumps(
                {"op": "edit", "circuit": "R1-C1", "path": [1], "action": "series", "code": "L"}
            )
        ),
        handle(json.dumps({"op": "preview", "circuit": "R1-C1", "spectrum": spectrum.to_wire()})),
        handle(
            json.dumps(
                {
                    "op": "fit",
                    "circuit": "R1-C1",
                    "spectrum": spectrum.to_wire(),
                    "restarts": 2,
                    "seed": 0,
                }
            )
        ),
        handle(json.dumps({"op": "circuit", "circuit": "Q1"})),
    ]
    for response_text in responses:
        parsed = json.loads(response_text)
        _assert_wire_safe(parsed)
