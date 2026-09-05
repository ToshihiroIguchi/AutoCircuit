"""Gates A1-A4 for docs/IMPACT_PLAN.md item A (multi-condition joint fitting).

Each gate is written with its decision rule stated before the run, in the form this
repository's other benchmarks use (``benchmarks/noise_estimation.py``,
``benchmarks/discovery_v2.py``): print every row as it is produced, then a pass/fail line per
gate and a process exit code.

A5 (byte-identical ``DiscoveryResult`` under both objectives on a ``SpectrumSet``) is not run
here: there is no objective-consuming report for a ``SpectrumSet`` result on this pass (see the
module docstring of ``autocircuit.core.multicondition``), so the invariant has nothing to
measure yet. It is recorded as deferred in ``docs/IMPACT_PLAN.md``, not silently skipped.

Usage::

    python benchmarks/multi_condition.py --out report.txt
    python benchmarks/multi_condition.py --gate a1 --seeds 3   # fast smoke run
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass

import numpy as np

sys.path.insert(0, "src")

from autocircuit.core.circuit import Circuit  # noqa: E402
from autocircuit.core.discover import discover  # noqa: E402
from autocircuit.core.multicondition import (  # noqa: E402
    BOLTZMANN_EV_PER_K,
    discover_set,
    select_level2,
)
from autocircuit.core.spectrum import Spectrum, SpectrumSet  # noqa: E402

# -- Shared scenario for A1-A3: the equivalence pair CLAUDE.md and docs/HANDOFF.md section 3 use.
FORM_A = "R1-p(R2,C1)"  # the "true" generating form
FORM_B = "p(R1,C1-R2)"  # its exact algebraic equivalent (verified below, not merely asserted)

TEMPS: tuple[float, ...] = (300.0, 325.0, 350.0, 375.0, 400.0)
NOISE_FRAC = 0.01
F_MIN, F_MAX, N_POINTS = 1.0, 1.0e6, 61
R1_AT_300 = 1000.0
R2_AT_300 = 3000.0
C1_VALUE = 1.0e-6

#: [measured] Gate A1's own threshold, re-used by A2 as the "still one class" band. A pair whose
#: BIC differs by more than this many points is one this project's own convention (see
#: ``docs/CRITERION_SELECTION_PLAN.md``) would already call separated.
CLASS_BIC_TOL = 10.0

A1_SEEDS = tuple(range(10))
A2_SEEDS = tuple(range(10))
A3_SEEDS = tuple(range(10))
#: A4 escalates the number of temperatures until level 1 pools enough evidence, or gives up --
#: exactly the fallback docs/IMPACT_PLAN.md section 3.3 (gate A4) states in advance.
A4_CONDITION_COUNTS = (2, 3)


def _verify_equivalence_transform() -> None:
    """The algebraic identity A1-A3 depend on, checked numerically rather than only cited."""
    r1, r2, c1 = 100.0, 200.0, 1.0e-6
    r1p = r1 + r2
    r2p = r1 * (r1 + r2) / r2
    c1p = r2**2 * c1 / (r1 + r2) ** 2
    f = np.geomspace(1.0, 1.0e6, 25)
    omega = 2 * np.pi * f
    z_a = r1 + 1.0 / (1.0 / r2 + 1j * omega * c1)
    z_b = 1.0 / (1.0 / r1p + 1.0 / (r2p + 1.0 / (1j * omega * c1p)))
    worst = float(np.max(np.abs(z_a - z_b) / np.abs(z_a)))
    if worst > 1e-9:
        raise AssertionError(
            f"{FORM_A} / {FORM_B} equivalence transform is wrong: worst relative gap {worst:.3g}"
        )


def _x0_for(target_at_300: float, ea_ev: float) -> float:
    """The Arrhenius prefactor giving ``target_at_300`` ohms at 300 K for activation ``ea_ev``."""
    return target_at_300 / math.exp(ea_ev / (BOLTZMANN_EV_PER_K * 300.0))


def _make_set(ea1: float, ea2: float, seed: int) -> SpectrumSet:
    rng = np.random.default_rng(seed)
    f = np.geomspace(F_MIN, F_MAX, N_POINTS)
    omega = 2 * np.pi * f
    circuit = Circuit.parse(FORM_A)
    x0_1, x0_2 = _x0_for(R1_AT_300, ea1), _x0_for(R2_AT_300, ea2)
    spectra = []
    for temperature in TEMPS:
        r1 = x0_1 * math.exp(ea1 / (BOLTZMANN_EV_PER_K * temperature))
        r2 = x0_2 * math.exp(ea2 / (BOLTZMANN_EV_PER_K * temperature))
        z = circuit.impedance(omega, np.array([r1, r2, C1_VALUE]))
        noise = (
            NOISE_FRAC
            * np.abs(z)
            * (rng.normal(size=z.shape) + 1j * rng.normal(size=z.shape))
            / np.sqrt(2)
        )
        spectra.append(Spectrum(f, z + noise))
    return SpectrumSet(tuple(spectra), TEMPS, "temperature_K")


@dataclass
class GateOutcome:
    name: str
    passed: bool
    lines: list[str]


def run_a1(seeds: tuple[int, ...] = A1_SEEDS) -> GateOutcome:
    """A1: the degeneracy breaks when the two forms' activation energies differ."""
    lines: list[str] = []
    wins = 0
    for seed in seeds:
        sset = _make_set(0.3, 0.8, seed)
        best_a = select_level2(FORM_A, sset, seed=seed)
        best_b = select_level2(FORM_B, sset, seed=seed)
        gap = best_b.statistics.bic - best_a.statistics.bic
        won = gap > CLASS_BIC_TOL
        wins += int(won)
        line = (
            f"  seed={seed} bic({FORM_A})={best_a.statistics.bic:.3f} "
            f"bic({FORM_B})={best_b.statistics.bic:.3f} gap={gap:+.3f} "
            f"status_a={best_a.status} status_b={best_b.status} "
            f"({'A wins' if won else 'no separation'})"
        )
        print(line, flush=True)
        lines.append(line)
    passed = wins >= 9
    verdict = (
        f"A1: {wins}/{len(seeds)} seeds separate {FORM_A} from {FORM_B} by >{CLASS_BIC_TOL} BIC"
        f" ({'PASS' if passed else 'FAIL'}, need >= 9/10)"
    )
    print(verdict, flush=True)
    lines.append(verdict)
    return GateOutcome("A1", passed, lines)


def run_a2(seeds: tuple[int, ...] = A2_SEEDS) -> GateOutcome:
    """A2: the negative control -- equal activation energies must stay one equivalence class."""
    lines: list[str] = []
    ties = 0
    for seed in seeds:
        sset = _make_set(0.3, 0.3, seed)
        best_a = select_level2(FORM_A, sset, seed=seed)
        best_b = select_level2(FORM_B, sset, seed=seed)
        gap = abs(best_b.statistics.bic - best_a.statistics.bic)
        tied = gap <= CLASS_BIC_TOL
        ties += int(tied)
        line = (
            f"  seed={seed} bic({FORM_A})={best_a.statistics.bic:.3f} "
            f"bic({FORM_B})={best_b.statistics.bic:.3f} |gap|={gap:.3f} "
            f"({'still equivalent' if tied else 'FALSELY SEPARATED'})"
        )
        print(line, flush=True)
        lines.append(line)
    passed = ties == len(seeds)
    verdict = (
        f"A2: {ties}/{len(seeds)} seeds correctly stay one class at equal Ea"
        f" ({'PASS' if passed else 'FAIL'}, need 10/10)"
    )
    print(verdict, flush=True)
    lines.append(verdict)
    return GateOutcome("A2", passed, lines)


def run_a3(seeds: tuple[int, ...] = A3_SEEDS) -> GateOutcome:
    """A3: the activation energies themselves are recovered, with a calibrated standard error."""
    lines: list[str] = []
    ea1_hat: list[float] = []
    ea2_hat: list[float] = []
    ea1_se: list[float] = []
    ea2_se: list[float] = []
    within_3se = 0
    for seed in seeds:
        sset = _make_set(0.3, 0.8, seed)
        best_a = select_level2(FORM_A, sset, seed=seed)
        law1 = best_a.laws.get("R1.R")
        law2 = best_a.laws.get("R2.R")
        if law1 is None or law2 is None or best_a.status.get("resistive") != "lawful":
            line = (
                f"  seed={seed}: {FORM_A} did not select lawful resistances"
                f" (status={best_a.status}) -- skipped"
            )
            print(line, flush=True)
            lines.append(line)
            continue
        ea1_hat.append(law1.ea_ev)
        ea2_hat.append(law2.ea_ev)
        ea1_se.append(law1.ea_stderr)
        ea2_se.append(law2.ea_stderr)
        ok1 = abs(law1.ea_ev - 0.3) <= 3 * law1.ea_stderr
        ok2 = abs(law2.ea_ev - 0.8) <= 3 * law2.ea_stderr
        both_ok = ok1 and ok2
        within_3se += int(both_ok)
        line = (
            f"  seed={seed} Ea(R1)={law1.ea_ev:.4f}+/-{law1.ea_stderr:.4f} (truth 0.300) "
            f"Ea(R2)={law2.ea_ev:.4f}+/-{law2.ea_stderr:.4f} (truth 0.800) "
            f"({'within 3se' if both_ok else 'OUTSIDE 3se'})"
        )
        print(line, flush=True)
        lines.append(line)

    n = len(ea1_hat)
    scatter1 = float(np.std(ea1_hat, ddof=1)) if n > 1 else math.nan
    scatter2 = float(np.std(ea2_hat, ddof=1)) if n > 1 else math.nan
    mean_se1 = float(np.mean(ea1_se)) if ea1_se else math.nan
    mean_se2 = float(np.mean(ea2_se)) if ea2_se else math.nan
    se_ok1 = mean_se1 > 0 and 0.5 <= scatter1 / mean_se1 <= 2.0
    se_ok2 = mean_se2 > 0 and 0.5 <= scatter2 / mean_se2 <= 2.0
    calib_line = (
        f"  seed-to-seed scatter vs reported stderr: Ea(R1) scatter={scatter1:.4f} "
        f"mean_se={mean_se1:.4f} ratio={scatter1 / mean_se1 if mean_se1 else math.nan:.2f}; "
        f"Ea(R2) scatter={scatter2:.4f} mean_se={mean_se2:.4f} "
        f"ratio={scatter2 / mean_se2 if mean_se2 else math.nan:.2f}"
    )
    print(calib_line, flush=True)
    lines.append(calib_line)

    passed = within_3se >= 9 and se_ok1 and se_ok2
    verdict = (
        f"A3: {within_3se}/{n} seeds recover both Ea within 3 stderr, stderr within a factor of"
        f" 2 of scatter: R1 {'OK' if se_ok1 else 'FAIL'}, R2 {'OK' if se_ok2 else 'FAIL'}"
        f" ({'PASS' if passed else 'FAIL'})"
    )
    print(verdict, flush=True)
    lines.append(verdict)
    return GateOutcome("A3", passed, lines)


# -- A4: level 1 pools evidence for a topology single-spectrum discovery cannot reach alone.
#
# Pool and element cap are deliberately narrowed from the project's usual ("R", "C", "L",
# "CPE") / 5-element defaults: the truth is a 4-element circuit built entirely from R and C, a
# full exhaustive search at those defaults measures in minutes *per spectrum* on this machine
# (docs/TOPOLOGY_6PLUS_PLAN.md and this plan's own runs confirm it), and A4 needs several such
# searches (one per single-spectrum baseline, one per condition-count tried). Dropping to
# ("R", "C", "L") at a 4-element cap still contains the truth and its plausible alternatives --
# it just does not ask whether an L or a CPE would explain the data better, which single- and
# multi-condition discovery are equally blind to here, so the comparison the gate cares about
# is unaffected.
A4_POOL = ("R", "C", "L")
A4_ELEMENT_CAP = 4
A4_TRUTH = "p(R1,C1)-p(R2,C2)"
A4_R2, A4_C1, A4_C2 = 5000.0, 1.0e-5, 1.0e-7
# [measured, a pre-run scan over share = 0.02 .. 0.15 with these R2/C1/C2] a single spectrum's
# own `recommended` only picks up the small block at share >= 0.08; below that the parsimony
# rule declines it (0.05: on the front but not recommended) or the search does not even reach
# its equivalence class (0.02: docs/HANDOFF.md section 21 item 5's own "2%, not recoverable
# alone" case). Both endpoints below are chosen inside that "individually insufficient" band,
# which is what makes a pooled recommendation -- if it happens -- attributable to pooling
# rather than to one condition already being enough on its own.
A4_R1_SMALL_SHARE = 102.04  # R1/(R1+R2) = 2.0%
A4_R1_LARGE_SHARE = 263.16  # R1/(R1+R2) = 5.0%


def _a4_spectrum(r1: float, seed: int) -> Spectrum:
    rng = np.random.default_rng(seed)
    f = np.geomspace(F_MIN, F_MAX, N_POINTS)
    omega = 2 * np.pi * f
    circuit = Circuit.parse(A4_TRUTH)
    z = circuit.impedance(omega, np.array([r1, A4_C1, A4_R2, A4_C2]))
    noise = (
        NOISE_FRAC
        * np.abs(z)
        * (rng.normal(size=z.shape) + 1j * rng.normal(size=z.shape))
        / np.sqrt(2)
    )
    return Spectrum(f, z + noise)


def _truth_class(result, truth_circuit: Circuit) -> list | None:
    """The truth's full evaluated equivalence class (itself plus everything :meth:`equivalents_of`
    finds), or ``None`` when the literal truth topology was never evaluated at all.

    A literal string match is not the right test here: two structurally different topologies
    routinely reproduce the same response to machine precision (``CLAUDE.md``'s whole reason
    for reporting equivalence classes rather than "the answer"), and A4's own truth turned out
    to have exactly such a competitor (``p(p(R1,C1)-R2,C2)``, tied with the truth to every
    reported digit). This reuses the search's own :meth:`equivalents_of`, the same instrument
    :class:`~autocircuit.core.discover.DiscoveryResult` and
    :class:`~autocircuit.core.multicondition.SetDiscoveryResult` both already expose, rather
    than re-deriving equivalence from scratch.
    """
    truth_form = truth_circuit.canonical_form()
    literal = next((c for c in result.candidates if c.circuit.canonical_form() == truth_form), None)
    if literal is None:
        return None
    return [literal, *result.equivalents_of(literal)]


def _truth_on_front(result, truth_circuit: Circuit) -> bool:
    truth_class = _truth_class(result, truth_circuit)
    if truth_class is None:
        return False
    front_forms = {c.circuit.canonical_form() for c in result.pareto}
    return any(c.circuit.canonical_form() in front_forms for c in truth_class)


def _truth_recommended(result, truth_circuit: Circuit) -> bool:
    rec = result.recommended
    if rec is None:
        return False
    truth_class = _truth_class(result, truth_circuit)
    if truth_class is None:
        return False
    return any(c.circuit.canonical_form() == rec.circuit.canonical_form() for c in truth_class)


def run_a4(condition_counts: tuple[int, ...] = A4_CONDITION_COUNTS) -> GateOutcome:
    lines: list[str] = []
    truth_circuit = Circuit.parse(A4_TRUTH)
    small_share = A4_R1_SMALL_SHARE / (A4_R1_SMALL_SHARE + A4_R2)
    large_share = A4_R1_LARGE_SHARE / (A4_R1_LARGE_SHARE + A4_R2)
    header = (
        f"  small-block share {small_share:.3%} at the first condition, "
        f"{large_share:.3%} at the last, {len(condition_counts)} condition-count(s) tried"
    )
    print(header, flush=True)
    lines.append(header)

    # Single-spectrum baseline: does discover() alone reach the truth at either endpoint?
    for label, r1 in (("small-share", A4_R1_SMALL_SHARE), ("large-share", A4_R1_LARGE_SHARE)):
        sp = _a4_spectrum(r1, seed=0)
        result = discover(
            sp, pool=A4_POOL, mode="exhaustive", exhaustive_limit=A4_ELEMENT_CAP, seed=0
        )
        on_front = _truth_on_front(result, truth_circuit)
        recommended = _truth_recommended(result, truth_circuit)
        rec_text = result.recommended.circuit.to_string() if result.recommended else None
        line = (
            f"  single-spectrum {label} (R1={r1:g}): truth_on_front={on_front} "
            f"truth_recommended={recommended} recommended={rec_text}"
        )
        print(line, flush=True)
        lines.append(line)

    winning_n: int | None = None
    for n_conditions in condition_counts:
        r1_values = np.geomspace(A4_R1_SMALL_SHARE, A4_R1_LARGE_SHARE, n_conditions)
        temps = tuple(np.linspace(300.0, 300.0 + 25.0 * (n_conditions - 1), n_conditions))
        spectra = tuple(_a4_spectrum(float(r1), seed=i) for i, r1 in enumerate(r1_values))
        sset = SpectrumSet(spectra, temps, "temperature_K")
        started = time.perf_counter()
        result = discover_set(sset, pool=A4_POOL, exhaustive_limit=A4_ELEMENT_CAP, seed=0)
        elapsed = time.perf_counter() - started
        on_front = _truth_on_front(result, truth_circuit)
        recommended = _truth_recommended(result, truth_circuit)
        rec_text = result.recommended.circuit.to_string() if result.recommended else None
        line = (
            f"  level 1, n_conditions={n_conditions}: truth_on_front={on_front} "
            f"truth_recommended={recommended} recommended={rec_text} ({elapsed:.1f}s)"
        )
        print(line, flush=True)
        lines.append(line)
        if on_front and winning_n is None:
            winning_n = n_conditions

    if winning_n is not None:
        verdict = (
            f"A4: level 1 reaches the two-block truth's front at n_conditions={winning_n} (PASS)"
        )
        passed = True
    else:
        verdict = (
            f"A4: level 1 did not reach the two-block truth's front at any of "
            f"{condition_counts} conditions tried -- level 1's pooling claim is WITHDRAWN for"
            " this scenario, per the plan's own fallback rule (FAIL)"
        )
        passed = False
    print(verdict, flush=True)
    lines.append(verdict)
    return GateOutcome("A4", passed, lines)


GATES = {"a1": run_a1, "a2": run_a2, "a3": run_a3, "a4": run_a4}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", choices=sorted(GATES), default=None, help="run one gate only")
    parser.add_argument("--seeds", type=int, default=None, help="override seed count for a1/a2/a3")
    parser.add_argument("--out", type=str, default=None, help="also write the report to this file")
    args = parser.parse_args()

    _verify_equivalence_transform()
    print(f"Verified {FORM_A} / {FORM_B} equivalence transform to machine precision.", flush=True)

    gate_names = [args.gate] if args.gate else ["a1", "a2", "a3", "a4"]
    outcomes: list[GateOutcome] = []
    for name in gate_names:
        print(f"\n## {name.upper()}", flush=True)
        if name in ("a1", "a2", "a3") and args.seeds is not None:
            seeds = tuple(range(args.seeds))
            outcomes.append(GATES[name](seeds))
        else:
            outcomes.append(GATES[name]())

    print("\n" + "\n".join(f"{o.name}: {'PASS' if o.passed else 'FAIL'}" for o in outcomes))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            for outcome in outcomes:
                fh.write(f"## {outcome.name}\n")
                fh.write("\n".join(outcome.lines) + "\n\n")

    return 0 if all(o.passed for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
