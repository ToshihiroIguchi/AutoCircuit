"""SPICE export tests.

The important test here is not that the ladder maths is right in isolation -- that is checked
directly -- but that the *emitted netlist* has the impedance it is supposed to have. Node
allocation for nested series/parallel structures is exactly the kind of thing that produces a
netlist which looks plausible and simulates as something else entirely, so these tests parse
the generated netlist back and solve it by nodal analysis, the same way an AC sweep would.
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from autocircuit.core.circuit import Circuit
from autocircuit.core.elements import REGISTRY
from autocircuit.core.spice import Ladder, synthesize_ladder, to_netlist


# -- A minimal SPICE AC engine ---------------------------------------------------------------


def netlist_impedance(
    netlist: str, omega: NDArray[np.float64], port_a: str = "1", port_b: str = "2"
) -> NDArray[np.complex128]:
    """Solve a passive R/C/L subcircuit by nodal analysis and return Z between its ports.

    One ampere is injected at ``port_a`` with ``port_b`` grounded, so the resulting node
    voltage at ``port_a`` is numerically the port impedance. This is what a SPICE AC analysis
    of the same netlist computes.
    """
    devices: list[tuple[str, str, str, float]] = []
    for raw in netlist.splitlines():
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith("."):
            continue
        parts = line.split()
        if len(parts) != 4:
            raise AssertionError(f"unexpected netlist line: {line!r}")
        name, node_a, node_b, value = parts
        kind = name[0].upper()
        if kind not in "RCL":
            raise AssertionError(f"unsupported device in netlist: {line!r}")
        devices.append((kind, node_a, node_b, float(value)))

    nodes = sorted({n for _, a, b, _ in devices for n in (a, b)} - {port_b})
    index = {name: i for i, name in enumerate(nodes)}
    n = len(nodes)

    out = np.empty(omega.shape, dtype=np.complex128)
    for k, w in enumerate(omega):
        y_matrix = np.zeros((n, n), dtype=np.complex128)
        for kind, node_a, node_b, value in devices:
            if kind == "R":
                y = 1.0 / value
            elif kind == "C":
                y = 1j * w * value
            else:
                y = 1.0 / (1j * w * value)
            for node, sign in ((node_a, 1), (node_b, 1)):
                if node in index:
                    y_matrix[index[node], index[node]] += y * sign
            if node_a in index and node_b in index:
                y_matrix[index[node_a], index[node_b]] -= y
                y_matrix[index[node_b], index[node_a]] -= y
        current = np.zeros(n, dtype=np.complex128)
        current[index[port_a]] = 1.0
        voltages = np.linalg.solve(y_matrix, current)
        out[k] = voltages[index[port_a]]
    return out


def test_netlist_engine_matches_known_series_rlc() -> None:
    """Sanity-check the test engine itself before trusting it to judge the exporter."""
    netlist = ".subckt T 1 2\nR_a 1 n1 10\nL_a n1 n2 1e-3\nC_a n2 2 1e-6\n.ends T"
    omega = 2 * np.pi * np.logspace(1, 5, 25)
    expected = 10.0 + 1j * omega * 1e-3 + 1.0 / (1j * omega * 1e-6)
    np.testing.assert_allclose(netlist_impedance(netlist, omega), expected, rtol=1e-10)


def test_netlist_engine_matches_known_parallel_rc() -> None:
    netlist = ".subckt T 1 2\nR_a 1 2 100\nC_a 1 2 1e-9\n.ends T"
    omega = 2 * np.pi * np.logspace(1, 8, 25)
    expected = 100.0 / (1.0 + 1j * omega * 100.0 * 1e-9)
    np.testing.assert_allclose(netlist_impedance(netlist, omega), expected, rtol=1e-10)


# -- Ladder synthesis ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "values", "form"),
    [
        ("CPE", np.array([1e-6, 0.8]), "rc"),
        ("CPE", np.array([1e-6, 0.5]), "rc"),
        ("CPE", np.array([1e-6, 0.2]), "rc"),
        ("W", np.array([100.0]), "rc"),
        ("Ws", np.array([50.0, 1e-5]), "rc"),
        ("Wo", np.array([50.0, 1e-5]), "rc"),
        ("G", np.array([50.0, 1e-5]), "rc"),
        ("SKINF", np.array([2e-5, 0.5]), "rl"),
        ("SKINF", np.array([2e-5, 0.7]), "rl"),
        ("SKINW", np.array([1e-2, 1e-8]), "rl"),
    ],
)
def test_ladder_meets_accuracy_target(code: str, values: np.ndarray, form: str) -> None:
    """Every fractional element must be reproducible to 1% over seven decades."""
    element = REGISTRY[code]
    f_min, f_max = 1e2, 1e9
    ladder = synthesize_ladder(
        lambda w: element.impedance(w, values), f_min, f_max, form, error_target=0.01
    )
    omega = 2 * np.pi * np.logspace(np.log10(f_min), np.log10(f_max), 500)
    error = np.max(np.abs(ladder.impedance(omega) - element.impedance(omega, values))
                   / np.abs(element.impedance(omega, values)))
    assert error <= 0.01, f"{code} ladder error {error:.3%}"
    assert ladder.max_relative_error <= 0.01


@pytest.mark.parametrize(("code", "values", "form"), [
    ("CPE", np.array([1e-6, 0.5]), "rc"),
    ("SKINF", np.array([2e-5, 0.5]), "rl"),
])
def test_ladder_sections_are_passive(code: str, values: np.ndarray, form: str) -> None:
    """Non-negative least squares must never emit a negative R, C or L."""
    element = REGISTRY[code]
    ladder = synthesize_ladder(
        lambda w: element.impedance(w, values), 1e2, 1e9, form, error_target=0.01
    )
    assert ladder.r_series >= 0.0
    assert ladder.reactive_series >= 0.0
    for r, x in ladder.sections:
        assert r > 0.0
        assert x > 0.0


def test_ladder_rejects_bad_band() -> None:
    element = REGISTRY["W"]
    with pytest.raises(ValueError):
        synthesize_ladder(lambda w: element.impedance(w, np.array([1.0])), 1e3, 1e2, "rc")


def test_ladder_impedance_of_empty_ladder() -> None:
    ladder = Ladder("rc", 5.0, 0.0, (), 1.0, 10.0, 0.0)
    omega = 2 * np.pi * np.array([1.0, 10.0])
    np.testing.assert_allclose(ladder.impedance(omega), np.full(2, 5.0 + 0j))


# -- Netlist generation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dsl", "params"),
    [
        ("R1", {"R1.R": 47.0}),
        ("C1-R1-L1", {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10}),
        ("p(R1,C1)", {"R1.R": 1e4, "C1.C": 1e-10}),
        (
            "p(R1,C1)-p(R2,C2)",
            {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8},
        ),
        (
            "R1-p(C1,R2-L1)",
            {"R1.R": 20.0, "C1.C": 1e-6, "R2.R": 100.0, "L1.L": 1e-6},
        ),
        (
            "p(R1,C1-p(R2,L1))-R3",
            {"R1.R": 1e3, "C1.C": 1e-9, "R2.R": 200.0, "L1.L": 1e-5, "R3.R": 7.0},
        ),
    ],
)
def test_primitive_netlist_reproduces_model_exactly(dsl: str, params: dict[str, float]) -> None:
    """Circuits made only of R, C and L must map onto SPICE with no approximation at all."""
    circuit = Circuit.parse(dsl)
    netlist = to_netlist(circuit, params, f_min=1e-1, f_max=1e9)
    omega = 2 * np.pi * np.logspace(-1, 9, 60)
    expected = circuit.impedance(omega, circuit.values_array(params))
    np.testing.assert_allclose(netlist_impedance(netlist, omega), expected, rtol=1e-9)


@pytest.mark.parametrize(
    ("dsl", "params", "f_min", "f_max"),
    [
        (
            "C1-R1-L1-SKINF1",
            {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
            1e2,
            1e9,
        ),
        (
            "R1-p(C1,R2-W1)",
            {"R1.R": 20.0, "C1.C": 1e-5, "R2.R": 100.0, "W1.A": 150.0},
            1e-2,
            1e5,
        ),
        (
            "R1-p(CPE1,R2)",
            {"R1.R": 50.0, "CPE1.Q": 3e-9, "CPE1.n": 0.8, "R2.R": 8e4},
            1e-1,
            1e7,
        ),
        (
            "R1-p(R2,Ws1)",
            {"R1.R": 5.0, "R2.R": 200.0, "Ws1.R": 80.0, "Ws1.tau": 1e-3},
            1e-2,
            1e5,
        ),
    ],
)
def test_fractional_netlist_matches_model_within_ladder_error(
    dsl: str, params: dict[str, float], f_min: float, f_max: float
) -> None:
    """With fractional elements the netlist must match to the synthesis tolerance."""
    circuit = Circuit.parse(dsl)
    netlist = to_netlist(circuit, params, f_min=f_min, f_max=f_max, error_target=0.01)
    omega = 2 * np.pi * np.logspace(np.log10(f_min), np.log10(f_max), 120)
    expected = circuit.impedance(omega, circuit.values_array(params))
    actual = netlist_impedance(netlist, omega)
    error = np.max(np.abs(actual - expected) / np.abs(expected))
    assert error < 0.02, f"{dsl}: netlist deviates by {error:.3%}"


def test_netlist_records_band_and_parameters() -> None:
    circuit = Circuit.parse("C1-R1-SKINF1")
    params = {"C1.C": 1e-6, "R1.R": 1e-2, "SKINF1.A": 2e-5, "SKINF1.n": 0.5}
    netlist = to_netlist(circuit, params, f_min=1e2, f_max=1e9, name="CAP")

    assert ".subckt CAP 1 2" in netlist
    assert ".ends CAP" in netlist
    assert "Valid over 100 Hz .. 1e+09 Hz" in netlist
    for name in circuit.param_names:
        assert name in netlist
    # The skin-effect element must be documented as a synthesised ladder, not silently dropped.
    assert "RL ladder" in netlist


def test_netlist_accepts_array_values() -> None:
    circuit = Circuit.parse("R1-C1")
    values = circuit.values_array({"R1.R": 10.0, "C1.C": 1e-6})
    netlist = to_netlist(circuit, values, f_min=1.0, f_max=1e5)
    omega = 2 * np.pi * np.logspace(0, 5, 20)
    np.testing.assert_allclose(
        netlist_impedance(netlist, omega), circuit.impedance(omega, values), rtol=1e-9
    )
