"""Additional truths for the non-hardware speedup experiments (docs/SEARCH_SPEEDUP_PLAN.md).

The nine truths in ``benchmarks/six_plus/truths.py`` top out at four series Maxwell-Wagner
blocks (``par8`` in ``benchmarks/six_plus/depth8.py``, 8 elements) and at two inductors that were
never characterised as producing two *separate* resonant peaks. Two gaps the user asked this round
to close specifically:

* **more than four series Maxwell-Wagner blocks** -- ``mw5`` (5 blocks, 10 elements) and ``mw6``
  (6 blocks, 12 elements) here, plus ``mw4cpe`` (four blocks, two of them CPE instead of an ideal
  capacitor, since a real dielectric relaxation is rarely an ideal ``p(R,C)``);
* **more than one self-resonant frequency** -- ``srf2`` and ``srf3``, chained parallel-tank blocks
  ``p(C,R-L)`` (a lone shunt capacitor across a series R-L branch, resonating at
  ``1/sqrt(LC)``), tuned so the resonant frequencies sit two decades apart and well inside the
  sweep -- not at its edge, which is the already-documented, different failure mode in
  ``docs/TOPOLOGY_6PLUS_PLAN.md`` (d).

Every truth here is admitted through the *same* four-part screen as ``six_plus/truths.py``
(leverage, feasibility, zero unresolved parameters, <=50% value-matched deviation) via that
module's own :func:`screen`/:func:`tune_until_screened`, reused rather than re-implemented. The
only reason this module cannot just call ``six_plus.truths.tune_until_screened`` unmodified is
that its ``TUNE_RANGES`` has no entry for a CPE's ``Q``/``n`` fields; :data:`TUNE_RANGES` below
extends it, and :func:`tune` / :func:`tune_until_screened` are local copies of the six_plus
versions parameterised on that wider range dict (duplicated rather than monkeypatching the
imported module's globals, which would leak into anything else importing it in the same process).

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/speedup/truths.py --check
    python benchmarks/speedup/truths.py --tune
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import differential_evolution

_BENCH_DIR = Path(__file__).resolve().parent.parent

# Loaded via importlib under a name distinct from this module's own ("truths" would collide:
# any script that does `from truths import ...` after adding both benchmarks/speedup and
# benchmarks/six_plus to sys.path re-enters *this* partially-initialized module instead of
# six_plus's, because Python keys sys.modules by name, not by path. [measured] this broke every
# standalone script under benchmarks/speedup/ that imported this module -- see the fix note in
# docs/SEARCH_SPEEDUP_PLAN.md.
import importlib.util as _importlib_util  # noqa: E402

_spec = _importlib_util.spec_from_file_location(
    "six_plus_truths", _BENCH_DIR / "six_plus" / "truths.py"
)
assert _spec is not None and _spec.loader is not None
_six_plus_truths = _importlib_util.module_from_spec(_spec)
sys.modules.setdefault("six_plus_truths", _six_plus_truths)
_spec.loader.exec_module(_six_plus_truths)

COMPONENT_WINDOW = _six_plus_truths.COMPONENT_WINDOW
MAX_DEVIATION = _six_plus_truths.MAX_DEVIATION
NOISE = _six_plus_truths.NOISE
ScreenVerdict = _six_plus_truths.ScreenVerdict
Truth = _six_plus_truths.Truth
_min_leverage = _six_plus_truths._min_leverage
screen = _six_plus_truths.screen
spectrum_for = _six_plus_truths.spectrum_for

from autocircuit.core.circuit import Circuit  # noqa: E402

#: six_plus.truths.TUNE_RANGES plus CPE's two fields. CPE's ``Q`` plays the same role a
#: capacitance does (``Z = 1/(Q*(jw)^n)``), so it gets C's range; ``n`` is restricted to
#: [0.5, 1.0] rather than the element's full [0.02, 1.0] to keep every block visibly
#: capacitor-like (a CPE near n=0 is closer to a resistor, which is a different experiment).
TUNE_RANGES: dict[str, tuple[float, float]] = {
    "R": (1e-2, 1e6),
    "C": (1e-12, 1e-2),
    "L": (1e-12, 1e-2),
    "Q": (1e-12, 1e-2),
    "n": (0.5, 1.0),
}

#: Wider than six_plus's EC_WINDOW: five and six series relaxations need more decades of room
#: to keep their time constants separated than three do.
MW_WINDOW = (1e-3, 1e8)

#: srf2/srf3's resonant frequencies are placed two decades apart and at least 1.5 decades in
#: from each edge, so a resonance is never partially cut off by the sweep -- that edge-of-window
#: failure is the *different*, already-documented gap in TOPOLOGY_6PLUS_PLAN.md (d); this round
#: is about *multiple* resonances, not incomplete ones.
SRF_WINDOW = (1e1, 1e10)


def tune(
    truth: Truth,
    *,
    seed: int = 0,
    maxiter: int = 400,
    ranges: dict[str, tuple[float, float]] | None = None,
) -> tuple[dict[str, float], float]:
    """Local copy of ``six_plus.truths.tune``, parameterised on a wider range dict (adds CPE)."""
    ranges = ranges if ranges is not None else TUNE_RANGES
    parsed = Circuit.parse(truth.circuit)
    names = list(parsed.param_names)
    frequencies = truth.frequencies

    bounds: list[tuple[float, float]] = []
    for name in names:
        field = name.split(".")[-1]
        low, high = ranges.get(field, (1e-3, 1e3))
        bounds.append((math.log10(low), math.log10(high)))

    def objective(x: np.ndarray) -> float:
        values = {name: float(10.0**xi) for name, xi in zip(names, x, strict=True)}
        return -_min_leverage(truth.circuit, frequencies, values)

    result = differential_evolution(
        objective, bounds, seed=seed, maxiter=maxiter, popsize=24, tol=1e-8, polish=True
    )
    values = {name: float(10.0**xi) for name, xi in zip(names, result.x, strict=True)}
    return values, -float(result.fun)


def tune_until_screened(
    truth: Truth,
    *,
    seeds: Sequence[int] = (0, 1, 2, 3, 4, 5, 6, 7),
    noise: float = NOISE,
    ranges: dict[str, tuple[float, float]] | None = None,
) -> tuple[dict[str, float], float, int]:
    """Local copy of ``six_plus.truths.tune_until_screened`` against the wider range dict."""
    attempts: list[tuple[dict[str, float], float, int]] = []
    for seed in seeds:
        values, worst = tune(truth, seed=seed, ranges=ranges)
        candidate = replace(truth, params=values)
        verdict = screen(candidate, noise=noise)
        attempts.append((values, worst, seed))
        if verdict.passed:
            return values, worst, seed
    detail = ", ".join(f"seed {s}: weakest {w * 100:.3f}%" for _v, w, s in attempts)
    raise RuntimeError(
        f"{truth.id}: no tuned parameter set passed the four-part screen ({detail}). "
        "Reconsider the topology rather than the values."
    )


# =====================================================================================
# Topologies. Values are filled in by --tune (never hand-picked; see module docstring).
# =====================================================================================

#: weakest leverage 8.016% (tuner seed 0)
MW5 = Truth(
    "mw5",
    "parallel",
    "p(R1,C1)-p(R2,C2)-p(R3,C3)-p(R4,C4)-p(R5,C5)",
    {
        "R1.R": 3548.99,
        "C1.C": 0.000111886,
        "R2.R": 0.1434,
        "C2.C": 3.63701e-08,
        "R3.R": 54013.7,
        "C3.C": 0.00161326,
        "R4.R": 3.90177,
        "C4.C": 4.18043e-07,
        "R5.R": 116.254,
        "C5.C": 7.08379e-06,
    },
    *MW_WINDOW,
)

#: weakest leverage 7.275% (tuner seed 0)
MW6 = Truth(
    "mw6",
    "parallel",
    "p(R1,C1)-p(R2,C2)-p(R3,C3)-p(R4,C4)-p(R5,C5)-p(R6,C6)",
    {
        "R1.R": 195.825,
        "C1.C": 3.13977e-07,
        "R2.R": 366300,
        "C2.C": 0.000264907,
        "R3.R": 2715.36,
        "C3.C": 2.81815e-06,
        "R4.R": 42362.8,
        "C4.C": 3.11904e-05,
        "R5.R": 12.2245,
        "C5.C": 3.14013e-08,
        "R6.R": 0.834378,
        "C6.C": 4.72131e-09,
    },
    *MW_WINDOW,
)

#: weakest leverage 8.638% (tuner seed 5)
MW4CPE = Truth(
    "mw4cpe",
    "parallel",
    "p(R1,CPE1)-p(R2,C1)-p(R3,CPE2)-p(R4,C2)",
    {
        "R1.R": 10.2798,
        "CPE1.Q": 1.74346e-06,
        "CPE1.n": 0.999326,
        "R2.R": 837.469,
        "C1.C": 6.5944e-05,
        "R3.R": 0.134916,
        "CPE2.Q": 5.49612e-08,
        "CPE2.n": 0.999915,
        "R4.R": 31455,
        "C2.C": 0.00229951,
    },
    *MW_WINDOW,
)

#: weakest leverage 10.000% (seed 1). separation fixed at 3 decades (SRF_SEPARATION_DECADES);
#: absolute placement, rho and R all found by the same leverage-maximising tuner as every other
#: truth in this file (tune_srf) -- see that function's docstring for why f0 is not hand-fixed.
SRF2 = Truth(
    "srf2",
    "series",
    "p(C1,R1-L1)-p(C2,R2-L2)",
    {
        "L1.L": 0.161279,
        "C1.C": 2.56735e-09,
        "L2.L": 2.3155e-07,
        "C2.C": 1.78821e-09,
        "R1.R": 4841.92,
        "R2.R": 0.0923343,
    },
    *SRF_WINDOW,
)

#: weakest leverage 9.991% (seed 0). Same shape as SRF2, separation tightened to 1 decade.
SRF2_CLOSE = Truth(
    "srf2_close",
    "series",
    "p(C1,R1-L1)-p(C2,R2-L2)",
    {
        "L1.L": 2.49128e-05,
        "C1.C": 9.67787e-12,
        "L2.L": 1.27928e-08,
        "C2.C": 1.88468e-10,
        "R1.R": 47.3275,
        "R2.R": 0.0254194,
    },
    *SRF_WINDOW,
)

#: weakest leverage 9.940% (seed 0). separation fixed at 2 decades, everything else tuned.
SRF3 = Truth(
    "srf3",
    "series",
    "p(C1,R1-L1)-p(C2,R2-L2)-p(C3,R3-L3)",
    {
        "L1.L": 0.154942,
        "C1.C": 2.35984e-09,
        "L2.L": 1.55664e-06,
        "C2.C": 2.3489e-08,
        "L3.L": 1.30842e-09,
        "C3.C": 2.7945e-09,
        "R1.R": 583.969,
        "R2.R": 0.110988,
        "R3.R": 0.0391032,
    },
    *SRF_WINDOW,
)

#: weakest leverage 9.909% (seed 0). Same shape as SRF3, separation tightened to 1 decade.
SRF3_CLOSE = Truth(
    "srf3_close",
    "series",
    "p(C1,R1-L1)-p(C2,R2-L2)-p(C3,R3-L3)",
    {
        "L1.L": 0.0053688,
        "C1.C": 1.55619e-10,
        "L2.L": 1.15389e-05,
        "C2.C": 7.24061e-10,
        "L3.L": 1.48066e-07,
        "C3.C": 5.64268e-10,
        "R1.R": 621.531,
        "R2.R": 3.60268,
        "R3.R": 0.716069,
    },
    *SRF_WINDOW,
)

REGISTRY: dict[str, Truth] = {
    t.id: t for t in (MW5, MW6, MW4CPE, SRF2, SRF2_CLOSE, SRF3, SRF3_CLOSE)
}


#: The **only** deliberately fixed quantity for srf2/srf3: how many decades apart consecutive
#: resonances are, in units of the window's own span. This is the one thing this sub-experiment
#: is actually about (same role as ``six_plus/truths.py`` deliberately fixing "shape" while
#: tuning every value) -- everything else, *including where in the window the whole comb of
#: resonances sits*, is left to the same leverage-maximising tuner as every other parameter in
#: this file, via one extra free variable (``f0_first``) in :func:`tune_srf`. Fixing the absolute
#: frequencies by hand, as a first version of this file did, was arbitrary in exactly the sense
#: hand-picked R/C/L values are arbitrary elsewhere: the tuner's earlier attempt to place srf2's
#: high block on its own leverage judgement pushed it to 0.47 decades from the window's top edge,
#: and srf3's high block *past* it entirely -- so pure leverage-only placement is not safe either.
#: "_far" keeps >=2 decades between neighbours; "_close" tightens that to 1 decade. Not a full
#: grid (``docs/TOPOLOGY_6PLUS_PLAN.md``'s X2 does that at far larger scale) but enough that a
#: speedup idea's effect is checked at more than one separation before it is trusted.
SRF_SEPARATION_DECADES: dict[str, float] = {
    "srf2": 3.0,
    "srf2_close": 1.0,
    "srf3": 2.0,
    "srf3_close": 1.0,
}

#: Minimum decades kept between the outermost resonance and either edge of SRF_WINDOW.
SRF_EDGE_MARGIN_DECADES: float = 1.5


def _srf_blocks(circuit: str) -> list[tuple[str, str]]:
    """[(C-label, L-label), ...] in circuit order, e.g. [("1","1"), ("2","2")] for srf2."""
    import re

    return re.findall(r"C(\d+),R\d+-L(\d+)", circuit)


def tune_srf(
    truth: Truth, *, seed: int = 0, maxiter: int = 400
) -> tuple[dict[str, float], float]:
    """Tune srf2/srf3: fix the *spacing* between resonances at :data:`SRF_SEPARATION_DECADES`,
    search everything else -- where the comb sits in the window, each block's characteristic
    impedance ``rho=sqrt(L/C)`` (sets Q/bandwidth, not frequency), and each series R.

    For block ``i`` (0-indexed), ``f0_i = f0_first * 10**(i * separation)``. ``L = rho/(2*pi*f0)``,
    ``C = 1/(rho*2*pi*f0)`` place that block's resonance at exactly ``f0_i`` for any ``rho``.
    ``f0_first`` itself is a free search variable, bounded only so the *whole* comb still respects
    :data:`SRF_EDGE_MARGIN_DECADES` at both ends -- the tuner picks where in that range to put it.
    """
    blocks = _srf_blocks(truth.circuit)
    separation = SRF_SEPARATION_DECADES[truth.id]
    n = len(blocks)

    parsed = Circuit.parse(truth.circuit)
    r_names = [n_ for n_ in parsed.param_names if n_.split(".")[-1] == "R"]
    frequencies = truth.frequencies

    log_f_min, log_f_max = math.log10(truth.f_min), math.log10(truth.f_max)
    span = (n - 1) * separation
    f0_first_lo = log_f_min + SRF_EDGE_MARGIN_DECADES
    f0_first_hi = log_f_max - SRF_EDGE_MARGIN_DECADES - span
    if f0_first_hi <= f0_first_lo:
        raise ValueError(
            f"{truth.id}: separation {separation} decades leaves no room in the window"
        )

    # variables: [log10(f0_first), rho_1..rho_n (log10 ohms), R_1..R_n (log10 ohms)]
    bounds = (
        [(f0_first_lo, f0_first_hi)]
        + [(math.log10(1e-2), math.log10(1e4))] * n
        + [(math.log10(1e-2), math.log10(1e6))] * len(r_names)
    )

    def to_values(x: np.ndarray) -> dict[str, float]:
        f0_first = 10.0 ** x[0]
        rhos = x[1 : 1 + n]
        r_vals = x[1 + n :]
        values: dict[str, float] = {}
        for i, ((c_label, l_label), log_rho) in enumerate(zip(blocks, rhos, strict=True)):
            f0_i = f0_first * 10.0 ** (i * separation)
            rho = 10.0**log_rho
            omega0 = 2.0 * math.pi * f0_i
            values[f"L{l_label}.L"] = rho / omega0
            values[f"C{c_label}.C"] = 1.0 / (rho * omega0)
        for name, log_r in zip(r_names, r_vals, strict=True):
            values[name] = 10.0**log_r
        return values

    def objective(x: np.ndarray) -> float:
        return -_min_leverage(truth.circuit, frequencies, to_values(x))

    result = differential_evolution(
        objective, bounds, seed=seed, maxiter=maxiter, popsize=24, tol=1e-8, polish=True
    )
    return to_values(result.x), -float(result.fun)


def tune_until_screened_srf(
    truth: Truth, *, seeds: Sequence[int] = (0, 1, 2, 3, 4, 5, 6, 7), noise: float = NOISE
) -> tuple[dict[str, float], float, int]:
    attempts: list[tuple[dict[str, float], float, int]] = []
    for seed in seeds:
        values, worst = tune_srf(truth, seed=seed)
        candidate = replace(truth, params=values)
        verdict = screen(candidate, noise=noise)
        attempts.append((values, worst, seed))
        if verdict.passed:
            return values, worst, seed
    detail = ", ".join(f"seed {s}: weakest {w * 100:.3f}%" for _v, w, s in attempts)
    raise RuntimeError(
        f"{truth.id}: no tuned parameter set passed the four-part screen ({detail})."
    )


def resonant_frequencies(truth: Truth) -> dict[str, float]:
    """``1/(2*pi*sqrt(L*C))`` for every parallel (C, R-L) tank block -- srf2/srf3 only."""
    out: dict[str, float] = {}
    import re

    for label_c, label_l in re.findall(r"C(\d+),R\d+-L(\d+)", truth.circuit):
        c = truth.params[f"C{label_c}.C"]
        inductance = truth.params[f"L{label_l}.L"]
        out[f"C{label_c}/L{label_l}"] = 1.0 / (2.0 * math.pi * math.sqrt(inductance * c))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--tune", action="store_true")
    parser.add_argument("--resonances", action="store_true")
    parser.add_argument("--noise", type=float, default=NOISE)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    truths = list(REGISTRY.values())

    if args.resonances:
        for truth in (SRF2, SRF2_CLOSE, SRF3, SRF3_CLOSE):
            freqs = resonant_frequencies(truth)
            print(f"{truth.id}: window {truth.f_min:g}..{truth.f_max:g} Hz")
            for k, v in freqs.items():
                decades_from_low = math.log10(v / truth.f_min)
                decades_from_high = math.log10(truth.f_max / v)
                print(
                    f"    {k}: f0={v:.4g} Hz  "
                    f"({decades_from_low:.2f} decades from f_min, "
                    f"{decades_from_high:.2f} decades from f_max)"
                )
        return

    if args.tune:
        for truth in truths:
            if truth.id in SRF_SEPARATION_DECADES:
                values, worst, used = tune_until_screened_srf(truth, noise=args.noise)
            else:
                values, worst, used = tune_until_screened(truth, noise=args.noise)
            print(f"# {truth.id}: weakest leverage {worst * 100:.3f}% (tuner seed {used})")
            print(f'        "{truth.circuit}",')
            print("        {")
            for name, value in values.items():
                print(f'            "{name}": {value:.6g},')
            print("        },")
        return

    if not args.check:
        for truth in truths:
            print(f"{truth.id:10s} {truth.n_elements} el  {truth.circuit}")
        return

    verdicts: list[ScreenVerdict] = []
    print(
        "| truth | verdict | weakest parameter | below noise | unresolved | worst deviation "
        "| survives the feasibility filter |"
    )
    print("|---|---|---|---:|---:|---:|---|")
    for truth in truths:
        if not truth.params:
            print(f"| {truth.id} | SKIP | (no params -- run --tune first) | | | | |")
            continue
        verdict = screen(truth, noise=args.noise)
        verdicts.append(verdict)
        print(verdict.row())
    print()
    failed = [v.truth_id for v in verdicts if not v.passed]
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    else:
        print("All truths pass the four-part screen.")

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
