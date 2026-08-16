"""Tests for the circuit DSL, the Circuit expression tree and the Spectrum container."""

from __future__ import annotations

import numpy as np
import pytest
from numpy.testing import assert_allclose

from autocircuit.core.circuit import Circuit, CircuitError, move_subtree, remove_subtree, simplify
from autocircuit.core.dsl import CircuitSyntaxError
from autocircuit.core.spectrum import Spectrum

Float = np.ndarray


def _omega(f_hz: Float | list[float]) -> Float:
    return 2.0 * np.pi * np.asarray(f_hz, dtype=np.float64)


# =============================================================================================
# DSL parsing
# =============================================================================================


def test_round_trips_through_to_string() -> None:
    circuit = Circuit.parse("R1-L1-p(R2,C1)")
    assert circuit.to_string() == "R1-L1-p(R2,C1)"


def test_auto_labelling_fills_in_missing_labels_in_evaluation_order() -> None:
    circuit = Circuit.parse("R-C-L")
    assert circuit.to_string() == "R1-C1-L1"
    assert circuit.param_names == ("R1.R", "C1.C", "L1.L")


def test_explicit_labels_are_preserved() -> None:
    circuit = Circuit.parse("R5-C2")
    assert circuit.to_string() == "R5-C2"
    assert circuit.param_names == ("R5.R", "C2.C")


def test_mixed_explicit_and_auto_labels_avoid_collisions() -> None:
    # R2 is explicit; the auto-labeller must not reuse "R2" for the unlabelled R.
    circuit = Circuit.parse("R2-R")
    labels = [leaf.label for leaf in circuit.leaves]
    assert labels == ["R2", "R1"]


def test_duplicate_explicit_labels_raise() -> None:
    with pytest.raises(CircuitError):
        Circuit.parse("R1-R1")


@pytest.mark.parametrize(
    ("text", "expected_code"),
    [
        ("ws1", "Ws"),
        ("WS1", "Ws"),
        ("cc1", "CC"),
        ("Cc1", "CC"),
        ("w1", "W"),
        ("W1", "W"),
        ("cpe1", "CPE"),
        ("CPE1", "CPE"),
        ("skinf1", "SKINF"),
        ("skinw1", "SKINW"),
    ],
)
def test_codes_are_matched_case_insensitively_and_longest_first(
    text: str, expected_code: str
) -> None:
    circuit = Circuit.parse(text)
    assert len(circuit.leaves) == 1
    assert circuit.leaves[0].code == expected_code


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "R1-",
        "p(R1)",
        "Q1",
        "p(R1,C1",
        "p(,R1)",
        "R1-p(C1,R2))",
    ],
)
def test_syntax_errors_raise_circuit_syntax_error(text: str) -> None:
    with pytest.raises(CircuitSyntaxError):
        Circuit.parse(text)


# =============================================================================================
# Evaluation
# =============================================================================================


def test_series_impedance_is_the_sum() -> None:
    circuit = Circuit.parse("R1-L1")
    omega = _omega([100.0, 1000.0, 1.0e6])
    r, ind = 47.0, 3.3e-3
    z = circuit.impedance(omega, np.array([r, ind]))
    expected = r + 1j * omega * ind
    assert_allclose(z, expected, rtol=1e-12)


def test_parallel_impedance_matches_hand_computed_closed_form() -> None:
    circuit = Circuit.parse("p(R1,C1)")
    r, c = 220.0, 1.0e-7
    omega = _omega([10.0, 1000.0, 1.0e6])
    z = circuit.impedance(omega, np.array([r, c]))
    expected = r / (1.0 + 1j * omega * r * c)
    assert_allclose(z, expected, rtol=1e-12)


def test_nested_series_and_parallel_structure_evaluates_correctly() -> None:
    # p(R1, C1-p(R2,L1)): outer parallel of R1 with [C1 in series with (R2 || L1)].
    circuit = Circuit.parse("p(R1,C1-p(R2,L1))")
    r1, c1, r2, l1 = 100.0, 2.0e-7, 50.0, 1.0e-3
    omega = _omega([200.0, 5000.0, 2.0e6])

    z_r2_l1 = 1.0 / (1.0 / r2 + 1.0 / (1j * omega * l1))
    z_branch = 1.0 / (1j * omega * c1) + z_r2_l1
    expected = 1.0 / (1.0 / r1 + 1.0 / z_branch)

    z = circuit.impedance(omega, np.array([r1, c1, r2, l1]))
    assert_allclose(z, expected, rtol=1e-12)


def test_impedance_raises_on_wrong_length_parameter_vector() -> None:
    circuit = Circuit.parse("R1-C1")
    with pytest.raises(CircuitError):
        circuit.impedance(_omega([1.0]), np.array([1.0]))


def test_impedance_raises_on_wrong_row_count_for_batched_values() -> None:
    circuit = Circuit.parse("R1-C1")
    with pytest.raises(CircuitError):
        circuit.impedance(_omega([1.0, 2.0]), np.ones((3, 5)))


# =============================================================================================
# canonical_form
# =============================================================================================


def test_canonical_form_is_order_independent_within_a_parallel_block() -> None:
    a = Circuit.parse("p(R1,C1)")
    b = Circuit.parse("p(C9,R3)")
    assert a.canonical_form() == b.canonical_form()
    assert a == b


def test_canonical_form_distinguishes_series_from_parallel() -> None:
    series = Circuit.parse("R1-C1")
    parallel = Circuit.parse("p(R1,C1)")
    assert series.canonical_form() != parallel.canonical_form()
    assert series != parallel


# =============================================================================================
# canonicalize_values
# =============================================================================================


def test_canonicalize_values_reorders_swapped_identical_blocks_to_the_same_vector() -> None:
    circuit = Circuit.parse("p(R1,C1)-p(R2,C2)")
    assert circuit.param_names == ("R1.R", "C1.C", "R2.R", "C2.C")

    block_a = [10.0, 1.0e-6]
    block_b = [20.0, 2.0e-6]
    values_forward = np.array(block_a + block_b)
    values_swapped = np.array(block_b + block_a)

    canon_forward = circuit.canonicalize_values(values_forward)
    canon_swapped = circuit.canonicalize_values(values_swapped)
    assert_allclose(canon_forward, canon_swapped)

    omega = _omega([100.0, 1.0e4, 1.0e7])
    z_forward = circuit.impedance(omega, values_forward)
    z_canon = circuit.impedance(omega, canon_forward)
    assert_allclose(z_forward, z_canon, rtol=1e-12)


# =============================================================================================
# simplify
# =============================================================================================


def test_simplify_collapses_series_resistors() -> None:
    result = Circuit(simplify(Circuit.parse("R1-R2").root))
    assert result.to_string() == "R1"


def test_simplify_collapses_parallel_resistors() -> None:
    result = Circuit(simplify(Circuit.parse("p(R1,R2)").root))
    assert result.to_string() == "R1"


def test_simplify_collapses_series_capacitors() -> None:
    result = Circuit(simplify(Circuit.parse("C1-C2").root))
    assert result.to_string() == "C1"


def test_simplify_collapses_parallel_inductors() -> None:
    result = Circuit(simplify(Circuit.parse("p(L1,L2)").root))
    assert result.to_string() == "L1"


def test_simplify_leaves_series_rc_untouched() -> None:
    result = Circuit(simplify(Circuit.parse("R1-C1").root))
    assert result.to_string() == "R1-C1"


def test_simplify_leaves_parallel_rc_untouched() -> None:
    result = Circuit(simplify(Circuit.parse("p(R1,C1)").root))
    assert result.to_string() == "p(R1,C1)"


def test_simplify_leaves_cpe_pair_untouched() -> None:
    # CPE is not in the mergeable set even though two of them sit in series.
    result = Circuit(simplify(Circuit.parse("CPE1-CPE2").root))
    assert result.to_string() == "CPE1-CPE2"


# =============================================================================================
# remove_subtree
# =============================================================================================


def test_remove_subtree_collapses_a_two_branch_parallel_into_the_surviving_branch() -> None:
    circuit = Circuit.parse("C1-R1-p(R2,C2)")
    result = Circuit(remove_subtree(circuit.root, (2, 1)))
    assert result.to_string() == "C1-R1-R2"


def test_remove_subtree_goes_through_series_and_parallel_matching_a_fresh_parse() -> None:
    # Removing R2 collapses p(R2,C1) down to the surviving branch C1, which must merge into
    # the surrounding series connection exactly as series() would when parsing from scratch.
    circuit = Circuit.parse("R1-p(R2,C1)-L1")
    result = Circuit(remove_subtree(circuit.root, (1, 0)))
    assert result.to_string() == "R1-C1-L1"
    reparsed = Circuit.parse(result.to_string())
    assert result.canonical_form() == reparsed.canonical_form()


def test_remove_subtree_removes_an_element_nested_inside_a_branch() -> None:
    circuit = Circuit.parse("R1-p(R2-C1,L1)")
    result = Circuit(remove_subtree(circuit.root, (1, 0, 1)))
    assert result.to_string() == "R1-p(R2,L1)"


def test_remove_subtree_of_the_root_raises() -> None:
    circuit = Circuit.parse("R1-C1")
    with pytest.raises(CircuitError):
        remove_subtree(circuit.root, ())


def test_remove_subtree_with_an_out_of_range_index_raises() -> None:
    # Must raise rather than silently deleting a different child.
    circuit = Circuit.parse("R1-C1-L1")
    with pytest.raises(CircuitError):
        remove_subtree(circuit.root, (5,))


def test_remove_subtree_with_a_negative_index_raises() -> None:
    # A negative index must not be interpreted as Python-style indexing from the end -- that
    # would silently delete a different child than the one the path names.
    circuit = Circuit.parse("R1-C1-L1")
    with pytest.raises(CircuitError):
        remove_subtree(circuit.root, (-1,))


def test_remove_subtree_running_past_a_leaf_raises() -> None:
    circuit = Circuit.parse("R1-C1")
    with pytest.raises(CircuitError):
        remove_subtree(circuit.root, (0, 0))


# =============================================================================================
# move_subtree
# =============================================================================================


def test_move_subtree_reorders_a_series_element() -> None:
    circuit = Circuit.parse("R1-C1-L1")
    result = Circuit(move_subtree(circuit.root, (0,), (2,), "series"))
    assert result.to_string() == "C1-L1-R1"


def test_move_subtree_moves_an_element_into_parallel_with_another() -> None:
    circuit = Circuit.parse("R1-C1-L1")
    result = Circuit(move_subtree(circuit.root, (1,), (2,), "parallel"))
    assert result.to_string() == "R1-p(L1,C1)"


def test_move_subtree_out_of_a_two_branch_parallel_block_collapses_it_into_the_survivor() -> None:
    # Moving R2 out of p(R2,C2) leaves only C2 there, which collapses into the surrounding
    # series connection exactly as remove_subtree already does on its own.
    circuit = Circuit.parse("C1-R1-p(R2,C2)")
    result = Circuit(move_subtree(circuit.root, (2, 0), (0,), "series"))
    assert result.to_string() == "C1-R2-R1-C2"


def test_move_subtree_preserves_the_moved_element_label() -> None:
    circuit = Circuit.parse("R1-C1-L1")
    result = Circuit(move_subtree(circuit.root, (0,), (2,), "series"))
    assert "R1.R" in result.param_names
    assert "C1.C" in result.param_names
    assert "L1.L" in result.param_names


def test_move_subtree_with_source_equal_to_target_is_a_no_op() -> None:
    circuit = Circuit.parse("R1-C1-L1")
    result = Circuit(move_subtree(circuit.root, (1,), (1,), "series"))
    assert result.to_string() == "R1-C1-L1"


def test_move_subtree_into_the_parallel_block_the_element_is_already_in_is_a_no_op() -> None:
    circuit = Circuit.parse("R2-p(R1,C1)")
    result = Circuit(move_subtree(circuit.root, (1, 0), (1,), "parallel"))
    assert result == Circuit.parse("R2-p(R1,C1)")


def test_move_subtree_of_the_root_raises() -> None:
    circuit = Circuit.parse("R1-C1")
    with pytest.raises(CircuitError):
        move_subtree(circuit.root, (), (1,), "series")


def test_move_subtree_with_a_source_path_running_past_a_leaf_raises() -> None:
    circuit = Circuit.parse("R1-C1")
    with pytest.raises(CircuitError):
        move_subtree(circuit.root, (0, 0), (1,), "series")


# =============================================================================================
# values_dict / values_array
# =============================================================================================


def test_values_dict_and_values_array_round_trip() -> None:
    circuit = Circuit.parse("R1-C1-L1")
    values = np.array([10.0, 1.0e-6, 2.0e-3])
    mapping = circuit.values_dict(values)
    assert mapping == {"R1.R": 10.0, "C1.C": 1.0e-6, "L1.L": 2.0e-3}
    round_tripped = circuit.values_array(mapping)
    assert_allclose(round_tripped, values)


def test_values_array_raises_on_missing_parameter() -> None:
    circuit = Circuit.parse("R1-C1")
    with pytest.raises(CircuitError):
        circuit.values_array({"R1.R": 10.0})


# =============================================================================================
# Spectrum
# =============================================================================================


def test_spectrum_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        Spectrum(np.array([]), np.array([]))


def test_spectrum_rejects_non_positive_frequencies() -> None:
    with pytest.raises(ValueError):
        Spectrum(np.array([1.0, -2.0]), np.array([1 + 1j, 2 + 2j]))


def test_spectrum_rejects_zero_frequency() -> None:
    with pytest.raises(ValueError):
        Spectrum(np.array([0.0, 1.0]), np.array([1 + 1j, 2 + 2j]))


def test_spectrum_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        Spectrum(np.array([1.0, 2.0, 3.0]), np.array([1 + 1j, 2 + 2j]))


def test_spectrum_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError):
        Spectrum(np.array([1.0, np.nan]), np.array([1 + 1j, 2 + 2j]))
    with pytest.raises(ValueError):
        Spectrum(np.array([1.0, 2.0]), np.array([1 + 1j, complex(np.inf, 0.0)]))


def test_spectrum_sorts_unsorted_frequencies_and_reorders_z_with_them() -> None:
    spectrum = Spectrum(np.array([3.0, 1.0, 2.0]), np.array([3 + 3j, 1 + 1j, 2 + 2j]))
    assert_allclose(spectrum.f, [1.0, 2.0, 3.0])
    assert_allclose(spectrum.z, [1 + 1j, 2 + 2j, 3 + 3j])


def test_from_polar_and_from_parts_agree_for_the_same_data() -> None:
    f = np.array([10.0, 100.0, 1000.0])
    re = np.array([3.0, -1.0, 5.0])
    im = np.array([4.0, 2.0, -2.0])
    from_parts = Spectrum.from_parts(f, re, im)

    magnitude = np.abs(re + 1j * im)
    phase_deg = np.degrees(np.angle(re + 1j * im))
    from_polar = Spectrum.from_polar(f, magnitude, phase_deg)

    assert_allclose(from_polar.z.real, from_parts.z.real, atol=1e-10)
    assert_allclose(from_polar.z.imag, from_parts.z.imag, atol=1e-10)


def test_select_windows_by_frequency_inclusive() -> None:
    f = np.array([1.0, 10.0, 100.0, 1000.0])
    z = np.array([1 + 0j, 2 + 0j, 3 + 0j, 4 + 0j])
    spectrum = Spectrum(f, z)
    windowed = spectrum.select(f_min=10.0, f_max=100.0)
    assert_allclose(windowed.f, [10.0, 100.0])
    assert_allclose(windowed.z, [2 + 0j, 3 + 0j])


def test_select_raises_when_window_is_empty() -> None:
    spectrum = Spectrum(np.array([1.0, 2.0]), np.array([1 + 0j, 2 + 0j]))
    with pytest.raises(ValueError):
        spectrum.select(f_min=100.0)
