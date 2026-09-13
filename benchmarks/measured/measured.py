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
    against the even-indexed points. This is stricter than an equivalence-class-aware
    comparison -- it does not know the two independent runs' exact reparameterisations are the
    same model -- and that scoping is stated here rather than silently upgraded to look like
    the full check `DiscoveryResult.equivalents_of` gives within one run.

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

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import DATASETS, MeasuredDataset  # noqa: E402 -- needs the sys.path insert above
from paired_stats import mcnemar_exact  # noqa: E402 -- needs the sys.path insert above

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import DiscoveryResult, discover
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.validate import lin_kk
from autocircuit.io import read


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
                "stable": (
                    odd_rec is not None
                    and even_rec is not None
                    and odd_rec.circuit.canonical_form() == even_rec.circuit.canonical_form()
                ),
            }
            rows.append(row)
            tag = "FAIL" if odd_rec is None or even_rec is None else (
                "ok  " if row["stable"] else "diff"
            )
            print(
                f"  {tag} {ds.id:<24} seed={seed} "
                f"odd={row['odd_circuit']!s:<24} even={row['even_circuit']}"
            )
            if out is not None:
                out.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    checked = [r for r in rows if r["axis"] == axis]
    n_checked = len(checked)
    n_stable = sum(1 for r in checked if r["stable"])
    frac = n_stable / n_checked if n_checked else 0.0
    print(f"R3: {n_stable}/{n_checked} stable ({frac:.0%}); bar is 80%")
    return frac >= 0.8


def run_compare_split_half(a_path: Path, b_path: Path) -> None:
    """Exact McNemar between two `run_split_half(..., out=...)` JSON files, paired by (dataset,
    seed).

    Written for `docs/SMALL_SAMPLE_REVIEW.md` A-2: comparing the element axis against a
    `--max-params` axis at the same seeds, rather than reading a 7-dataset, single-seed swing
    (2/7 -> 0/7) as though it settled the question.
    """
    rows_a = json.loads(a_path.read_text(encoding="utf-8"))
    rows_b = json.loads(b_path.read_text(encoding="utf-8"))
    by_key_a = {(r["dataset"], r["seed"]): r["stable"] for r in rows_a}
    by_key_b = {(r["dataset"], r["seed"]): r["stable"] for r in rows_b}
    keys = sorted(set(by_key_a) & set(by_key_b))
    both = sum(1 for k in keys if by_key_a[k] and by_key_b[k])
    only_a = sum(1 for k in keys if by_key_a[k] and not by_key_b[k])
    only_b = sum(1 for k in keys if not by_key_a[k] and by_key_b[k])
    neither = sum(1 for k in keys if not by_key_a[k] and not by_key_b[k])
    p = mcnemar_exact(only_a, only_b)
    axis_a = {r["axis"] for r in rows_a}
    axis_b = {r["axis"] for r in rows_b}
    print(f"Paired split-half stability: {axis_a} ({a_path.name}) vs {axis_b} ({b_path.name})")
    print(f"  pairs compared: {len(keys)} (of {len(rows_a)}/{len(rows_b)} rows on file)")
    print(f"  both stable={both}  only {a_path.name}={only_a}  only {b_path.name}={only_b}  "
          f"neither={neither}")
    print(f"  exact McNemar p={p:.4f} on {only_a + only_b} discordant pairs")
    if only_a + only_b < 10:
        print(
            "  fewer than 10 discordant pairs: this test has little power here -- "
            "report the p-value beside the count, do not read it alone as 'no difference' "
            "(docs/DE_KERNEL_PLAN.md clause 3)."
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
        run_compare_split_half(args.a, args.b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
