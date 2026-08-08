"""Tests for the structural feasibility filter (docs/DISCOVERY_V2_PLAN.md gate G3).

Covers, in order:

1. That the element exponent metadata (``dc_exponent`` / ``hf_exponent`` on every
   ``autocircuit.core.elements`` class) is numerically true -- checked against the empirical
   log-log slope of ``impedance()`` itself, never against the formula that produced the
   metadata.
2. ``endpoint_exponents`` on a handful of hand-derived topologies at ``budget=0``.
3. That a larger degeneracy budget only ever widens the reachable hull.
4. That ``EndpointBehaviour.from_spectrum`` reads a measured spectrum correctly.
5. **Gate G3 itself**: the filter must never mark the true topology, or any of its known exact
   equivalents, infeasible.
6. That the filter is not a no-op -- it actually shrinks the enumeration -- while never
   producing anything the unfiltered enumeration would not.
7. That an uninformative spectrum (no usable endpoint slope) disables the filter entirely.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pytest

from autocircuit.core.circuit import Circuit, canonical_form
from autocircuit.core.elements import REGISTRY, Element
from autocircuit.core.enumerate import (
    DEFAULT_DEGENERACY_BUDGET,
    EndpointBehaviour,
    endpoint_exponents,
    enumerate_topologies,
    feasible_topologies,
    is_feasible,
)
from autocircuit.core.simulate import log_frequencies, simulate

# =============================================================================================
# 1. Element exponent metadata is numerically true
# =============================================================================================

#: Two closely spaced probe frequencies at each edge of the axis, chosen far enough out that
#: every element in the registry has settled into (or very nearly into) its asymptotic regime.
_LOW_OMEGA: tuple[float, float] = (1e-9, 1e-8)
_HIGH_OMEGA: tuple[float, float] = (1e11, 1e12)

#: Absolute slack around the declared interval, allowing for numerical effects and for elements
#: whose exponent is small (so convergence to the asymptote is intrinsically slow but the
#: resulting slope error stays small in absolute terms).
_EXPONENT_SLACK = 0.05


def _log_log_slope(magnitude: np.ndarray, omega: tuple[float, float]) -> float | None:
    """Empirical ``d log10|Z| / d log10(omega)`` between two frequencies.

    Returns ``None`` (meaning "skip") if either magnitude is zero or non-finite.
    """
    if not np.all(np.isfinite(magnitude)) or np.any(magnitude <= 0.0):
        return None
    return float(
        (np.log10(magnitude[1]) - np.log10(magnitude[0]))
        / (np.log10(omega[1]) - np.log10(omega[0]))
    )


def _empirical_dc_hf_slopes(
    element: Element, values: list[float]
) -> tuple[float | None, float | None]:
    """Empirical (dc, hf) log-log slope of ``element`` at the given parameter values."""
    values_arr = np.array(values, dtype=np.float64)
    z_lo = element.impedance(np.array(_LOW_OMEGA), values_arr)
    z_hi = element.impedance(np.array(_HIGH_OMEGA), values_arr)
    return (
        _log_log_slope(np.abs(z_lo), _LOW_OMEGA),
        _log_log_slope(np.abs(z_hi), _HIGH_OMEGA),
    )


def _assert_in_band(slope: float | None, band: tuple[float, float], label: str) -> None:
    if slope is None:
        pytest.skip(f"{label}: |Z| was zero or non-finite at the probe frequencies")
    lo, hi = band
    assert lo - _EXPONENT_SLACK <= slope <= hi + _EXPONENT_SLACK, (
        f"{label}: empirical slope {slope:+.4f} outside declared band "
        f"[{lo:+.2f}, {hi:+.2f}] (+/- {_EXPONENT_SLACK})"
    )


#: Parameter values for elements whose exponent interval is a single point (no free exponent).
#: Scales follow the task's suggestion (R=100, C=1e-6, L=1e-3, tau=1e-3) so |Z| stays in a
#: numerically sane range at both the very low and the very high probe frequencies.
_FIXED_EXPONENT_VALUES: dict[str, list[float]] = {
    "R": [100.0],
    "C": [1e-6],
    "L": [1e-3],
    "W": [100.0],
    "Ws": [100.0, 1e-3],
    "Wo": [100.0, 1e-3],
    "G": [100.0, 1e-3],
    "SKINW": [10.0, 1e-3],
}

#: Elements with a free exponent, checked separately at both ends of their hard limits.
_FREE_EXPONENT_CODES = frozenset({"CPE", "CC", "HN", "SKINF"})


def test_every_registry_element_is_covered_by_an_exponent_metadata_test() -> None:
    """Guard against a new element being added without exponent-metadata coverage."""
    covered = set(_FIXED_EXPONENT_VALUES) | _FREE_EXPONENT_CODES
    assert covered == set(REGISTRY)


@pytest.mark.parametrize("code", sorted(_FIXED_EXPONENT_VALUES))
def test_fixed_exponent_metadata_matches_empirical_slope(code: str) -> None:
    element = REGISTRY[code]
    dc_slope, hf_slope = _empirical_dc_hf_slopes(element, _FIXED_EXPONENT_VALUES[code])
    _assert_in_band(dc_slope, element.dc_exponent, f"{code} (dc)")
    _assert_in_band(hf_slope, element.hf_exponent, f"{code} (hf)")


def test_cpe_exponent_metadata_at_hard_limits() -> None:
    # |Z| = 1 / (Q * omega^n), independent of Q, so the slope is exactly -n at every frequency.
    cpe = REGISTRY["CPE"]
    n_lo, n_hi = cpe.params[1].hard_lo, cpe.params[1].hard_hi
    # n=hard_hi gives the most negative (capacitive) slope, n=hard_lo the least negative.
    for n, expected_dc_end, expected_hf_end in (
        (n_hi, cpe.dc_exponent[0], cpe.hf_exponent[0]),
        (n_lo, cpe.dc_exponent[1], cpe.hf_exponent[1]),
    ):
        dc_slope, hf_slope = _empirical_dc_hf_slopes(cpe, [1e-6, n])
        expected = -n
        assert dc_slope is not None and abs(dc_slope - expected) < _EXPONENT_SLACK
        assert hf_slope is not None and abs(hf_slope - expected) < _EXPONENT_SLACK
        assert abs(expected - expected_dc_end) < 1e-9
        assert abs(expected - expected_hf_end) < 1e-9


def test_cole_cole_exponent_metadata_at_hard_limits() -> None:
    # dc plateau is always R (slope 0); hf slope tends to -alpha.
    cc = REGISTRY["CC"]
    alpha_lo, alpha_hi = cc.params[2].hard_lo, cc.params[2].hard_hi
    for alpha, expected_hf_end in (
        (alpha_hi, cc.hf_exponent[0]),
        (alpha_lo, cc.hf_exponent[1]),
    ):
        dc_slope, hf_slope = _empirical_dc_hf_slopes(cc, [100.0, 1e-3, alpha])
        _assert_in_band(dc_slope, cc.dc_exponent, f"CC alpha={alpha} (dc)")
        expected = -alpha
        assert hf_slope is not None and abs(hf_slope - expected) < _EXPONENT_SLACK
        assert abs(expected - expected_hf_end) < 1e-9


def test_havriliak_negami_exponent_metadata_at_hard_limits() -> None:
    # dc plateau is always R (slope 0); hf slope tends to -alpha*beta, whose extremes over the
    # square [hard_lo, hard_hi]^2 sit at the two matching corners (both at hard_lo, both at
    # hard_hi), since the product is monotonic in each factor.
    hn = REGISTRY["HN"]
    alpha_spec, beta_spec = hn.params[2], hn.params[3]
    assert (alpha_spec.hard_lo, alpha_spec.hard_hi) == (beta_spec.hard_lo, beta_spec.hard_hi)
    lim_lo, lim_hi = alpha_spec.hard_lo, alpha_spec.hard_hi
    for exponent, expected_hf_end in (
        (lim_hi, hn.hf_exponent[0]),
        (lim_lo, hn.hf_exponent[1]),
    ):
        dc_slope, hf_slope = _empirical_dc_hf_slopes(hn, [100.0, 1e-3, exponent, exponent])
        _assert_in_band(dc_slope, hn.dc_exponent, f"HN alpha=beta={exponent} (dc)")
        expected = -(exponent * exponent)
        assert hf_slope is not None and abs(hf_slope - expected) < _EXPONENT_SLACK
        assert abs(expected - expected_hf_end) < 1e-9


def test_skinf_exponent_metadata_at_hard_limits() -> None:
    # |Z| = A * omega^n, independent of A, so the slope is exactly +n at every frequency, at
    # both edges (SKINF is inductive-like at both ends over its whole allowed exponent range).
    skinf = REGISTRY["SKINF"]
    n_lo, n_hi = skinf.params[1].hard_lo, skinf.params[1].hard_hi
    for n, expected_dc_end, expected_hf_end in (
        (n_lo, skinf.dc_exponent[0], skinf.hf_exponent[0]),
        (n_hi, skinf.dc_exponent[1], skinf.hf_exponent[1]),
    ):
        dc_slope, hf_slope = _empirical_dc_hf_slopes(skinf, [1e-6, n])
        expected = n
        assert dc_slope is not None and abs(dc_slope - expected) < _EXPONENT_SLACK
        assert hf_slope is not None and abs(hf_slope - expected) < _EXPONENT_SLACK
        assert abs(expected - expected_dc_end) < 1e-9
        assert abs(expected - expected_hf_end) < 1e-9


# =============================================================================================
# 2. endpoint_exponents on hand-checked topologies, at budget=0
# =============================================================================================


@pytest.mark.parametrize(
    "text,low,high",
    [
        ("R1", (0.0, 0.0), (0.0, 0.0)),
        ("C1", (-1.0, -1.0), (-1.0, -1.0)),
        ("L1", (1.0, 1.0), (1.0, 1.0)),
        # Series: at low frequency the biggest |Z| (smallest exponent) wins.
        ("R1-C1", (-1.0, -1.0), (0.0, 0.0)),
        # Parallel: at low frequency the smallest |Z| (biggest exponent) wins.
        ("p(R1,C1)", (0.0, 0.0), (-1.0, -1.0)),
        ("C1-R1-L1", (-1.0, -1.0), (1.0, 1.0)),
        ("R1-p(R2,C1)", (0.0, 0.0), (0.0, 0.0)),
        ("p(R1,C1-R2)", (0.0, 0.0), (0.0, 0.0)),
    ],
)
def test_endpoint_exponents_on_hand_checked_topologies_at_budget_zero(
    text: str, low: tuple[float, float], high: tuple[float, float]
) -> None:
    node = Circuit.parse(text).root
    assert endpoint_exponents(node, "low", budget=0) == low
    assert endpoint_exponents(node, "high", budget=0) == high


# =============================================================================================
# 3. Budget monotonicity: a larger budget can only widen the hull
# =============================================================================================

_MONOTONICITY_TOPOLOGIES = [
    "R1",
    "R1-C1",
    "p(R1,C1)",
    "C1-R1-L1",
    "R1-p(R2,C1)",
    "p(R1,C1)-p(R2,C2)",
]


@pytest.mark.parametrize("budget", [0, 1, 2])
@pytest.mark.parametrize("text", _MONOTONICITY_TOPOLOGIES)
def test_budget_monotonicity_widens_the_hull(text: str, budget: int) -> None:
    node = Circuit.parse(text).root
    for end in ("low", "high"):
        lo_b, hi_b = endpoint_exponents(node, end, budget=budget)
        lo_b1, hi_b1 = endpoint_exponents(node, end, budget=budget + 1)
        assert lo_b1 <= lo_b, f"{text} {end}: budget {budget + 1} narrowed the low bound"
        assert hi_b1 >= hi_b, f"{text} {end}: budget {budget + 1} narrowed the high bound"


# =============================================================================================
# 4. EndpointBehaviour.from_spectrum reads the data correctly
# =============================================================================================


def test_from_spectrum_pure_capacitor_gives_capacitive_bands() -> None:
    data = simulate("C1", log_frequencies(1e0, 1e6, 10), {"C1.C": 1e-6}, seed=0)
    behaviour = EndpointBehaviour.from_spectrum(data)
    assert behaviour.low_band[0] <= -1.0 <= behaviour.low_band[1]
    assert behaviour.high_band[0] <= -1.0 <= behaviour.high_band[1]


def test_from_spectrum_pure_inductor_gives_inductive_bands() -> None:
    data = simulate("L1", log_frequencies(1e0, 1e6, 10), {"L1.L": 1e-3}, seed=0)
    behaviour = EndpointBehaviour.from_spectrum(data)
    assert behaviour.low_band[0] <= 1.0 <= behaviour.low_band[1]
    assert behaviour.high_band[0] <= 1.0 <= behaviour.high_band[1]


def test_from_spectrum_pure_resistor_gives_resistive_bands() -> None:
    data = simulate("R1", log_frequencies(1e0, 1e6, 10), {"R1.R": 100.0}, seed=0)
    behaviour = EndpointBehaviour.from_spectrum(data)
    assert behaviour.low_band[0] <= 0.0 <= behaviour.low_band[1]
    assert behaviour.high_band[0] <= 0.0 <= behaviour.high_band[1]


def test_from_spectrum_with_fewer_than_five_points_disables_the_filter() -> None:
    data = simulate("R1", log_frequencies(1e0, 1e2, 1), {"R1.R": 100.0}, seed=0)
    assert data.n < 5  # sanity check on the fixture itself
    behaviour = EndpointBehaviour.from_spectrum(data)
    assert behaviour.low_band == (-math.inf, math.inf)
    assert behaviour.high_band == (-math.inf, math.inf)
    assert behaviour.active is False


# =============================================================================================
# 5. Gate G3 -- conservativeness: the truth and its known exact equivalents must always survive
# =============================================================================================


@dataclass(frozen=True)
class _GateCase:
    """One reference topology plus the size-matched topologies known to fit it identically.

    ``equivalents`` were measured by fitting every same-size topology to noise-free data and
    keeping those that matched to 1e-9, so this really is "the truth and its known equivalents",
    not a guess.
    """

    truth: str
    params: dict[str, float]
    f_min: float
    f_max: float
    equivalents: tuple[str, ...]


_GATE_CASES = [
    _GateCase(
        "R1-p(R2,C1)",
        {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8},
        1e0,
        1e7,
        ("p(R1-C1,R2)",),
    ),
    _GateCase(
        "C1-R1-L1",
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        1e2,
        1e9,
        (),
    ),
    _GateCase(
        "p(R1,C1)-p(R2,C2)",
        {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8},
        1e-1,
        1e7,
        ("p(R1-C1,R2,C2)", "p(p(R1,C1)-C2,R2)", "p(p(R1,C1)-R2,C2)"),
    ),
    _GateCase(
        "C1-R1-L1-SKINF1",
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
        1e2,
        1e9,
        (),
    ),
    _GateCase(
        "R1-p(C1,R2-W1)",
        {"R1.R": 20.0, "C1.C": 1e-5, "R2.R": 200.0, "W1.A": 50.0},
        1e-2,
        1e5,
        (),
    ),
]


@pytest.mark.parametrize("budget", [DEFAULT_DEGENERACY_BUDGET, 0])
@pytest.mark.parametrize("noise", [0.0, 0.01])
@pytest.mark.parametrize("case", _GATE_CASES, ids=lambda c: c.truth)
def test_gate_g3_feasibility_never_excludes_truth_or_equivalents(
    case: _GateCase, noise: float, budget: int
) -> None:
    f = log_frequencies(case.f_min, case.f_max, 10)
    data = simulate(case.truth, f, case.params, noise=noise, seed=0)
    behaviour = EndpointBehaviour.from_spectrum(data)
    for text in (case.truth, *case.equivalents):
        node = Circuit.parse(text).root
        assert is_feasible(node, behaviour, budget=budget), (
            f"{text!r} (truth={case.truth!r}, noise={noise}, budget={budget}) was marked "
            f"infeasible; {behaviour.describe()}"
        )


# =============================================================================================
# 6. The filter is not a no-op, and it only ever removes
# =============================================================================================


def test_feasibility_filter_only_removes_and_is_not_a_noop() -> None:
    # "The capacitor reference": case (d), C1-R1-L1-SKINF1.
    case = _GATE_CASES[3]
    f = log_frequencies(case.f_min, case.f_max, 10)
    data = simulate(case.truth, f, case.params, noise=0.0, seed=0)
    behaviour = EndpointBehaviour.from_spectrum(data)
    pool = ("R", "C", "L", "CPE", "SKINF")

    total_all = 0
    total_kept = 0
    for n in range(1, 5):
        all_forms = {canonical_form(node) for node in enumerate_topologies(pool, n)}
        kept_forms = {
            canonical_form(node)
            for node in feasible_topologies(enumerate_topologies(pool, n), behaviour)
        }
        assert kept_forms <= all_forms, f"n={n}: filter kept a topology enumeration never gave"
        total_all += len(all_forms)
        total_kept += len(kept_forms)

    assert total_kept < total_all, "filter removed nothing at all across n=1..4"


# =============================================================================================
# 7. An uninformative spectrum disables the filter
# =============================================================================================


def test_uninformative_behaviour_keeps_everything() -> None:
    behaviour = EndpointBehaviour((-math.inf, math.inf), (-math.inf, math.inf), math.nan, math.nan)
    assert behaviour.active is False
    pool = ("R", "C", "L", "CPE")
    for n in range(1, 4):
        for node in enumerate_topologies(pool, n):
            assert is_feasible(node, behaviour)
