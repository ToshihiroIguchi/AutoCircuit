# Web UI — Phase 6 Plan

Status: draft for approval (2026-08-09). Nothing here is implemented.
Prerequisite reading: `docs/IMPLEMENTATION_PLAN.md` §9 (the original sketch, now partly
superseded by measurement), `benchmarks/pyodide/README.md` (every performance number below),
and `docs/HANDOFF.md` §3.

## 1. What is already settled by measurement

The original §9 sketch was written before anything had been run under WASM, and it hedged
accordingly: "if in-browser topology search proves too slow, options are (a) reduced default
budgets, (b) Rust/WASM port of the fitness inner loop". Both hedges can be dropped.

| question | answer | evidence |
|----------|--------|----------|
| How much slower is WASM? | 1.3–1.8× on numerical work, 3.9× on the import | `benchmarks/pyodide` |
| Does the fitter need a smaller web budget? | **No** | same fit budget, 1.3× |
| Rust port of the inner loop? | **No** | the cost is already in WASM-compiled numpy/scipy |
| Cold start to first fit | ~4 s (1.2 boot + 1.1 packages + 1.6 import) | same |
| `discover` at `exhaustive_limit=4`, 1 thread | 169 s | same |
| Worker pool speed-up | ~2.3× at 4 workers, saturating; 8 is worse than 6 | `run_workers.mjs` |

Two consequences shape the whole design:

1. **A real search takes minutes, not seconds.** 169 s single-threaded, ~75 s across four
   workers. There is no arrangement of this software that makes topology discovery feel
   instant in a browser, so the UI has to be built around a long-running job — streamed
   progress, partial results, and a cancel button — rather than around a request/response.
2. **`fit` on a known topology takes under a second**, and that is the interactive path. The
   two modes deserve different treatment in the UI: manual fitting is live, discovery is a job.

A third point is worth stating because it is counter-intuitive: **the screening budget must not
be reduced for the browser.** `benchmarks/discovery_v2.py screen-rank` measured what happens
when it is, and the answer is that the truth drops off the tier-2 shortlist while its exact
equivalents stay on it — so the report still looks healthy. Trading correctness for browser
latency is exactly the trade this project exists not to make. Reduce `exhaustive_limit`
instead: that costs *coverage*, which `complete_up_to` reports honestly.

## 2. Architecture

```
  main thread (React)                    worker pool (N Pyodide instances)
  ┌───────────────────────┐              ┌──────────────────────────────┐
  │ file import, plots,   │  postMessage │ autocircuit.core             │
  │ circuit canvas,       │─────────────>│  read / validate / fit       │
  │ Pareto front, report  │<─────────────│  screen (tier 1, fanned out) │
  └───────────────────────┘   progress   │  discover (tier 2)           │
                                         └──────────────────────────────┘
```

- **Static site, no server.** Vite + TypeScript + React, deployable to GitHub Pages. Confirmed
  viable: everything the CLI does runs in Pyodide unchanged.
- **The core is shipped as source, not a wheel.** `benchmarks/pyodide/make_zip.py` already
  demonstrates the mechanism (`unpackArchive` into the Pyodide FS, put it on `sys.path`).
  A wheel is nicer but adds a build step for no measured benefit; revisit if it matters.
- **Worker pool sized 4 by default**, `navigator.hardwareConcurrency` capped at 4, because the
  measured speed-up saturates there and eight workers were *slower* than six. Each worker costs
  ~1.5 s of start-up and its own copy of numpy/scipy, so the pool is created once at load and
  kept.
- **Nothing but strings and typed arrays crosses the boundary.** `core/discover.py`'s tier-1
  worker already re-parses a circuit string by design, so the same contract works here
  unchanged. This is the one place where the existing code was built for the browser in
  advance and it should be kept that way.

**Open design question for the planning session:** the parallel screen currently lives inside
`discover()`, which uses `multiprocessing`. In the browser the fan-out has to happen in
JavaScript instead. Two options:

- (a) Expose the stages separately (`enumerate_feasible()`, `screen_many(texts)`,
  `refit_shortlist(scored)`) so the JS side orchestrates. Honest, but it moves the two-tier
  logic — including the per-size quota that gate G1 depends on — into JavaScript, where it is
  untested and can drift from the Python one.
- (b) Keep orchestration in Python, run `discover(workers=1)` in **one** worker, and have that
  worker delegate its screen through a callback into JS. Keeps a single implementation of the
  logic that G1 covers; costs a round trip per chunk.

(b) is the safer default given how much of this project's value sits in that shortlist logic,
but it needs a prototype before committing. Neither option is a code change to make blind.

## 3. Screens

Following ZView's workflow, which is what the target users know:

1. **Data** — drag-drop import (all four readers already exist), a table of loaded spectra,
   frequency-window trimming, and the Lin-KK verdict shown *before* anything is fitted. The
   validator's runs-test explanation text is already written; reuse it verbatim.
2. **Fit** — circuit canvas (drag-drop series/parallel blocks reading like a schematic) with a
   live model preview overlaid on the data before fitting. This is the differentiator and it
   should feel like the point of the app: no initial values, press Fit, get parameters with
   honest standard errors. Sub-second, so no progress UI needed.
3. **Discover** — the job screen. Pool selection, `exhaustive_limit`, live progress
   (`on_progress` already reports `done/total/best`), streamed partial Pareto front, cancel.
   The completeness line (`complete_up_to`) is displayed as a first-class result, not a
   footnote — it is the thing the genetic search could never say.
4. **Report** — equivalence classes shown as classes, never as a ranked list with a winner;
   JSON / CSV / netlist download; the DRT structure probe beside the search as the CLI already
   prints it.

Plots: linked Nyquist / Bode(|Z|, θ) / residuals, zoom-synced, log axes. Plotly.js to start
(fast to ship, replaceable) — the only external JS dependency of consequence.

## 4. What must not regress

- **`numpy` and `scipy` stay the only runtime dependencies of the Python core.** The web build
  may add JS dependencies freely; it may not add Python ones.
- **No file-dialog, GUI or OS-specific code in `autocircuit.core`.** File handling is the JS
  side's job; the core takes arrays.
- **The web UI must not fork the science.** Every number it displays comes from the same
  functions the CLI calls. If the browser needs different behaviour, it gets a different
  *argument*, not a different code path.

## 5. Work order

| step | contents | size |
|------|----------|------|
| 1 | Pyodide worker harness + the §2 orchestration decision, prototyped both ways | M |
| 2 | Vite/React scaffold, data import, plots, Lin-KK panel | M |
| 3 | Circuit canvas + live preview + manual fit | L |
| 4 | Discovery job screen: progress, streaming, cancel, completeness | M |
| 5 | Report: equivalence classes, exports, DRT panel | M |
| 6 | Example datasets, loading states, dark/light, deploy to Pages | S |

## 6. Acceptance gates

- **W1** — the browser and the CLI produce identical fitted parameters for the nine-circuit
  synthetic corpus, to the last reported digit. Same code, so any difference is a bug in the
  bridge.
- **W2** — `discover` at `exhaustive_limit=4` on the capacitor reference completes in the
  browser, streams progress at least once a second, and reports the same
  `complete_up_to` and equivalence classes as the CLI.
- **W3** — cold load to an interactive first fit under 10 s on a mid-range laptop.
- **W4** — cancel actually stops the work (not just the UI), and a cancelled run reports the
  coverage it reached rather than a wrong number.
- **W5** — the site works offline after first load, and from `file://` as well as Pages.

## 7. Out of scope

- Server-side compute of any kind. The moment there is a backend, the "static site" property
  and its deployment story are gone.
- Multi-user features, project files, cloud storage.
- Rewriting the fitter in Rust/WASM. Measured as unnecessary (§1); revisit only if a profile
  says otherwise.
