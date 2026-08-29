"""Tests for `benchmarks/autoeis_round/translate.py`, the AutoEIS <-> AutoCircuit translator.

A mistranslated circuit still parses and still fits something, so a bug here would silently
turn into a wrong benchmark score with no visible symptom -- which is why this translator gets
its own test suite rather than being trusted on sight. See the module docstring of
`translate.py` for the two grammars this reconciles.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from numpy.testing import assert_allclose

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks" / "autoeis_round"))

from translate import TranslationError, to_autocircuit, to_autoeis  # noqa: E402

from autocircuit.core.circuit import Circuit  # noqa: E402

Float = np.ndarray


def _omega(f_hz: Float | list[float]) -> Float:
    return 2.0 * np.pi * np.asarray(f_hz, dtype=np.float64)


# =============================================================================================
# Forward topology translation, hand-checked
# =============================================================================================


def test_single_element_translates_unchanged() -> None:
    text, params = to_autocircuit("R1")
    assert text == "R1"
    assert params == {}


def test_two_branch_parallel_translates_to_p_form() -> None:
    text, _ = to_autocircuit("[R1,C2]")
    assert text == "p(R1,C1)"


def test_series_of_element_and_parallel_renumbers_per_type() -> None:
    text, _ = to_autocircuit("R1-[P2,R3]")
    assert text == "R1-p(CPE1,R2)"


def test_three_branch_parallel() -> None:
    text, _ = to_autocircuit("[R1,C2,L3]")
    assert text == "p(R1,C1,L1)"


def test_nested_parallel_matches_hand_derived_string() -> None:
    # Source tree, from AutoEIS's own left-to-right, single-global-counter numbering:
    #   Series(
    #     Parallel(
    #       Series(Parallel(Series(P1, L2), R3), Parallel(L4, R5)),
    #       R6,
    #     ),
    #     R7,
    #   )
    # Leaves in written order: P1, L2, R3, L4, R5, R6, R7.
    # Renumbering per AutoCircuit type, in that same left-to-right order:
    #   P1 -> CPE1, L2 -> L1, R3 -> R1, L4 -> L2, R5 -> R2, R6 -> R3, R7 -> R4.
    # Rebuilding the same tree shape with those labels and formatting with 'p(...)' for
    # parallel gives, innermost first:
    #   Series(P1, L2)        -> "CPE1-L1"
    #   Parallel(that, R3)    -> "p(CPE1-L1,R1)"
    #   Parallel(L4, R5)      -> "p(L2,R2)"
    #   Series(the two above) -> "p(CPE1-L1,R1)-p(L2,R2)"
    #   Parallel(that, R6)    -> "p(p(CPE1-L1,R1)-p(L2,R2),R3)"
    #   Series(that, R7)      -> "p(p(CPE1-L1,R1)-p(L2,R2),R3)-R4"
    text, _ = to_autocircuit("[[P1-L2,R3]-[L4,R5],R6]-R7")
    assert text == "p(p(CPE1-L1,R1)-p(L2,R2),R3)-R4"


# =============================================================================================
# Parameter translation
# =============================================================================================


def test_parameter_mapping_including_a_cpe() -> None:
    text, params = to_autocircuit("[P1,R2]", {"P1w": 1e-5, "P1n": 0.8, "R2": 200.0})
    assert text == "p(CPE1,R1)"
    assert params == {"CPE1.Q": 1e-5, "CPE1.n": 0.8, "R1.R": 200.0}


def test_to_autoeis_parameter_mapping_including_a_cpe() -> None:
    text, params = to_autoeis("p(CPE1,R1)", {"CPE1.Q": 1e-5, "CPE1.n": 0.8, "R1.R": 200.0})
    assert text == "[P1,R2]"
    assert params == {"P1w": 1e-5, "P1n": 0.8, "R2": 200.0}


def test_none_params_translates_topology_only() -> None:
    text, params = to_autocircuit("R1-C2")
    assert text == "R1-C1"
    assert params == {}
    text, params = to_autoeis("R1-C1")
    assert text == "R1-C2"
    assert params == {}


# =============================================================================================
# Round trip: AutoCircuit -> AutoEIS -> AutoCircuit returns the original string
# =============================================================================================


@pytest.mark.parametrize(
    "text",
    [
        "R1",
        "p(R1,C1)",
        "R1-p(CPE1,R2)",
        "p(R1,C1,L1)",
        "p(R1,C1)-p(R2,C2)",
        "R1-p(CPE1,R2-C1)",
        "R1-L1-p(CPE1,R2)-p(R3,C1)",
        "p(p(CPE1-L1,R1)-p(L2,R2),R3)-R4",
    ],
)
def test_round_trip_through_autoeis_recovers_the_original_string(text: str) -> None:
    autoeis_text, _ = to_autoeis(text)
    recovered, _ = to_autocircuit(autoeis_text)
    assert recovered == text


# =============================================================================================
# Numerical round trip: translation must not rewire the circuit
# =============================================================================================


def _autoeis_impedance_series_with_one_cpe_parallel_block(
    omega: Float, r1: float, p2w: float, p2n: float, r3: float
) -> Float:
    """Hand-assembled impedance of AutoEIS's ``R1-[P2,R3]``, independent of translate.py."""
    z_p2 = 1.0 / (p2w * (1j * omega) ** p2n)
    z_parallel = 1.0 / (1.0 / z_p2 + 1.0 / r3)
    return r1 + z_parallel


def test_numerical_round_trip_series_with_one_cpe_parallel_block() -> None:
    autoeis_params = {"R1": 50.0, "P2w": 2.0e-4, "P2n": 0.75, "R3": 120.0}
    text, params = to_autocircuit("R1-[P2,R3]", autoeis_params)

    omega = _omega(np.logspace(-1, 6, 25))
    circuit = Circuit.parse(text)
    z_translated = circuit.impedance(omega, circuit.values_array(params))
    z_reference = _autoeis_impedance_series_with_one_cpe_parallel_block(
        omega, autoeis_params["R1"], autoeis_params["P2w"], autoeis_params["P2n"],
        autoeis_params["R3"],
    )
    assert_allclose(z_translated, z_reference, rtol=1e-12)


def _autoeis_impedance_nested_example(
    omega: Float,
    p1w: float, p1n: float, l2: float, r3: float, l4: float, r5: float, r6: float, r7: float,
) -> Float:
    """Hand-assembled impedance of AutoEIS's ``[[P1-L2,R3]-[L4,R5],R6]-R7``.

    Tree: Series(Parallel(Series(Parallel(Series(P1,L2),R3), Parallel(L4,R5)), R6), R7).
    Built independently of translate.py, straight from the impedance formulas in the module
    docstring, so a translation that parses correctly but rewires which elements are in series
    versus in parallel is still caught.
    """
    z_p1 = 1.0 / (p1w * (1j * omega) ** p1n)
    z_l2 = 1j * omega * l2
    branch_a = 1.0 / (1.0 / (z_p1 + z_l2) + 1.0 / r3)
    branch_b = 1.0 / (1.0 / (1j * omega * l4) + 1.0 / r5)
    mid_series = branch_a + branch_b
    outer_parallel = 1.0 / (1.0 / mid_series + 1.0 / r6)
    return outer_parallel + r7


def test_numerical_round_trip_nested_example() -> None:
    autoeis_params = {
        "P1w": 1.0e-5, "P1n": 0.8, "L2": 1.0e-3, "R3": 50.0,
        "L4": 2.0e-3, "R5": 80.0, "R6": 30.0, "R7": 10.0,
    }
    text, params = to_autocircuit("[[P1-L2,R3]-[L4,R5],R6]-R7", autoeis_params)

    omega = _omega(np.logspace(-1, 6, 25))
    circuit = Circuit.parse(text)
    z_translated = circuit.impedance(omega, circuit.values_array(params))
    z_reference = _autoeis_impedance_nested_example(
        omega,
        autoeis_params["P1w"], autoeis_params["P1n"], autoeis_params["L2"], autoeis_params["R3"],
        autoeis_params["L4"], autoeis_params["R5"], autoeis_params["R6"], autoeis_params["R7"],
    )
    assert_allclose(z_translated, z_reference, rtol=1e-12)


# =============================================================================================
# Error cases
# =============================================================================================


def test_empty_string_raises_both_directions() -> None:
    with pytest.raises(TranslationError):
        to_autocircuit("")
    with pytest.raises(TranslationError):
        to_autoeis("")
    with pytest.raises(TranslationError):
        to_autocircuit("   ")


def test_unknown_element_type_inbound_raises() -> None:
    # AutoEIS only has R, C, L and P; 'Q' is not one of them.
    with pytest.raises(TranslationError):
        to_autocircuit("Q1")


@pytest.mark.parametrize("code", ["W", "Ws", "Wo", "G", "CC", "HN", "SKINF", "SKINW"])
def test_element_with_no_autoeis_equivalent_raises_outbound(code: str) -> None:
    with pytest.raises(TranslationError):
        to_autoeis(f"{code}1")


def test_parallel_block_with_one_branch_raises_inbound() -> None:
    with pytest.raises(TranslationError):
        to_autocircuit("[R1]")


def test_parallel_block_with_one_branch_raises_outbound() -> None:
    with pytest.raises(TranslationError):
        to_autoeis("p(R1)")


def test_unbalanced_brackets_raises_inbound() -> None:
    with pytest.raises(TranslationError):
        to_autocircuit("[R1,C2")


def test_unbalanced_parens_raises_outbound() -> None:
    with pytest.raises(TranslationError):
        to_autoeis("p(R1,C2")


def test_trailing_junk_raises_inbound() -> None:
    with pytest.raises(TranslationError):
        to_autocircuit("R1]")


def test_trailing_junk_raises_outbound() -> None:
    with pytest.raises(TranslationError):
        to_autoeis("R1)")


def test_missing_parameter_key_raises_inbound() -> None:
    with pytest.raises(TranslationError):
        to_autocircuit("R1-C2", {"R1": 10.0})  # C2 missing


def test_extra_parameter_key_raises_inbound() -> None:
    with pytest.raises(TranslationError):
        to_autocircuit("R1", {"R1": 10.0, "C2": 5.0})  # C2 not in the circuit


def test_missing_parameter_key_raises_outbound() -> None:
    with pytest.raises(TranslationError):
        to_autoeis("R1-C1", {"R1.R": 10.0})  # C1.C missing


def test_extra_parameter_key_raises_outbound() -> None:
    with pytest.raises(TranslationError):
        to_autoeis("R1", {"R1.R": 10.0, "C1.C": 5.0})  # C1.C not in the circuit


def test_duplicate_labels_raise_inbound() -> None:
    with pytest.raises(TranslationError):
        to_autocircuit("R1-R1")


def test_duplicate_labels_raise_outbound() -> None:
    with pytest.raises(TranslationError):
        to_autoeis("R1-R1")
