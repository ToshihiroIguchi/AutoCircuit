"""Gate C4 and the wiring: what deriving the pool from the spectrum costs a spectrum that
does not need it, and what a run that widened is allowed to claim.

**Gate C4 -- a spectrum that needs nothing pays nothing.** ``discover(pool=None)`` on data the
base pool already explains must produce the same report, to the digit, as ``discover(pool=
DEFAULT_POOL)``. This is the invariant that makes the change safe to make the default: the
widening is a second search that only ever happens on evidence, so a ceramic capacitor's
spectrum takes exactly the path it took before. It is fingerprinted the way EV5 is -- compare
the whole serialised report rather than a summary line -- because the failure this project keeps
finding is a report that looks healthy while a number underneath it moved.

**Gate C5 -- a run that widened says so, and says what widening cost.** Two pools were searched,
so there are two completeness statements. The coverage sentence has to carry both, because
``complete_up_to`` alone would either overclaim the wide pool or throw away what the narrow one
covered.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from autocircuit.core.circuit import Circuit
from autocircuit.core.descriptors import WIDENING_CANDIDATES, PoolChoice
from autocircuit.core.discover import DiscoveryResult, discover
from autocircuit.core.elements import DEFAULT_POOL
from autocircuit.core.spectrum import Spectrum

# Kept small on purpose: gate C4 is about two runs agreeing, not about recovering a truth, so
# the enumeration limit is the smallest that still exercises the exhaustive stage end to end.
LIMIT = 3


def _spectrum(
    dsl: str, values: dict[str, float], *, noise: float = 0.01, seed: int = 0
) -> Spectrum:
    f = np.logspace(-1, 4, 31)
    circuit = Circuit.parse(dsl)
    array = np.array([values[name] for name in circuit.param_names], dtype=float)
    z = np.asarray(circuit.impedance(2 * np.pi * f, array), dtype=np.complex128)
    rng = np.random.default_rng(seed)
    noisy = z * (
        1.0 + noise * rng.standard_normal(z.shape) + 1j * noise * rng.standard_normal(z.shape)
    )
    return Spectrum(f=f, z=np.asarray(noisy, dtype=np.complex128))


ONE_ARC = ("R1-p(R2,C1)", {"R1.R": 10.0, "R2.R": 100.0, "C1.C": 1e-5})


def _without_wall_clock(value: object) -> object:
    """Strip ``elapsed_s`` everywhere so the comparison is about numbers, not about the clock.

    It is the only field that differs between two identical searches, and it appears on the
    result, on every candidate, on the Pareto rows and on the recommendation. Dropping it by
    name at every depth is deliberate: a blanket float tolerance would also hide a chi-squared
    that moved, which is exactly what this gate is for.
    """
    if isinstance(value, dict):
        return {k: _without_wall_clock(v) for k, v in value.items() if k != "elapsed_s"}
    if isinstance(value, list):
        return [_without_wall_clock(v) for v in value]
    return value


def _search(spectrum: Spectrum, pool: tuple[str, ...] | None) -> DiscoveryResult:
    return discover(
        spectrum,
        pool=pool,
        mode="exhaustive",
        exhaustive_limit=LIMIT,
        seed=0,
        workers=1,
    )


# -- Gate C4 --------------------------------------------------------------------------------


def test_c4_a_spectrum_that_needs_nothing_takes_the_old_path() -> None:
    """Every number in the report is identical; only the pool commentary differs."""
    spectrum = _spectrum(*ONE_ARC)
    derived = _search(spectrum, None)
    fixed = _search(spectrum, DEFAULT_POOL)

    assert derived.pool == fixed.pool == DEFAULT_POOL
    assert derived.pool_choice is not None and derived.pool_choice.added == ()
    assert derived.base_complete_up_to is None

    left, right = derived.to_dict(), fixed.to_dict()
    # The two keys that exist *because* the pool was derived, plus the coverage sentence that
    # quotes them. Everything else has to match to the digit.
    for key in ("pool_choice", "base_complete_up_to", "coverage"):
        left.pop(key), right.pop(key)
    assert _without_wall_clock(left) == _without_wall_clock(right)


def test_c4_the_untriggered_choice_is_still_reported() -> None:
    """"Nothing was added" is a claim about the diffusion elements, not silence about them.

    The defect being repaired is that the old default said nothing. A derived pool that adds
    nothing and *also* says nothing has reproduced it exactly.
    """
    result = _search(_spectrum(*ONE_ARC), None)
    assert result.pool_choice is not None
    named = set(result.pool_choice.added) | {code for code, _ in result.pool_choice.rejected}
    assert set(WIDENING_CANDIDATES) <= named
    assert result.pool_choice.sentence() in result.completeness()


def test_c4_an_explicit_pool_records_no_choice() -> None:
    """A caller who named a pool narrowed the search themselves and knows it."""
    result = _search(_spectrum(*ONE_ARC), DEFAULT_POOL)
    assert result.pool_choice is None
    assert "Pool:" not in result.completeness()


# -- Gate C5 --------------------------------------------------------------------------------


def _widened(base_level: int, level: int) -> DiscoveryResult:
    """A result shaped like one whose widening cost a completeness level.

    Built rather than searched: the sentence under test is a property of the report, and
    driving a real search into this state costs minutes for something the fields already
    determine.
    """
    return DiscoveryResult(
        candidates=[],
        pareto=[],
        n_evaluated=1234,
        generations=0,
        elapsed_s=1.0,
        pool=DEFAULT_POOL + ("Ws", "G"),
        mode="exhaustive",
        complete_up_to=level,
        pool_choice=PoolChoice(
            base=DEFAULT_POOL,
            added=("Ws", "G"),
            rejected=(("Wo", "a DC limit of exponent -1.00 is outside the measured band"),),
            low_band=(-0.51, 0.36),
            diffusion_decades=3.4,
            residual_runs_z=-2.07,
        ),
        base_complete_up_to=base_level,
    )


def test_c5_a_lost_level_is_stated_with_both_numbers() -> None:
    sentence = _widened(base_level=5, level=4).completeness()
    assert "Ws, G" in sentence
    assert "complete to 5 elements" in sentence
    assert "and the wider one to 4" in sentence
    assert "5 elements using an added code was not evaluated" in sentence


def test_c5_no_lost_level_says_nothing_about_one() -> None:
    sentence = _widened(base_level=5, level=5).completeness()
    assert "Widening cost a level" not in sentence
    assert "Ws, G" in sentence


@pytest.mark.parametrize(
    ("expected", "decades", "runs_z"),
    [
        ("unasked", 0.2, math.nan),
        ("unasked", 3.4, math.nan),
        ("no", 0.2, -0.26),
        ("yes", 0.2, -5.42),
        ("yes", 3.4, -0.26),
    ],
)
def test_c5_every_trigger_state_produces_a_distinct_sentence(
    expected: str, decades: float, runs_z: float
) -> None:
    """``unasked`` is not a spelling of ``no``, and the report must not blur them.

    A search that never completed a pool has no evidence either way; one that completed a pool
    and found no systematic residual has checked. Reporting the first as the second would claim
    a check that never ran -- and the two rows with the same verdict but different readings are
    the point of naming both: they are different runs and the sentence must say so.
    """
    choice = PoolChoice(
        base=DEFAULT_POOL,
        added=("Ws",) if expected == "yes" else (),
        rejected=tuple((code, "reason") for code in WIDENING_CANDIDATES),
        low_band=(-0.5, 0.4),
        diffusion_decades=decades,
        residual_runs_z=runs_z,
    )
    assert choice.triggered == expected
    sentence = choice.sentence()
    assert sentence.startswith("Pool:")
    if expected == "unasked":
        assert "Nothing tested the fit's residual" in sentence
    else:
        assert "runs z" in sentence
    assert f"{decades:.2f}" in sentence


def test_c5_a_shape_reading_cannot_outvote_a_missing_search() -> None:
    """``unasked`` wins over a firing shape reading, and the sentence still reports both.

    Half the evidence is absent whatever the other half says. Reporting this as ``yes`` would
    claim a widening that the genetic search never performs; reporting it as ``no`` would claim
    a check that never ran. The shape reading is stated either way, so a spectrum that looks
    like diffusion under a search that could not check says exactly that.
    """
    choice = PoolChoice(
        base=DEFAULT_POOL,
        added=(),
        rejected=(("Ws", "reason"),),
        low_band=(-0.5, 0.4),
        diffusion_decades=3.4,
        residual_runs_z=math.nan,
    )
    assert choice.triggered == "unasked"
    assert choice.shape_asks
    assert "3.40-decade 45-degree branch" in choice.sentence()


# -- The widening under a skeleton -----------------------------------------------------------


WARBURG = ("R1-Ws1", {"R1.R": 10.0, "Ws1.R": 100.0, "Ws1.tau": 1.0})


def _warburg_spectrum() -> Spectrum:
    """A finite-length diffusion spectrum, swept low enough to reach its resistive limit.

    ``tau = 1 s`` puts the transition near 0.16 Hz, so the sweep has to start below that for the
    DC limit that identifies ``Ws`` over ``Wo`` to be in the data at all.
    """
    f = np.logspace(-2, 3, 31)
    circuit = Circuit.parse(WARBURG[0])
    array = np.array([WARBURG[1][name] for name in circuit.param_names], dtype=float)
    z = np.asarray(circuit.impedance(2 * np.pi * f, array), dtype=np.complex128)
    rng = np.random.default_rng(0)
    noisy = z * (
        1.0 + 0.01 * rng.standard_normal(z.shape) + 1j * 0.01 * rng.standard_normal(z.shape)
    )
    return Spectrum(f=f, z=np.asarray(noisy, dtype=np.complex128))


def test_the_pool_widens_and_recovers_the_truth() -> None:
    """The end the whole feature is for: a topology the old default pool could not express.

    `R1-Ws1` is a transmission line. No tree of R, C, L and CPE reproduces one, so before this
    change the search could only ever return an approximation -- measured at 4x to 17x the noise
    floor for a comparable parameter count (docs/POOL_FROM_SPECTRUM_PLAN.md section 1).
    """
    result = _search(_warburg_spectrum(), None)
    assert result.pool_choice is not None
    assert result.pool_choice.added == ("Ws", "G")
    assert result.recommended is not None
    assert result.recommended.circuit.to_string() == "R1-Ws1"


def test_a_skeleton_run_widens_and_says_both_things() -> None:
    """A constrained search still derives its pool, and the report carries both constraints.

    They narrow different axes -- the skeleton narrows which topologies, the pool narrows which
    elements -- so one sentence cannot stand in for the other, and a reader who sees only the
    skeleton clause does not know a family of elements was also decided about.
    """
    result = discover(
        _warburg_spectrum(),
        pool=None,
        skeleton="R1",
        mode="exhaustive",
        exhaustive_limit=LIMIT,
        seed=0,
        workers=1,
    )
    assert result.pool_choice is not None
    assert result.pool_choice.added == ("Ws", "G")
    assert result.pool == DEFAULT_POOL + ("Ws", "G")

    coverage = result.completeness()
    assert "contains R1" in coverage
    assert "Ws, G was added" in coverage


def test_c5_a_widened_pool_that_finished_no_size_keeps_the_narrow_claim() -> None:
    """When the wider enumeration overflows entirely, what the narrow pool covered survives.

    ``complete_up_to`` describes the pool that was reported, so a widening that never finished
    a size leaves it None -- and the narrow pool's completeness, which is still true, would go
    out with it. It is the only claim left, so the sentence states it rather than reporting the
    run as "sampled, not exhaustive" and nothing more.
    """
    result = _widened(base_level=5, level=4)
    result.complete_up_to = None
    sentence = result.completeness()
    assert "reached no complete size at all" in sentence
    assert "up to 5 elements from R, C, L, CPE" in sentence
