# How much slower is AutoCircuit in a browser?

Phase 6 of `docs/IMPLEMENTATION_PLAN.md` puts the same core in a browser through Pyodide, and
three of its design decisions were resting on a guess about WASM performance: what
`exhaustive_limit` can default to, whether progress has to be streamed, and whether the fitter
needs a separate reduced budget for the web. This measures it.

No browser is involved, and none is needed: Node and a browser load the identical Pyodide WASM
build, and nothing measured here touches the DOM, the network or a worker boundary.

```powershell
$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"
python benchmarks/pyodide/bench.py            # CPython baseline

cd benchmarks/pyodide
npm install
python make_zip.py
node run_pyodide.mjs src.zip bench.py         # the same script under Pyodide
```

`bench.py` is deliberately shared between the two: a browser-versus-desktop ratio is only worth
having if both sides ran identical code. Everything is single-threaded, because a browser has
no `multiprocessing`.

## Results

Pyodide 314.0.3 (Python 3.14.2, numpy 2.4.3, scipy 1.18.0) under Node 24 against CPython 3.13.14
with numpy 2.5.1 and scipy 1.17.1, same machine, both single-core. Medians.

| operation | CPython | Pyodide | ratio |
|-----------|--------:|--------:|------:|
| `import autocircuit...` | 0.40 s | 1.58 s | 3.9× |
| `fit`, 3 parameters | 0.163 s | 0.265 s | 1.6× |
| `fit`, 6 parameters | 0.704 s | 0.906 s | 1.3× |
| `screen`, 3 elements | 13.3 ms | 23.6 ms | 1.8× |
| `screen`, 4 elements | 32.2 ms | 45.1 ms | 1.4× |
| `lin_kk` | 10.2 ms | 20.1 ms | 2.0× |
| enumerate + feasibility, n ≤ 5 (6,598 kept) | 0.200 s | 0.316 s | 1.6× |
| `discover`, R/C pool, n ≤ 4 (17 screened) | 4.95 s | 7.10 s | 1.4× |
| **`discover`, component pool, n ≤ 4 (741 screened)** | **127.5 s** | **169.1 s** | **1.33×** |
| Pyodide boot | — | 1.17 s | — |
| numpy + scipy load (warm cache) | — | 1.1 s | — |

**WASM is not the problem.** The plan's risk section expected "minutes-not-seconds"; the real
penalty on the numerical work is 1.3–1.8×, because the expensive part is numpy and scipy
compiled to WASM rather than interpreted Python. The interpreter-bound paths pay more — the
import is 3.9× — but that is a one-off 1.6 s. The ratio is *smallest* on the heaviest job,
which is the good direction.

What this settles for phase 6:

- **Cold start to the first fit is about 4 s**: 1.2 s boot, 1.1 s numpy/scipy from cache
  (2.2 s the first time, when the wheels are fetched), 1.6 s importing the package. That needs
  a loading state, not an architecture.
- **`exhaustive_limit=4` is the right web default, and it is 2.8 minutes** single-threaded, or
  a measured 2.0 min end to end across a four-worker pool (both tiers fanned out, last section).
  Not seconds either way, so progress streaming through the existing `on_progress` callback is
  required, not a nicety.
- **`exhaustive_limit=5` is not a default.** The same search over 6,598 candidates costs ~22
  min single-core on CPython, so ~30 min here, and a worker pool only takes that to ~12 min.
  It stays available as an explicit choice.
- **The fitter does not need a separate web budget.** `restarts=5, popsize=20` and the
  `8×40` screen run 1.3–1.6× slower and are otherwise unchanged, and the screening budget is
  already known to have no headroom (`benchmarks/README.md`, `screen-rank`). Cutting it for the
  browser would trade the answer for the clock in exactly the way that experiment measured.

## Does it scale across Web Workers?

The browser has no `multiprocessing`, so the CLI's `--workers` has no direct analogue — but it
does have Web Workers, and each can hold its own Pyodide instance. Screening is embarrassingly
parallel and `core/discover.py`'s tier-1 worker already takes a circuit string and re-parses
it, so nothing but strings and arrays would have to cross the boundary. Whether that actually
buys anything decides what the web UI can offer.

```powershell
node benchmarks/pyodide/run_workers.mjs src.zip "1,2,4,6,8"
```

Screening the whole capacitor n ≤ 4 space (741 candidates) on a 12-core machine, one Pyodide
instance per Node worker thread — the same isolation shape as a browser worker:

| workers | start-up | screen | speed-up |
|--------:|---------:|-------:|---------:|
| 1 | 4.7 s | 94 s | 1.00× |
| 2 | 6.4 s | 59 s | 1.6× |
| 4 | 9.3 s | 41 s | 2.3× |
| 6 | 11.4 s | 37 s | 2.5× |
| **8** | 13.5 s | **44 s** | **2.2×** |

**Parallelism helps, but far less than on CPython, and it stops helping at about four
workers.** Eight is slower than six. Treat the ratios as the *shape* rather than as precise
figures: a repeat of the single-worker case came out 30% apart (94 s and 124 s) run to run, so
these are single-run numbers with real error bars. The shape is clear enough to design
against, and it is the opposite of the CLI's, where `--workers 8` is the main lever.

Start-up grows roughly 1.5 s per worker, since each instance loads its own copy of numpy and
scipy. Four workers cost ~9 s of start-up to save ~50 s of screening on this workload, so the
pool is worth having but wants creating once and keeping.

## Does the browser get the same answer as the CLI?

`run_orchestrated.mjs` is the prototype of the architecture `docs/WEB_UI_PLAN.md` §2.1 settles
on: orchestration stays in Python — `discover.screen_plan()` yields batches of screening work
and receives their costs, `discover.refit_plan()` does the same for the full-budget refits —
while JavaScript does nothing but carry those batches out to workers. Nothing that gate G1
depends on is reimplemented in JS.

```powershell
node benchmarks/pyodide/run_orchestrated.mjs src.zip 4
```

Capacitor reference, `exhaustive_limit=4`, four Pyodide workers, against CPython with four
processes:

| | browser | CPython |
|---|---|---|
| candidates screened | 741 | 741 |
| `complete_up_to` | 4 | 4 |
| refitted candidates | 37, same order | 37 |
| worst AICc difference | **0.0** | — |
| recommendation | `[C-L-R-SKINF]` (the truth) | same |
| tier 1 | 37 s | — |
| tier 2 | 86 s | — |
| total | **123 s** | 90 s |

Identical results, which is the point: every one of the 37 refitted candidates, the whole
Pareto front and the recommendation match the run made when tier 2 was still serial, so
fanning it out changed the clock and nothing else.

**Tier 2 used to be 80% of this run** — 232 s of 287 s — because a refit returns a whole
`FitResult` and there was no way to get one across a worker boundary without losing the
covariance and the restart spread. `FitResult.to_wire()` is that way (see
`docs/WEB_UI_PLAN.md` §2.2), and with it the stage drops to 86 s and the browser lands within
1.4× of CPython's four-process time instead of 3.2×.

Two things about the fan-out are worth keeping:

- **Refits are handed out one at a time, not sliced up front.** The screen can be split
  round-robin because 741 sloppy fits average out; full-budget fits of different topologies
  differ by an order of magnitude, so a static split leaves most of the pool waiting on
  whichever slice drew the expensive ones.
- **The payload is ~7 KB per candidate** at 71 frequency points (values, fitted response,
  residuals, standard errors and the correlation matrix, as JSON text). Against a stage that
  costs minutes, recomputing any of it to save that is the wrong trade — and recomputing
  `z_model` in particular would stake the browser's agreement with the CLI on numpy returning
  bit-identical results in a second WASM interpreter. That has since been measured, by
  `run_fit_parity.mjs` below, and the answer is that it would have been wrong for any circuit
  built on a transcendental.

Timings are single-run and this workload is noisy: the tier-1 screen came out 55 s in the
earlier run and 37 s here with identical work, in line with the ±30% seen in the worker sweep
above. Treat the ratio, not the seconds, as the result.

`src.zip` is a build artifact (gitignored); `make_zip.py` regenerates it. It exists because
PowerShell's `Compress-Archive` writes backslash separators that Python's `zipfile` unpacks
into files literally named `autocircuit\__init__.py`, which fails only at the import.

## `fit_parity.py` + `run_fit_parity.mjs` — gate W1

Does a manual fit in the browser return what the command line's does?

```powershell
python benchmarks/pyodide/fit_parity.py          # the CLI's half -> fit_parity_ref.json
node benchmarks/pyodide/run_fit_parity.mjs src.zip
```

The reference file carries the *spectra* as well as the answers, and the corpus is imported from
`tests/test_fit.py::SYNTHETIC_SUITE` rather than copied, so the two interpreters demonstrably fit
the same numbers and the nine circuits stay defined in one place. The browser half goes through
`autocircuit.web.bridge.handle` — the entry point the Pyodide worker in `web/` calls — not
through Python the browser never runs.

**[measured]** at three restarts, seed 0:

| comparison | result |
|------------|--------|
| 34 fitted parameters, six significant digits | all agree |
| 34 fitted parameters, bit for bit | none agree; worst relative difference 2.4e-7 |
| 1042 impedance components at CPython's fitted values | 1001 bit-identical, worst 5.0e-14 |

The second row is the finding: a fitted parameter travels through differential evolution and a
trust-region solve, so a last-bit difference compounds into the optimizer's *path*, and only its
answer is reproducible across interpreters. The third row locates the difference — evaluating a
circuit is bit-identical everywhere except the skin-effect-on-a-wire case, whose `tanh` and
complex `sqrt` come from a libm that differs between WASM and the desktop.

WASM is 1.2–4× slower per fit here (8.1 s against 0.8 s on the easiest, 36 s against 48 s on the
hardest — that last one favouring the browser, which is noise, not a result).
