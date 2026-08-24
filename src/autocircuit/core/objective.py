"""What the user came here for -- applied to a report that has already been computed.

There are two reasons to bring an impedance spectrum to this project, and they want different
reports out of the *same* analysis (``CLAUDE.md``, "Objectives"):

* **model** -- an equivalent circuit to simulate with. The deliverable is the SPICE subcircuit
  plus the band it is valid over, and the readouts are the terminal ones: ESR over the band,
  ESL, the self-resonant frequency, Q, minimum ``|Z|``, tan delta, DC resistance. Its claim is
  complete and checkable from the data alone -- *this reproduces the measured Z over this band*.
* **interpret** -- what the spectrum says is happening inside the part. The deliverable is the
  processes the data can distinguish, and its claim is always conditional.

**The objective never reaches a number.** :func:`~autocircuit.core.discover.discover` and
:func:`~autocircuit.core.fit.fit` do not take it and this module is not imported by either, so
the rule is enforced by construction rather than by convention: everything here consumes a
*finished* result. Two people with the same spectrum get the same circuit and the same values
whatever they came for; the moment an objective narrows the pool, reorders the Pareto front or
changes what is recommended, the analyst-independence this project exists for is gone. Gate O1
is that statement measured -- the full pipeline under both objectives produces a byte-identical
wire payload, and only the rendered report differs (``benchmarks/o1_objective.py``).

What the objective legitimately changes is **how loudly the report says the data cannot
decide**. ``R1-p(R2,C1)`` and ``p(R1,C1-R2)`` fit the same data to 1.2e-15. Under ``model``
that is harmless: same terminal behaviour over the measured band, either one exports and
simulates identically, and asking which is "right" has no content. Under ``interpret`` it *is*
the question, because whether a resistance is a grain boundary or an electrode interface is
exactly that difference in form -- so that report leads with the equivalence class and this one
mentions it as a non-problem with the one caveat that survives (outside the band the members
are free to differ, which is why the band is part of the deliverable).

``model`` is the default for one reason: its claim is the one the data can check by itself.
"""

from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from .interpret import (
    ClassInterpretation,
    Quantity,
    interpret_class,
    interpret_values,
)
from .spectrum import Spectrum
from .stats import unresolved_mask

if TYPE_CHECKING:  # importing either at run time would pull scipy into the data path
    from .discover import Candidate, DiscoveryResult
    from .fit import FitResult

#: What the user wants out. Orthogonal to the *mode*, which is how much of the topology they fix.
Objective = Literal["model", "interpret"]

OBJECTIVES: tuple[Objective, ...] = ("model", "interpret")

#: The objective whose claim the data can check without any further assumption.
DEFAULT_OBJECTIVE: Objective = "model"

OBJECTIVE_LABELS: dict[Objective, str] = {
    "model": "a circuit to simulate with",
    "interpret": "what the spectrum says is inside the part",
}

OBJECTIVE_NOTES: dict[Objective, str] = {
    "model": (
        "The deliverable is the SPICE subcircuit and the band it is valid over, with the"
        " terminal readouts beside it: ESR over the band, ESL, the self-resonant frequency, Q,"
        " minimum |Z|, tan delta and the DC resistance. Every one of those is a property of Z,"
        " so the topologies this search could not tell apart all give the same numbers and the"
        " choice between them does not matter here."
    ),
    "interpret": (
        "The deliverable is the processes the spectrum can distinguish -- how many relaxations,"
        " each one's time constant and relaxation frequency, each block's share of the"
        " polarisation, how distributed each process is. Those depend on which member of the"
        " equivalence class was reported, so this report leads with the class and states what"
        " the data cannot decide."
    ),
}

#: Quantities of :mod:`~autocircuit.core.interpret` the model report shows, in reading order.
#: All of them are marked invariant there, which is what lets this report say the equivalence
#: class does not matter for this purpose.
MODEL_READOUTS: tuple[str, ...] = (
    "r_dc",
    "z_min",
    "self_resonant_frequency",
    "esr_at_resonance",
    "inductance_at_f_max",
    "capacitance_at_f_min",
    "tan_delta",
    "q_factor",
)

#: How many frequencies the ESR curve is sampled at, endpoints included.
ESR_SAMPLES = 6

#: Width the free-text notes are wrapped to, matching the rest of the command-line report.
NOTE_WIDTH = 88


def _wrap(note: str) -> list[str]:
    """One note as printable lines. A paragraph that runs off the terminal is not read."""
    return textwrap.wrap(note, NOTE_WIDTH) or [note]


def _esr_curve(candidate_circuit: Any, values: Any, spectrum: Spectrum) -> tuple[
    tuple[float, float], ...
]:
    """``Re Z`` of the fitted model at a few frequencies across the measured band.

    Sampled from the *model* rather than from the data on purpose: the model is what the user
    is taking away, and reading the data back would say nothing about the deliverable. The
    frequencies are inside the measured band at both ends, so nothing here is extrapolation.
    """
    f = np.geomspace(float(spectrum.f[0]), float(spectrum.f[-1]), ESR_SAMPLES)
    z = candidate_circuit.impedance(2 * np.pi * f, np.asarray(values, dtype=np.float64))
    return tuple(
        (float(freq), float(value.real))
        for freq, value in zip(f, np.asarray(z, dtype=np.complex128), strict=True)
    )


@dataclass(frozen=True)
class ModelReport:
    """The ``model`` objective's answer: a circuit, the band it is good over, and by how much."""

    circuit: str
    f_min: float
    f_max: float
    relative_error: float
    """RMS ``|dZ|/|Z|`` over the band -- the fit's own weighting-independent error."""
    worst_relative_error: float
    """The single worst point, because an RMS hides a band edge that has come apart."""
    chi2_reduced: float
    readouts: tuple[Quantity, ...]
    esr_curve: tuple[tuple[float, float], ...]
    equivalents: tuple[str, ...]
    """Other topologies in the same report with the same response over this band."""
    n_unresolved: int
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "circuit": self.circuit,
            "band": {"f_min": self.f_min, "f_max": self.f_max},
            "relative_error": self.relative_error,
            "worst_relative_error": self.worst_relative_error,
            "chi2_reduced": self.chi2_reduced,
            "readouts": [q.to_dict() for q in self.readouts],
            "esr_curve": [{"f_hz": f, "esr_ohm": r} for f, r in self.esr_curve],
            "equivalents": list(self.equivalents),
            "n_unresolved": self.n_unresolved,
            "notes": list(self.notes),
        }

    def summary(self) -> str:
        lines = [
            f"Circuit        : {self.circuit}",
            f"Valid over     : {self.f_min:.6g} Hz .. {self.f_max:.6g} Hz, the measured band"
            " -- outside it this",
            "                 model is extrapolation and nothing here has tested it.",
            f"Agreement      : RMS |dZ|/|Z| {self.relative_error:.4%}, worst point "
            f"{self.worst_relative_error:.4%}, chi2_red {self.chi2_reduced:.4g}",
            "",
            "Terminal readouts (properties of Z, so every equivalent topology agrees):",
        ]
        if self.readouts:
            for q in self.readouts:
                pm = "" if q.stderr is None else f" +/- {q.stderr:.3g}"
                unit = "" if q.unit == "-" else f" {q.unit}"
                note = "" if q.note is None else f"   [{q.note}]"
                lines.append(f"  {q.name} = {q.value:.6g}{pm}{unit}{note}")
        else:
            lines.append("  (none the measured band determines)")
        if self.esr_curve:
            lines += ["", "ESR = Re Z of this model across the band:"]
            lines.extend(f"  {f:>12.6g} Hz{r:>14.6g} ohm" for f, r in self.esr_curve)
        for note in self.notes:
            lines += ["", *_wrap(note)]
        return "\n".join(lines)


@dataclass(frozen=True)
class ObjectiveReport:
    """One analysis rendered for one objective. Holds no number the analysis did not."""

    objective: Objective
    model: ModelReport | None = None
    reading: ClassInterpretation | None = None
    notes: tuple[str, ...] = ()
    unavailable: str | None = None
    """Why there is nothing to report, when there is not."""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "objective": self.objective,
            "label": OBJECTIVE_LABELS[self.objective],
            "notes": list(self.notes),
        }
        if self.unavailable is not None:
            payload["unavailable"] = self.unavailable
        if self.model is not None:
            payload["model"] = self.model.to_dict()
        if self.reading is not None:
            payload["interpretation"] = self.reading.to_dict()
        return payload

    def summary(self) -> str:
        head = f"What you came for: {OBJECTIVE_LABELS[self.objective]} (--objective "
        head += f"{self.objective})"
        lines = [head, "=" * len(head), ""]
        if self.unavailable is not None:
            lines.append(self.unavailable)
            return "\n".join(lines)
        if self.model is not None:
            lines.append(self.model.summary())
        if self.reading is not None:
            lines.append(self.reading.summary())
        for note in self.notes:
            lines += ["", *_wrap(note)]
        return "\n".join(lines)


def _worst_relative_error(result: FitResult, spectrum: Spectrum) -> float:
    """The largest per-point ``|dZ|/|Z|``; NaN when the model is not on this spectrum's grid."""
    z_model = np.asarray(result.z_model, dtype=np.complex128)
    z_data = np.asarray(spectrum.z, dtype=np.complex128)
    if z_model.shape != z_data.shape:
        return math.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        deviation = np.abs(z_model - z_data) / np.abs(z_data)
    finite = deviation[np.isfinite(deviation)]
    return float(np.max(finite)) if finite.size else math.nan


def _model_report(
    result: FitResult,
    spectrum: Spectrum,
    *,
    equivalents: tuple[str, ...],
    n_unresolved: int,
    notes: tuple[str, ...],
) -> ModelReport:
    reading = interpret_values(
        result.circuit,
        result.values,
        spectrum,
        stderr=result.statistics.stderr,
        correlation=result.statistics.correlation,
    )
    by_name = {q.name: q for q in reading.quantities}
    readouts = tuple(by_name[name] for name in MODEL_READOUTS if name in by_name)
    return ModelReport(
        circuit=result.circuit.to_string(),
        f_min=float(spectrum.f[0]),
        f_max=float(spectrum.f[-1]),
        relative_error=float(result.relative_error),
        worst_relative_error=_worst_relative_error(result, spectrum),
        chi2_reduced=float(result.chi2_reduced),
        readouts=readouts,
        esr_curve=_esr_curve(result.circuit, result.values, spectrum),
        equivalents=equivalents,
        n_unresolved=n_unresolved,
        notes=notes,
    )


def _equivalence_note(equivalents: tuple[str, ...]) -> str:
    """What the equivalence class means for somebody who wants a circuit to simulate with."""
    if not equivalents:
        return (
            "No other topology in this report reproduces this response, so there is no"
            " ambiguity of form to declare here."
        )
    names = ", ".join(equivalents)
    one = len(equivalents) == 1
    return (
        f"{len(equivalents)} other topolog{'y' if one else 'ies'} in this report"
        f" reproduce{'s' if one else ''} the same response over this band: {names}."
        " For this purpose the"
        " choice does not matter -- they have the same terminal Z here, so they export and"
        " simulate identically. Outside the measured band they are free to differ, which is"
        " why the band above is part of the deliverable and not a footnote to it."
    )


def _unresolved_note(n_unresolved: int) -> str:
    return (
        f"{n_unresolved} parameter(s) came back with a standard error larger than the value"
        " itself. For a simulation model that is not fatal -- the model still reproduces the"
        " measured Z -- but those values carry no information individually, so do not read"
        " them as measurements of anything, and expect them to move under a refit."
    )


def discovery_report(
    result: DiscoveryResult,
    spectrum: Spectrum,
    objective: Objective = DEFAULT_OBJECTIVE,
    *,
    candidate: Candidate | None = None,
    drt_peaks: int | None = None,
) -> ObjectiveReport:
    """Render a finished search for what the user came for. Changes no number in ``result``.

    ``candidate`` is which row to report, defaulting to the recommendation. The browser lets a
    reader ask about a row they selected, and that is a question about the *report* -- the
    equivalence class it is read against is still the search's own
    (:meth:`~autocircuit.core.discover.DiscoveryResult.equivalents_of`), never re-derived here.
    """
    if objective not in OBJECTIVES:
        raise ValueError(f"unknown objective {objective!r}; expected one of {OBJECTIVES}")
    chosen: Candidate | None = result.recommended if candidate is None else candidate
    if chosen is None:
        return ObjectiveReport(
            objective=objective,
            unavailable=(
                "No candidate was fitted, so there is nothing to report for any objective."
                " The coverage line above says whether that is for want of candidates or"
                " because nothing fitted."
            ),
        )
    family = [chosen, *result.equivalents_of(chosen)]
    equivalents = tuple(c.circuit.to_string() for c in family[1:])

    if objective == "model":
        notes = [_equivalence_note(equivalents)]
        if chosen.n_unresolved:
            notes.append(_unresolved_note(chosen.n_unresolved))
        return ObjectiveReport(
            objective=objective,
            model=_model_report(
                chosen.result,
                spectrum,
                equivalents=equivalents,
                n_unresolved=chosen.n_unresolved,
                notes=tuple(notes),
            ),
        )

    reading = interpret_class([c.result for c in family], spectrum, drt_peaks=drt_peaks)
    return ObjectiveReport(
        objective=objective,
        reading=reading,
        notes=(
            "Everything above is conditional on the reported form. The search found the"
            " topologies the data cannot tell apart and this report reads all of them, but"
            " naming which of them is the physics is knowledge about the sample -- it is not"
            " in the spectrum, and no longer search would put it there.",
        ),
    )


def fit_report(
    result: FitResult,
    spectrum: Spectrum,
    objective: Objective = DEFAULT_OBJECTIVE,
    *,
    drt_peaks: int | None = None,
) -> ObjectiveReport:
    """The same two reports for a circuit the user wrote down (mode 1).

    The difference from :func:`discovery_report` is not the objective -- that axis is
    orthogonal to the mode -- but that there is no equivalence class here: nothing was
    searched, so nothing else was found to compare the reported form against. Both reports say
    so rather than presenting a class of one as agreement.
    """
    if objective not in OBJECTIVES:
        raise ValueError(f"unknown objective {objective!r}; expected one of {OBJECTIVES}")
    asserted = (
        "This topology is the one you asserted; no other was fitted, so nothing here has been"
        " checked against a second form. Topologies that reproduce this same response exist"
        " -- discovery finds them and reads them all."
    )
    if objective == "model":
        unresolved = int(
            np.count_nonzero(unresolved_mask(result.values, result.statistics.stderr))
        )
        notes = [asserted]
        if unresolved:
            notes.append(_unresolved_note(unresolved))
        return ObjectiveReport(
            objective=objective,
            model=_model_report(
                result,
                spectrum,
                equivalents=(),
                n_unresolved=unresolved,
                notes=tuple(notes),
            ),
        )
    return ObjectiveReport(
        objective=objective,
        reading=interpret_class([result], spectrum, drt_peaks=drt_peaks),
        notes=(asserted,),
    )
