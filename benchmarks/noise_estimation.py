"""Gates N1-N4 for ``docs/IMPACT_PLAN.md`` item B: ``weighting="auto"``.

Four questions, each with a decision rule fixed before running it (that plan's section 2.4).
**Read section 2.2 before touching this file or ``core/noise.py``'s constants**: an earlier
version of the estimator used a fixed local-polynomial window, tuned by sweeping it until the
Maxwell-Wagner reference passed, and that was withdrawn as a method error (a constant fitted to
the test) rather than kept because the number looked right. What ships instead cross-validates
its own window per spectrum; this file measures the result, not a knob.

* **N1** -- does :func:`autocircuit.core.noise.estimate_sigma` recover the injected noise level,
  on data generated under noise families it was never told about? Measured on the three
  ``benchmarks/discovery_v2.py`` references (the gating rows) plus a ferrite-bead reference with
  a genuine anti-resonance (an informational row only -- see N4).
* **N2** -- does switching a completed discovery run's weighting from ``"modulus"`` to
  ``"auto"`` ever *lose* the truth (``recovered``) or its recommendation
  (``recommended_correct``)? This is the ratchet clause: any cell that regresses is named, and
  two or more means ``"auto"`` does not become a default on the strength of this run. **Scoped
  down** from the plan's full 37-cell grid (which would repeat
  ``docs/CRITERION_SELECTION_PLAN.md``'s own multi-hour sweep) to the three ``REFERENCES`` at a
  configurable number of noise-realisation seeds each, with the wider grid recorded as still
  open in ``docs/IMPACT_PLAN.md``.
* **N3** -- **measured, contradicted, and withdrawn; kept for the record, not gating.** The
  prediction was that ``"auto"`` reports a smaller relative standard error than ``"modulus"``
  for the capacitor's ESR. It reports a *larger* one on every seed tried, because the test data
  is generated under proportional noise, which is nearly what ``"modulus"`` already assumes --
  see ``docs/IMPACT_PLAN.md`` item B for why this made the prediction untestable on this data
  rather than wrong about the mechanism. This function still runs and reports the numbers, but
  does not affect this script's exit status.
* **N4** -- the safe-failure-direction claim for a resonance: no smoother tried in section 2.2
  tracks a genuine anti-resonance, and every one of them over-, not under-, estimates sigma
  there. Does that over-estimate still let the fitter recover the true parameters of a
  resonance-bearing circuit under ``weighting="auto"``, the way it already does for every other
  synthetic case in this repository? If not, the safe-direction argument is wrong and
  ``weighting="auto"`` needs a stated exclusion for resonance-bearing pools.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/noise_estimation.py --out noise_estimation.txt
    python benchmarks/noise_estimation.py --n2-seeds 1 --out noise_estimation_fast.txt

Exit status is 1 if N1, N2 or N4 fails. N3 never fails the run; it is reported and withdrawn.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from discovery_v2 import REFERENCES  # noqa: E402

from autocircuit.core.circuit import Circuit, CircuitError  # noqa: E402
from autocircuit.core.discover import EQUIVALENCE_RTOL, Candidate, discover  # noqa: E402
from autocircuit.core.fit import fit  # noqa: E402
from autocircuit.core.noise import estimate_sigma  # noqa: E402
from autocircuit.core.simulate import log_frequencies, simulate  # noqa: E402
from autocircuit.core.spectrum import Spectrum  # noqa: E402

#: N1's tolerance: the estimate must land within this factor of the true noise scale, on the
#: *median* point (see ``core/noise.py`` for why a sharp local feature can read high and is why
#: the check is a median over the whole spectrum rather than a per-point bound).
N1_FACTOR = 2.0

#: N1's noise-realisation seeds per reference per family.
N1_SEEDS = (0, 1, 2)

#: N2's noise-realisation seeds per reference (a subset of what a full 37-cell grid would use).
N2_SEEDS = (0, 1, 2)

#: N3's capacitor reference is REFERENCES[0]; its ESR is R1 and its bulk capacitance is C1.
N3_ESR_PARAM = "R1.R"
N3_CAP_PARAM = "C1.C"

#: N4's ferrite-bead reference: R1-p(R2,L1,C1), a genuine parallel (anti-)resonance in series
#: with an ESR -- not one of the three REFERENCES, added specifically because none of them
#: contains a pole (see docs/IMPACT_PLAN.md item B section 2.2).
N4_CIRCUIT = "R1-p(R2,L1,C1)"
N4_TRUTH = {"R1.R": 0.1, "R2.R": 1e4, "L1.L": 1e-6, "C1.C": 1e-11}
N4_F_MIN, N4_F_MAX = 1e4, 1e9
N4_SEEDS = (0, 1, 2)


class Referee:
    """Is this circuit the truth, or an exact reparameterisation of it?

    Reproduced from ``benchmarks/criterion_selection.py`` rather than imported, matching that
    script's own reason: this one should not depend on another benchmark's ``sys.path`` surgery.
    """

    def __init__(self, truth_circuit: str, spectrum: Spectrum) -> None:
        self.spectrum = spectrum
        self.canonical = Circuit.parse(truth_circuit).canonical_form()
        self.z_truth = fit(truth_circuit, spectrum, seed=0).z_model
        self.magnitude = np.abs(self.z_truth)
        self._cache: dict[str, bool] = {}

    def matches(self, candidate: Candidate) -> bool:
        text = candidate.circuit.to_string()
        if text in self._cache:
            return self._cache[text]
        verdict = self._decide(text, candidate.result.z_model)
        self._cache[text] = verdict
        return verdict

    def _decide(self, circuit: str, z_reported: np.ndarray | None) -> bool:
        try:
            if Circuit.parse(circuit).canonical_form() == self.canonical:
                return True
            if z_reported is not None and self._same(z_reported):
                return True
            z = fit(circuit, self.spectrum, seed=0).z_model
        except (CircuitError, ValueError, np.linalg.LinAlgError):
            return False
        return self._same(z)

    def _same(self, z: np.ndarray) -> bool:
        if z.shape != self.z_truth.shape:
            return False
        return bool(np.max(np.abs(z - self.z_truth) / self.magnitude) <= EQUIVALENCE_RTOL)


def _noise_ratio_row(
    label: str, circuit: str, params: dict[str, float], f_min: float, f_max: float
) -> tuple[list[float], list[float]]:
    """Median (estimate/truth) ratios over :data:`N1_SEEDS`, for proportional and absolute noise."""
    prop_ratios: list[float] = []
    abs_ratios: list[float] = []
    base = simulate(circuit, log_frequencies(f_min, f_max, 10), params, seed=0)
    abs_noise = 0.01 * float(np.median(np.abs(base.z)))
    for seed in N1_SEEDS:
        f = log_frequencies(f_min, f_max, 10)
        prop_data = simulate(circuit, f, params, noise=0.01, noise_model="proportional", seed=seed)
        prop_ratios.append(
            float(np.median(estimate_sigma(prop_data) / (0.01 * np.abs(prop_data.z))))
        )
        abs_data = simulate(circuit, f, params, noise=abs_noise, noise_model="absolute", seed=seed)
        abs_ratios.append(float(np.median(estimate_sigma(abs_data) / abs_noise)))
    return prop_ratios, abs_ratios


def run_n1(lines: list[str]) -> bool:
    lines.append("## N1 -- estimate_sigma recovers the injected noise level\n")
    ok = True
    for ref in REFERENCES:
        prop_ratios, abs_ratios = _noise_ratio_row(
            ref.label, ref.circuit, ref.params, ref.f_min, ref.f_max
        )
        for label, ratios in (("1% proportional", prop_ratios), ("matched absolute", abs_ratios)):
            median_ratio = float(np.median(ratios))
            passed = (1.0 / N1_FACTOR) <= median_ratio <= N1_FACTOR
            ok &= passed
            row_line = (
                f"  {ref.label:<32} {label:<18} median(estimate/truth) = {median_ratio:.3f} "
                f"({'PASS' if passed else 'FAIL'}, seeds {[round(r, 3) for r in ratios]})"
            )
            lines.append(row_line)
            print(row_line, flush=True)
    prop_ratios, abs_ratios = _noise_ratio_row(
        "ferrite bead (anti-res.)", N4_CIRCUIT, N4_TRUTH, N4_F_MIN, N4_F_MAX
    )
    for label, ratios in (("1% proportional", prop_ratios), ("matched absolute", abs_ratios)):
        row_line = (
            f"  {'ferrite bead (anti-res.)':<32} {label:<18} median(estimate/truth) = "
            f"{np.median(ratios):.3f} (informational only, not gated -- see N4)"
        )
        lines.append(row_line)
        print(row_line, flush=True)
    lines.append("")
    return ok


def run_n2(lines: list[str], seeds: tuple[int, ...] = N2_SEEDS) -> bool:
    lines.append(
        f"## N2 -- switching to auto weighting loses no recovered/recommended cell "
        f"({len(seeds)} seed(s))\n"
    )
    lines.append(
        f"   [scoped down from the plan's 37-cell grid to 3 references x {len(seeds)} seed(s)"
        f" = {3 * len(seeds)} cells; the wider grid is recorded as still open]\n"
    )
    print("\n".join(lines[-2:]), flush=True)
    regressions: list[str] = []
    for ref in REFERENCES:
        for seed in seeds:
            data = ref.spectrum(seed)
            referee = Referee(ref.circuit, data)
            row: dict[str, tuple[bool, bool]] = {}
            for weighting in ("modulus", "auto"):
                started = time.perf_counter()
                result = discover(
                    data, pool=ref.pool, mode="exhaustive", weighting=weighting, seed=0
                )
                elapsed = time.perf_counter() - started
                recovered = any(referee.matches(c) for c in result.candidates)
                recommended_correct = (
                    result.recommended is not None and referee.matches(result.recommended)
                )
                row[weighting] = (recovered, recommended_correct)
                row_line = (
                    f"  {ref.label:<32} seed={seed} {weighting:<8} recovered={recovered!s:<5} "
                    f"recommended_correct={recommended_correct!s:<5} ({elapsed:.1f}s)"
                )
                lines.append(row_line)
                print(row_line, flush=True)
            base_rec, base_rc = row["modulus"]
            auto_rec, auto_rc = row["auto"]
            if base_rec and not auto_rec:
                regressions.append(f"{ref.label} seed={seed}: recovered True -> False")
            if base_rc and not auto_rc:
                regressions.append(f"{ref.label} seed={seed}: recommended_correct True -> False")
    ok = len(regressions) < 2
    lines.append("")
    if regressions:
        lines.append(f"  regressions ({len(regressions)}):")
        lines.extend(f"    - {r}" for r in regressions)
        lines.append(
            f"  decision rule: ships as a default only with 0 regressions; "
            f"stays an opt-in lever with {'<2' if ok else '>=2'} (rule met: {ok})"
        )
    else:
        lines.append("  no regressions")
    lines.append("")
    return ok


def run_n3(lines: list[str]) -> None:
    """Measured, contradicted, withdrawn (docs/IMPACT_PLAN.md item B). Reported, never gates."""
    lines.append(
        "## N3 -- the capacitor's ESR standard error, auto vs modulus"
        " [withdrawn, informational only]\n"
    )
    ref = REFERENCES[0]
    for seed in (0, 1, 2):
        data = ref.spectrum(seed)
        results = {w: fit(ref.circuit, data, weighting=w, seed=0) for w in ("modulus", "auto")}
        stderr = {
            w: dict(zip(r.circuit.param_names, r.statistics.stderr, strict=True))
            for w, r in results.items()
        }
        values = {
            w: dict(zip(r.circuit.param_names, r.values, strict=True)) for w, r in results.items()
        }
        rel_esr = {
            w: stderr[w][N3_ESR_PARAM] / abs(values[w][N3_ESR_PARAM]) for w in ("modulus", "auto")
        }
        rel_cap = {
            w: stderr[w][N3_CAP_PARAM] / abs(values[w][N3_CAP_PARAM]) for w in ("modulus", "auto")
        }
        esr_improved = rel_esr["auto"] < rel_esr["modulus"]
        verdict = "smaller under auto" if esr_improved else "larger under auto, as expected now"
        lines.append(
            f"  seed={seed} ESR relative stderr: modulus={rel_esr['modulus']:.4%} "
            f"auto={rel_esr['auto']:.4%} ({verdict})"
        )
        lines.append(
            f"           C relative stderr: modulus={rel_cap['modulus']:.4%} "
            f"auto={rel_cap['auto']:.4%}"
        )
    lines.append("")


def run_n4(lines: list[str]) -> bool:
    lines.append(
        "## N4 -- a resonance-bearing circuit still fits correctly under auto weighting\n"
    )
    circuit = Circuit.parse(N4_CIRCUIT)
    ok = True
    for seed in N4_SEEDS:
        data = simulate(circuit, log_frequencies(N4_F_MIN, N4_F_MAX, 10), N4_TRUTH,
                         noise=0.01, seed=seed)
        result = fit(circuit, data, weighting="auto", seed=0)
        got = circuit.values_dict(result.values)
        within_tol = all(
            abs(got[name] - value) <= 0.2 * abs(value) for name, value in N4_TRUTH.items()
        )
        passed = within_tol and result.relative_error < 0.05
        ok &= passed
        row_line = (
            f"  seed={seed} relative_error={result.relative_error:.4%} "
            f"params={ {k: round(v, 6) for k, v in got.items()} } ({'PASS' if passed else 'FAIL'})"
        )
        lines.append(row_line)
        print(row_line, flush=True)
    lines.append("")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--n2-seeds", type=int, default=len(N2_SEEDS),
        help="how many of N2_SEEDS to use for the N2 ratchet (fewer cells, faster, weaker "
        "signal against the 37-cell grid this scopes down from)",
    )
    args = parser.parse_args()

    lines: list[str] = []
    n1 = run_n1(lines)
    n2 = run_n2(lines, seeds=N2_SEEDS[: args.n2_seeds])
    run_n3(lines)
    n4 = run_n4(lines)

    lines.append(f"N1: {'PASS' if n1 else 'FAIL'}")
    lines.append(f"N2: {'PASS' if n2 else 'FAIL'}")
    lines.append("N3: withdrawn (informational only, see docs/IMPACT_PLAN.md item B)")
    lines.append(f"N4: {'PASS' if n4 else 'FAIL'}")
    report = "\n".join(lines)
    print(report)
    if args.out is not None:
        args.out.write_text(report + "\n", encoding="utf-8")

    sys.exit(0 if (n1 and n2 and n4) else 1)


if __name__ == "__main__":
    main()
