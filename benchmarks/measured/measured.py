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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


from datasets import DATASETS, MeasuredDataset  # noqa: E402 -- needs the sys.path insert above

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
    weighting: str = "auto", pool: str | None = None, time_limit: float | None = None
) -> bool:
    print(f"R2: pipeline finishes and its numbers mean something (weighting={weighting!r})")
    ok = True
    for ds in DATASETS:
        spectrum = _load(ds)
        kk = lin_kk(spectrum, weighting=weighting)  # type: ignore[arg-type]
        pool_arg = tuple(pool.split(",")) if pool else None
        result = discover(  # type: ignore[arg-type]
            spectrum, pool=pool_arg, weighting=weighting, seed=0, time_limit=time_limit
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


def run_split_half(weighting: str = "auto", time_limit: float | None = None) -> bool:
    print("R3: split-half stability (stricter than equivalence-class-aware -- see docstring)")
    n_stable = 0
    n_checked = 0
    for ds in DATASETS:
        spectrum = _load(ds)
        if spectrum.n < 8:
            print(f"  skip {ds.id}: only {spectrum.n} points, too few to split meaningfully")
            continue
        odd, even = _split_half(spectrum)
        odd_result = discover(odd, weighting=weighting, seed=0, time_limit=time_limit)  # type: ignore[arg-type]
        even_result = discover(even, weighting=weighting, seed=0, time_limit=time_limit)  # type: ignore[arg-type]
        odd_rec = odd_result.recommended
        even_rec = even_result.recommended
        n_checked += 1
        if odd_rec is None or even_rec is None:
            print(f"  FAIL {ds.id}: no recommendation on one half")
            continue
        stable = odd_rec.circuit.canonical_form() == even_rec.circuit.canonical_form()
        n_stable += int(stable)
        print(
            f"  {'ok  ' if stable else 'diff'} {ds.id:<24} "
            f"odd={odd_rec.circuit.canonical_form():<24} even={even_rec.circuit.canonical_form()}"
        )
    frac = n_stable / n_checked if n_checked else 0.0
    print(f"R3: {n_stable}/{n_checked} stable ({frac:.0%}); bar is 80%")
    return frac >= 0.8


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
    parser.add_argument("gate", choices=["readers", "pipeline", "split-half", "literature", "all"])
    parser.add_argument("--weighting", default="auto")
    parser.add_argument("--pool", default=None, help="comma-separated element codes, e.g. R,C,L")
    parser.add_argument(
        "--time-limit",
        type=float,
        default=None,
        help="wall-clock budget per discover() call, seconds (default: no limit)",
    )
    args = parser.parse_args()

    if args.gate in ("readers", "all"):
        run_readers()
    if args.gate in ("pipeline", "all"):
        run_pipeline(args.weighting, args.pool, args.time_limit)
    if args.gate in ("split-half", "all"):
        run_split_half(args.weighting, args.time_limit)
    if args.gate in ("literature", "all"):
        run_literature(args.weighting, args.time_limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
