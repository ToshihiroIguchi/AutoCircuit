"""SPICE netlist export, including ladder synthesis for fractional-order elements.

R, C and L map straight onto SPICE primitives. Constant phase elements, Warburg and Gerischer
impedances and the skin-effect elements do not: SPICE has no ``(j*omega)^n`` device. The
established remedy is to approximate them with a passive ladder that matches the target
impedance over the frequency range of interest -- Valsa and Vlach, "RC models of a constant
phase element" (Int. J. Circuit Theory Appl. 41, 59, 2013) for capacitive fractional elements,
and Kim and Neikirk's RL ladder (IEEE MTT-S 1996) for the skin effect.

Rather than transcribing one closed-form recipe per element, this module solves the general
problem once. Both ladder families are *linear in their resistances* once the time constants
are fixed on a logarithmic grid:

* RC (capacitive) Foster form: ``Z = R0 + 1/(j w C0) + sum_k R_k / (1 + j w tau_k)``
* RL (inductive) Foster form:  ``Z = R0 + j w L0 + sum_k R_k * (j w tau_k)/(1 + j w tau_k)``

so the section values follow from a *non-negative* least squares solve against the exact
element impedance. Non-negativity is not a detail: it is what guarantees the synthesised
network is passive and therefore actually simulable. Any element added to AutoCircuit later
gets SPICE export for free by declaring which of the two forms it belongs to.

The result is only valid over the band it was fitted on. Every generated subcircuit carries
that band and the achieved accuracy in its comments.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import nnls

from . import elements
from .circuit import Circuit, ElementNode, Node, Parallel, Series

Float = NDArray[np.float64]
Complex = NDArray[np.complex128]

Dialect = Literal["ngspice", "ltspice"]

#: Decades of margin added on each side of the measured band when synthesising a ladder.
BAND_MARGIN_DECADES = 0.5
#: Section counts tried, in order, until the accuracy target is met.
SECTION_LADDER = (3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40)
#: Frequency points used to evaluate the synthesis error.
SYNTHESIS_POINTS = 400


@dataclass(frozen=True)
class Ladder:
    """A synthesised passive ladder approximating one fractional element."""

    form: Literal["rc", "rl"]
    r_series: float
    """Series resistance R0."""
    reactive_series: float
    """C0 (farads) for the RC form, L0 (henries) for the RL form; 0 when unused."""
    sections: tuple[tuple[float, float], ...]
    """``(R_k, C_k)`` for the RC form or ``(R_k, L_k)`` for the RL form."""
    f_min: float
    f_max: float
    max_relative_error: float

    @property
    def n_sections(self) -> int:
        return len(self.sections)

    def impedance(self, omega: Float) -> Complex:
        """Evaluate the synthesised ladder, for verifying it against the exact element."""
        z = np.full(omega.shape, complex(self.r_series))
        if self.reactive_series > 0.0:
            if self.form == "rc":
                z = z + 1.0 / (1j * omega * self.reactive_series)
            else:
                z = z + 1j * omega * self.reactive_series
        for r, x in self.sections:
            if self.form == "rc":
                z = z + r / (1.0 + 1j * omega * r * x)
            else:
                tau = x / r
                z = z + r * (1j * omega * tau) / (1.0 + 1j * omega * tau)
        return z


def _design_columns(
    omega: Float, tau: Float, form: Literal["rc", "rl"]
) -> tuple[Complex, int]:
    """Basis functions of the Foster form; returns the matrix and the reactive column index."""
    columns: list[Complex] = [np.ones_like(omega, dtype=np.complex128)]
    if form == "rc":
        columns.append(np.asarray(1.0 / (1j * omega), dtype=np.complex128))  # coefficient is 1/C0
    else:
        columns.append(
            np.asarray(1j * omega + 0.0 * omega, dtype=np.complex128)
        )  # coefficient is L0
    for t in tau:
        if form == "rc":
            columns.append(1.0 / (1.0 + 1j * omega * t))  # coefficient is R_k
        else:
            columns.append((1j * omega * t) / (1.0 + 1j * omega * t))  # coefficient is R_k
    return np.stack(columns, axis=1), 1


def synthesize_ladder(
    impedance: Callable[[Float], Complex],
    f_min: float,
    f_max: float,
    form: Literal["rc", "rl"],
    *,
    error_target: float = 0.01,
    max_sections: int = 40,
) -> Ladder:
    """Fit a passive ladder to an arbitrary impedance function over a frequency band.

    Args:
        impedance: Callable mapping angular frequency to complex impedance.
        f_min, f_max: Band over which the approximation must hold, in Hz.
        form: ``'rc'`` for capacitive elements, ``'rl'`` for inductive / skin-effect ones.
        error_target: Maximum relative |Z| error accepted; the section count is raised until
            this is met or ``max_sections`` is reached.
        max_sections: Upper limit on ladder sections.

    Returns:
        The smallest :class:`Ladder` meeting the target, or the most accurate one found.
    """
    if not 0 < f_min < f_max:
        raise ValueError("require 0 < f_min < f_max")

    margin = 10.0**BAND_MARGIN_DECADES
    omega = 2.0 * np.pi * np.logspace(
        math.log10(f_min), math.log10(f_max), SYNTHESIS_POINTS
    )
    target = impedance(omega)
    weight = 1.0 / np.abs(target)

    # The time constants straddle the band, extended slightly so the ladder does not run out
    # of sections exactly where the data starts.
    tau_lo = 1.0 / (2.0 * np.pi * f_max * margin)
    tau_hi = margin / (2.0 * np.pi * f_min)

    best: Ladder | None = None
    for k in SECTION_LADDER:
        if k > max_sections:
            break
        tau = np.logspace(math.log10(tau_lo), math.log10(tau_hi), k)
        design, _ = _design_columns(omega, tau, form)

        a = np.vstack([design.real * weight[:, None], design.imag * weight[:, None]])
        b = np.concatenate([target.real * weight, target.imag * weight])
        # Column scaling keeps the solve conditioned; NNLS is unaffected by positive scaling.
        norms = np.linalg.norm(a, axis=0)
        norms[norms == 0.0] = 1.0
        scaled, _ = nnls(a / norms, b, maxiter=10 * a.shape[1])
        coefficients = scaled / norms

        ladder = _to_ladder(coefficients, tau, form, f_min, f_max)
        error = float(np.max(np.abs(ladder.impedance(omega) - target) / np.abs(target)))
        ladder = Ladder(
            form=ladder.form,
            r_series=ladder.r_series,
            reactive_series=ladder.reactive_series,
            sections=ladder.sections,
            f_min=f_min,
            f_max=f_max,
            max_relative_error=error,
        )
        if best is None or error < best.max_relative_error:
            best = ladder
        if error <= error_target:
            return ladder

    assert best is not None
    return best


def _to_ladder(
    coefficients: Float, tau: Float, form: Literal["rc", "rl"], f_min: float, f_max: float
) -> Ladder:
    r_series = float(coefficients[0])
    reactive_coefficient = float(coefficients[1])
    if form == "rc":
        # The column carries 1/C0, so a zero coefficient means "no series capacitor".
        reactive = 1.0 / reactive_coefficient if reactive_coefficient > 0.0 else 0.0
    else:
        reactive = reactive_coefficient

    sections: list[tuple[float, float]] = []
    for r, t in zip(coefficients[2:], tau, strict=True):
        if r <= 0.0:
            continue  # NNLS zeroed this section out; leave it out of the netlist entirely
        sections.append((float(r), float(t / r) if form == "rc" else float(r * t)))
    return Ladder(form, r_series, reactive, tuple(sections), f_min, f_max, math.inf)


def _fmt(value: float) -> str:
    """SPICE-friendly number formatting; plain scientific notation is portable everywhere."""
    return f"{value:.9g}"


class _NetlistBuilder:
    """Walks the circuit tree, allocating nodes and emitting device lines."""

    def __init__(self, circuit: Circuit, values: Float, f_min: float, f_max: float,
                 error_target: float, max_sections: int) -> None:
        self.circuit = circuit
        self.values = values
        self.f_min = f_min
        self.f_max = f_max
        self.error_target = error_target
        self.max_sections = max_sections
        self.lines: list[str] = []
        self.notes: list[str] = []
        self._node = 0
        self._cursor = 0

    def new_node(self) -> str:
        self._node += 1
        return f"n{self._node}"

    def take(self, count: int) -> Float:
        chunk = self.values[self._cursor : self._cursor + count]
        self._cursor += count
        return chunk

    def emit(self, node: Node, a: str, b: str) -> None:
        if isinstance(node, ElementNode):
            self.emit_element(node, a, b)
        elif isinstance(node, Series):
            previous = a
            for index, child in enumerate(node.children):
                terminal = b if index == len(node.children) - 1 else self.new_node()
                self.emit(child, previous, terminal)
                previous = terminal
        elif isinstance(node, Parallel):
            for child in node.children:
                self.emit(child, a, b)
        else:  # pragma: no cover - exhaustive over the Node union
            raise TypeError(f"unexpected node type {type(node)!r}")

    def emit_element(self, node: ElementNode, a: str, b: str) -> None:
        element = elements.get(node.code)
        values = self.take(element.n_params)
        label = node.label

        if element.spice_form == "primitive":
            prefix = {"R": "R", "C": "C", "L": "L"}[element.code]
            self.lines.append(f"{prefix}_{label} {a} {b} {_fmt(values[0])}")
            return

        form: Literal["rc", "rl"] = "rc" if element.spice_form == "rc" else "rl"

        def _impedance(
            w: Float, e: elements.Element = element, v: Float = values
        ) -> Complex:
            return e.impedance(w, v)

        ladder = synthesize_ladder(
            _impedance,
            self.f_min,
            self.f_max,
            form,
            error_target=self.error_target,
            max_sections=self.max_sections,
        )
        self._emit_ladder(ladder, label, element, a, b)

    def _emit_ladder(
        self, ladder: Ladder, label: str, element: elements.Element, a: str, b: str
    ) -> None:
        self.lines.append(
            f"* {label} ({element.name}) -> {ladder.form.upper()} ladder, "
            f"{ladder.n_sections} sections, max error {ladder.max_relative_error:.3%} "
            f"over {_fmt(ladder.f_min)} Hz .. {_fmt(ladder.f_max)} Hz"
        )
        if ladder.max_relative_error > self.error_target:
            self.notes.append(
                f"{label}: ladder synthesis reached {ladder.max_relative_error:.2%} error, "
                f"above the {self.error_target:.2%} target even at {ladder.n_sections} "
                "sections"
            )

        previous = a
        if ladder.r_series > 0.0:
            terminal = self.new_node()
            self.lines.append(f"R_{label}_s {previous} {terminal} {_fmt(ladder.r_series)}")
            previous = terminal
        if ladder.reactive_series > 0.0:
            terminal = self.new_node()
            prefix, value = (
                ("C", ladder.reactive_series) if ladder.form == "rc"
                else ("L", ladder.reactive_series)
            )
            self.lines.append(f"{prefix}_{label}_s {previous} {terminal} {_fmt(value)}")
            previous = terminal

        for index, (r, x) in enumerate(ladder.sections, start=1):
            terminal = b if index == len(ladder.sections) else self.new_node()
            if ladder.form == "rc":
                # Parallel R||C section: the pair shares both nodes.
                self.lines.append(f"R_{label}_{index} {previous} {terminal} {_fmt(r)}")
                self.lines.append(f"C_{label}_{index} {previous} {terminal} {_fmt(x)}")
            else:
                # Parallel R||L section.
                self.lines.append(f"R_{label}_{index} {previous} {terminal} {_fmt(r)}")
                self.lines.append(f"L_{label}_{index} {previous} {terminal} {_fmt(x)}")
            previous = terminal

        if not ladder.sections:
            # Degenerate case: the whole element collapsed onto the series terms.
            self.lines.append(f"R_{label}_0 {previous} {b} 1e-12")
        elif previous != b:  # pragma: no cover - defensive
            self.lines.append(f"R_{label}_link {previous} {b} 1e-12")


def _how_to_drive(name: str, f_min: float, f_max: float) -> list[str]:
    """The deck that turns this subcircuit back into an impedance, and the one snag in it.

    [measured, ngspice 42] Every model that begins with a capacitor is an open circuit at DC, so
    the operating point comes out singular and gmin and source stepping both fail -- while ngspice
    still exits 0 and still computes the right AC answer, because an AC analysis of a linear
    network does not depend on the operating point. Saying so here is cheaper than letting each
    user discover it; ``tests/test_spice_ngspice.py`` is where it is pinned.
    """
    return [
        "*",
        "* To recover Z(f) from this subcircuit, drive its port with a 1 A AC current source",
        "* and read the port voltage:",
        "*",
        f"*   X1 probe 0 {name}",
        "*   I1 0 probe DC 0 AC 1",
        f"*   .ac dec 20 {_fmt(f_min)} {_fmt(f_max)}",
        "*",
        "* Z(f) is then V(probe). A network beginning with a capacitor is a DC open, so ngspice",
        "* may report a singular matrix at the operating point; the AC result is unaffected, and",
        "* `.option rshunt=1e12` silences it at a cost of up to ~1e-6 in |Z|.",
        "*",
    ]


def to_netlist(
    circuit: Circuit,
    values: Float | dict[str, float],
    *,
    f_min: float,
    f_max: float,
    name: str = "AUTOCIRCUIT",
    dialect: Dialect = "ngspice",
    error_target: float = 0.01,
    max_sections: int = 40,
    header: str | None = None,
) -> str:
    """Render a fitted circuit as a SPICE ``.subckt`` with two terminals.

    Args:
        circuit: The circuit topology.
        values: Fitted parameters, as an array or a name mapping.
        f_min, f_max: Band over which fractional elements must be accurate -- normally the
            measured frequency range. The synthesised ladders are only valid here.
        name: Subcircuit name.
        dialect: ``ngspice`` or ``ltspice``; affects only comment syntax details.
        error_target: Accuracy target for ladder synthesis.
        max_sections: Cap on ladder sections per fractional element.
        header: Extra comment lines placed at the top of the file.

    Returns:
        The netlist text.
    """
    array = (
        circuit.values_array(values) if isinstance(values, dict)
        else np.asarray(values, dtype=np.float64)
    )
    builder = _NetlistBuilder(circuit, array, f_min, f_max, error_target, max_sections)
    builder.emit(circuit.root, "1", "2")

    out: list[str] = [
        f"* {name} - generated by AutoCircuit",
        f"* Circuit: {circuit.to_string()}",
        f"* Valid over {_fmt(f_min)} Hz .. {_fmt(f_max)} Hz",
        "* Fractional-order elements (CPE, Warburg, Gerischer, skin effect) have no SPICE",
        "* primitive and are realised as passive ladders fitted over the band above.",
        "* Outside that band the ladders do not represent the fitted element.",
    ]
    if header:
        out.extend(f"* {line}" for line in header.splitlines())
    for note in builder.notes:
        out.append(f"* WARNING: {note}")
    out.append("*")
    out.append(f"* Fitted parameters ({dialect} dialect):")
    for param_name, value, spec in zip(
        circuit.param_names, array, circuit.param_specs(), strict=True
    ):
        out.append(f"*   {param_name} = {_fmt(float(value))} {spec.unit}")
    out.extend(_how_to_drive(name, f_min, f_max))
    out.append(f".subckt {name} 1 2")
    out.extend(builder.lines)
    out.append(f".ends {name}")
    out.append("")
    return "\n".join(out)
