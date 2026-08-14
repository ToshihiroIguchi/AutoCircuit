"""JSON wire-transport tests: the worker-boundary contract must be bit-identical, not close.

A `FitResult` computed in a Web Worker has to reach the orchestrator exactly as it left the
worker, because the numbers on the far side are what the report is built from -- a refit that
loses its covariance to the transport is a refit whose non-identifiability warning never
reaches the user (see the module docstring of `autocircuit.core.wire`). Every assertion below is
therefore exact equality (`==`, `repr`, or `np.array_equal(..., equal_nan=True)`), never
`np.allclose` and never a tolerance.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import Candidate, RefitTask, refit_plan
from autocircuit.core.fit import WIRE_VERSION, FitResult, fit
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.stats import Statistics
from autocircuit.core.wire import (
    NEGATIVE_INFINITY,
    NOT_A_NUMBER,
    POSITIVE_INFINITY,
    decode_array,
    decode_complex_array,
    decode_float,
    decode_mapping,
    encode_array,
    encode_complex_array,
    encode_float,
    encode_mapping,
)

# =============================================================================================
# 1. Scalar sentinels
# =============================================================================================


def test_scalar_round_trip_for_sentinels_and_ordinary_values() -> None:
    values = [
        math.inf,
        -math.inf,
        math.nan,
        0.0,
        -0.0,
        1e-300,
        1.7976931348623157e308,
        1.0,
        -1.0,
        3.14159,
        -2.5e-10,
        6.02214076e23,
    ]
    for value in values:
        encoded = encode_float(value)
        decoded = decode_float(encoded)
        if math.isnan(value):
            assert math.isnan(decoded)
        else:
            assert decoded == value
            # repr() distinguishes 0.0 from -0.0, which == does not.
            assert repr(decoded) == repr(value)


def test_sentinel_strings_are_exactly_what_the_module_documents() -> None:
    assert encode_float(math.inf) == POSITIVE_INFINITY == "inf"
    assert encode_float(-math.inf) == NEGATIVE_INFINITY == "-inf"
    assert encode_float(math.nan) == NOT_A_NUMBER == "nan"


def test_negative_zero_keeps_its_sign_bit() -> None:
    decoded = decode_float(encode_float(-0.0))
    assert np.signbit(decoded)
    assert math.copysign(1.0, decoded) == -1.0

    decoded_positive = decode_float(encode_float(0.0))
    assert not np.signbit(decoded_positive)


def test_decode_float_rejects_an_unknown_sentinel() -> None:
    with pytest.raises(ValueError, match="unknown float sentinel"):
        decode_float("bogus")


# =============================================================================================
# 2. Real arrays
# =============================================================================================


def test_all_finite_array_round_trips_and_takes_the_fast_path() -> None:
    array = np.array([1.0, -2.5, 0.0, -0.0, 1e-300, 1.7976931348623157e308])
    payload = json.loads(json.dumps(encode_array(array)))
    # The fast path in encode_array skips per-element sentinel encoding for an all-finite
    # array, so every entry on the wire is a plain JSON number, never a sentinel string.
    assert all(isinstance(v, float) for v in payload["data"])
    back = decode_array(payload)
    assert back.dtype == np.float64
    assert np.array_equal(back, array)
    assert np.signbit(back[3])  # -0.0 survived the fast path too


def test_array_mixing_non_finite_and_finite_values_round_trips() -> None:
    array = np.array([1.5, math.inf, -math.inf, math.nan, -0.0, -7.25, 0.0])
    payload = json.loads(json.dumps(encode_array(array)))
    back = decode_array(payload)
    assert back.dtype == np.float64
    assert np.array_equal(back, array, equal_nan=True)
    assert np.signbit(back[4])


def test_two_dimensional_array_preserves_its_shape() -> None:
    # Shaped like the correlation matrix a Statistics object carries.
    correlation = np.array([[1.0, 0.5, math.nan], [0.5, 1.0, -0.3], [math.nan, -0.3, 1.0]])
    payload = json.loads(json.dumps(encode_array(correlation)))
    assert payload["shape"] == [3, 3]
    back = decode_array(payload)
    assert back.shape == (3, 3)
    assert back.dtype == np.float64
    assert np.array_equal(back, correlation, equal_nan=True)


# =============================================================================================
# 3. Complex arrays
# =============================================================================================


def test_complex_array_round_trips_through_json() -> None:
    array = np.array([1.0 + 2.0j, -3.5 - 4.5j, 0.0 + 0.0j], dtype=np.complex128)
    payload = json.loads(json.dumps(encode_complex_array(array)))
    back = decode_complex_array(payload)
    assert back.dtype == np.complex128
    assert back.shape == array.shape
    assert np.array_equal(back, array)


def test_complex_array_with_only_the_imaginary_part_non_finite() -> None:
    # Built from explicit (real, imag) pairs rather than e.g. `3.0 + math.inf * 1j`: complex
    # multiplication by 1j computes the real part as `inf * 0 - 0 * 1`, which is nan, not 0 --
    # so that expression would poison the "real part" this test is specifically about.
    array = np.array(
        [
            complex(1.0, 2.0),
            complex(3.0, math.inf),
            complex(5.0, math.nan),
            complex(-6.0, -math.inf),
        ],
        dtype=np.complex128,
    )
    assert np.all(np.isfinite(array.real))
    payload = json.loads(json.dumps(encode_complex_array(array)))
    back = decode_complex_array(payload)
    assert back.dtype == np.complex128
    assert np.array_equal(back, array, equal_nan=True)


# =============================================================================================
# 4. Mappings
# =============================================================================================


def test_mapping_round_trip_with_an_infinite_value() -> None:
    values = {"R1.R": 25.0, "C1.C": math.inf, "L1.L": -3.5e-10, "W1.A": -math.inf}
    payload = json.loads(json.dumps(encode_mapping(values)))
    back = decode_mapping(payload)
    assert back == values
    for name in values:
        assert repr(back[name]) == repr(values[name])


# =============================================================================================
# 5. Random round trip across many decades
# =============================================================================================


def test_finite_float64_survives_json_decimal_representation_losslessly() -> None:
    """The claim the whole module rests on: JSON's shortest-round-trip decimal representation
    reproduces the exact double, across everything a fitted parameter set can contain -- unit
    scale and fifteen decades either side of it.
    """
    rng = np.random.default_rng(0)
    parts = [rng.standard_normal(100)]
    for k in range(-300, 301, 15):
        parts.append(rng.standard_normal(20) * (10.0**k))
    values = np.concatenate(parts)
    assert values.size >= 500
    assert np.all(np.isfinite(values)), "test construction overflowed to inf; narrow the range"

    payload = json.loads(json.dumps(encode_array(values)))
    back = decode_array(payload)
    assert back.dtype == np.float64
    assert np.array_equal(back, values)


# =============================================================================================
# 6. FitResult round trip on a corpus of circuits
# =============================================================================================

# Circuit strings, true parameters and frequency windows reused from tests/test_fit.py's
# SYNTHETIC_SUITE (series RC, capacitor with ESR/ESL, Randles cell, Maxwell-Wagner) plus the
# R1-p(R2,C1) truth used in tests/test_discover_skeleton.py -- rather than inventing a new
# corpus, this is the same set of five circuits named as the fallback in the task brief.
WIRE_CORPUS = [
    ("R1-C1", {"R1.R": 25.0, "C1.C": 4.7e-6}, 1e0, 1e6, 5),
    ("R1-p(R2,C1)", {"R1.R": 20.0, "R2.R": 1000.0, "C1.C": 1e-8}, 1e1, 1e5, 8),
    (
        "p(R1,C1)-p(R2,C2)",
        {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8},
        1e-1,
        1e7,
        4,
    ),
    (
        "R1-p(C1,R2-W1)",
        {"R1.R": 20.0, "C1.C": 1e-5, "R2.R": 100.0, "W1.A": 150.0},
        1e-2,
        1e5,
        5,
    ),
    ("C1-R1-L1", {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10}, 1e2, 1e9, 5),
]


@pytest.mark.parametrize(
    ("dsl", "truth", "f_min", "f_max", "points_per_decade"),
    WIRE_CORPUS,
    ids=[case[0] for case in WIRE_CORPUS],
)
def test_fit_result_round_trips_exactly_through_the_wire(
    dsl: str,
    truth: dict[str, float],
    f_min: float,
    f_max: float,
    points_per_decade: int,
) -> None:
    circuit = Circuit.parse(dsl)
    frequencies = log_frequencies(f_min, f_max, points_per_decade)
    data = simulate(circuit, frequencies, truth, noise=0.01, seed=11)
    result = fit(circuit, data, restarts=2, seed=0)

    payload = json.loads(json.dumps(result.to_wire()))
    back = FitResult.from_wire(payload)

    assert back.circuit.to_string() == result.circuit.to_string()
    assert back.circuit.param_names == result.circuit.param_names
    assert back.circuit.canonical_form() == result.circuit.canonical_form()
    assert np.array_equal(back.values, result.values)
    assert np.array_equal(back.z_model, result.z_model, equal_nan=True)
    assert np.array_equal(back.residuals, result.residuals)
    assert back.weighting == result.weighting
    assert back.success == result.success
    assert back.message == result.message
    assert back.n_restarts == result.n_restarts
    assert back.restart_spread == result.restart_spread
    assert back.fixed == result.fixed
    assert repr(back.elapsed_s) == repr(result.elapsed_s)

    stats, back_stats = result.statistics, back.statistics
    assert back_stats.n_data == stats.n_data
    assert back_stats.n_params == stats.n_params
    assert repr(back_stats.ssr) == repr(stats.ssr)
    assert repr(back_stats.chi2_reduced) == repr(stats.chi2_reduced)
    assert np.array_equal(back_stats.stderr, stats.stderr, equal_nan=True)
    assert np.array_equal(back_stats.correlation, stats.correlation, equal_nan=True)
    assert repr(back_stats.aic) == repr(stats.aic)
    assert repr(back_stats.aicc) == repr(stats.aicc)
    assert repr(back_stats.bic) == repr(stats.bic)
    assert back_stats.rank == stats.rank
    assert back_stats.warnings == stats.warnings

    assert back.summary(data) == result.summary(data)
    assert back.to_dict() == result.to_dict()


# =============================================================================================
# 7. The non-finite path
# =============================================================================================


def test_non_finite_statistics_survive_the_wire_exactly() -> None:
    """Non-finite stderr/correlation is what an unidentifiable model looks like on the wire.

    A *stderr* of inf or nan turns out to be unreachable from a real fit, and that is worth
    recording rather than re-derived. Two degenerate fits were tried -- "R1-R2-C1" against data
    generated from "R1-C1" (R1 and R2 are only constrained through their sum), and
    "R1-p(R2,C1)-R3" against data from "R1-p(R2,C1)" (R3 is redundant with R1). Neither
    produces a non-finite value: `compute_statistics` clips the covariance diagonal to `>= 0`
    before the square root and runs `np.nan_to_num` then `np.clip(..., -1.0, 1.0)` on the
    correlation, so a rank-deficient fit reports a tiny finite stderr and a correlation pinned
    to exactly +-1.0. Only `_covariance`'s two failure returns (a singular-value spectrum that
    is entirely zero, or a `LinAlgError`) fill those arrays with inf/nan, so this test builds
    the `Statistics` directly.

    The information criteria are a different matter: they reach -inf from an ordinary fit, and
    `test_a_degenerate_fit_really_does_put_negative_infinity_on_the_wire` covers that path.
    """
    circuit = Circuit.parse("R1-C1")
    data = simulate(circuit, log_frequencies(1e0, 1e5, 5), {"R1.R": 25.0, "C1.C": 4.7e-6}, seed=0)

    stats = Statistics(
        n_data=2 * data.n,
        n_params=2,
        ssr=1.5,
        chi2_reduced=0.05,
        stderr=np.array([math.inf, math.nan]),
        correlation=np.array([[1.0, math.nan], [math.nan, math.inf]]),
        aic=-100.0,
        aicc=math.inf,
        bic=math.nan,
        rank=1,
        warnings=("the Jacobian has rank 1 for 2 parameters",),
    )
    result = FitResult(
        circuit=circuit,
        values=np.array([25.0, 4.7e-6]),
        z_model=data.z,
        residuals=np.zeros(2 * data.n),
        statistics=stats,
        weighting="modulus",
        success=True,
        message="ok",
        n_restarts=1,
    )

    payload = json.loads(json.dumps(result.to_wire()))
    back = FitResult.from_wire(payload)

    assert np.array_equal(back.statistics.stderr, stats.stderr, equal_nan=True)
    assert np.array_equal(back.statistics.correlation, stats.correlation, equal_nan=True)
    assert math.isinf(back.statistics.aicc) and back.statistics.aicc > 0
    assert math.isnan(back.statistics.bic)
    assert back.statistics.warnings == stats.warnings


def test_a_degenerate_fit_really_does_put_negative_infinity_on_the_wire() -> None:
    """Two resistors in parallel, fitted to one resistor's noise-free response.

    The pair reproduces the data exactly, so the weighted sum of squared residuals is not
    merely small but exactly 0.0, and `compute_statistics` maps that to a log-likelihood term
    of -inf: AIC, AICc and BIC all come back -inf. Nothing about this is exotic -- exact
    equivalents on clean data are what the equivalence-class report exists to surface -- so the
    sentinel path is a routine path, not a defensive one.
    """
    data = simulate("R1", log_frequencies(1e0, 1e5, 5), {"R1.R": 25.0}, noise=0.0, seed=0)
    result = fit("p(R1,R2)", data, restarts=2, seed=0)
    assert result.statistics.ssr == 0.0
    assert result.statistics.aic == -math.inf

    payload = json.loads(json.dumps(result.to_wire()))
    assert payload["statistics"]["aic"] == NEGATIVE_INFINITY
    back = FitResult.from_wire(payload)
    assert back.statistics.aic == -math.inf
    assert back.statistics.aicc == result.statistics.aicc
    assert back.statistics.bic == result.statistics.bic
    assert back.statistics.rank == result.statistics.rank
    assert back.statistics.warnings == result.statistics.warnings


def test_the_payload_is_json_javascript_can_parse() -> None:
    """`json.dumps(..., allow_nan=False)` is the actual browser contract, and the default is not.

    Python emits bare `Infinity` and `NaN` tokens by default; `JSON.parse` rejects both, so a
    payload that survives `json.dumps` here can still be undeliverable to a Web Worker. Every
    non-finite value must therefore have been turned into a string sentinel before it reaches
    the encoder's output -- which is what this asserts, on both a healthy fit and a degenerate
    one whose criteria are -inf.
    """
    frequencies = log_frequencies(1e0, 1e5, 5)
    healthy = fit(
        "R1-C1",
        simulate("R1-C1", frequencies, {"R1.R": 25.0, "C1.C": 4.7e-6}, noise=0.01, seed=0),
        restarts=1,
        seed=0,
    )
    degenerate = fit(
        "p(R1,R2)",
        simulate("R1", frequencies, {"R1.R": 25.0}, noise=0.0, seed=0),
        restarts=2,
        seed=0,
    )
    for result in (healthy, degenerate):
        text = json.dumps(result.to_wire(), allow_nan=False)
        assert "Infinity" not in text and "NaN" not in text
        assert FitResult.from_wire(json.loads(text)).statistics.aic == result.statistics.aic


# =============================================================================================
# 8. Version check
# =============================================================================================


def test_from_wire_rejects_a_wrong_version() -> None:
    circuit = Circuit.parse("R1-C1")
    data = simulate(circuit, log_frequencies(1e0, 1e5, 5), {"R1.R": 25.0, "C1.C": 4.7e-6}, seed=0)
    result = fit(circuit, data, restarts=1, seed=0)
    payload = result.to_wire()

    wrong_version = dict(payload)
    wrong_version["version"] = WIRE_VERSION + 1
    with pytest.raises(ValueError, match="not"):
        FitResult.from_wire(wrong_version)

    missing_version = dict(payload)
    del missing_version["version"]
    with pytest.raises(ValueError, match="not"):
        FitResult.from_wire(missing_version)


# =============================================================================================
# 9. refit_plan equivalence
# =============================================================================================


def _refit_spectrum():
    return simulate(
        "R1-C1", log_frequencies(1e1, 1e4, 3), {"R1.R": 20.0, "C1.C": 1e-7}, noise=0.01, seed=0
    )


#: Kept tiny -- these tests are about the wire contract and the shortlist/chunking logic, not
#: about fit quality, so the differential-evolution budget is cut far below fit()'s defaults.
_TINY_POPSIZE = 6
_TINY_MAXITER = 12


def _drive_refit_plan(
    scored: list[tuple[float, str]],
    spectrum,
    *,
    n_refine: int,
    restarts: int,
    seed: int,
    as_wire: bool,
    chunk: int | None = None,
    drop_first_of_batch: bool = False,
) -> tuple[list[Candidate], list[RefitTask]]:
    """Run refit_plan to completion, computing each outcome with a tiny in-process fit."""
    plan = refit_plan(
        scored, n_refine=n_refine, n_data=2 * spectrum.n, restarts=restarts, seed=seed, chunk=chunk
    )
    all_tasks: list[RefitTask] = []
    try:
        tasks = next(plan)
        while True:
            all_tasks.extend(tasks)
            outcomes = []
            for i, task in enumerate(tasks):
                if drop_first_of_batch and i == 0:
                    outcomes.append(None)
                    continue
                result = fit(
                    task.text,
                    spectrum,
                    restarts=task.restarts,
                    seed=task.seed,
                    popsize=_TINY_POPSIZE,
                    maxiter=_TINY_MAXITER,
                )
                outcomes.append(json.loads(json.dumps(result.to_wire())) if as_wire else result)
            tasks = plan.send(outcomes)
    except StopIteration as done:
        return list(done.value), all_tasks


def test_refit_plan_gives_the_same_candidates_whether_outcomes_are_objects_or_wire_dicts() -> None:
    spectrum = _refit_spectrum()
    scored = [(1.0, "R1-C1"), (2.0, "R1-p(R2,C1)"), (3.0, "R1-C1-L1")]

    as_objects, _ = _drive_refit_plan(
        scored, spectrum, n_refine=3, restarts=1, seed=0, as_wire=False
    )
    as_wire, _ = _drive_refit_plan(
        scored, spectrum, n_refine=3, restarts=1, seed=0, as_wire=True
    )

    assert [c.circuit.to_string() for c in as_objects] == [c.circuit.to_string() for c in as_wire]
    for a, b in zip(as_objects, as_wire, strict=True):
        assert a.aicc == b.aicc
        assert np.array_equal(a.result.values, b.result.values)
        stderr_a, stderr_b = a.result.statistics.stderr, b.result.statistics.stderr
        assert np.array_equal(stderr_a, stderr_b, equal_nan=True)


def test_refit_plan_drops_a_task_that_comes_back_none() -> None:
    spectrum = _refit_spectrum()
    scored = [(1.0, "R1-C1"), (2.0, "R1-C1-L1")]
    candidates, _ = _drive_refit_plan(
        scored, spectrum, n_refine=2, restarts=1, seed=0, as_wire=False, drop_first_of_batch=True
    )
    # Both tasks are shortlisted (different sizes), but the first outcome in the one batch was
    # forced to None: only the second topology should survive.
    assert len(candidates) == 1
    assert candidates[0].circuit.to_string() == "R1-C1-L1"


def test_refit_plan_with_an_empty_shortlist_finishes_on_the_first_next() -> None:
    spectrum = _refit_spectrum()
    scored = [(math.inf, "R1-C1")]  # non-finite cost: _shortlist keeps only finite costs
    plan = refit_plan(scored, n_refine=3, n_data=2 * spectrum.n, restarts=1, seed=0)
    with pytest.raises(StopIteration) as excinfo:
        next(plan)
    assert excinfo.value.value == []


# =============================================================================================
# 10. refit_plan chunking
# =============================================================================================


def test_refit_plan_chunking_does_not_change_the_result() -> None:
    spectrum = _refit_spectrum()
    scored = [(1.0, "R1-C1"), (2.0, "R1-p(R2,C1)"), (3.0, "R1-C1-L1")]

    results_by_chunk: dict[str, list[Candidate]] = {}
    tasks_by_chunk: dict[str, list[RefitTask]] = {}
    for label, chunk in (("chunk_1", 1), ("chunk_2", 2), ("chunk_none", None)):
        candidates, tasks = _drive_refit_plan(
            scored, spectrum, n_refine=3, restarts=1, seed=0, as_wire=False, chunk=chunk
        )
        results_by_chunk[label] = candidates
        tasks_by_chunk[label] = tasks

    baseline = results_by_chunk["chunk_1"]
    for label in ("chunk_2", "chunk_none"):
        other = results_by_chunk[label]
        assert [c.circuit.to_string() for c in other] == [c.circuit.to_string() for c in baseline]
        for a, b in zip(baseline, other, strict=True):
            assert a.aicc == b.aicc
            assert np.array_equal(a.result.values, b.result.values)

    # The batches differ in shape (how many tasks per yield) but must carry the same tasks.
    baseline_tasks = tasks_by_chunk["chunk_1"]
    for label in ("chunk_2", "chunk_none"):
        assert tasks_by_chunk[label] == baseline_tasks
