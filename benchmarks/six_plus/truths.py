"""The pre-registered truth set for experiments above five elements.

Every frozen arena in this repository carries the **same** truth,
``p(R1,C1)-p(R2,C2)-p(R3,C3)``, and ``docs/SEARCH_ALGORITHM_SCREENING.md`` section 3.5.2 records
what that cost: a mutation sweep's strongest arm turned out to be winning by moving weight toward
parallel insertion *on a truth that is three parallel blocks*, and losing by the same margin on a
series-shaped one. A prior tuned on one truth's shape is not a search improvement; it is the
answer written into the question. This module fixes that by defining nine truths -- three shapes
crossed with three sizes -- before any arm is run.

**Shape is asserted at import time, not by eye.** :func:`shape_of` reads it off the parsed tree:

* ``parallel`` -- fewer than half the elements have a :class:`~autocircuit.core.circuit.Series`
  node as their parent, so most of the circuit lives inside parallel blocks;
* ``series`` -- more than half do;
* ``mixed`` -- a parallel node nested inside another parallel node, which neither of the other
  two shapes has. Checked first, because it is a statement about depth rather than about counts
  and a circuit can satisfy it while also being series- or parallel-heavy.

**Why three sizes and not two.** The five-element row is the negative control that
``docs/TOPOLOGY_6PLUS_PLAN.md`` section 4.7 requires: a method that always grows to six elements
would score perfectly on recovery and be worthless, and nothing measured in this repository so
far would catch it. Scoring on ``*5`` truths is how that is caught.

**Why the pool is R, C, L and nothing else.** ``TOPOLOGY_6PLUS_PLAN.md`` section 5.2 measures
separately what adding CPE does to identifiability -- it cuts the evidence for a sixth element
from 2.74x to 1.29x on the same truth and the same data. Mixing CPE into this set would confound
shape with pool, and the R,C,L spaces are the ones already enumerated
(``land_rcl6.json``, ``land_rcl7.json``).

Every truth here passes a **four**-part admission screen at the noise it will be used at: the
three parts of ``benchmarks/autoeis_round/arena.py`` -- per-parameter leverage above the noise,
no unresolved parameter when the truth is fitted to its own data, and a value-matched deviation
under 50% -- plus a fourth added here, that the search's own structural pre-filter does not
delete the truth before any fitting (:func:`survives_feasibility`). That requirement was written
down before the screen was run, and it is not a formality:

**[measured] the incumbent's own parameters fail it.** ``p(R1,C1)-p(R2,C2)-p(R3,C3)`` with the
values in ``benchmarks/screening_round/landscape.py`` -- the truth behind ``land_rcl6.json``,
``land_rcl7.json`` and ``land_rclcpe6.json``, and behind ``LARGE_REFERENCES[0]`` -- has ``C3.C``
at 0.700% leverage against 1% noise, i.e. a 10% change in that capacitance moves the spectrum by
less than the noise on it. Its second and third time constants are 1e-2 s and 4e-2 s, only 0.6
decades apart, and its second block's 500 kOhm swamps the third's 80 kOhm. So ``par6`` here keeps
the incumbent's *circuit* and not its *values*: the three blocks are given equal resistances and
time constants 2.5 decades apart. The incumbent is preserved verbatim as
:data:`INCUMBENT_PAR6` so the existing arenas stay describable, and it is marked as failing.
See ``docs/TOPOLOGY_6PLUS_PLAN.md`` section 5.3, where the same is measured for all three
``LARGE_REFERENCES``.

**The values below were not chosen by hand, and the first attempt to choose them by hand is why.**
Five of the nine first guesses failed the screen -- ``mix5`` at 0.023% leverage, ``mix7`` at
0.022%, ``mix6`` at 0.025%, ``ser6`` and ``ser7`` at 0.99% -- each for a reason that is obvious
only afterwards: a shunt capacitor two decades larger than the one it shunts hides it completely,
and a 0.5 Ohm resistance inside a block swamps a 0.05 Ohm ESR in series with it. So the values
come from :func:`tune`, which maximises the truth's **weakest** leverage. See :data:`ADJUSTMENTS`
for what moved and what it was.

Two consequences of tuning that are stated rather than left to be discovered:

* **The tuner picks the most identifiable member of each topology's parameter family.** That is
  the right control and not a flattering one: a search that fails on the most identifiable
  instance of a topology is failing at finding the topology, which is what these experiments are
  about.
* **It optimises identifiability and nothing else, so some values are not physically typical** --
  ``ser7``'s 1.2 mF and 2 mH put its internal resonance at the bottom of the window. These are
  instruments for measuring a search, not models of real parts; realism is what
  ``benchmarks/discovery_v2.py``'s references are for.

Two truths had their *circuit* changed as well, not just their values. ``ser6`` and ``ser7``
were first written as ``C1-R1-L1-p(R2,C2-R3)`` and ``C1-R1-L1-p(R2,C2-R3-L2)``, and on those the
tuner's answer was an exact symmetry: ``R1 = R3`` to six digits, at 5.000% leverage each. That is
the maximum available, because at high frequency ``C2`` shorts and the data sees only the sum
``R1 + R3`` -- so the optimum is to split it evenly, and the two resistances are then maximally
confusable with each other. Rather than ship a truth whose hardest feature is an artefact of the
tuner sitting on a saddle, the inner resistor was replaced by an inductor, which resonates with
``C2`` instead of adding to ``R1``. Both now tune to 9.9%.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/truths.py --check
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

import numpy as np
from scipy.optimize import differential_evolution

_BENCH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BENCH_DIR))
sys.path.insert(0, str(_BENCH_DIR / "autoeis_round"))

from deviation import worst_deviation  # noqa: E402

from autocircuit.core.circuit import Circuit, ElementNode, Node, Parallel, Series  # noqa: E402
from autocircuit.core.enumerate import EndpointBehaviour, is_feasible  # noqa: E402
from autocircuit.core.fit import fit  # noqa: E402
from autocircuit.core.simulate import log_frequencies, simulate  # noqa: E402
from autocircuit.core.spectrum import Spectrum  # noqa: E402
from autocircuit.core.stats import unresolved_mask  # noqa: E402

Shape = Literal["parallel", "series", "mixed"]

#: Proportional noise the whole set is screened and used at.
NOISE: float = 0.01

#: Relative parameter bump used by the leverage screen, matching ``arena.LEVERAGE_STEP``.
LEVERAGE_STEP: float = 0.10

#: Largest value-matched parameter deviation a truth may show when fitted to its own noisy data,
#: matching ``arena.MAX_DEVIATION``.
MAX_DEVIATION: float = 0.5

#: Seeds the screen fits at. One seed's deviation is a lottery for a marginal parameter
#: (``docs/AUTOEIS_COMPARISON.md``), so the screen is run on three and the worst one counts.
SCREEN_SEEDS: tuple[int, ...] = (0, 1, 2)


# =============================================================================================
# Shape, read off the tree rather than asserted
# =============================================================================================


def _series_parented(node: Node, parent: Node | None = None) -> tuple[int, int]:
    """(elements whose parent is a Series node, total elements) over the whole tree."""
    if isinstance(node, ElementNode):
        return (1 if isinstance(parent, Series) else 0, 1)
    series_count = 0
    total = 0
    for child in node.children:
        got, seen = _series_parented(child, node)
        series_count += got
        total += seen
    return series_count, total


def _parallel_inside_parallel(node: Node, inside: bool = False) -> bool:
    """True when some Parallel node has another Parallel node among its descendants."""
    if isinstance(node, ElementNode):
        return False
    if isinstance(node, Parallel):
        if inside:
            return True
        return any(_parallel_inside_parallel(child, True) for child in node.children)
    return any(_parallel_inside_parallel(child, inside) for child in node.children)


def shape_of(circuit: str) -> Shape:
    """Classify a circuit's shape from its parsed tree. See the module docstring."""
    root = Circuit.parse(circuit).root
    if _parallel_inside_parallel(root):
        return "mixed"
    in_series, total = _series_parented(root)
    return "series" if in_series * 2 > total else "parallel"


# =============================================================================================
# The truths
# =============================================================================================


@dataclass(frozen=True)
class Truth:
    """One pre-registered ground-truth circuit and the sweep it is measured over."""

    id: str
    shape: Shape
    circuit: str
    params: dict[str, float]
    f_min: float
    f_max: float
    pool: tuple[str, ...] = ("R", "C", "L")
    points_per_decade: int = 10

    @property
    def n_elements(self) -> int:
        return len(Circuit.parse(self.circuit).leaves)

    @property
    def frequencies(self) -> np.ndarray:
        return log_frequencies(self.f_min, self.f_max, self.points_per_decade)

    def time_constants(self) -> dict[str, float]:
        """R*C products for every (R, C) pair sharing a parallel node -- the relaxations.

        Keyed on the *label* (``R1``) rather than the element code (``R``), because a parameter
        name is ``label.field``: keying on the code produced ``R.R`` and a ``KeyError`` the
        first time this ran on a truth whose blocks were not the first two elements.
        """
        out: dict[str, float] = {}
        root = Circuit.parse(self.circuit).root
        for node in _walk(root):
            if not isinstance(node, Parallel):
                continue
            labels = [
                child.label for child in node.children if isinstance(child, ElementNode)
            ]
            resistors = [name for name in labels if name.startswith("R")]
            capacitors = [name for name in labels if name.startswith("C")]
            if resistors and capacitors:
                r, c = resistors[0], capacitors[0]
                out[f"{r}*{c}"] = self.params[f"{r}.R"] * self.params[f"{c}.C"]
        return out


def _walk(node: Node) -> list[Node]:
    if isinstance(node, ElementNode):
        return [node]
    out: list[Node] = [node]
    for child in node.children:
        out.extend(_walk(child))
    return out


#: The three electrochemical-style windows and the one component-style window used below.
#: Truths built from R and C alone live at 1e-2..1e7 Hz; anything containing an inductor needs a
#: window where omega*L is comparable to the resistances, which for realistic inductances means
#: the component window 1e2..1e9 Hz that the capacitor reference already uses.
EC_WINDOW = (1e-2, 1e7)
COMPONENT_WINDOW = (1e2, 1e9)


TRUTHS: tuple[Truth, ...] = (
    # -- five elements: the negative control -------------------------------------------------
    Truth(
        "par5",
        "parallel",
        "R1-p(R2,C1)-p(R3,C2)",
        {
            "R1.R": 2.30045,
            "R2.R": 928750,
            "C1.C": 7.22101e-06,
            "R3.R": 2039.07,
            "C2.C": 1.47902e-08,
        },
        *EC_WINDOW,
    ),
    Truth(
        "ser5",
        "series",
        "C1-R1-L1-p(R2,C2)",
        {
            "C1.C": 5.87331e-09,
            "R1.R": 0.661393,
            "L1.L": 2.81627e-07,
            "R2.R": 338549,
            "C2.C": 9.13317e-11,
        },
        *COMPONENT_WINDOW,
    ),
    Truth(
        "mix5",
        "mixed",
        "p(p(R1,C1)-R2,C2)-R3",
        {
            "R1.R": 20849.3,
            "C1.C": 0.00032273,
            "R2.R": 22.8605,
            "C2.C": 6.98138e-07,
            "R3.R": 0.0487194,
        },
        *EC_WINDOW,
    ),
    # -- six elements ------------------------------------------------------------------------
    Truth(
        "par6",
        "parallel",
        "p(R1,C1)-p(R2,C2)-p(R3,C3)",
        {
            "R1.R": 0.169308,
            "C1.C": 6.65808e-07,
            "R2.R": 27.2317,
            "C2.C": 4.15439e-05,
            "R3.R": 2146.47,
            "C3.C": 0.00329069,
        },
        *EC_WINDOW,
    ),
    Truth(
        "ser6",
        "series",
        "C1-R1-L1-p(R2,C2-L2)",
        {
            "C1.C": 2.74924e-09,
            "R1.R": 0.0183861,
            "L1.L": 1.46941e-11,
            "R2.R": 2.33075,
            "C2.C": 8.9913e-12,
            "L2.L": 4.46528e-09,
        },
        *COMPONENT_WINDOW,
    ),
    Truth(
        "mix6",
        "mixed",
        "p(p(R1,C1)-R2,C2)-p(R3,C3)",
        {
            "R1.R": 98441.7,
            "C1.C": 7.17682e-05,
            "R2.R": 7.60531,
            "C2.C": 1.4874e-08,
            "R3.R": 1238.36,
            "C3.C": 9.14767e-07,
        },
        *EC_WINDOW,
    ),
    # -- seven elements ----------------------------------------------------------------------
    Truth(
        "par7",
        "parallel",
        "R4-p(R1,C1)-p(R2,C2)-p(R3,C3)",
        {
            "R4.R": 0.0354496,
            "R1.R": 6529.75,
            "C1.C": 0.00115468,
            "R2.R": 2.54735,
            "C2.C": 7.97986e-07,
            "R3.R": 178.316,
            "C3.C": 2.98962e-05,
        },
        *EC_WINDOW,
    ),
    Truth(
        "ser7",
        "series",
        "C1-R1-L1-p(R2,C2-L2,C3)",
        {
            "C1.C": 0.00111987,
            "R1.R": 0.0114162,
            "L1.L": 3.17009e-11,
            "R2.R": 208.701,
            "C2.C": 0.00116799,
            "L2.L": 0.00200194,
            "C3.C": 3.17902e-07,
        },
        *COMPONENT_WINDOW,
    ),
    Truth(
        "mix7",
        "mixed",
        "p(p(R1,C1)-R2,C2)-p(R3,C3)-R4",
        {
            "R1.R": 931830,
            "C1.C": 8.32173e-06,
            "R2.R": 12572.3,
            "C2.C": 2.34361e-07,
            "R3.R": 331.595,
            "C3.C": 6.25244e-09,
            "R4.R": 4.5377,
        },
        *EC_WINDOW,
    ),
)

#: The incumbent, kept verbatim and **not** part of the pre-registered set: its ``C3.C`` sits at
#: 0.700% leverage against 1% noise. It is here so that a run can reproduce what the existing
#: arenas were built on, and so that the difference between "the truth was not found" and "the
#: truth was not in the data" can be measured on the same circuit rather than argued about.
INCUMBENT_PAR6 = Truth(
    "par6_incumbent",
    "parallel",
    "p(R1,C1)-p(R2,C2)-p(R3,C3)",
    {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8, "R3.R": 8e4, "C3.C": 5e-7},
    *EC_WINDOW,
)

BY_ID: dict[str, Truth] = {t.id: t for t in (*TRUTHS, INCUMBENT_PAR6)}

#: What had to move from the first guess, and why. A truth that needed no adjustment is absent
#: rather than listed as "none". Every entry here is a measured failure of a hand-picked value,
#: kept so that the next person to add a truth does not repeat it.
ADJUSTMENTS: dict[str, str] = {
    "par5": "hand-picked values passed at 2.93% weakest leverage; re-tuned to 9.05%",
    "ser5": "hand-picked values (landscape.py's own `series` reference) passed the first three "
            "parts at 8.19%. The first *tuned* set then failed the fourth: the search's own "
            "feasibility filter deleted it, because the tuner had put the inductive asymptote "
            "above the top of the window and the measured high-frequency slope reads -1.15 "
            "against a reachable band of (0, +1). Tuner seed 1 passes all four at 9.68%.",
    "mix5": "FAILED by hand at C1.C = 0.023%: a C2 two decades larger than C1 shunts the inner "
            "block away entirely. Re-tuned to 9.05%.",
    "par6": "hand-picked values passed at 1.88%; re-tuned to 8.87%. The *incumbent* values fail "
            "at C3.C = 0.700% -- see INCUMBENT_PAR6 and TOPOLOGY_6PLUS_PLAN.md section 5.3.",
    "ser6": "FAILED by hand at R1.R = 0.99%: a 0.5 Ohm resistor inside the block swamps a "
            "0.05 Ohm ESR in series with it. The circuit changed too, C2-R3 -> C2-L2, because "
            "on the original the tuner's optimum was the exact symmetry R1 = R3 at 5.000% -- "
            "the maximum available, since at high frequency C2 shorts and only R1 + R3 is in "
            "the data. Needed tuner seed 3 to pass the feasibility part. 9.85%.",
    "mix6": "FAILED by hand at C1.C = 0.025%, the same shunt as mix5. Re-tuned to 8.87%.",
    "par7": "hand-picked values passed at 1.81%; re-tuned to 8.63%",
    "ser7": "FAILED by hand at R1.R = 0.99%, and the circuit changed for the same symmetry as "
            "ser6. Re-tuned to 10.00%.",
    "mix7": "FAILED by hand at C1.C = 0.022%, the same shunt as mix5. Re-tuned to 8.64%.",
}


# Shape and size are asserted at import time, so a mislabelled truth cannot be used.
for _truth in TRUTHS:
    _seen = shape_of(_truth.circuit)
    if _seen != _truth.shape:
        raise AssertionError(f"{_truth.id}: labelled {_truth.shape!r} but the tree says {_seen!r}")
    _expected_size = int(_truth.id[-1])
    if _truth.n_elements != _expected_size:
        raise AssertionError(
            f"{_truth.id}: id says {_expected_size} elements, circuit has {_truth.n_elements}"
        )


def spectrum_for(truth: Truth, *, noise: float = NOISE, seed: int | None = 0) -> Spectrum:
    """The one place a spectrum is built from a truth, so every experiment builds the same data."""
    return simulate(truth.circuit, truth.frequencies, truth.params, noise=noise, seed=seed)


# =============================================================================================
# The identifiability screen
# =============================================================================================


def parameter_leverage(truth: Truth) -> dict[str, float]:
    """Per-parameter leverage: the largest relative change in Z a 10% change in it produces.

    The same instrument as ``benchmarks/autoeis_round/arena.py``, reimplemented here only because
    that one reads its window and noise from module-level constants and this set uses two
    different windows. Below the noise level, the data does not contain the parameter --
    ``docs/AUTOEIS_COMPARISON.md`` records that this direct question is what worked after two
    versions built on standard errors let through truths nothing could recover.
    """
    circuit = Circuit.parse(truth.circuit)
    frequencies = truth.frequencies
    base = simulate(circuit, frequencies, truth.params).z
    scale = np.abs(base)
    out: dict[str, float] = {}
    for name, value in truth.params.items():
        bumped = dict(truth.params)
        bumped[name] = value * (1.0 + LEVERAGE_STEP)
        moved = simulate(circuit, frequencies, bumped).z
        out[name] = float(np.max(np.abs(moved - base) / scale))
    return out


@dataclass(frozen=True)
class ScreenVerdict:
    """What the four-part screen says about one truth."""

    truth_id: str
    leverage: dict[str, float]
    min_leverage: float
    n_below_noise: int
    n_unresolved: int
    worst_deviation: float
    feasible: bool
    passed: bool

    def row(self) -> str:
        weakest = min(self.leverage, key=lambda k: self.leverage[k])
        mark = "pass" if self.passed else "FAIL"
        return (
            f"| {self.truth_id} | {mark} | {weakest} {self.min_leverage * 100:.3f}% | "
            f"{self.n_below_noise} | {self.n_unresolved} | {self.worst_deviation * 100:.1f}% | "
            f"{'yes' if self.feasible else 'NO'} |"
        )


def survives_feasibility(truth: Truth, *, noise: float = NOISE, seed: int = 1) -> bool:
    """Does the search's own structural pre-filter keep this truth, or delete it?

    **The fourth part, added after it caught a truth the other three passed.** [measured] The
    first tuned ``ser5``, ``C1-R1-L1-p(R2,C2)``, passed leverage at 9.09%, fitted its own data
    to 0.7% and was then **deleted before any fitting** by
    :func:`~autocircuit.core.enumerate.is_feasible` at the default degeneracy budget of 1 -- so
    a search on that spectrum could not have found it however good the search was.

    The mechanism is worth stating because it is not a bug in the filter so much as an
    assumption in it. The filter compares the model's *asymptotic* endpoint exponents against
    the *measured* edge slope. That truth's inductive asymptote lies above the top of its own
    frequency window -- at 1 GHz the shunt capacitance is still falling faster than the series
    inductance is rising -- so the measured high-frequency slope is -1.15 where the truth's
    reachable band is (0, +1), and the filter concludes, correctly on its own terms, that the
    two cannot be reconciled. It survives at ``budget=2``.

    Two things follow and both are recorded rather than fixed here. For this module: a truth the
    pipeline's own filter removes cannot measure the search, so it is not admitted. For the
    library: **the filter assumes the window reaches the asymptote**, and gate G3 of
    ``docs/DISCOVERY_V2_PLAN.md`` was measured on references whose windows do. A real spectrum
    that stops short of its own asymptote is in exactly this position, silently.
    """
    spectrum = spectrum_for(truth, noise=noise, seed=seed)
    node = Circuit.parse(truth.circuit).root
    return bool(is_feasible(node, EndpointBehaviour.from_spectrum(spectrum)))


def screen(truth: Truth, *, noise: float = NOISE) -> ScreenVerdict:
    """Run all four parts. Leverage first, because it costs no fit and rejects most bad draws."""
    leverage = parameter_leverage(truth)
    below = sum(1 for v in leverage.values() if v < noise)
    feasible = survives_feasibility(truth, noise=noise)

    worst_dev = 0.0
    unresolved = 0
    for seed in SCREEN_SEEDS:
        result = fit(truth.circuit, spectrum_for(truth, noise=noise, seed=seed), seed=seed)
        unresolved = max(
            unresolved,
            int(np.count_nonzero(unresolved_mask(result.values, result.statistics.stderr))),
        )
        worst_dev = max(worst_dev, float(worst_deviation(result.params, truth.params)))

    return ScreenVerdict(
        truth_id=truth.id,
        leverage=leverage,
        min_leverage=min(leverage.values()),
        n_below_noise=below,
        n_unresolved=unresolved,
        worst_deviation=worst_dev,
        feasible=feasible,
        passed=(
            below == 0
            and unresolved == 0
            and worst_dev <= MAX_DEVIATION
            and feasible
        ),
    )


def check(truths: Sequence[Truth], *, noise: float = NOISE) -> list[ScreenVerdict]:
    verdicts = [screen(t, noise=noise) for t in truths]
    print(
        "| truth | verdict | weakest parameter | below noise | unresolved | worst deviation "
        "| survives the feasibility filter |"
    )
    print("|---|---|---|---:|---:|---:|---|")
    for verdict in verdicts:
        print(verdict.row())
    print()
    for truth, verdict in zip(truths, verdicts, strict=True):
        taus = truth.time_constants()
        tau_text = ", ".join(f"{k}={v:.3g}s" for k, v in taus.items()) or "(no R||C pair)"
        print(f"{truth.id:15s} {truth.shape:8s} {truth.circuit}")
        print(f"    relaxations: {tau_text}")
        for name, value in sorted(verdict.leverage.items(), key=lambda kv: kv[1]):
            flag = "   <-- BELOW NOISE" if value < noise else ""
            print(f"      {name:12s} {value * 100:9.3f}%{flag}")
    return verdicts


# =============================================================================================
# Choosing the values, by measurement rather than by eye
# =============================================================================================

#: Search ranges for the tuner, per element field. Wide enough to move a relaxation across the
#: whole window, narrow enough to stay physical.
TUNE_RANGES: dict[str, tuple[float, float]] = {
    "R": (1e-2, 1e6),
    "C": (1e-12, 1e-2),
    "L": (1e-12, 1e-2),
}


def _min_leverage(circuit: str, frequencies: np.ndarray, values: dict[str, float]) -> float:
    parsed = Circuit.parse(circuit)
    base = simulate(parsed, frequencies, values).z
    scale = np.abs(base)
    if not np.all(np.isfinite(base)) or np.any(scale == 0.0):
        return -1.0
    worst = np.inf
    for name, value in values.items():
        bumped = dict(values)
        bumped[name] = value * (1.0 + LEVERAGE_STEP)
        moved = simulate(parsed, frequencies, bumped).z
        if not np.all(np.isfinite(moved)):
            return -1.0
        worst = min(worst, float(np.max(np.abs(moved - base) / scale)))
    return worst


def tune(truth: Truth, *, seed: int = 0, maxiter: int = 300) -> tuple[dict[str, float], float]:
    """Pick parameter values that maximise the truth's *weakest* leverage.

    Hand-picking values does not scale past a couple of circuits and it picked badly here: the
    first guesses for ``mix5``, ``mix6``, ``ser6``, ``ser7`` and ``mix7`` all failed the screen,
    one of them at 0.022% leverage against 1% noise, because a shunt capacitor two decades larger
    than the one it shunts hides it completely. Maximising the minimum leverage states the
    requirement directly instead: **every parameter must move the spectrum by more than the noise
    on it.**

    This deliberately picks the *most identifiable* member of each topology's parameter family.
    That is the right control rather than a flattering one -- a search that fails on the most
    identifiable instance of a topology is failing at finding the topology, which is what these
    experiments are about, and ``docs/TOPOLOGY_6PLUS_PLAN.md`` section 5.3 is what happens when
    nobody checks.
    """
    parsed = Circuit.parse(truth.circuit)
    names = list(parsed.param_names)
    frequencies = truth.frequencies

    bounds: list[tuple[float, float]] = []
    for name in names:
        field = name.split(".")[-1]
        low, high = TUNE_RANGES.get(field, (1e-3, 1e3))
        bounds.append((math.log10(low), math.log10(high)))

    def objective(x: np.ndarray) -> float:
        values = {name: float(10.0 ** xi) for name, xi in zip(names, x, strict=True)}
        return -_min_leverage(truth.circuit, frequencies, values)

    result = differential_evolution(
        objective, bounds, seed=seed, maxiter=maxiter, popsize=20, tol=1e-8, polish=True
    )
    values = {name: float(10.0 ** xi) for name, xi in zip(names, result.x, strict=True)}
    return values, -float(result.fun)


def tune_until_screened(
    truth: Truth, *, seeds: Sequence[int] = (0, 1, 2, 3, 4), noise: float = NOISE
) -> tuple[dict[str, float], float, int]:
    """Tune, then *check*, and keep tuning until a candidate passes all three parts.

    **Maximising leverage is not enough, and ``ser6`` is why.** [measured] Its first tuned set
    scored 9.903% on the weakest parameter -- comfortably above the 1% noise -- and then failed
    the fit outright: one unresolved parameter and a 4379% value-matched deviation. The tuner had
    driven ``R2`` to 296 kOhm, which opens the parallel branch, and the circuit
    ``C1-R1-L1-p(R2,C2-L2)`` then collapses to a plain series R-C-L with the two capacitances and
    the two inductances determined only by their series combinations. Every parameter still moves
    the spectrum on its own, which is all leverage asks; no fit can separate them, which is what
    the other two parts ask.

    So leverage is a necessary condition and a cheap one -- it costs no fit and rejects most bad
    draws -- but a truth is admitted only once :func:`screen` has agreed on all three. This is the
    same lesson ``docs/AUTOEIS_COMPARISON.md`` records from the opposite direction: there the
    standard-error test passed truths nothing could recover and leverage was the fix, here
    leverage passes one and the fit is the fix. Neither part subsumes the other.

    Returns ``(values, weakest leverage, seed that passed)``; raises if no seed passes, rather
    than returning the least bad, because a truth that cannot be made identifiable needs its
    *topology* reconsidered and silently shipping the best failure would hide that.
    """
    attempts: list[tuple[dict[str, float], float, int]] = []
    for seed in seeds:
        values, worst = tune(truth, seed=seed)
        candidate = replace(truth, params=values)
        verdict = screen(candidate, noise=noise)
        attempts.append((values, worst, seed))
        if verdict.passed:
            return values, worst, seed
    detail = ", ".join(f"seed {s}: weakest {w * 100:.3f}%" for _v, w, s in attempts)
    raise RuntimeError(
        f"{truth.id}: no tuned parameter set passed the three-part screen ({detail}). "
        "Reconsider the topology rather than the values."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="run the identifiability screen")
    parser.add_argument(
        "--tune",
        action="store_true",
        help="search for parameter values maximising the weakest leverage, and print them",
    )
    parser.add_argument(
        "--incumbent",
        action="store_true",
        help="include the incumbent par6 values, which are expected to FAIL",
    )
    parser.add_argument("--noise", type=float, default=NOISE)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    selected = list(TRUTHS) + ([INCUMBENT_PAR6] if args.incumbent else [])

    if args.tune:
        for truth in selected:
            values, worst, used = tune_until_screened(truth, noise=args.noise)
            print(f"# {truth.id}: weakest leverage {worst * 100:.3f}% (tuner seed {used})")
            print(f'        "{truth.circuit}",')
            print("        {")
            for name, value in values.items():
                print(f'            "{name}": {value:.6g},')
            print("        },")
        return

    if not args.check:
        for truth in selected:
            print(f"{truth.id:15s} {truth.shape:8s} {truth.n_elements} el  {truth.circuit}")
        return

    verdicts = check(selected, noise=args.noise)
    failed = [v.truth_id for v in verdicts if not v.passed]
    print()
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    else:
        print("All truths pass the three-part screen.")

    if args.out is not None:
        payload: list[dict[str, Any]] = [
            {
                "truth_id": v.truth_id,
                "leverage": v.leverage,
                "min_leverage": v.min_leverage,
                "n_below_noise": v.n_below_noise,
                "n_unresolved": v.n_unresolved,
                "worst_deviation": v.worst_deviation,
                "feasible": v.feasible,
                "passed": v.passed,
            }
            for v in verdicts
        ]
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
