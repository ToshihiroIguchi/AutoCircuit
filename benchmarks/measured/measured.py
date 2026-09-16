"""The measured-data arena: `docs/IMPACT_PLAN.md` item C, gates R1-R5.

Every prior gate in this repository runs on data generated from a circuit in the vocabulary
being searched, at 1% proportional noise, independent across points. This is the first that
does not: it runs the same pipeline against real instrument files (`datasets.py`), which is not
evidence *for* recovering a truth -- there is none here to recover -- but is the first evidence
about what a real spectrum's own artefacts (a fixture inductance, drift, a noise floor that is
not what `simulate()` injects) do to a pipeline every other gate has only ever seen behave.

There is no truth, so every gate below is a stability gate written to be able to fail:

``readers`` (R1)
    Every file is read by its format's reader without error, and the point count is reported
    against a manual count of the file's own data rows (this repository has no vendor software
    to compare against, which is recorded rather than silently substituted for).

``pipeline`` (R2)
    On every dataset: Lin-KK produces a verdict, `--pool auto --weighting auto` produces a
    front, and the recommended model's chi2_reduced under the estimated sigma(f) is checked
    against [0.5, 3]. Outside that band the pipeline is over- or under-claiming.

``split-half`` (R3)
    The recommended candidate's canonical topology on the odd-indexed points is compared
    against the even-indexed points (`stable`). Alongside it, two looser verdicts answer
    `docs/IMPACT_PLAN.md` section 4.4's own question -- does the odd half's recommendation,
    refit to the even half's data, reach the same score as the even half's own recommendation:
    `stable_equiv` (delta AICc within 2 of the even half's own fit, both directions checked
    separately) and `stable_reparam` (the strictly narrower claim that the two fitted responses
    agree to `EQUIVALENCE_RTOL`, the same test `discover.py`'s own equivalence-class grouping
    uses). `stable` is never replaced, only joined -- see `docs/SMALL_SAMPLE_REVIEW.md` A-2.

``rescore-split-half``
    Recomputes `stable_equiv`/`stable_reparam` for an existing `split-half --out ...` file,
    offline, without re-running `discover()` -- see `run_rescore_split_half`'s docstring for
    what that trades away.

``literature`` (R4)
    For every dataset that names a `published_circuit`, whether that circuit's canonical form
    appears among the candidates evaluated, is on the front, or is the recommendation -- as a
    table, no pass fraction, because the published circuit was chosen by the expert this
    project exists to replace and may itself be wrong.

Run with the package on the path (it is not pip-installed on the dev machine)::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/measured/measured.py readers
    python benchmarks/measured/measured.py pipeline
    python benchmarks/measured/measured.py split-half
    python benchmarks/measured/measured.py literature
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import DATASETS, MeasuredDataset  # noqa: E402 -- needs the sys.path insert above
from paired_stats import mcnemar_exact  # noqa: E402 -- needs the sys.path insert above

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import EQUIVALENCE_RTOL, DiscoveryResult, discover
from autocircuit.core.fit import FitResult, fit
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.validate import lin_kk
from autocircuit.io import read

#: `docs/IMPACT_PLAN.md` section 4.4's own criterion for "reaches the same score": the
#: conventional AICc indistinguishability band, fixed here before any row is scored.
EQUIV_AICC_BAND = 2.0


def _load(ds: MeasuredDataset) -> Spectrum:
    return read(ds.path, format=ds.format, **ds.reader_hints)


def _manual_row_count(ds: MeasuredDataset) -> int:
    """Counts non-blank lines of the raw file minus the header lines this reader consumed.

    Not a substitute for comparing against the vendor's own software (none is available here);
    this exists so a reader silently dropping rows shows up as a mismatch against the file's
    own visible line count rather than passing by never being checked at all.
    """
    text = ds.path.read_text(encoding="utf-8-sig", errors="replace")
    return sum(1 for line in text.splitlines() if line.strip())


def run_readers() -> bool:
    print("R1: every dataset is read by its format's reader")
    ok = True
    for ds in DATASETS:
        try:
            spectrum = _load(ds)
        except Exception as exc:  # noqa: BLE001 -- reported, not re-raised
            print(f"  FAIL {ds.id}: {exc}")
            ok = False
            continue
        raw_lines = _manual_row_count(ds)
        print(
            f"  ok   {ds.id:<24} n={spectrum.n:<4} "
            f"(raw file has {raw_lines} non-blank lines) "
            f"f={spectrum.f.min():.4g}..{spectrum.f.max():.4g} Hz"
        )
    print("R1:", "pass" if ok else "FAIL")
    return ok


def run_pipeline(
    weighting: str = "auto",
    pool: str | None = None,
    time_limit: float | None = None,
    max_params: int | None = None,
) -> bool:
    print(f"R2: pipeline finishes and its numbers mean something (weighting={weighting!r})")
    ok = True
    for ds in DATASETS:
        spectrum = _load(ds)
        kk = lin_kk(spectrum, weighting=weighting)  # type: ignore[arg-type]
        pool_arg = tuple(pool.split(",")) if pool else None
        result = discover(  # type: ignore[arg-type]
            spectrum,
            pool=pool_arg,
            weighting=weighting,
            seed=0,
            time_limit=time_limit,
            max_params=max_params,
        )
        rec = result.recommended
        if rec is None:
            print(f"  FAIL {ds.id}: no candidate recommended at all")
            ok = False
            continue
        chi2 = rec.result.statistics.chi2_reduced
        in_band = 0.5 <= chi2 <= 3.0
        ok &= in_band
        print(
            f"  {'ok  ' if in_band else 'FAIL'} {ds.id:<24} "
            f"KK={kk.verdict:<12} "
            f"recommended={rec.circuit.canonical_form():<28} "
            f"chi2_reduced={chi2:.4g} relative_error={rec.relative_error * 100:.4g}%"
        )
    print("R2:", "pass" if ok else "FAIL (see rows above)")
    return ok


def _split_half(spectrum: Spectrum) -> tuple[Spectrum, Spectrum]:
    odd = Spectrum(spectrum.f[1::2], spectrum.z[1::2], dict(spectrum.metadata))
    even = Spectrum(spectrum.f[0::2], spectrum.z[0::2], dict(spectrum.metadata))
    return odd, even


def _axis_label(max_params: int | None) -> str:
    return "elements" if max_params is None else f"params<={max_params}"


def _bracket_to_dsl(canonical: str) -> str:
    """Convert a `Circuit.canonical_form()` string to a DSL string `Circuit.parse` accepts.

    `canonical_form()` writes series blocks as `[A-B]` with no element labels, a syntax
    `Circuit.parse` rejects outright. Deleting every bracket character yields a plain,
    label-free DSL string that parses -- verified here, on every string this converts, to
    round-trip back to the *exact same* canonical form, rather than assumed once and trusted.
    """
    dsl = canonical.replace("[", "").replace("]", "")
    if Circuit.parse(dsl).canonical_form() != canonical:
        raise ValueError(f"bracket-strip round trip failed: {canonical!r} -> {dsl!r}")
    return dsl


def _same_response(a: np.ndarray, b: np.ndarray) -> bool:
    """The same equivalence test `discover.py`'s own class grouping applies to `z_model`."""
    if a.shape != b.shape:
        return False
    scale = np.abs(b)
    if np.any(scale == 0.0):
        return False
    return bool(np.max(np.abs(a - b) / scale) <= EQUIVALENCE_RTOL)


def _equiv_verdicts(
    odd_dsl: str,
    even_dsl: str,
    odd_spectrum: Spectrum,
    even_spectrum: Spectrum,
    weighting: str,
    *,
    odd_own: FitResult | None = None,
    even_own: FitResult | None = None,
) -> dict[str, Any]:
    """`docs/IMPACT_PLAN.md` section 4.4's own question, both directions: does the odd half's
    recommendation, refit to the even half's data, reach the same score as the even half's own
    recommendation fitted there -- and symmetrically.

    `odd_own`/`even_own` let a caller holding the live `Candidate.result` from the search that
    actually produced these circuits pass it in rather than have this function refit it fresh;
    `run_rescore_split_half` has no such thing (a stored grid keeps only canonical-form strings,
    never a `FitResult`) and always refits both. A fresh refit landing in a worse basin than the
    original search inflates the delta AICc, which reads as *less* stable never more -- biased
    against the change this measures, not for it.
    """
    if even_own is None:
        even_own = fit(even_dsl, even_spectrum, weighting=weighting, seed=0)  # type: ignore[arg-type]
    if odd_own is None:
        odd_own = fit(odd_dsl, odd_spectrum, weighting=weighting, seed=0)  # type: ignore[arg-type]

    odd_on_even = fit(odd_dsl, even_spectrum, weighting=weighting, seed=0)  # type: ignore[arg-type]
    delta_o2e = odd_on_even.aicc - even_own.aicc
    reparam_o2e = _same_response(odd_on_even.z_model, even_own.z_model)

    even_on_odd = fit(even_dsl, odd_spectrum, weighting=weighting, seed=0)  # type: ignore[arg-type]
    delta_e2o = even_on_odd.aicc - odd_own.aicc
    reparam_e2o = _same_response(even_on_odd.z_model, odd_own.z_model)

    stable_equiv = abs(delta_o2e) <= EQUIV_AICC_BAND
    stable_equiv_reverse = abs(delta_e2o) <= EQUIV_AICC_BAND
    return {
        "delta_aicc_odd_to_even": round(delta_o2e, 3),
        "delta_aicc_even_to_odd": round(delta_e2o, 3),
        "stable_equiv": stable_equiv,
        "stable_equiv_both": stable_equiv and stable_equiv_reverse,
        "stable_reparam": reparam_o2e,
        "stable_reparam_both": reparam_o2e and reparam_e2o,
        "even_own_aicc": round(even_own.aicc, 3),
        "odd_own_aicc": round(odd_own.aicc, 3),
    }


def _equiv_report(
    odd_dsl: str,
    even_dsl: str,
    odd_spectrum: Spectrum,
    even_spectrum: Spectrum,
    *,
    odd_own: FitResult | None = None,
    even_own: FitResult | None = None,
) -> dict[str, Any]:
    """`_equiv_verdicts` at the search's own weighting (`auto`, unsuffixed, the primary
    verdict) plus a `modulus` sensitivity column (`_modulus` suffix) -- pre-registered because
    `docs/IMPACT_PLAN.md` section 4.3 measured `weighting="auto"`'s sigma(f) estimate to be
    orders of magnitude wrong on these exact spectra, and a constant rescaling of sigma cancels
    in a delta AICc on the same data but its *shape* does not. The precomputed `odd_own`/
    `even_own` (a live search's own fit) are usable only for the `auto` column, since that is
    the weighting that actually produced them; the `modulus` column always refits both circuits
    fresh, on both call sites, for the same reason `_equiv_verdicts` always refits when no
    precomputed fit is given.
    """
    out: dict[str, Any] = {}
    for weighting, suffix, own in (
        ("auto", "", (odd_own, even_own)),
        ("modulus", "_modulus", (None, None)),
    ):
        verdicts = _equiv_verdicts(
            odd_dsl, even_dsl, odd_spectrum, even_spectrum, weighting,
            odd_own=own[0], even_own=own[1],
        )
        for key, value in verdicts.items():
            out[f"{key}{suffix}"] = value
    return out


def run_split_half(
    weighting: str = "auto",
    time_limit: float | None = None,
    max_params: int | None = None,
    seeds: tuple[int, ...] = (0,),
    out: Path | None = None,
) -> bool:
    """R3, and (with `seeds` beyond the default) `docs/SMALL_SAMPLE_REVIEW.md`'s A-2 grid.

    `seeds` varies `discover(seed=...)` on *both* halves of a pair identically -- it is a search
    RNG axis, the same knob `benchmarks/six_plus/recovery.py` calls a noise seed's opposite
    number. The default `(0,)` reproduces every prior invocation of this function byte-for-byte
    (same single call, same return value), so nothing about R3 as already recorded changes
    unless `--seeds` is passed explicitly.
    """
    print("R3: split-half stability (stricter than equivalence-class-aware -- see docstring)")
    rows: list[dict[str, Any]] = []
    if out is not None and out.exists():
        rows = json.loads(out.read_text(encoding="utf-8"))
        print(f"  resuming with {len(rows)} rows already on disk", flush=True)
    done = {(r["dataset"], r["axis"], r["seed"]) for r in rows}
    axis = _axis_label(max_params)

    for ds in DATASETS:
        spectrum = _load(ds)
        if spectrum.n < 8:
            print(f"  skip {ds.id}: only {spectrum.n} points, too few to split meaningfully")
            continue
        odd, even = _split_half(spectrum)
        for seed in seeds:
            if (ds.id, axis, seed) in done:
                continue
            started = time.perf_counter()
            odd_result = discover(  # type: ignore[arg-type]
                odd, weighting=weighting, seed=seed, time_limit=time_limit, max_params=max_params
            )
            even_result = discover(  # type: ignore[arg-type]
                even,
                weighting=weighting,
                seed=seed,
                time_limit=time_limit,
                max_params=max_params,
            )
            elapsed = time.perf_counter() - started
            odd_rec = odd_result.recommended
            even_rec = even_result.recommended
            row: dict[str, Any] = {
                "dataset": ds.id,
                "axis": axis,
                "max_params": max_params,
                "seed": seed,
                "time_limit": time_limit,
                "seconds": round(elapsed, 1),
                "odd_circuit": None if odd_rec is None else odd_rec.circuit.canonical_form(),
                "even_circuit": None if even_rec is None else even_rec.circuit.canonical_form(),
                "odd_circuit_dsl": None if odd_rec is None else odd_rec.circuit.to_string(),
                "even_circuit_dsl": None if even_rec is None else even_rec.circuit.to_string(),
                "stable": (
                    odd_rec is not None
                    and even_rec is not None
                    and odd_rec.circuit.canonical_form() == even_rec.circuit.canonical_form()
                ),
            }
            if odd_rec is not None and even_rec is not None:
                report = _equiv_report(
                    row["odd_circuit_dsl"], row["even_circuit_dsl"], odd, even,
                    odd_own=odd_rec.result if weighting == "auto" else None,
                    even_own=even_rec.result if weighting == "auto" else None,
                )
                if weighting == "auto":
                    live_gap = abs(report["even_own_aicc"] - even_rec.result.aicc)
                    if live_gap > 0.5:
                        print(
                            f"  NOTE {ds.id} seed={seed}: this function's own fresh refit of "
                            f"the even half's recommendation landed {live_gap:.2f} AICc away "
                            "from the search's own fit -- basin drift, not a bug in the check"
                        )
            else:
                report = {
                    "delta_aicc_odd_to_even": None, "delta_aicc_even_to_odd": None,
                    "stable_equiv": False, "stable_equiv_both": False,
                    "stable_reparam": False, "stable_reparam_both": False,
                    "delta_aicc_odd_to_even_modulus": None, "delta_aicc_even_to_odd_modulus": None,
                    "stable_equiv_modulus": False, "stable_equiv_both_modulus": False,
                    "stable_reparam_modulus": False, "stable_reparam_both_modulus": False,
                }
            report.pop("even_own_aicc", None)
            report.pop("odd_own_aicc", None)
            report.pop("even_own_aicc_modulus", None)
            report.pop("odd_own_aicc_modulus", None)
            row.update(report)
            rows.append(row)
            tag = "FAIL" if odd_rec is None or even_rec is None else (
                "ok  " if row["stable"] else ("equiv" if row["stable_equiv"] else "diff")
            )
            print(
                f"  {tag} {ds.id:<24} seed={seed} "
                f"odd={row['odd_circuit']!s:<24} even={row['even_circuit']} "
                f"dAICc={row['delta_aicc_odd_to_even']}"
            )
            if out is not None:
                out.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    checked = [r for r in rows if r["axis"] == axis]
    n_checked = len(checked)
    n_stable = sum(1 for r in checked if r["stable"])
    n_equiv = sum(1 for r in checked if r["stable_equiv"])
    n_reparam = sum(1 for r in checked if r["stable_reparam"])
    frac = n_stable / n_checked if n_checked else 0.0
    frac_equiv = n_equiv / n_checked if n_checked else 0.0
    print(f"R3: {n_stable}/{n_checked} stable ({frac:.0%}); bar is 80%")
    print(
        f"R3 (equivalence-aware): {n_equiv}/{n_checked} stable_equiv ({frac_equiv:.0%}), "
        f"{n_reparam}/{n_checked} stable_reparam -- see docs/SMALL_SAMPLE_REVIEW.md A-2"
    )
    return frac >= 0.8


def run_compare_split_half(a_path: Path, b_path: Path, field: str = "stable") -> None:
    """Exact McNemar between two `run_split_half(..., out=...)` JSON files, paired by (dataset,
    seed), on `field` (`stable`, `stable_equiv`, `stable_reparam`, ...).

    Written for `docs/SMALL_SAMPLE_REVIEW.md` A-2: comparing the element axis against a
    `--max-params` axis at the same seeds, rather than reading a 7-dataset, single-seed swing
    (2/7 -> 0/7) as though it settled the question.
    """
    rows_a = json.loads(a_path.read_text(encoding="utf-8"))
    rows_b = json.loads(b_path.read_text(encoding="utf-8"))
    by_key_a = {(r["dataset"], r["seed"]): r[field] for r in rows_a}
    by_key_b = {(r["dataset"], r["seed"]): r[field] for r in rows_b}
    keys = sorted(set(by_key_a) & set(by_key_b))
    both = sum(1 for k in keys if by_key_a[k] and by_key_b[k])
    only_a = sum(1 for k in keys if by_key_a[k] and not by_key_b[k])
    only_b = sum(1 for k in keys if not by_key_a[k] and by_key_b[k])
    neither = sum(1 for k in keys if not by_key_a[k] and not by_key_b[k])
    p = mcnemar_exact(only_a, only_b)
    axis_a = {r["axis"] for r in rows_a}
    axis_b = {r["axis"] for r in rows_b}
    print(f"Paired {field}: {axis_a} ({a_path.name}) vs {axis_b} ({b_path.name})")
    print(f"  pairs compared: {len(keys)} (of {len(rows_a)}/{len(rows_b)} rows on file)")
    print(f"  both {field}={both}  only {a_path.name}={only_a}  only {b_path.name}={only_b}  "
          f"neither={neither}")
    print(f"  exact McNemar p={p:.4f} on {only_a + only_b} discordant pairs")
    if only_a + only_b < 10:
        print(
            "  fewer than 10 discordant pairs: this test has little power here -- "
            "report the p-value beside the count, do not read it alone as 'no difference' "
            "(docs/DE_KERNEL_PLAN.md clause 3)."
        )


def run_rescore_split_half(in_path: Path, out_path: Path) -> None:
    """Offline `stable_equiv`/`stable_reparam` for an existing `split-half --out ...` file.

    The split is deterministic (`_split_half` on a deterministic file read), so this needs no
    `discover()` re-run -- it pairs cell-for-cell with the already-published `stable`, in
    minutes rather than hours, and carries none of the wall-clock non-determinism
    `docs/SMALL_SAMPLE_REVIEW.md` A-2 measured in the `discover()`-calling command itself.

    **What this trades away.** The stored grid keeps only canonical-form strings, never a
    `FitResult`, so both circuits are refit fresh here -- there is no live fit to assert a
    fresh refit is no worse than (`_equiv_verdicts`'s docstring). That biases a fresh refit
    landing in a worse basin *against* stability, never for it, so a pass from this function is
    not weakened by the gap and a fail is not fully conclusive from it alone.

    **The positive control.** `stable_equiv` is decided from the refit alone, never from
    `stable` -- `stable_equiv >= stable` would otherwise hold by construction and prove nothing.
    So every row where `stable` is already `True` (the canonical forms match) is refit anyway,
    as a check that the independently-computed `stable_equiv` agrees. A row that disagrees means
    the refit landed in a different basin than the same topology's own recommendation did --
    reported as a defect in the check, not as a finding about the data.
    """
    rows = json.loads(in_path.read_text(encoding="utf-8"))
    ds_by_id = {ds.id: ds for ds in DATASETS}
    spectra_cache: dict[str, tuple[Spectrum, Spectrum]] = {}
    out_rows: list[dict[str, Any]] = []
    n_control_checked = 0
    n_control_failed = 0

    for row in rows:
        out_row = dict(row)
        if row["odd_circuit"] is None or row["even_circuit"] is None:
            out_row.update(
                delta_aicc_odd_to_even=None, delta_aicc_even_to_odd=None,
                stable_equiv=False, stable_equiv_both=False,
                stable_reparam=False, stable_reparam_both=False,
                delta_aicc_odd_to_even_modulus=None, delta_aicc_even_to_odd_modulus=None,
                stable_equiv_modulus=False, stable_equiv_both_modulus=False,
                stable_reparam_modulus=False, stable_reparam_both_modulus=False,
            )
            out_rows.append(out_row)
            continue

        if row["dataset"] not in spectra_cache:
            spectra_cache[row["dataset"]] = _split_half(_load(ds_by_id[row["dataset"]]))
        odd, even = spectra_cache[row["dataset"]]
        odd_dsl = _bracket_to_dsl(row["odd_circuit"])
        even_dsl = _bracket_to_dsl(row["even_circuit"])

        report = _equiv_report(odd_dsl, even_dsl, odd, even)
        report.pop("even_own_aicc", None)
        report.pop("odd_own_aicc", None)
        report.pop("even_own_aicc_modulus", None)
        report.pop("odd_own_aicc_modulus", None)

        if row["stable"]:
            n_control_checked += 1
            if not report["stable_equiv"]:
                n_control_failed += 1
                print(
                    f"  POSITIVE-CONTROL FAIL: {row['dataset']} axis={row['axis']} "
                    f"seed={row['seed']} -- canonical forms match but a fresh refit put "
                    f"delta AICc at {report['delta_aicc_odd_to_even']:.3f}"
                )

        out_row.update(report)
        print(
            f"  {row['dataset']:<24} axis={row['axis']:<12} seed={row['seed']} "
            f"stable={row['stable']!s:<5} stable_equiv={report['stable_equiv']!s:<5} "
            f"dAICc={report['delta_aicc_odd_to_even']:.2f}"
        )
        out_rows.append(out_row)

    out_path.write_text(json.dumps(out_rows, indent=2), encoding="utf-8")

    for axis in sorted({r["axis"] for r in out_rows}):
        subset = [r for r in out_rows if r["axis"] == axis]
        n = len(subset)
        n_stable = sum(r["stable"] for r in subset)
        n_equiv = sum(r["stable_equiv"] for r in subset)
        n_both = sum(r["stable_equiv_both"] for r in subset)
        n_reparam = sum(r["stable_reparam"] for r in subset)
        print(
            f"{axis}: stable {n_stable}/{n} ({n_stable / n:.0%})  "
            f"stable_equiv {n_equiv}/{n} ({n_equiv / n:.0%})  "
            f"stable_equiv_both {n_both}/{n} ({n_both / n:.0%})  "
            f"stable_reparam {n_reparam}/{n} ({n_reparam / n:.0%})"
        )
    if n_control_checked:
        print(
            f"positive control: {n_control_checked - n_control_failed}/{n_control_checked} "
            "rows with stable=True independently confirmed stable_equiv"
        )


def run_literature(weighting: str = "auto", time_limit: float | None = None) -> None:
    print("R4: agreement with the source's own fit -- reported, not scored")
    for ds in DATASETS:
        if ds.published_circuit is None:
            continue
        spectrum = _load(ds)
        result: DiscoveryResult = discover(  # type: ignore[arg-type]
            spectrum, weighting=weighting, seed=0, time_limit=time_limit
        )
        target = Circuit.parse(ds.published_circuit).canonical_form()
        canonical_forms = {c.circuit.canonical_form() for c in result.candidates}
        on_front = target in {c.circuit.canonical_form() for c in result.pareto}
        rec = result.recommended
        is_recommended = rec is not None and rec.circuit.canonical_form() == target
        status = (
            "recommended"
            if is_recommended
            else "on front"
            if on_front
            else "evaluated, not on front"
            if target in canonical_forms
            else "absent"
        )
        print(f"  {ds.id:<24} published={ds.published_circuit!r:<40} -> {status}")
        print(f"      ({ds.published_circuit_note})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "gate",
        choices=[
            "readers", "pipeline", "split-half", "literature", "all", "compare-split-half",
            "rescore-split-half",
        ],
    )
    parser.add_argument("--weighting", default="auto")
    parser.add_argument("--pool", default=None, help="comma-separated element codes, e.g. R,C,L")
    parser.add_argument(
        "--time-limit",
        type=float,
        default=None,
        help="wall-clock budget per discover() call, seconds (default: no limit)",
    )
    parser.add_argument(
        "--max-params",
        type=int,
        default=None,
        help="budget the exhaustive stage by free parameters instead of raw element count "
        "(docs/PARAM_BUDGET_PLAN.md); applies to pipeline and split-half only",
    )
    parser.add_argument(
        "--seeds",
        default=None,
        help="comma-separated discover() seeds for split-half (default: 0 only, "
        "reproducing every prior R3 invocation byte-for-byte)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="split-half only: write/resume per-(dataset,seed) rows as JSON to this path",
    )
    parser.add_argument("--a", type=Path, default=None, help="compare-split-half: first JSON file")
    parser.add_argument("--b", type=Path, default=None, help="compare-split-half: second JSON file")
    parser.add_argument(
        "--field",
        default="stable",
        help="compare-split-half: which row field to pair on (default: stable)",
    )
    parser.add_argument(
        "--in", dest="in_path", type=Path, default=None,
        help="rescore-split-half: an existing split-half --out JSON file to read",
    )
    args = parser.parse_args()

    seeds = (0,) if args.seeds is None else tuple(int(s) for s in args.seeds.split(","))

    if args.gate in ("readers", "all"):
        run_readers()
    if args.gate in ("pipeline", "all"):
        run_pipeline(args.weighting, args.pool, args.time_limit, args.max_params)
    if args.gate in ("split-half", "all"):
        run_split_half(args.weighting, args.time_limit, args.max_params, seeds, args.out)
    if args.gate in ("literature", "all"):
        run_literature(args.weighting, args.time_limit)
    if args.gate == "compare-split-half":
        if args.a is None or args.b is None:
            raise SystemExit("compare-split-half needs --a and --b")
        run_compare_split_half(args.a, args.b, args.field)
    if args.gate == "rescore-split-half":
        if args.in_path is None or args.out is None:
            raise SystemExit("rescore-split-half needs --in and --out")
        run_rescore_split_half(args.in_path, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
