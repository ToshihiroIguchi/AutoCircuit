"""Tests for deriving the element pool from the spectrum (``core/descriptors.py``).

The gates, in order:

1. **Gate C1 -- the derived pool never narrows.** Whatever the spectrum says, every code in the
   base pool survives, and ``W`` is never added. The second half has a measurement behind it
   (``docs/POOL_FROM_SPECTRUM_PLAN.md`` section 1): a CPE at ``n = 0.5`` *is* a semi-infinite
   Warburg, so a slot spent on ``W`` buys parsimony and no reach.
2. **Gate C2 -- the admitted set contains the true code.** On spectra generated from each
   finite-length diffusion element, the low-frequency band must admit that element. This is the
   half the search cannot recover from: a code the descriptor leaves out is never enumerated.
3. **Gate C3 -- every decision appears in the report.** The union of what was added and what was
   rejected must cover every code that was ever a candidate. This is the gate the whole plan
   exists for. The defect being repaired is not that the old default pool was wrong, it is that
   it was *silent*, and a widening that reports only its additions is silent in exactly the same
   way about its omissions.

Gate C4 (a spectrum that needs nothing produces byte-identical results to a fixed default pool)
lives with the search, in ``tests/test_discover_pool.py``, because it needs a full run.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from autocircuit.core.circuit import Circuit
from autocircuit.core.descriptors import (
    DIFFUSION_RUN_DECADES,
    WIDENING_CANDIDATES,
    PoolChoice,
    Trigger,
    admissible_diffusion_codes,
    choose_pool,
    diffusion_branch_decades,
    is_diffusion_shaped,
)
from autocircuit.core.elements import DEFAULT_POOL
from autocircuit.core.spectrum import Spectrum

# The generating circuits, with values chosen so that every feature the descriptor reads sits
# inside the measured window: 0.01 Hz to 100 kHz. ``tau = 1 s`` puts each finite-length
# element's transition near 0.16 Hz, two decades above the bottom of the sweep, so the DC limit
# that identifies it is actually reached.
DIFFUSION_TRUTHS: dict[str, tuple[str, dict[str, float]]] = {
    "semi-infinite": ("R1-W1", {"R1.R": 10.0, "W1.A": 100.0}),
    "short": ("R1-Ws1", {"R1.R": 10.0, "Ws1.R": 100.0, "Ws1.tau": 1.0}),
    "open": ("R1-Wo1", {"R1.R": 10.0, "Wo1.R": 100.0, "Wo1.tau": 1.0}),
    "gerischer": ("R1-G1", {"R1.R": 10.0, "G1.R": 100.0, "G1.tau": 1.0}),
    "arc + short": (
        "R1-p(R2,C1)-Ws1",
        {"R1.R": 10.0, "R2.R": 50.0, "C1.C": 1e-5, "Ws1.R": 100.0, "Ws1.tau": 1.0},
    ),
}

NO_DIFFUSION_TRUTHS: dict[str, tuple[str, dict[str, float]]] = {
    "resistor": ("R1", {"R1.R": 100.0}),
    "series RC": ("R1-C1", {"R1.R": 10.0, "C1.C": 1e-5}),
    "one arc": ("R1-p(R2,C1)", {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-5}),
    "resonator": ("C1-R1-L1", {"C1.C": 1e-6, "R1.R": 0.05, "L1.L": 1e-8}),
    "depressed arc": (
        "R1-p(R2,CPE1)",
        {"R1.R": 10.0, "R2.R": 100.0, "CPE1.Q": 1e-4, "CPE1.n": 0.85},
    ),
}


def _spectrum(
    dsl: str, values: dict[str, float], *, noise: float = 0.01, seed: int = 0
) -> Spectrum:
    f = np.logspace(-2, 5, 61)
    circuit = Circuit.parse(dsl)
    array = np.array([values[name] for name in circuit.param_names], dtype=float)
    z = np.asarray(circuit.impedance(2 * np.pi * f, array), dtype=np.complex128)
    rng = np.random.default_rng(seed)
    noisy = z * (
        1.0 + noise * rng.standard_normal(z.shape) + 1j * noise * rng.standard_normal(z.shape)
    )
    return Spectrum(f=f, z=np.asarray(noisy, dtype=np.complex128))


ALL_TRUTHS = {**DIFFUSION_TRUTHS, **NO_DIFFUSION_TRUTHS}


# -- 1. Gate C1: the derived pool never narrows ---------------------------------------------


@pytest.mark.parametrize("label", sorted(ALL_TRUTHS))
@pytest.mark.parametrize("runs_z", [-5.0, 0.0, math.nan])
def test_c1_base_pool_always_survives(label: str, runs_z: float) -> None:
    dsl, values = ALL_TRUTHS[label]
    choice = choose_pool(_spectrum(dsl, values), residual_runs_z=runs_z)
    assert set(DEFAULT_POOL) <= set(choice.pool)
    assert choice.pool[: len(DEFAULT_POOL)] == DEFAULT_POOL


@pytest.mark.parametrize("label", sorted(ALL_TRUTHS))
def test_c1_w_is_never_added(label: str) -> None:
    """A CPE at n = 0.5 is a semi-infinite Warburg, so ``W`` reaches nothing new.

    Measured in docs/POOL_FROM_SPECTRUM_PLAN.md section 1: on an ``R1-W1`` spectrum the truth
    fits to 1.3344% relative error and ``R1-CPE1`` fits to 1.3344%, the same five figures.
    """
    dsl, values = ALL_TRUTHS[label]
    choice = choose_pool(_spectrum(dsl, values), residual_runs_z=-5.0)
    assert "W" not in choice.added


def test_c1_nothing_is_added_when_neither_reading_asks() -> None:
    """Two quiet readings widen nothing, whatever the band would have admitted.

    The band admits ``Ws`` and ``G`` for almost any spectrum whose low-frequency end is
    resistive, including a plain resistor -- which is why the band is the wrong instrument to
    *fire* on and only the right one to choose with. Only the diffusion-free truths are used
    here, because on the others the shape reading fires on its own and should.
    """
    for dsl, values in NO_DIFFUSION_TRUTHS.values():
        choice = choose_pool(_spectrum(dsl, values), residual_runs_z=0.0)
        assert choice.added == ()
        assert choice.pool == DEFAULT_POOL
        assert choice.triggered == "no"


# -- 2. Gate C2: the true code is admitted --------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [("short", "Ws"), ("open", "Wo"), ("gerischer", "G"), ("arc + short", "Ws")],
)
def test_c2_true_code_is_admitted(label: str, expected: str) -> None:
    dsl, values = DIFFUSION_TRUTHS[label]
    admitted, _ = admissible_diffusion_codes(_spectrum(dsl, values))
    assert expected in admitted


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("noise", [0.005, 0.02])
def test_c2_survives_noise_and_seed(seed: int, noise: float) -> None:
    for label, expected in (("short", "Ws"), ("open", "Wo"), ("gerischer", "G")):
        dsl, values = DIFFUSION_TRUTHS[label]
        admitted, _ = admissible_diffusion_codes(_spectrum(dsl, values, noise=noise, seed=seed))
        assert expected in admitted, f"{label} at noise={noise} seed={seed}: {admitted}"


def test_c2_ws_and_g_are_admitted_together() -> None:
    """They are not substitutes, so admitting one without the other would exclude an answer.

    [measured, docs/POOL_FROM_SPECTRUM_PLAN.md section 4] Swapping them costs 3.3x to 3.6x in
    relative error: truth ``R1-Ws1`` fits at 1.333% and ``R1-G1`` at 4.334% on the same data.
    They share a DC limit and the band cannot separate them, which is the honest outcome rather
    than a shortcoming -- but it is also what makes the widened pool six codes wide, and section
    2 measured that this is what costs the fifth completeness level.
    """
    for label in ("short", "gerischer"):
        dsl, values = DIFFUSION_TRUTHS[label]
        admitted, _ = admissible_diffusion_codes(_spectrum(dsl, values))
        assert {"Ws", "G"} <= set(admitted)


def test_c2_semi_infinite_warburg_admits_no_finite_length_code() -> None:
    """``R1-W1`` falls to -0.5 at DC, which neither a resistive nor a blocking limit matches."""
    dsl, values = DIFFUSION_TRUTHS["semi-infinite"]
    admitted, rejected = admissible_diffusion_codes(_spectrum(dsl, values))
    assert admitted == ()
    assert {code for code, _ in rejected} == set(WIDENING_CANDIDATES)


# -- 3. Gate C3: every decision appears in the report ---------------------------------------


@pytest.mark.parametrize("label", sorted(ALL_TRUTHS))
@pytest.mark.parametrize("runs_z", [-5.0, 0.0, math.nan])
def test_c3_every_candidate_code_is_accounted_for(label: str, runs_z: float) -> None:
    """Added or rejected, but never merely absent.

    The defect this module repairs is not a wrong pool, it is a silent one. A widening that
    lists what it added and says nothing about what it left out has reproduced the defect at a
    smaller scale.
    """
    dsl, values = ALL_TRUTHS[label]
    choice = choose_pool(_spectrum(dsl, values), residual_runs_z=runs_z)
    accounted = set(choice.added) | {code for code, _ in choice.rejected}
    assert set(WIDENING_CANDIDATES) <= accounted
    assert "W" in accounted, "the one code excluded by measurement must be named"


@pytest.mark.parametrize("label", sorted(ALL_TRUTHS))
@pytest.mark.parametrize("runs_z", [-5.0, 0.0, math.nan])
def test_c3_sentence_names_the_codes_it_decided_about(label: str, runs_z: float) -> None:
    dsl, values = ALL_TRUTHS[label]
    choice = choose_pool(_spectrum(dsl, values), residual_runs_z=runs_z)
    sentence = choice.sentence()
    for code in choice.added:
        assert code in sentence
    for code, _ in choice.rejected:
        assert code in sentence
    assert sentence.startswith("Pool:")


def test_c3_rejection_reasons_are_not_empty() -> None:
    for dsl, values in ALL_TRUTHS.values():
        choice = choose_pool(_spectrum(dsl, values), residual_runs_z=-5.0)
        for code, reason in choice.rejected:
            assert reason.strip(), f"{code} was rejected without saying why"


# -- 4. The report must survive a spectrum that constrains nothing ---------------------------


def test_an_unconstrained_band_serialises_as_valid_json() -> None:
    """``json.dumps`` writes ``-Infinity`` for a float infinity and no other parser reads it.

    The low-frequency band is ``(-inf, +inf)`` whenever the data says nothing about its
    low-frequency end -- too few points, a non-positive magnitude, a slope with no determinable
    standard error. That reaches the CLI's ``--json`` and the browser's download, and the
    browser's parser rejects it, so the edges go out as null.
    """
    choice = PoolChoice(
        base=DEFAULT_POOL,
        added=(),
        rejected=(("Ws", "reason"),),
        low_band=(-math.inf, math.inf),
        diffusion_decades=0.2,
        residual_runs_z=-0.26,
    )
    payload = json.dumps(choice.to_dict(), allow_nan=False)
    assert '"low_band": [null, null]' in payload


@pytest.mark.parametrize(
    ("triggered", "runs_z"), [("yes", -5.42), ("no", -0.26), ("unasked", math.nan)]
)
def test_an_unconstrained_band_is_not_printed_as_a_measurement(
    triggered: Trigger, runs_z: float
) -> None:
    """"[-inf, +inf] admits it" would read as evidence for exactly the opposite of the truth."""
    choice = PoolChoice(
        base=DEFAULT_POOL,
        added=("Ws",) if triggered == "yes" else (),
        rejected=(("Wo", "reason"),),
        low_band=(-math.inf, math.inf),
        diffusion_decades=0.2,
        residual_runs_z=runs_z,
    )
    assert choice.triggered == triggered
    sentence = choice.sentence()
    assert "inf" not in sentence
    if triggered == "yes":
        assert "never reaches" in sentence


# -- 5. Gate C6: two triggers, and neither one is sufficient ---------------------------------
#
# The union is not caution, it is what the measurements left. Each reading fails on spectra the
# other catches, so a version of this feature with one of them removed passes every other gate
# here and silently loses a whole class of answer. These tests pin the two failure cases that
# forced the design, so that dropping either instrument fails loudly.


def test_c6_shape_catches_what_the_residual_loses() -> None:
    """``R1-Ws1`` is where the residual reading stops being evidence.

    [measured, docs/POOL_FROM_SPECTRUM_PLAN.md section 6] At the production element limit the
    best default-pool fit leaves runs z -2.07 at one noise seed and -0.77 at the next -- given
    five elements the pool builds an eight-parameter CPE stack that explains the data to within
    noise, so whether the residual looks systematic is down to the noise realisation. The shape
    reading does not depend on a fit at all and never falls below 1.60 decades here.
    """
    dsl, values = DIFFUSION_TRUTHS["short"]
    for seed in (0, 1, 2):
        for noise in (0.005, 0.02):
            spectrum = _spectrum(dsl, values, noise=noise, seed=seed)
            assert is_diffusion_shaped(spectrum), (
                f"seed={seed} noise={noise}: "
                f"{diffusion_branch_decades(spectrum):.2f} decades"
            )
            # And it widens on the shape alone, with the residual saying nothing is wrong.
            assert choose_pool(spectrum, residual_runs_z=0.0).added


def test_c6_residual_catches_what_the_shape_loses() -> None:
    """``R1-p(R2,CPE1)-Wo1`` is where the shape reading stops being evidence.

    A relaxation sitting on the diffusion branch blends the two, and the 45-degree run collapses
    to 0.20-0.60 decades -- inside the range diffusion-free spectra occupy, so no threshold
    admits it. The residual reads -5.42 on the same data.
    """
    dsl = "R1-p(R2,CPE1)-Wo1"
    values = {
        "R1.R": 10.0,
        "R2.R": 50.0,
        "CPE1.Q": 1e-4,
        "CPE1.n": 0.85,
        "Wo1.R": 100.0,
        "Wo1.tau": 1.0,
    }
    spectrum = _spectrum(dsl, values)
    assert not is_diffusion_shaped(spectrum)
    assert choose_pool(spectrum, residual_runs_z=-5.42).added == ("Wo",)


def test_c6_the_shape_reading_never_fires_on_a_diffusion_free_spectrum() -> None:
    """192 measured trials, zero false positives; this is the cheap half of that claim.

    The threshold is 0.75 decades against a measured diffusion-free maximum of 0.50. If a
    change pushes an ordinary arc over the line, the cost is a second search on every such
    spectrum, which is exactly the regression this asserts against.
    """
    for dsl, values in NO_DIFFUSION_TRUTHS.values():
        for seed in (0, 1, 2):
            for noise in (0.005, 0.02):
                spectrum = _spectrum(dsl, values, noise=noise, seed=seed)
                decades = diffusion_branch_decades(spectrum)
                assert decades < DIFFUSION_RUN_DECADES, f"{dsl} seed={seed}: {decades:.2f}"


def test_c6_both_readings_are_named_whichever_fired() -> None:
    """A reader who sees only the reading that fired cannot tell agreement from disagreement."""
    dsl, values = DIFFUSION_TRUTHS["short"]
    sentence = choose_pool(_spectrum(dsl, values), residual_runs_z=0.0).sentence()
    assert "runs z" in sentence
    assert "45-degree branch" in sentence
