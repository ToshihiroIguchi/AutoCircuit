"""Tests for the reporting layer that knows what the user came for (``core/objective.py``).

Covers, in order:

1. **Gate O1's structural half**, which is the one that actually holds the property: neither
   ``discover()`` nor ``fit()`` takes an objective, and neither module imports the objective
   module. A byte comparison that passed while the parameter existed would say only that two
   runs happened to agree on the spectra it was given.
2. **Gate O1's measured half**, in miniature: the same search rendered under both objectives
   produces the same wire payload and a different report. ``benchmarks/o1_objective.py`` is the
   full version, over the three reference spectra and the whole command line.
3. What each report is allowed to say. The ``model`` report's readouts must every one be marked
   invariant in :mod:`~autocircuit.core.interpret`, because that is what licenses its sentence
   that the equivalence class does not matter for this purpose -- the one place this module
   could quietly over-claim.
4. The readouts themselves: an ESL that appears for a part that turns inductive and stays
   absent for one that does not.
"""

from __future__ import annotations

import ast
import inspect
import json
import math
from pathlib import Path

import numpy as np
import pytest

from autocircuit.core import discover as discover_module
from autocircuit.core import fit as fit_module
from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import discover
from autocircuit.core.fit import fit
from autocircuit.core.objective import (
    MODEL_READOUTS,
    OBJECTIVES,
    discovery_report,
    fit_report,
)
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum


def _spectrum(circuit: str, params: dict[str, float], f_min: float, f_max: float) -> Spectrum:
    return simulate(circuit, log_frequencies(f_min, f_max, 8), params, noise=0.0, seed=0)


# -- 1. Gate O1, structural -------------------------------------------------------------------


@pytest.mark.parametrize("function", [discover, fit])
def test_the_search_cannot_see_the_objective(function: object) -> None:
    """The invariant by construction: a value the search cannot receive cannot change it."""
    assert "objective" not in inspect.signature(function).parameters  # type: ignore[arg-type]


@pytest.mark.parametrize("module", [discover_module, fit_module])
def test_neither_search_module_imports_the_reporting_layer(module: object) -> None:
    source = Path(inspect.getsourcefile(module) or "").read_text(encoding="utf-8")  # type: ignore[arg-type]
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module or ''}.{alias.name}" for alias in node.names)
    assert not [name for name in imported if name.endswith("objective")]


# -- 2. Gate O1, measured ---------------------------------------------------------------------


def test_both_objectives_read_the_same_search_and_change_nothing_in_it() -> None:
    """One search, two reports: the payload is identical and the rendered text is not."""
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1.0, 1e6, 8),
        {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-6},
        noise=0.01,
        seed=0,
    )
    result = discover(
        data, pool=("R", "C"), mode="exhaustive", exhaustive_limit=3, seed=0, workers=1
    )
    before = json.dumps(result.to_dict(), sort_keys=True)
    reports = {
        objective: discovery_report(result, data, objective)  # type: ignore[arg-type]
        for objective in OBJECTIVES
    }
    after = json.dumps(result.to_dict(), sort_keys=True)

    assert before == after, "rendering a report mutated the result it was rendered from"
    assert reports["model"].summary() != reports["interpret"].summary()
    assert reports["model"].model is not None
    assert reports["interpret"].reading is not None


def test_an_unknown_objective_is_an_error_rather_than_a_default() -> None:
    data = _spectrum("R1-C1", {"R1.R": 100.0, "C1.C": 1e-7}, 10.0, 1e5)
    result = fit(Circuit.parse("R1-C1"), data, restarts=1, popsize=8, maxiter=40, seed=0)
    with pytest.raises(ValueError, match="unknown objective"):
        fit_report(result, data, "structure")  # type: ignore[arg-type]


# -- 3. What the model report is allowed to claim ---------------------------------------------


def test_every_model_readout_is_an_invariant_quantity() -> None:
    """The licence for "every equivalent topology agrees" -- checked, not asserted.

    If a form-dependent quantity ever reaches :data:`MODEL_READOUTS`, the model report starts
    printing a property of the reported tree under a heading promising a property of Z.
    """
    circuit = "C1-R1-L1"
    params = {"C1.C": 1e-6, "R1.R": 0.05, "L1.L": 5e-9}
    data = _spectrum(circuit, params, 1e2, 1e8)
    result = fit(
        Circuit.parse(circuit), data, restarts=2, popsize=12, maxiter=120, seed=0
    )
    report = fit_report(result, data, "model")
    assert report.model is not None
    assert report.model.readouts, "no readouts at all makes the check vacuous"
    for quantity in report.model.readouts:
        assert quantity.invariant, quantity.name
    assert {q.name for q in report.model.readouts} <= set(MODEL_READOUTS)


def test_a_manual_fit_says_it_has_no_second_form_to_check_against() -> None:
    """Mode 1 has no equivalence class, and a class of one must not read as agreement."""
    data = _spectrum("R1-C1", {"R1.R": 100.0, "C1.C": 1e-7}, 10.0, 1e5)
    result = fit(Circuit.parse("R1-C1"), data, restarts=1, popsize=8, maxiter=40, seed=0)
    for objective in OBJECTIVES:
        text = fit_report(result, data, objective).summary()  # type: ignore[arg-type]
        assert "no other was fitted" in text


def test_the_model_report_is_json_safe() -> None:
    data = _spectrum("R1-C1", {"R1.R": 100.0, "C1.C": 1e-7}, 10.0, 1e5)
    result = fit(Circuit.parse("R1-C1"), data, restarts=1, popsize=8, maxiter=40, seed=0)
    payload = fit_report(result, data, "model").to_dict()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["objective"] == "model"
    assert round_tripped["model"]["band"]["f_min"] == pytest.approx(10.0)


# -- 4. The readouts --------------------------------------------------------------------------


def test_esl_is_reported_where_the_part_turns_inductive_and_not_where_it_does_not() -> None:
    """A capacitor above its resonance has an ESL; an RC cell has none to report.

    The value is the *apparent* series inductance at the top of the band, ``Im Z / omega``,
    which for a series R-L-C is ``L - 1 / (omega^2 C)``: it approaches L only well above
    resonance, and the note beside the number says at which frequency it was read.
    """
    inductance = 5e-9
    capacitance = 1e-6
    f_max = 1e8
    data = _spectrum(
        "C1-R1-L1", {"C1.C": capacitance, "R1.R": 0.05, "L1.L": inductance}, 1e2, f_max
    )
    result = fit(
        Circuit.parse("C1-R1-L1"), data, restarts=2, popsize=12, maxiter=120, seed=0
    )
    report = fit_report(result, data, "model")
    assert report.model is not None
    esl = {q.name: q for q in report.model.readouts}.get("inductance_at_f_max")
    assert esl is not None, "a capacitor above resonance must report an ESL"
    omega = 2 * math.pi * f_max
    assert esl.value == pytest.approx(
        inductance - 1.0 / (omega**2 * capacitance), rel=1e-3
    )

    cell = _spectrum("R1-p(R2,C1)", {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-6}, 1.0, 1e6)
    rc = fit(Circuit.parse("R1-p(R2,C1)"), cell, restarts=2, popsize=12, maxiter=120, seed=0)
    rc_report = fit_report(rc, cell, "model")
    assert rc_report.model is not None
    assert "inductance_at_f_max" not in {q.name for q in rc_report.model.readouts}


def test_the_esr_curve_stays_inside_the_measured_band() -> None:
    """Nothing in the model report is extrapolation; the band is the claim."""
    data = _spectrum("R1-p(R2,C1)", {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-6}, 1.0, 1e6)
    result = fit(
        Circuit.parse("R1-p(R2,C1)"), data, restarts=2, popsize=12, maxiter=120, seed=0
    )
    report = fit_report(result, data, "model")
    assert report.model is not None
    frequencies = [f for f, _ in report.model.esr_curve]
    assert frequencies[0] == pytest.approx(float(data.f[0]))
    assert frequencies[-1] == pytest.approx(float(data.f[-1]))
    assert all(np.isfinite(esr) and esr > 0 for _, esr in report.model.esr_curve)
