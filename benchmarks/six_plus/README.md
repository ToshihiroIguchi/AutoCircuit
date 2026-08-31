# `benchmarks/six_plus` — topology discovery above five elements

The measurement half of `docs/TOPOLOGY_6PLUS_PLAN.md`. Read that document's §2 first: "six
elements does not work" is four independent problems — information, search, parameters, reporting
— and every script here is deliberately about one of them, because an experiment that cannot say
which axis it moved is not worth running.

Everything needs the project interpreter and the source path:

```powershell
$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"
```

**Use `py -3.13`.** `python` on this machine is 3.12 and has no numpy — that install exists for
`autoeis` (`docs/HANDOFF.md` §32). A `ModuleNotFoundError: numpy` here means the wrong
interpreter, not a broken environment.

## The files

| file | axis | what it answers |
|---|---|---|
| `truths.py` | — | The nine pre-registered truths, three shapes × three sizes, and the four-part admission screen every one of them passes |
| `oracle.py` | parameters | With the true topology given and no search at all, does the fitter reach the optimum? (X8) |
| `order.py` | information | Can a rational fit to Z(s) say how many relaxations the data supports? (X9) |
| `recovery.py` | all four | Does the whole pipeline recover the truth, across shapes and sizes? (X4) |
| `build_arenas.py` | search | Freeze one `screening_round` landscape and target set per truth |

## `truths.py` — the truth set

```powershell
py -3.13 benchmarks/six_plus/truths.py                 # list them
py -3.13 benchmarks/six_plus/truths.py --check --incumbent   # run the four-part screen
py -3.13 benchmarks/six_plus/truths.py --tune          # re-derive the parameter values
```

Three shapes (`parallel`, `series`, `mixed`) × three sizes (5, 6, 7). **Shape is read off the
parsed tree and asserted at import time**, so a mislabelled truth cannot be used. The
five-element row is the negative control: a method that always grows to six elements would score
perfectly on recovery and be worthless.

**Why the values are searched rather than chosen.** Five of nine hand-picked sets failed the
screen, one at 0.023% leverage against 1% noise. `tune()` maximises the *weakest* parameter's
leverage; `tune_until_screened()` then checks the result and tries another seed if it fails,
because — measured — maximising leverage is necessary and not sufficient: `ser6`'s first tuned
set scored 9.9% and still could not be fitted, since the tuner had opened a parallel branch and
collapsed the circuit to a series R-C-L.

The four parts, in the order they are cheap:

1. every parameter's leverage exceeds the noise (no fit needed);
2. the search's own feasibility filter does not delete the truth;
3. fitting the truth to its own noisy data leaves no unresolved parameter;
4. the value-matched deviation stays under 50%.

Part 2 was added here, after it caught a truth the other three passed. See
`survives_feasibility`'s docstring for the mechanism — it is a real assumption in the library,
not a quirk of this truth.

## `oracle.py` — X8, the parameter ceiling

```powershell
py -3.13 benchmarks/six_plus/oracle.py --out benchmarks/six_plus/x8_oracle.json `
    --budgets "r1/p8/m40,r5/p20/m400,r20/p20/m400" --fit-seeds 12 --workers 1
```

Noise-free data makes this decidable: the truth's own parameters give cost exactly zero.
**Run it with more than one `--fit-seeds`.** The first version of this file ran one seed per
cell, which cannot separate a budget that is too small from a basin the search only sometimes
reaches, and it read the two cases backwards.

## `order.py` — X9, rational-approximation order estimation

```powershell
py -3.13 benchmarks/six_plus/order.py --out benchmarks/six_plus/x9_order.json --seeds 5
```

Three estimators (`scipy.interpolate.AAA`, a hand-rolled Loewner pencil, a stabilisation
diagram), scored against truths whose relaxation count is known. **This is a completed negative
result** — exact on dense noise-free data, 0.04–0.20 exact-recovery at 1% noise — and no
production code follows from it. It is kept runnable because a rejection that cannot be re-run is
a claim rather than a measurement.

## `recovery.py` — X4, the end-to-end gate

```powershell
py -3.13 benchmarks/six_plus/recovery.py --out benchmarks/six_plus/x4_recovery.json --workers 8
py -3.13 benchmarks/six_plus/recovery.py --out ... --arms base,grow      # the primary comparison
```

Resumable: it writes after every run and skips what is already on disk, so an interrupted run
keeps its hours. Four arms crossing `growth_width` with `screen_restarts`; `base` is the shipped
configuration and is never omitted.

Three readings per run — `reported`, `on_front`, `recommended` — **never pooled**, because the
search owns the first two and the report owns the third, and a number that merges them cannot say
which moved. The five-element truths are scored separately, on whether the recommendation is
*over-grown*.

This is wall-clock and therefore the *last* check, never the comparison: for comparing searches
in a unit that does not drift with machine load, use `benchmarks/screening_round` and count fits.

## `build_arenas.py` — one frozen landscape per truth

```powershell
py -3.13 benchmarks/six_plus/build_arenas.py --dry-run
py -3.13 benchmarks/six_plus/build_arenas.py --workers 8
```

Long: `--n-max 7` on the R,C,L pool is 11,033 screening fits, about 15 minutes on 8 workers, and
the target pass refits every candidate inside the truth's cost band. Resumable and idempotent —
an existing landscape or target file is skipped.

Five-element truths get `--n-max 6` and the larger ones `--n-max 7`; the reasoning is in the
module docstring, and the short version is that the negative control only needs to be able to
show a *sixth* element being wrongly preferred.
