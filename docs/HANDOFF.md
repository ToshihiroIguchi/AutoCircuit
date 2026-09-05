# Handoff — state of AutoCircuit as of 2026-08-16

Written at the end of the session that built the backend, updated after discovery v2 steps
1–5, again after the skeleton-constrained mode (all of `docs/PARTIAL_TOPOLOGY_PLAN.md`), and
again after each step of `docs/WEB_UI_PLAN.md` (all seven now), again after the ngspice
round-trip (§15), again after taking both workflows off Node 20 (§16), and again after the three
questions the deployed site raised — what the Discover→Fit hand-off carries, moving an element that
is already on the canvas, and a start-up that made a visitor wait for scipy before it would read a
CSV (§19), and again while giving the genetic search its first quality gate (§20, and **finished
at §31** — all six steps of `docs/EVOLVE_SEARCH_PLAN.md`, two EV4 clauses recorded as failed
rather than reworded), and again after the first of the geometry-free readouts that `CLAUDE.md`'s purpose
point 2 asks for (§21 — landed and gated, with its own list of what is not done), and again
after the reporting-path defect that the search-algorithm screening round turned up (§23) and the
bounded breeding pool that round recommended (§25).
Read this first, then `CLAUDE.md`, then the plan for whichever part you are touching.

## 1. Where things stand

The command-line backend is **complete and verified**: [measured] 797 tests collected, **778
pass and 19 skip** on this machine (`python -m pytest tests -q`, 9 min 15 s on the run that
produced these numbers — and that is one full run, not a union of subsets). The nineteen skips
are the ngspice round-trip (§15), because ngspice
does not run on Windows; `.github/workflows/tests.yml` installs it, and §4 says how to run them
here through WSL. [measured] On `ubuntu-latest` **all 712 run**, the round-trip among them, in
417 s on one run and 520 s on another — same suite, different runner, so the spread is not a
regression (§16). Phases 0–6 of `docs/IMPLEMENTATION_PLAN.md` are done. Phase 6 (web UI) has **all seven steps built
and measured**: a lossless `FitResult` across a worker boundary, so the browser fans out both
tiers of the search (§8); the Data screen — import, plots and the Lin-KK verdict — running the
same core through Pyodide (§9); the Fit screen — schematic canvas, live preview and a manual fit
that needs no initial values (§10), which closed gate W1; the Discover screen — the topology
search as a job, with streamed progress, a partial Pareto front and a cancel that terminates the
workers (§11), which closed gates W2 and W4; the Report screen — equivalence classes as
classes, what a skeleton excluded, the downloads and the DRT probe (§12), which closed gate W6;
the finish — example data, dark/light, honest loading states and the deployment (§13); and
step 7, which shipped the Python side compiled and closed the last two gates (§14).

**The site is live at <https://toshihiroiguchi.github.io/AutoCircuit/>**, published by
`.github/workflows/pages.yml` on every push to `main`. Step 7 (§14) closed the two gates step 6
left open, in opposite ways: **W3 passes on a rested machine and not on a loaded one** — the cold
start went ~13 s → ~5 s by shipping bytecode instead of source, which is about 2×, and the 10 s
target now sits inside this machine's own 2× drift — and **W5 is retired**, because a `file://`
page cannot load this application at all (measured) and the offline half was declined rather than
built. Phase 6 is therefore complete.

**Discovery v2 is fully implemented** (see §2) and all five gates pass: G1 30/30 across the
three reference spectra, G2 exactly reproducing the measured counts table, G3 with the truth
and every known exact equivalent surviving the feasibility filter, G4 with DRT counting 1, 2
and 3 relaxations 10/10 at both 0% and 1% noise, and G5 with the whole suite green.

**Skeleton-constrained discovery (mode 2 of `CLAUDE.md`) is implemented through step 4** —
`discover(skeleton=...)` and `--skeleton` work end to end, the completeness sentence names the
constraint, and the report states placement ambiguity and total non-identifiability. §3.3 —
naming the indistinguishable topologies the skeleton excluded — is opt-in rather than
automatic, because the plan's estimate that it was cheap was wrong and the corrected cost is
about that of the search itself. **Gates P1, P3 and P4 pass; P2's experiment has been run and
rewrote the gate** — a wrong skeleton turns out to be invisible in the residuals and in chi²,
and the one place it does surface is an asserted element the fit had to switch off, which the
report now names. See §7.

Working end to end today:

```powershell
$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"
python -m autocircuit elements
python -m autocircuit simulate -c "C1-R1-L1-SKINF1" -p C1.C=1e-6 -p R1.R=1e-2 `
    -p L1.L=5e-10 -p SKINF1.A=2e-5 -p SKINF1.n=0.5 --fmin 100 --fmax 1e9 --noise 0.01 -o cap.csv
python -m autocircuit validate cap.csv
python -m autocircuit fit cap.csv -c "C1-R1-L1-SKINF1" --spice cap.cir --json cap.json
python -m autocircuit discover cap.csv --pool component --workers 8 --progress
python -m autocircuit discover cap.csv --pool component --skeleton "C1-R1-L1" --workers 8
python -m autocircuit discover cap.csv --pool component --mode evolve --time-limit 120
python -m autocircuit drt cell.csv --json drt.json     # exits 1 if DRT does not apply
```

Module map (`src/autocircuit/`):

| module | role |
|--------|------|
| `core/elements.py` | 12 elements; broadcast-safe `impedance()`; data-derived bounds; endpoint slope metadata |
| `core/circuit.py` | series/parallel AST, canonical forms, `simplify`, value canonicalisation |
| `core/dsl.py` | parser for `R1-p(C1,R2-W1)` |
| `core/fit.py` | the no-initial-values fitter (log transform → DE → TRF polish → restarts); `screen()` for rank-only fits |
| `core/stats.py` | covariance, AICc, identifiability warnings |
| `core/validate.py` | Lin-KK data validation |
| `core/enumerate.py` | exhaustive topology enumeration, skeleton-constrained growth, the structural feasibility filter |
| `core/drt.py` | regularised distribution of relaxation times; structure probing only |
| `core/interpret.py` | a fitted circuit read as internal structure, split invariant vs form-dependent |
| `core/discover.py` | exhaustive and genetic topology search, Pareto front, equivalence classes |
| `core/wire.py` | lossless JSON encoding of the arrays that cross a worker boundary |
| `web/bridge.py` | the browser's only entry point: JSON in, JSON out, no decisions |
| `core/spice.py` | netlist export + NNLS Foster-form ladder synthesis |
| `io/` | generic CSV, ZView/ZPlot, Touchstone, Keysight readers |
| `cli/main.py` | argparse CLI |

## 2. Discovery v2 — what was built

All seven steps of `docs/DISCOVERY_V2_PLAN.md` are implemented; that file's §5 table records
the status of each, §5.1 what the search implementation added that the plan had not foreseen,
and §5.2 the same for DRT.

The rationale, so it is not re-litigated: the filtered topology space at ≤ 5 elements is only
~10²–10⁴ candidates and exact degeneracy is bounded at 1–4 equivalents per truth, so
enumeration beats stochastic search outright — it is affordable *and* it can state "every
plausible topology up to N elements was evaluated", which the genetic search can never claim.
The GP is now a fallback for > 5 elements.

Four things worth knowing before touching this code:

- **`benchmarks/topology_space.py` still has its own enumerator, on purpose.** The library one
  filters sub-levels and streams; the benchmark one is the naive version. Gate G2 is checked
  against an independent implementation that way. Their outputs were compared as *sets* for
  every pool through n = 6: identical.
- **`discover()`'s default mode is now `"auto"`**, so calls that used to run a quick genetic
  search now enumerate first. Tests that are specifically about the genetic operators pass
  `mode="evolve"`; that is why `tests/test_discover.py` has `FAST_EVOLVE`.
- **The feasibility filter is conservative by construction and therefore modest**: 1.75× on
  the capacitor sweep, 1.15–1.18× elsewhere, against the 2–5× the plan hoped for. The lever
  that actually matters is `--workers`.
- **`discover.screen_plan()` is a generator on purpose, and it is the browser's seam.** It
  yields batches of screening work and receives their costs, so the batching and the
  early-abandon thresholds — the decisions gate G1 rests on — have exactly one implementation
  no matter who runs the work: in-process, a process pool, or JavaScript fanning batches across
  Web Workers. Do not "simplify" it back into the loop it came from; that would put a second
  copy of that logic in JavaScript, untested.
- **`core/drt.py` is deliberately not wired into the search.** The CLI prints it beside the
  discovery report and `core/discover.py` does not import it at all. That is a decision, not
  an omission — see `docs/DISCOVERY_V2_PLAN.md` §3.4 and §6 item 0 below.

## 3. Facts that cost real time to establish

Do not re-derive these; do not "fix" them without reading the reasoning first. Each is
recorded in the code as a comment and in `docs/IMPLEMENTATION_PLAN.md` marked **[measured]**.

- **Covariance must be computed in the log search space**, then mapped to parameter units.
  In parameter space the Gauss-Newton Hessian has condition number ~1e20 and its
  pseudo-inverse collapses to near rank one, reporting a spurious ±1.0000 correlation between
  every pair of parameters.
- **The Lin-KK linear solve needs column scaling.** Without it a series RLC — which is
  exactly representable in the Lin-KK basis — came out with 6.9% residual instead of zero.
- **Lin-KK pass/fail cannot be a fixed residual threshold.** 1%-noise data legitimately gives
  ~2.7% peak residuals. The decision is a runs test on residual *signs*: noise alternates,
  a KK violation is smooth.
- **A failed Lin-KK test does not always mean the data is bad, and the report used to say it
  did.** The Voigt basis plus the three series terms has only real poles, so a complex *pole*
  of Z — an anti-resonance — is unreachable at any order. On a Butterworth-Van Dyke spectrum,
  which is KK-compliant by construction, the residual is 96.8% of |Z| from M = 3 to M = 317,
  flat to four figures: the order scan and the mu criterion are working, there is simply
  nothing to select. A genuine violation looks nothing like it — 40% drift is *tracked* to
  1.8% RMS — which is the discriminator sitting in `validate.MODEL_FAILURE_RMS` (25% RMS).
  Above it the outcome is `verdict == "inconclusive"`: the summary says the test could not be
  applied, the CLI exits 2 rather than 1, and the browser's badge reads NO VERDICT.
  **`passed` is deliberately unchanged**, so no threshold or measured number moved — only what
  the failure is allowed to blame. Do not "fix" this by making such spectra pass.
- **Three things about that escape are measured, and two of them are not what you would
  guess.** (a) *`passed` must be asked before the residual magnitude.* Noise inflates the
  residual without being a violation: KK-compliant data at 30% and 50% noise reads 28.1% and
  43.7% RMS, over the threshold, while passing correctly on the runs test. `KKResult.verdict`
  is the single place that order is decided, and the browser takes it over the wire rather
  than rebuilding it. (b) *A series resonance is representable.* A series R-L-C **is** the
  three series terms of the basis and passes at 0.98% residual; it is the pole, not the
  resonance. (c) *A residual magnitude alone does not catch it.* A moderately damped
  anti-resonance is half-reached — the same resonator at Q = 2, 3, 5, 10, 15 gives 1.3%, 2.6%,
  4.6%, 17.6%, 24.5% RMS, all under the threshold, with runs z from −5.7 to −17.3 — so the
  threshold reads those as a plain failure. That band is closed by the *resonance probe*; see
  the next entry and `docs/KK_RESONANCE_PLAN.md`.
- **The resonance probe is a probe and not a basis, and the measurement is why.** Giving the
  Lin-KK basis complex poles works mathematically — a parallel R-L-C block with its resonance
  and Q fixed on a grid keeps the amplitude linear, exactly as a fixed τ does — but **shipping
  it as the test destroys the test**. [measured] With a 200-column bank, a 61-point Randles
  spectrum drifting 1000% fits to **0.00% residual with random residual signs**: 122 equations
  cannot constrain 223 unknowns. The bank must be counted against the same `2 * len(spectrum)`
  budget as the Voigt elements, and even then sizing it is a two-dimensional order scan that
  moves every Lin-KK number here — a prototype that split the budget one third to relaxations
  was measured to *fail clean Randles data* at 14.1% residual. So the bank is used only to ask
  a second question of spectra that have **already failed**, at `PROBE_COLUMN_FRACTION` (15%)
  of 2N columns, and it can only ever turn `fail` into `inconclusive`. Nothing that passes is
  reachable from it, so no recorded number moved. Gates K1–K4 in `benchmarks/kk_resonance.py`:
  the drift family stays `fail` 12/12 across two orders of magnitude of drift and three point
  densities, and the resonator family reads `inconclusive` at Q = 2 to 300. Do not raise
  `PROBE_COLUMN_FRACTION` without re-running K2.
- **`SKINW`'s asymptotic branch needs three terms**, `J0/J1 = j + 1/(2q) - 3j/(8q²)`, and a
  switch at |q| = 1e5. The Hankel series converges as 1/|q|, *not* exponentially; the leading
  term alone at |q| = 300 left a 0.17% discontinuity.
- **`restarts=5, popsize=20`** is the measured optimum (0/25 failures). A larger population is
  worse per unit time.
- **Branch order must be canonicalised after fitting**, or symmetric circuits like
  `p(R1,C1)-p(R2,C2)` return either assignment at random and the uniqueness check misfires.
- **Elements are broadcast-safe on purpose.** `impedance()` takes `omega[None, :]` and
  `values[:, :, None]` to score a whole optimizer population in one call; this tripled
  discovery throughput. Never add a `float(values[i])` cast.
- **Equivalent circuits can be exactly identical.** `R1-p(R2,C1)` and `p(R1,C1-R2)` fit the
  same data to 1.2e-15. Reporting one as "the answer" is wrong; `DiscoveryResult` groups them.
- **AICc is a bad headline.** On a 71-point capacitor spectrum minimum-AICc selected a
  9-parameter circuit with two parameters whose standard errors exceeded their own values.
  `DiscoveryResult.recommended` applies parsimony instead.
- **Filtering the enumerator's sub-levels is safe**, and it is what makes enumeration fast.
  If a branch collapses under `simplify` then so does any network containing it, and if a
  branch is implausible then so is any network containing it — both properties are defined by
  recursion over every node of the tree. The counts were verified against the independent
  prototype before this was relied on.
- **Early abandon must switch itself off against an exact reference.** Skipping the polish for
  candidates 100× worse than the best of their complexity is a large saving, but on noise-free
  data the first *exact* equivalent screened sets a reference of order 1e-30, and every other
  exact equivalent then gets abandoned unpolished — losing precisely the equivalence class the
  report exists to produce. Hence `PERFECT_COST` in `discover.py`.
- **A screening pass must not rank by raw residual across sizes.** Raw cost always improves
  with parameters, so ranking the whole screen by it put nothing but five-element circuits on
  the tier-2 shortlist: on the capacitor reference all 60 shortlisted candidates had five
  elements and the four-element circuit *that generated the data* was never refitted. The
  shortlist is now a per-element-count quota ranked by a screening AICc. This was invisible in
  every small test case, because in a small space the shortlist covers every size anyway.
- **The tier-1 screening budget cannot be cut, and the capacitor reference cannot tell you
  that.** `popsize=8, maxiter=40` is the measured floor. Halving it is tempting — the screen is
  most of the runtime — and on the capacitor sweep the truth screens to rank 1 of 657 at every
  budget tried, so a 4× cut looks free. On the electrochemical references it is not: at
  `8×20` the Maxwell-Wagner truth screens to 1452× the best cost of its own size, falls to
  rank 19 of 330 and misses the shortlist, *while its three exact equivalents stay at ranks
  1–3* — so the report still looks healthy. `benchmarks/discovery_v2.py screen-rank` is the
  experiment; it exists because a 54-candidate sample could not have shown this.
- **A DRT peak cannot be thresholded against the tallest peak in the distribution.** The
  smaller block of the two-block Maxwell-Wagner reference — the case the module was built for
  — carries 2% of the total polarisation, and any "fraction of the largest peak" threshold
  high enough to reject regularisation ripple also rejects the block. A weight threshold
  cannot separate them either: the ripples carry 0.6–3.0%. The discriminator is the noise —
  the real block moves |Z| at its own frequency by 140× the RMS residual, the ripples by 0.6×.
- **DRT must be allowed to report that it does not apply.** A sum of capacitive RC relaxations
  cannot carry a distributed inductive process, so on the capacitor reference it returns no
  peaks, a series resistance wrong by 7× and a 64% residual. `well_described` exists so that
  is reported rather than dressed up as "0 relaxations".
- **"Contains the skeleton" is deletion-and-collapse, not subtree matching.** `series()` and
  `parallel()` flatten nested nodes of the same type, so the skeleton `R1-C1` is *not* a
  subtree of `R1-C1-p(R2,L1)` — that tree is one three-child series node. A subtree test
  rejects the most obvious candidate the user expects.
- **Growing a skeleton by attaching elements at existing positions leaves a hole.** A
  sub-group of a flattened node's children is not an addressable position, so putting a
  capacitor across only the `C1-L1` half of `R1-C1-L1` cannot be built by any attachment.
  Attachment alone found 7 of the 16 four-element topologies containing that skeleton, and 58
  of 139 at five elements — a silent hole in exactly the completeness guarantee the mode
  exists to provide, in an implementation that looked complete. `_insertions()` therefore also
  groups proper subsets of a node's children; `tests/test_skeleton.py` names the case.
- **A skeleton is the largest lever in the system, by a wide margin.** At five elements from
  the component pool: no skeleton 10,214 candidates, `R1` 6,711 (1.5×), `R1-L1` 2,631 (3.9×),
  `C1-R1-L1` 601 (17×), `C1-R1-L1-SKINF1` 71 (144×). Against 1.15–1.75× for the feasibility
  filter and ~2.3× for the browser's worker pool. It also brings six elements into range.
- **Each added element costs 40–70× the last, and enumeration memory runs out before compute
  does.** From a ten-element skeleton: +1 is 167 candidates, +2 is 11,418, +3 is 521,438, +4
  is ~2·10⁷. The shape matters more than the size — the same ten elements as one flat series
  chain gives 2,148,316 at +2, 188× worse, because a flat node with c children has 2^c ways to
  group a proper subset. `grow_up_to()` therefore abandons a level *while building it*.
- **The frontier is 1.3–3.9× larger than the level it produces**, rising with each level, so a
  frontier bound equal to `max_candidates` stops short of the budget it exists to enforce.
  Hence `FRONTIER_HEADROOM = 4`: at exactly `max_candidates` a default run would have lost the
  9,857-candidate six-element level, grown from a frontier of 18,682.
- **`FitResult.to_dict()` cannot transport a fit, and widening it would be the wrong fix.** It
  is the CLI's `--json` *report*: no `z_model`, no residuals, no correlation matrix, no rank, no
  raw values array, no restart count, no fixed values — so `Statistics` cannot be rebuilt from
  it and neither can a `Candidate`. `to_wire()`/`from_wire()` are a separate format for exactly
  that reason (`core/wire.py`, and §2.2 of `docs/WEB_UI_PLAN.md`).
- **The non-finite path on the wire is routine, not defensive, and the test for it is
  `allow_nan=False`.** An exact fit on noise-free data has `ssr == 0.0`, which makes AIC, AICc
  and BIC all `-inf` — `p(R1,R2)` against a single resistor is the two-line demonstration in
  `tests/test_wire.py`. Python's `json.dumps` emits bare `Infinity`/`NaN` tokens by default and
  `JSON.parse` rejects them, so a payload that survives the default dump can still be
  undeliverable to a Web Worker.
- **A non-finite *standard error*, on the other hand, is unreachable from a real fit.**
  `compute_statistics` clips the covariance diagonal to ≥ 0 before the square root and runs
  `nan_to_num` + `clip(-1, 1)` on the correlation, so a rank-deficient fit reports a tiny finite
  stderr and a correlation pinned to exactly ±1. Only `_covariance`'s two failure returns fill
  those arrays with inf/nan. Do not go looking for a degenerate circuit that produces one.
- **Refits must be handed to workers one at a time; screens can be sliced up front.** 741
  sloppy screening fits average out, so round-robin is fine there. Full-budget fits of different
  topologies differ by an order of magnitude, and a static split leaves most of the pool waiting
  on whichever slice drew the expensive ones.
- **A feasibility filter that lets every element degenerate has no structural power at all.**
  If any element may be shorted or opened, the reachable endpoint-slope hull of *any*
  topology collapses to the union of its leaves' hulls — the test degenerates into "does this
  topology contain a suitable element type". That is why the degeneracy budget is finite
  (default 1) and why the measured reduction is what it is.

## 4. Environment quirks on this machine

- **No `uv`, no `typer`, and the package is not pip-installed.** Always set
  `$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"`. Run the CLI as
  `python -m autocircuit`. `numpy` 2.5.1, `scipy` 1.17.1, `pytest` 9.1.1, Python 3.13.
- **`ruff` and `mypy` are installed and clean** (`python -m ruff check .`, `python -m mypy`,
  both from the repo root). Two things about that setup are deliberate:
  - **`scipy-stubs` is a dev dependency**, without which mypy cannot see scipy at all.
  - **mypy's `python_version` is 3.12 while `requires-python` is 3.11.** Not an oversight: the
    stubs bundled inside numpy ≥ 2.3 use 3.12 `type X = ...` statements, so asking mypy for
    3.11 fails while parsing *numpy*, before it reaches this project. 3.11 support is a
    packaging claim checked by running the suite, not by the type checker.
  - One `# type: ignore[arg-type]` exists, in `fit.py`'s `differential_evolution` call.
    `scipy-stubs` has a single non-overloaded signature that always types `func` as
    scalar-returning and does not model `vectorized=True`, which is the convention that whole
    code path depends on. It is a stub gap, not a defect here.
- **`pytest-timeout` is not installed** — `--timeout=` is rejected by the argument parser.
- **This machine's speed drifts, and one test is a wall-clock assertion.**
  `test_discover.py::test_time_limit_stops_the_search` allows 60 s for a run whose time limit is
  5 s (the limit governs the evolution loop; the final refit that follows is unbounded).
  [measured, 2026-08-15] It took 49.7 s on a rested machine and **72.9 s an hour later**, and the
  whole suite went 355 s → 653 s over the same period, with no code between the two runs — the
  same test fails at HEAD with the session's work stashed, which is how that was established.
  So: a failure *only* there, with a number in the 60–80 s range, is thermal, not a regression.
  Check it in isolation and against a stash before believing it, and **do not widen the bound**;
  it is the only test that would catch a time limit that stopped working.
  [measured, 2026-08-15, again] It failed at 67.1 s inside a 537 s full run and passed at 48.1 s
  in isolation a minute later, with no code between them. That is the second time; the protocol
  above is what it is for.
- **numpy and scipy are the only permitted runtime dependencies** — this is what keeps the
  Pyodide target viable. The CLI uses stdlib `argparse` for this reason.
- **PowerShell mangles quotes** in `python -c @'...'@`; heredocs lose `"` characters. Write a
  script into the scratchpad directory and run the file instead. The backtick is PowerShell's
  escape character, so a JavaScript template literal passed to `node -e` is eaten the same way.
- **`*>` redirects as UTF-16LE and `1>` as UTF-8 *with a BOM*.** Reading the latter back in
  Python needs `encoding="utf-8-sig"`, or it fails as a `cp932` decode error, which points at
  the wrong thing entirely.
- **Never rewrite a source file with PowerShell.** `Get-Content -Raw` decodes as `cp932`
  regardless of what the file is, so a round trip through `Get-Content | ... | Set-Content`
  silently turns `Ω` into `ﾎｩ` and `…` into `窶ｦ`. It looks like a successful edit. Use the
  editing tools, or Python with an explicit encoding.
- **`python -` hangs** (stdin is the null device). Never pipe a script into Python.
- **`native.exe | Select-Object -First N` returns exit code 255** by closing the pipe early.
  That is not a program failure — re-run without the truncation before believing an error.
- **Background jobs redirected with `Out-File` buffer until completion.** To wait on one, use
  `Monitor` with an `until grep -q ...` loop (it runs bash), not chained sleeps.
- Full suite ~6 min rested and 9 min loaded (712 tests, 19 of them skipped here); the fast subset
  is
  `python -m pytest tests -q -k "not test_fit and not test_discover"` (~4 s) — note that the
  `not test_discover` filter also drops `test_discover_exhaustive.py`, which is where the
  exhaustive mode is covered.
- **Node 24 is available**, which is what `benchmarks/pyodide/` and `web/` use to run the
  package under WASM without a browser. `npm install` needs network; `loadPackage` does not any
  more, because `web/scripts/build-assets.mjs` vendors the numpy and scipy wheels beside the
  Pyodide runtime in `web/public/pyodide/` and both the site and `npm run smoke` load from
  there. The npm `pyodide` package does not ship those wheels, but running Pyodide under Node
  once leaves them cached in its own directory, which is where the script looks first.
- **`unpackArchive` rejects a Node `Buffer`.** `readFileSync` returns one, and the error is
  `RuntimeError: Unknown typed array type 'Buffer'` from inside the wasm — wrap it:
  `new Uint8Array(readFileSync(...))`.
- **`Compress-Archive` produces zips Python cannot unpack as a package.** It writes backslash
  path separators, so `zipfile` extracts files literally named `autocircuit\__init__.py` and
  the failure only shows up as `ModuleNotFoundError`. Build such archives with Python
  (`benchmarks/pyodide/make_zip.py`).
- **ngspice does not run on this machine, and WSL is how it was verified anyway.** There is no
  winget package for it, but `wsl -d Ubuntu-24.04` is installed and `apt-get install ngspice`
  gives exactly the ngspice 42 that `ubuntu-latest` gives CI. `python3-numpy`, `python3-scipy`
  and `python3-pytest` were installed there too, so the round-trip can be run before it is
  pushed: `cd /mnt/c/Users/toshi/python/AutoCircuit && PYTHONPATH=$PWD/src python3 -m pytest
  tests/test_spice_ngspice.py -q`. It takes ~1 s. Note WSL has numpy 1.26 / scipy 1.11 against
  the Windows side's 2.5 / 1.17, which is a second interpreter for free. **Do not invoke `wsl`
  through the Bash tool** — Git Bash rewrites `/mnt/c/...` into `C:/Program Files/Git/mnt/c/...`
  and the path is not found. Use PowerShell, and put anything with quoting in a script file.
- **Every push to `main` republishes the public site.** `.github/workflows/pages.yml` builds and
  deploys <https://toshihiroiguchi.github.io/AutoCircuit/> on push. It gates on `tsc --noEmit` and
  `npm run smoke`, so a broken build fails rather than shipping — but a push is now an act of
  publication, not only of storage.
- **`npm run assets` runs the CLI, and now also runs Pyodide.** It generates `web/public/samples/`
  by invoking `python -m autocircuit simulate`, so it needs numpy and scipy importable; it sets
  `PYTHONPATH` to `src/` itself, so the package does not have to be installed. It then boots
  Pyodide under Node to compile the bytecode the site ships (§14), which costs ~30 s and is
  skipped when `web/public/.bytecode-stamp` still matches the Python source and the Pyodide
  version — so an unchanged tree rebuilds assets in seconds.
- **A cold browser measurement needs a fresh origin, and the page must time itself.** A reload is
  not a cold cache; a preview server on a port this browser has not seen is (the HTTP cache is
  keyed by origin). And do not time readiness by polling the DOM through browser automation: the
  poll starts when the tool's round trip lands, so it reported 10.8 s where the worker's own
  `console.info` line said 5.10 s. Every number in §14 is from the worker's clock.
- **The browser automation refuses `file://` URLs.** To test one, launch Edge with
  `--remote-debugging-port=9223 --user-data-dir=<temp> --headless=new` and drive it over the
  DevTools protocol from Node — `WebSocket` and `fetch` are both global in Node 24, so no
  dependency is needed. `/json/list` gives the page target, then `Log.enable`, `Runtime.enable`,
  `Page.navigate`, and `Runtime.evaluate` with `awaitPromise` for anything async.
- **`loadPackage` cannot be handed an absolute Windows path.** Pyodide derives a package name
  from the string it is given, so `C:\...\numpy-2.4.3-...whl` becomes a "package" named after the
  whole path and the wheel's metadata install fails (`UnsupportedWheel`, after the files have
  already been extracted — so it looks like it worked). Pass names and set `packageCacheDir` to
  the directory holding the vendored wheels.
- **Long benchmarks must be launched detached — and [measured, §24] the agent harness's own
  background mode is the way that works.** Passing `run_in_background` on the tool call survived
  a **25-minute** job to completion and reported its exit; the older advice below was written
  from two runs lost at about ten minutes, which is what happens to a *shell*-backgrounded
  command (`nohup … &` inside one is worse: the wrapper exits, the child goes with it, and the
  log file is never even created). Output goes to a task file that can be read while the job
  runs, so the `flush=True` rule still applies. `Start-Process python -ArgumentList ...
  -RedirectStandardOutput <file> -PassThru` remains the fallback outside the harness; set
  `$env:PYTHONPATH` first, the child inherits it. Two long runs were lost to this
  before the rule above was found again, and one of them produced no output at all, which reads
  like a crash rather than a kill -- the run's own prints were still sitting in the pipe buffer.
  A `print(..., flush=True)` per finished unit of work is what makes a detached run readable
  while it runs; without it the log stays empty for the whole first reference.
- **Two benchmarks at once is not free on this machine, and the reason is the CPU.** It is a
  Core 7 150U -- **2 performance cores and 8 efficient ones**, 12 threads -- so the second and
  third single-threaded run land on cores several times slower than the first. [measured] The
  fast test subset, 4 s on a quiet machine, took **118 s** while two `mode="evolve"` benchmark
  runs were going. This matters beyond convenience: every evolve measurement is budgeted in
  *wall-clock*, so a run sharing the machine evaluates fewer topologies in its 600 s and
  reports it as a property of the search. Run one at a time, and interleave the arms of a
  comparison seed by seed rather than arm by arm.

## 5. Working agreements from this session

From `CLAUDE.md`, and they were followed:

- **Conversation in Japanese; everything else in English** — code, comments, docs, CLI text.
- **Delegate cheap work to subagents**: simple investigation → `haiku`, simple implementation
  → `sonnet`. The I/O readers and four test modules were built this way and both agents
  produced good work — the test agent found a genuine library bug (the `SKINW` discontinuity
  above) because it was told to leave failures as `xfail` rather than weaken assertions.
  Keep that instruction; it is the reason the delegation was worth it.
- Verify subagent output rather than trusting the report: their tests were re-run and their
  most error-prone code (Touchstone S→Z conversion) was checked by hand.

The discovery-v2 session kept to the same split and it held up: the counts regression test
(G2), the feasibility tests (G3) and the CLI flags went to `sonnet` subagents with the
"xfail, do not weaken" instruction, while the enumeration algorithm, the feasibility rules and
the two-tier search stayed on the expensive model. All subagent output was re-run
independently before being committed. The repository is now under git with the history pushed
to https://github.com/ToshihiroIguchi/AutoCircuit — commit per plan step.

The DRT session did the same: `tests/test_drt.py` was written by a `sonnet` subagent from a
spec that named the measured tolerances, then re-run here before being committed, while the
regularisation, the λ-selection rule and the peak criterion stayed on the expensive model —
all three of which needed measurement to get right (§5.2 of the plan).

The skeleton session kept the same split: `tests/test_skeleton.py` and
`tests/test_discover_skeleton.py` were written by `sonnet` subagents from specs that named the
exact contracts, then read and re-run here; the enumeration algorithm, the clamping rule and
every decision about what the report may claim stayed on the expensive model.

## 6. Open items

0. Nothing is left of `docs/DISCOVERY_V2_PLAN.md`: step 6 (DRT, gate G4) is done, so all seven
   steps and all five gates are in. One decision inside it is worth not reopening by accident:
   **DRT is not wired into the search and should not be.** [measured] It could only raise the
   enumeration floor, which removes 0.1–0.4% of the filtered space (n = 5 alone is 85–89% of
   it, and the small sizes are the cheapest fits), while raising `exhaustive_min` deliberately
   clears `complete_up_to` — "all topologies up to N" is not true when the smaller sizes were
   skipped. `exhaustive_min` stays available to anyone who wants that trade explicitly.
1. ~~**Skeleton mode: gate P2, and §3.3.**~~ Both done; see §7.
2. ~~**Web UI (phase 6)**~~ — **nothing is left.** All seven steps of `docs/WEB_UI_PLAN.md` are
   built, the site is deployed (§8–§14), and both remaining gates were answered in step 7: W3 is
   met at 4.9–5.7 s cold on a rested machine and missed at 10.9 s on a loaded one (§14), and W5
   is retired — `file://` is impossible for any packaging of
   this application, and offline was declined rather than built. Two decisions worth not
   reopening by accident:
   - **If the cold start is attacked again, the target is the wheel install** (2.2 s rested,
     4.4 s loaded), which is now the largest stage; the import is 1.5–2.0 s. Anything that shaves
     seconds off the *transfer* helps too — the site is 41 MB, of which ~10 MB is step 7's
     bytecode.
   - **Do not add a service worker without deciding about staleness first.** It is the only way
     to make the site work offline, and it would put a cache between every visitor and a site
     that republishes on every push.
   - **Do not try `file://` again.** It is not a bundling problem: a `file://` page cannot
     `fetch` a sibling file, and Pyodide fetches its wasm, its stdlib and its wheels.
3. ~~ngspice round-trip in CI.~~ **Done** — `tests/test_spice_ngspice.py` and
   `.github/workflows/tests.yml`; see §15. One decision worth not reopening: **the round-trip
   compares ngspice against the suite's own nodal engine, not against the model.** Comparing
   against the model would leave the ladder-synthesis error at ~1e-2 in front of a dialect fault
   three orders of magnitude smaller.
4. ~~Gamry `.DTA` and BioLogic `.mpt` readers, once real files exist to test against.~~ **Done**
   — `io/gamry.py` and `io/biologic.py`, registered in `io/__init__.py`'s sniffing table.
   Verified against real vendor files (`impedance.py`'s bundled `exampleDataGamry.DTA` and
   `exampleDataBioLogic.mpt`), not only hand-built fixtures: a Gamry file's `ZCURVE TABLE` is
   found even when an `OCVCURVE TABLE` precedes it, and BioLogic's `-Im(Z)/Ohm` column is
   negated to this project's sign convention while a plain `Im(Z)/Ohm` column is left alone.
   See `docs/IMPACT_PLAN.md` §4 (item C) for the measured-data arena these readers feed.
5. ~~Pyodide performance measurement~~ — **done**, `benchmarks/pyodide/`. WASM costs 1.3–1.8×
   on the numerical work, not the order of magnitude the plan feared, so no reduced web budget
   and no Rust port are needed. What it does settle: `exhaustive_limit=4` is the browser
   default at 2.8 min single-threaded, which makes progress streaming mandatory, and
   `exhaustive_limit=5` is a ~30 min opt-in. Phase 6 can be planned on these numbers.

## 7. Skeleton-constrained discovery (mode 2)

`docs/PARTIAL_TOPOLOGY_PLAN.md` is the design; this is the state of it. The user asserts part
of the circuit — the *skeleton* — and the search adds elements to it and never removes them:

```powershell
python -m autocircuit discover cap.csv --pool component --skeleton "C1-R1-L1" --workers 8
```

The public surface: `discover(skeleton=...)`, `DiscoveryResult.skeleton`, `.placements_of()`
and `.unresolved_everywhere`, and in `core/enumerate.py` the four functions
`contains_skeleton` (the definition of the space), `grow_from_skeleton` (one level),
`grow_up_to` (level by level, with the clamp), and `count_skeleton_placements`.

Decisions already closed, none of which should be reopened without reading why:

- **A skeleton and the genetic search do not compose.** `mode="evolve"` with a skeleton
  raises, and `mode="auto"` runs the exhaustive stage alone rather than falling back —
  `mutate()` deletes and retypes elements, so an evolved population is not confined to the
  constrained space, and a report mixing candidates from two spaces cannot say which one it
  covered.
- **A `seeds=` circuit that does not contain the skeleton raises.** A seed adds to the
  candidate list, a skeleton constrains what that list may hold; the seed could otherwise be
  the recommendation, under a coverage line saying only constrained topologies were looked at.
- **`exhaustive_limit` is a total element count everywhere**, including here, and defaults to
  the skeleton's size + 5. That default reaches past what is affordable on purpose: the clamps
  decide where a given skeleton stops, and they land where §1.1 of the plan predicted with no
  new rule — +3 for a three-element skeleton (9,857 candidates), +2 for a ten-element one
  (11,418).
- **`max_elements` does not clamp the enumeration under a skeleton.** It caps the genetic
  search, which never runs here, and its default of 7 would cut a ten-element skeleton off
  below its own size.

What the report owes the user, from §3 of the plan: the completeness sentence names the
skeleton (§3.1, done), placement multiplicity is reported rather than resolved (§3.5, done),
and a front on which nothing is identifiable is stated as a finding about the *measurement*
(§3.4, done). **§3.3 — which equivalence-class members the skeleton excluded — is open**, and
the plan's claim that it is cheap has been corrected there: the excluded topologies are
precisely the ones never fitted, so identifying them means screening the same-size
unconstrained space, ~9,600 fits at five elements on the component pool.

### The gates

**P3 and P4 pass** (`tests/test_skeleton.py` cross-checks the generator against the definition
as sets; `tests/test_discover_skeleton.py` pins the unconstrained sentence character for
character, and the suite is green).

**P1 — the true skeleton must still recover the truth. [measured] Passes 30/30**, on all
three references, 10 seeds each: truth reported, on the Pareto front, and the recommendation
every time. 534 / 972 / 241 candidates against 6,598 / 2,581 / 3,713 unconstrained, and 1.7–6×
faster in wall clock. One result nobody was looking for: unconstrained, the capacitor truth is
the *recommendation* 9/10 (one seed cannot resolve the 10 mΩ ESR at 1% noise, so parsimony
drops it); with `C1-R1-L1` asserted it is 10/10. A skeleton puts prior knowledge where the
model-selection rule can use it, not only where the enumerator can.

**P2 — a wrong skeleton must not read as a successful search. [measured] and it changed the
question.** The headline: **a wrong skeleton is invisible in everything the report
emphasises** — residual structure 0/30, and `chi2_reduced` equal to what the *truth itself*
achieves on the same data, to two figures, in every seed. The escape valve the plan proposed
(screen a small unconstrained sample, warn if something outside fits materially better) is
dead on this evidence: nothing outside fits better.

Two things came out of reading the recommendations, and both are worth not re-deriving:

- **Two of the three "wrong" skeletons were not falsifiable at all.** `p(R1,CPE1)` is a strict
  generalisation of `p(R1,C1)` — a CPE with n = 1 *is* a capacitor — so those skeletons contain
  the truth's behaviour while `contains_skeleton` correctly says they do not contain its
  topology. Both return the skeleton itself, everything resolved, exponent at n ≈ 1. Wrong at
  the level of element codes is not wrong at the level of what the data can express, and
  demanding a warning there would be demanding a false one.
- **Where the skeleton *is* falsifiable, the signal is not the fit quality — it is an asserted
  element the fit had to switch off.** `R1-p(R2,C1)` against the capacitor truth returns
  `R1-p(R2,C1-L1-SKINF1)`, which becomes the truth exactly when R2 goes to an open; the element
  the fit had to neutralise is the one that will not resolve. 9/10 seeds carry an unresolved
  parameter and `unresolved_everywhere` is true on the same 9.

P2 is now written in three parts (§6 of the plan), and what it pointed at is built:
`DiscoveryResult.unsupported_assertion()` names *which of the user's asserted elements* the fit
could not pin down, under the recommendation. Placement multiplicity (§3.5) is the same
computation — the answer is taken over placements, so a skeleton that has any fully resolved
reading is reported as supported. It says the data does not *test* that part of the assertion
rather than that the assertion is wrong, which is both weaker and true, and is what keeps it
silent for a skeleton that merely generalises the truth.

§3.3 is built too, as an opt-in pass: `excluded_equivalents()` and `--excluded-equivalents`
screen the same-size topologies the skeleton removed against the reported model's own response
and name the ones that reproduce it exactly. [measured] Every equivalent it found, on all three
references, is a CPE standing in for an ideal element -- a capacitor at n = -1, an inductor at
n = +1, a Warburg at n = -0.5. What a skeleton costs is a commitment to an ideal element where
a distributed one fits identically. Opt-in because 1,132 screens is 137 s on one core (43 s on
eight) against a search of about a minute, and five elements is ~20 min single-core. It is in the
browser too as of step 5 (§12), which split it into `excluded_plan()` plus drivers so that it can
be fanned across workers and stopped — and being stoppable is what made its *report* have to
distinguish "checked and found nothing" from "did not check".

**What is left in this mode:** nothing but the documentation sweep, which this file is part
of.

## 8. Web UI step 1 — a fit that crosses a worker boundary

`docs/WEB_UI_PLAN.md` §2.2 is the record; this is what exists. The browser now fans out **both**
tiers of the search, which took one new module and one new generator:

- **`core/wire.py`** — JSON encoding for the numeric payloads: `encode_float`/`decode_float`,
  `encode_array`/`decode_array` (any rank, shape carried), `encode_complex_array`/
  `decode_complex_array`, `encode_mapping`/`decode_mapping`. Non-finite values are the strings
  `"inf"`, `"-inf"`, `"nan"`.
- **`Statistics.to_wire()`/`from_wire()`** and **`FitResult.to_wire()`/`from_wire()`**, with
  `fit.WIRE_VERSION` so a stale worker build fails loudly instead of reporting wrong numbers.
- **`discover.refit_plan()`** — the tier-2 mirror of `screen_plan()`: it yields batches of
  `RefitTask` and receives either `FitResult` objects or their wire form back, keeping the
  shortlist quota, the drop-what-cannot-be-fitted rule and the ordering in one place.
  `_refit_shortlist` is now a thin driver over it, and `_refit_worker` returns the wire payload
  even under `multiprocessing`, so every parallel CLI run exercises the browser's transport.
- **`benchmarks/pyodide/`** — `orchestrate.py` drives both plans; `screen_task_worker.mjs`
  answers both `screen` and `refit` messages; `run_orchestrated.mjs` hands refits out one at a
  time.

[measured] Bit-identical, twice over: a full-precision dump of `discover()` on all three
reference spectra at four workers — values, fitted response, residuals, standard errors,
correlation matrices — is unchanged from before the change, and the browser's report on the
capacitor reference matches the pre-fan-out run candidate for candidate, front for front,
recommendation included. The clock is what moved: **287 s → 123 s**, tier 2 from 232 s to 86 s,
against CPython's 90 s at four processes.

~~One thing this leaves for step 2: the *spectrum* still reaches each worker by being recomputed
there.~~ Closed by step 2: `Spectrum.to_wire()/from_wire()` exist and the browser now carries the
spectrum. `benchmarks/pyodide/screen_task_worker.mjs` still rebuilds its own with `simulate()`,
which is correct for a benchmark whose data is synthetic and known to both sides.

## 9. Web UI step 2 — the Data screen

`docs/WEB_UI_PLAN.md` §2.3 is the record; this is what exists and what to know before touching
it. `web/` is a Vite + React + TypeScript app; `web/README.md` is its map.

```powershell
cd web; npm install; npm run dev      # http://localhost:5173
npm run smoke                          # the Python path under Pyodide, headless, ~6 s
npm run build                          # -> web/dist/
```

- **`src/autocircuit/web/bridge.py` is the entire Python surface the browser sees.** One
  `handle(request) -> str`, four operations (`version`, `read`, `trim`, `validate`), every
  response `json.dumps(..., allow_nan=False)`, and every exception turned into a response
  because a Pyodide worker that dies costs 1.5 s plus its own numpy and scipy to replace.
- **A dropped file is written into the Pyodide filesystem and read from there** by
  `autocircuit.io.read_many`, so sniffing, extension hints and multi-sweep readers behave
  exactly as they do for the CLI. Only the path crosses the wire. `BridgeClient.readFile` puts
  the user's own file name back into any error message, since the reader's diagnostic otherwise
  names the scratch path the worker invented.
- **`web/src/core/wire.ts` decodes and cannot encode, on purpose.** A spectrum is held in the
  form Python produced it and handed back unaltered; an encoder would be a second implementation
  of the float format for the browser to disagree with the CLI through.
- **`web/public/` is generated and gitignored** — `web/scripts/build-assets.mjs` builds the
  source archive with the *same* `benchmarks/pyodide/make_zip.py` the benchmark uses and vendors
  the Pyodide runtime plus the numpy and scipy wheels (~29 MB) so nothing is fetched from a CDN.
  `npm run dev` and `npm run build` both run it first.
- **Do not size a Plotly panel with `layout.height`.** With `responsive: true` a plot measures
  the element it was given, and a CSS grid item with no height of its own measures zero at the
  moment it is first drawn — two of the four panels came out permanently 10 px tall and the
  other two did not, which looks like a Plotly bug and is not. `.plots-panel__plot` sets the
  height in CSS and the layout has none.

[measured] The browser's verdicts match the CLI's: three files (generic CSV, ZView, and a
deliberately drifted sweep) read with the format sniffed correctly and their Lin-KK element
counts, residuals and runs *z* agree with `python -m autocircuit validate` digit for digit,
including the failing one. Linked zoom across the three frequency-axis panels was checked in a
real browser, as was recovery from an unreadable file — the other files in the same drop still
load.

[measured] **Cold start is ~13 s, and it is not the download**: 14.2 s cold against 12.9 s with
a warm cache, split 6.6 s Pyodide boot / 0.8 s numpy+scipy / 5.8 s unpack-and-import. Node does
the same work in ~4 s. Gate W3 asks for under 10 s *to a first fit* and therefore fails today;
the import is the item worth attacking, and a wheel instead of a source archive is the first
thing to measure. Single-run figures from an automated Chrome — the ratio is the result, not the
seconds.


## 10. Web UI step 3 — the Fit screen

`docs/WEB_UI_PLAN.md` §2.4 is the record. `BRIDGE_VERSION` is now **2**: `elements`, `circuit`,
`edit`, `preview` and `fit` join `version`/`read`/`trim`/`validate`. The app has screens now — a
tab bar over `web/src/screens/DataScreen.tsx` and `FitScreen.tsx` — and `App.tsx` holds the
spectra both of them work on.

- **The canvas edits a tree in Python.** Each box and slot carries the path `subtree_at` takes,
  and the `edit` operation does the surgery with `series`/`parallel`/`replace_subtree`/
  `remove_subtree`. `web/src/components/CircuitCanvas.tsx` knows how a series run and a parallel
  block *look*; it cannot build a circuit string, and it must not learn to. A JavaScript circuit
  builder would be a second implementation of the grammar the CLI parses.
- **`core/circuit.remove_subtree()` is new** and belongs with the other tree-addressing helpers.
  Deleting one branch of a two-branch parallel collapses the block into the survivor, because
  that is what the network becomes; deleting the root raises.
- **`core/fit.search_space()` is new**, lifted out of the private `_Problem`, which now calls it.
  It returns `(lower, upper, start)`, and `start` is what the preview curve is drawn with — so
  the curve begins where the fitter begins rather than at a display default that resembles it.
  `core/fit.relative_error()` came out of `FitResult` for the same reason: the number under the
  preview and the number after the fit have to be the same quantity.
- **`POOLS` moved from `cli/main.py` to `core/elements.py`**, so the palette and `--pool` offer
  the same named sets.
- **The fit response carries `residual_real`/`residual_imag` already split.** The residual vector
  is real parts then imaginary parts, which is a detail of the objective function and not a
  promise; a front end that assumed it would mis-plot silently if it changed.

Three things the UI had to say out loud, and will have to again on the Discover screen:

- A table of editable numbers beside a Fit button implies the numbers seed the fit. **They do
  not** — Fit is the same global search the CLI runs. Only *Fix* binds a number, and it removes
  the parameter from the fit rather than nudging it. The table carries that sentence.
- **A new circuit's preview sits ~160% away from the data**, because the geometric centre of a
  fifteen-decade interval is not near anything. That is what "no starting guess" looks like;
  inventing a nicer-looking default would be inventing a guess.
- **Editing anything retires the fit.** Values survive (they are the next preview's starting
  point); the statistics do not, because they describe a model that is no longer on screen.

[measured] **Gate W1 passes at the precision the CLI reports, and only there.**
`benchmarks/pyodide/fit_parity.py` writes the CLI's fit of the nine circuits in
`tests/test_fit.py::SYNTHETIC_SUITE` — carrying the spectra themselves, not a recipe for
regenerating them — and `run_fit_parity.mjs` refits them through `bridge.handle` in Pyodide.
All 34 parameters agree at six significant digits; **none are bit-identical** (worst relative
difference 2.4e-7). Evaluating the circuits at CPython's fitted values *is* bit-identical for
1001 of 1042 components — the 41 that are not all belong to the skin-effect-on-a-wire circuit,
whose `tanh` and complex `sqrt` differ between the WASM libm and the desktop's at 5e-14.

That last row retires the assumption `FitResult.to_wire` was written around: it carries
`z_model` rather than recomputing it on arrival because nobody had measured whether numpy agrees
across interpreters. It does — except for elements built on transcendentals, which is precisely
the failure that would have looked like a bug in an element rather than in a transport.

Two smaller browser findings, of the kind only a browser produces:

- **A fit is not sub-second in the browser.** The plan's §3 said no progress UI was needed; a
  three-element fit took 5.2 s at five restarts and the corpus ran to 36 s at three. The button
  shows its state and the canvas locks while it runs.
- **JavaScript switches to exponential notation only below 1e-7**, which prints a 3.3 µF
  capacitance as `0.0000033`. The parameter table formats below 1e-3 and above 1e6 as
  exponential instead, so a value can be checked against a datasheet at a glance.

## 11. Web UI step 4 — the Discover screen

`docs/WEB_UI_PLAN.md` §2.5 is the record. `BRIDGE_VERSION` is now **3**, and the browser runs
the topology search itself: one orchestrator worker holding the plan, a pool of up to four more
answering `screen_task` and `refit_task`.

- **`discover.enumerate_candidates()` and `Enumeration.coverage()` are new**, lifted out of
  `_exhaustive`, which is now a driver over them. This is the same move `screen_plan` and
  `refit_plan` were: the completeness claim is derived in one place, and the browser drives it
  rather than re-deriving it. `benchmarks/pyodide/orchestrate.py` still enumerates for itself,
  which is correct for a benchmark and would not be for the app.
- **`refit_plan` yields `RefitBatch(tasks, done, total)`.** `done` is what a partial Pareto
  front is drawn from; building it in the driver would have meant a second decode of a
  `FitResult` and a second copy of the rule that a topology which cannot be fitted is dropped.
- **`DiscoveryResult.refit_progress` is the honesty of a cancelled run.** Cancelling during the
  screen lowers `complete_up_to`, which is the obvious half. Cancelling during the *refit* does
  not touch it — the screen really did cover everything — and leaves a front built from part of
  the shortlist that looks exactly like a finished one. The coverage sentence now says "only 8
  of the 37 shortlisted topologies have fitted parameters".
- **A search whose pool evaluates nothing says so.** [measured] With pool `("R", "C")` against a
  spectrum that turns inductive, the feasibility screen rejects every candidate, `n_evaluated`
  is 0 — and the old sentence still read "every plausible topology with up to 3 elements was
  evaluated", which is true of an empty set and reads as an assurance. `completeness()` now
  distinguishes "no candidate to fit" from "nothing fitted". Found by the smoke script, not by
  the tests.
- **`autocircuit.web.job` holds the only state the bridge has.** A search is a pair of
  generators that must survive between batches; the workers doing the fitting stay stateless,
  which is what lets one be terminated and replaced without losing anything.
- **`run_screen`/`run_refit` are the pool worker's entry points**, public so the browser runs
  the CLI's screening budget, abandon threshold and "a hopeless topology scores infinity rather
  than raising" rule instead of a second version assembled in the bridge.

[measured] **Gate W2's results pass exactly and its streaming clause does not.** In Chrome, at
`exhaustive_limit=4` on the capacitor reference with four workers: 741 topologies,
`complete_up_to` 4, a Pareto front matching `discover --workers 4` row for row and AICc for AICc
(−306.011, −654.405, −1208.84, −1316.28), the same recommendation, and a verbatim report
carrying the same equivalence class `C1-L1 == L1-CPE1`. ~84 s against the CLI's 77.6 s. But the
refit updates only when a fit finishes, and **the largest gap between two of them was 8.6 s** —
tier 1 streams under 1.5 s throughout, tier 2 cannot stream at all in the sense the gate meant.
The panel therefore runs its own 0.25 s clock: the elapsed time ticks, the counts and the front
move only when the search knows more. Inventing motion in a progress bar would hide a hung
search.

[measured] **Gate W4 passes.** Cancel terminates the pool — Pyodide is single-threaded, so a
worker inside a differential evolution never reads a stop message — and rebuilds it for the next
run (~1.5 s per worker). The in-flight batch is discarded rather than part-submitted: a missing
outcome would have to travel as `null`, which means "could not be fitted" and is a claim about
the topology rather than about the interruption.

Three things the browser found that nothing else did:

- **The version guard fired on the first load.** `web/src/worker/protocol.ts` still said bridge
  2 while Python answered 3; the page refused to run. Bump both when adding an operation.
- **The elapsed clock ran backwards** by about a second, because a progress report is stamped
  when the run emits it and rendered later. The displayed value is monotone now.
- **The pool is not built at page load**, contrary to `docs/WEB_UI_PLAN.md` §2: four more
  Pyodide workers on top of a ~13 s cold start, for every visitor who never searches. It comes
  up on the first Discover press and is kept afterwards.

## 12. Web UI step 5 — the Report screen

`docs/WEB_UI_PLAN.md` §2.6 is the record. `BRIDGE_VERSION` is now **4**: `excluded_start`,
`excluded_screen`, `excluded_report`, `excluded_cancel`, `drt` and `export`.

- **`excluded_plan()` is the third generator of the `screen_plan`/`refit_plan` shape**, and
  `excluded_equivalents()` is now a driver over it, as is `web/src/core/excluded.ts`. The pass
  had to be split this way rather than called: 1,132 screens is ~137 s on one desktop core, and
  in a single-threaded browser interpreter that is minutes of a frozen page with no progress and
  no way out. Its batches carry `so_far` — the report as it stands — for the same reason
  `RefitBatch` carries `done`.
- **`ExcludedEquivalents.screened` is new, and it is the third instance of this project's
  characteristic failure.** "None of them reproduces your model" is a claim about every excluded
  topology; a pass stopped after 8 of 55 knows nothing about the other 47, and without this the
  sentence it printed was the finished one. Found by asking what the finished wording would mean
  after a cancel — the same question that produced `refit_progress` in step 4 and the coverage
  sentence in mode 2.
- **The pass screens against the candidate's fitted response, and that target crosses the wire.**
  `excluded_start` answers with a whole `Spectrum`. Naming it instead ("use the model") would put
  the choice in JavaScript, and against a noisy sample an exact reparameterisation looks no
  better than a topology that merely fits well.
- **The pool workers did not change.** An excluded screen is a `screen_task`; only the target
  differs. A second kind of fanned-out, cancellable work with no second worker protocol is what
  "JavaScript makes no decisions" is worth.
- **`DiscoveryResult.to_dict()` / `.to_csv()` and `fit.report_dict()` are where the CLI's files
  are now built**, so `export` hands the browser the same text. `discover --csv` was added for
  the same reason: the table the Report screen offers has a command-line counterpart rather than
  being the browser's own invention. Those files may contain bare `Infinity` — an exact fit has
  `-inf` information criteria — which is fine, because by the time one reaches a response it is
  a *string* inside strict JSON.
- **`DRTResult.to_wire()` had to exist before the probe could be shown.** `to_dict()` writes a
  bare `inf` for the series capacitance whenever the data does not block, which is the ordinary
  case and is exactly what `allow_nan=False` refuses.
- **`App.tsx` owns the worker pool now**, because two screens run work on it. It is still built
  on first use, not at page load.

[measured] **In Chrome**, skeleton `C1-R1`, component pool, `exhaustive_limit=3`: the search
covers 3 elements in ~40 s; the excluded pass then checks 132 of the 146 three-element topologies
in **~7 s across four workers** and finds one exact equivalent of the reported `C1-R1-SKINF1` —
`R1-CPE1-SKINF1`, the same CPE-is-a-capacitor substitution §7 measured at four elements.
Cancelled mid-pass: 64 of 132 checked, the equivalent kept, and "Another 68 were never checked,
so this list is not the whole of what was lost."

Three things the browser found, all of them about state rather than about numbers:

- **A screen is unmounted on a tab switch and everything in it is lost.** Harmless while there
  were three screens used in order; a fourth that you walk back to makes it a trap, and it cost a
  wrong measurement here — a form *displaying* "3 elements, with a skeleton" ran an
  unconstrained four-element search, because those were restored defaults. `App` now owns the
  search settings, the excluded pass and the DRT result. Anything that costs minutes or states an
  intent belongs there, not in a screen.
- **Two different netlists downloaded under one file name**, because the name came from the SPICE
  subcircuit name and both default to `AUTOCIRCUIT`. Named for what they are now
  (`autocircuit-discovery.cir`, `autocircuit-fit.cir`).
- **A column of "Class n — 1 topology" headings buries the finding.** The panel now says how many
  classes hold more than one member before listing them, including when the answer is none.

[measured] **Gate W6 passes.** A search driven through the bridge and exported gives the same
JSON as `discover()` on the same data — every key equal after dropping the clocks — the same CSV
text, and a netlist of the same recommended candidate; the manual-fit export equals what
`fit --json` and `--spice` write. That is `tests/test_web_job.py` §6 and `tests/test_web_bridge.py`
§17.

## 13. Web UI step 6 — example data, theme, loading states, and the deployment

`docs/WEB_UI_PLAN.md` §2.7 is the record. **No new bridge operation**: `BRIDGE_VERSION` stays 4,
because none of this is a new question for Python to answer. **The site is live at
<https://toshihiroiguchi.github.io/AutoCircuit/>.**

- **The example datasets are generated, not committed.** `web/scripts/samples.mjs` holds the three
  references `benchmarks/discovery_v2.py` uses, and `build-assets.mjs` runs the project's own
  `simulate` for each at build time into `web/public/samples/` (gitignored) with an `index.json`
  carrying the recipe *and the literal command line*. Checking in three CSVs would have made the
  site the one place in this project holding data no command produces.
- **A sample takes the path a dropped file takes.** Fetched, wrapped in a `File`, handed to the
  same loader — so `read_many`, the format sniffing and the multi-sweep readers are exercised
  rather than bypassed.
- **The true circuit is shown on every row, with the noise.** Loading a sample and recovering its
  circuit is passing a test whose answer is printed beside it; that is fair to demonstrate and only
  fair while it is labelled. Each sample also carries the skeleton a user of it would assert, so
  mode 2 has a worked example on all three.
- **The theme is `data-theme` on `<html>`** — stamped by `index.html` before the first paint and by
  `web/src/core/theme.ts` afterwards — and every colour in `styles.css` is a custom property.
  **The plots are the exception CSS cannot reach**: Plotly draws into a canvas, so `theme.ts` reads
  those same properties back and hands them over as values. Do not write a second palette in
  TypeScript.
- **The attribute is stamped by whatever decides the theme, never by an effect.** The plots read
  the computed style during the render that follows a change, and a child's effects run *before*
  its parent's — so an effect would leave the plots one render stale and would make it hard to see
  why.
- **The dark palette is not an inversion.** Both series are lightened (a hue that reads as blue on
  paper reads as black on a dark plot) and the text colour on an accent fill flips with them.
- **The loading state is the honest half of a failing gate.** The status line runs a clock; the
  three screens that are not the Data screen say why their controls are dead, because a greyed-out
  Fit button looks the same whether Pyodide is importing numpy or has thrown. The clock is the only
  thing advancing on a timer — same rule as §11.
- **`.github/workflows/pages.yml` is this repository's first workflow.** It needs Python as well as
  Node (`npm run assets` runs `make_zip.py` and then `simulate`), and two of its four steps are
  gates: `npm run build` runs `tsc --noEmit` first, and `npm run smoke` then drives the whole
  Python path under Pyodide headless, so a site that cannot read a file is not published. Pages was
  enabled with `build_type=workflow`; there is no branch to publish from and no `gh-pages`.

[measured] **The deployed site gets the command line's answer.** In Chrome, from the public URL:
the Randles sample reads as `generic_csv` and its Lin-KK verdict matches
`python -m autocircuit validate` digit for digit (16 Voigt, mu 0.836, max 3.4378%, RMS 1.0747%,
runs *z* −0.48); fitting `R1-p(C1,R2-W1)` with no initial values converged in 1.25 s to `R1.R`
20.0289 ± 0.0426, `C1.C` 9.99754e-06 ± 3.34e-08, `R2.R` 199.845 ± 0.429, `W1.A` 49.7134 ± 0.401,
AICc −1310.89, RMS 1.3590% — every reported digit equal to `python -m autocircuit fit` on the same
file. Gate W1 again, on a circuit outside the corpus it was measured on.

[not measured] **W3 and W5 were not attacked, and the deployment did not wait for them.** 9.3 s
from navigation to a usable page was measured on the deployed site, but with a warm HTTP cache and
before any fit, so it does not answer W3 — reporting it as if it did would be the quiet
reinterpretation §11's gate rewrite exists to refuse. The import is still the lever (§9).
Step 7 (§14) did that work.

## 14. Web UI step 7 — bytecode instead of source, and the end of W5

`docs/WEB_UI_PLAN.md` §2.8 is the record. **No new bridge operation**: `BRIDGE_VERSION` stays 4.
Nothing about what the program computes changed; what changed is *when Python was compiled*.

- **`web/scripts/precompile.mjs` compiles at build time, inside Pyodide.** A `.pyc` is only valid
  for the interpreter that wrote it, and this machine runs 3.13 while Pyodide 314 runs 3.14 — so
  the build boots Pyodide under Node, imports what the page imports, and writes three artefacts:
  `public/pyodide/python_stdlib.zip` rebuilt with a `.pyc` beside every `.py` (zipimport prefers
  the bytecode, and the boot alone imports 559 stdlib modules), `public/pyodide-bytecode.zip` —
  an overlay of 576 numpy and scipy `__pycache__` entries unpacked into site-packages after the
  wheels are installed — and `public/autocircuit-src.zip` rewritten with its own bytecode inside.
- **Sizes:** stdlib 2.5 → 7.1 MB, overlay 5.8 MB new, package 0.14 → 0.41 MB; `web/dist` 31 → 41 MB.
  Bought with ~10 MB of transfer, and worth it on any connection where 10 MB costs less than 8 s.
- **[measured] Node, one process, alternating**: all-source boot 1.36 s / import 3.20 s / total
  5.89 s; bytecode stdlib 0.34 / 2.72 / 4.27; + overlay 0.20 / 0.99 / 2.50; + package 0.34 / 0.92
  / 2.60. The stdlib is worth ~1 s, the overlay ~1.7 s, this package ~0.07 s.
- **[measured] Browser, cold, Edge 151, fresh port per run — and read in pairs, because this
  machine drifts 2× (§4).** Rested: **5.10 / 5.70 / 4.86 s** to a usable page against **12.75 s**
  without the bytecode. Loaded, fifteen minutes later: **10.85 s** against **19.55 / 25.36 s**.
  Loading the Randles example adds 0.2 s and fitting `R1-p(C1,R2-W1)` takes 1.17–1.25 s rested
  and 2.4 s loaded, so a first fit is finished **~6.6 s after navigation rested and ~13 s
  loaded**. **W3's 10 s is therefore met in the state its 13 s failure was measured in, and
  missed at this machine's worst** — the change is worth ~2×, and the gate is now inside the
  machine's variance instead of outside it. The fit's standard errors are the ones §13 recorded
  from the deployed site, digit for digit.
- **[measured] From the public URL after this shipped:** 21.12 s cold — 41 MB over the network,
  so mostly transfer — and 10.2–10.6 s warm. `localhost` in the same minute gave 10.85 s, which
  is how it was established that the warm figure was the machine and not the deployment. Do not
  compare a number from Pages with a number from `localhost` taken at another time.
- **The invalidation mode is per artefact and it matters.** Nothing is timestamp-invalidated: the
  wheels are unpacked at run time with an mtime the browser invents, so a timestamp always reads
  as stale. The stdlib zip gets PEP 552 *unchecked* hashes, since its sources and bytecode are
  one file. The overlay and the package get *checked* hashes, because a browser can hold either
  in its cache across a deployment and lay it over sources it was not compiled from — unchecked
  bytecode would just run, which is a wrong answer nobody would ever see. Checked hashing costs
  nothing measurable.
- **The step's input and its output must not be one path.** `make_zip.py` now writes
  `web/.build/autocircuit-source.zip` and precompile writes `public/autocircuit-src.zip`. When
  both were the same file, the second `npm run assets` in a tree overwrote the compiled archive
  with a source-only one and the stamp still said "up to date" — a silent loss of the bytecode.
- **`npm run smoke` unpacks the overlay too**, so the deployment gate exercises the artefacts the
  browser will actually load rather than a path only the build takes.

[measured] **W5's `file://` half is impossible, and not because of how this is bundled.** Driving
Edge over the DevTools protocol — the usual browser automation refuses `file://` URLs — the built
`dist/index.html` opened as a file renders nothing: the module script and the stylesheet are both
blocked by CORS from origin `null`. Probing the same page: `fetch('./autocircuit-src.zip')` is
blocked, a module worker is blocked (`cannot be accessed from origin 'null'`), and a blob worker
runs but can fetch nothing. Pyodide fetches its wasm, its stdlib and its wheels, so **no
packaging of this application starts from a file:// page.**

[decided, not measured] **Offline was declined.** With the preview server stopped, a reload is a
network-error page: a static site with no service worker is only as offline-capable as the
browser's HTTP cache, which does not cover the entry document. A service worker would fix it and
would put a cache between every visitor and a site that republishes on every push. The gate is
retired with both halves stated rather than left open against work nobody intends to do.

## 15. The ngspice round-trip, and the repository's first test workflow

`docs/IMPLEMENTATION_PLAN.md` §7 is the record. Open item 3 is closed: the netlist is now known
to be *dialect* right and not only electrically right.

- **`tests/test_spice_ngspice.py`** exports nine circuits — R alone, C+ESR+ESL, two RC blocks, a
  nested `p(R1,C1-p(R2,L1))-R3`, Randles with a Warburg, a CPE, a finite Warburg, a skin-effect
  capacitor and a `SKINW` wire — drives each with a 1 A AC current source, and reads the port
  voltage back out of ngspice's **binary** rawfile. It skips itself when ngspice is not on PATH.
- **The comparison is against `test_spice.py`'s own nodal engine, not against the model, and that
  is the whole design.** Against the model the four ladder-synthesised elements sit at ~1e-2 by
  construction, which would hide any dialect fault smaller than itself; against the engine the
  synthesis error cancels exactly, because both are reading the same file. [measured] **exactly
  zero for the lone resistor and 4.6e-15 .. 4.5e-12 for the other eight**, ladders included; the
  diagnostic count is 9 for each of the two DC-open cases and 0 for the other seven. The
  tolerance asserted is 1e-9. Incidentally the ladder values themselves differ between scipy 1.11
  and 1.17 in their last digits, and the agreement does not move — which is what it means for
  this test to be about the reading of a file rather than about its contents.
- **`.github/workflows/tests.yml` is the repository's second workflow and its first for tests.**
  It installs ngspice, then runs ruff, mypy and the suite. The round-trip gets a step of its own
  that greps the summary for `skipped` and fails on it — **a skipped test reports as a pass**, so
  an ngspice that failed to install would retire the gate and leave the run green. That is the
  same failure this project has now hit four times in other forms (§3, §11, §12). [measured] The
  guard was run both ways before it was pushed, by hiding `/usr/bin/ngspice` in WSL: installed it
  is 19 passed and exit 0, hidden it is 19 skipped and **exit 1**. On the first CI run (7m52s):
  ngspice 42, `19 passed in 0.64s` at that step, and `712 passed in 417.29s` for the suite —
  including the wall-clock test that had failed thermally here minutes earlier.
- **Both workflows carried a Node 20 deprecation annotation.** Fixed since; see §16.

Three things a real simulator said that nothing here could:

- **ngspice exits 0 with a failed operating point.** Every model beginning with a capacitor is a
  DC open at its port, so the op point comes out singular and both gmin stepping and source
  stepping fail — and the AC sweep that follows is still right to 4.5e-12, because an AC analysis
  of a linear network does not depend on the operating point. A round-trip gated on the return
  code would have passed a deck ngspice had given up on. The test therefore asserts on the
  *diagnostics*: a network with a DC path at its port must produce none at all, and one without
  may produce only the operating-point family — an unknown device, an unparsable value or a node
  name read differently all land outside it. [measured] An unknown device is `Error on line`,
  exit 1, and **no rawfile written at all**, which is why the harness treats a missing rawfile as
  a failure rather than as nothing to compare; `test_the_round_trip_notices_a_netlist_ngspice_
  cannot_read` pins that.
- **`.option rshunt=1e12` silences those diagnostics and is the wrong fix here.** [measured] It
  costs up to **7.2e-7** in |Z| — five orders worse than the quantity being measured, and not
  simply |Z|/R, because the ladder's own internal nodes get shunted too (the CPE case is 10× its
  port-level prediction). The test deck therefore adds nothing to help the simulator. The netlist
  header mentions the option, with its cost, for users who want a clean log.
- **The netlist now carries the deck that drives it.** `_how_to_drive()` in `core/spice.py` emits
  the four lines above the `.subckt`, with this fit's own band in the `.ac` line, plus the DC-open
  note. A user handed a two-terminal `.subckt` otherwise has to guess at both.
## 16. Both workflows off Node 20, and a README that admits the site exists

Nothing computes differently. Two things changed: the five actions the workflows call, and the
front page.

- **The annotation named more actions than the workflow files do.** [measured] Before the change,
  the three warnings on commit `46b4785` were: `checkout@v4, setup-node@v4, setup-python@v5,
  upload-artifact@v4` on the Pages build job, `deploy-pages@v4` on the Pages deploy job, and
  `checkout@v4, setup-python@v5` on Tests. `upload-artifact@v4` appears nowhere in this
  repository — it is the upload step *inside* the composite `upload-pages-artifact@v3` — and
  `deploy-pages@v4` sits in a second job whose annotations have to be asked for separately.
  Counting the `uses:` lines gives three actions to bump; reading the annotations gives five.
  Ask the API, per job: `gh api repos/OWNER/REPO/check-runs/<job-id>/annotations`.
- **The bumps are to the current majors**: `checkout@v7`, `setup-python@v7`, `setup-node@v7`,
  `upload-pages-artifact@v5`, `deploy-pages@v5`. Two cross a documented behaviour change:
  - `setup-node@v5` added automatic caching driven by a `packageManager` field in package.json.
    It reads the repository root, which has no package.json at all here, so the explicit
    `cache: npm` with `cache-dependency-path: web/package-lock.json` is what was and still is
    doing the work. It is not redundant; the workflow says so in a comment.
  - **`upload-pages-artifact@v4` stopped putting hidden files in the artifact**, and `web/dist`
    has exactly one: `.bytecode-stamp`, written by `scripts/precompile.mjs` so it can skip a
    rebuild whose inputs have not moved. Nothing in the browser fetches it and CI builds from an
    empty checkout every time, so the published site is unchanged. [measured] The run log shows
    `include-hidden-files: false`, and against the deployed site every asset the page loads
    answers 200 while `/.bytecode-stamp` answers **404**. If a dotfile the site actually serves
    ever appears, that input has to be set to `true`.
- **[measured] After: zero annotations on any job of either run** (Pages `31878793165`, Tests
  `31878793147`), against three before. Both green — but both were green *before* as well, which
  is why the annotation count is the measurement and the tick is not.
- **[measured] The Tests run still did the work**: ngspice 42, `19 passed` at the round-trip step,
  `712 passed in 519.90s`. That is 520 s against the 417 s of the previous run; the suite is the
  same, the runner is not. **Do not read a wall-clock difference between two GitHub runners as a
  regression.**
- **[measured] The deployed site was opened in a real browser afterwards**, not just curled:
  boot 5.33 s, packages 7.78 s, unpack 0.26 s, import 1.90 s, worker ready 16.46 s after
  navigation, no console errors; loading the Randles example gives `generic_csv`, 71 points,
  `19.6 Ω .. 387 Ω`, and a Lin-KK **PASS** on 16 Voigt elements. A deploy action that changed
  major version is not verified by a green deploy step.
- **The README now links the site** and describes it, and one sentence in it had quietly become
  false: "the same code to run in a browser under Pyodide *later*" was written before phase 6.
  The cold-start figure quoted there is the one measured **from the public URL** (21 s cold,
  5-11 s with the runtime cached), not the `localhost` 5 s — §14 says not to mix the two, and the
  flattering number is the one a reader will not experience.

## 17. Seven model-selection criteria, and six UI questions

`docs/METRICS_AND_UX_PLAN.md` is the record. Seven items were raised together; one of them
changes what every report in this project ranks by, three are a few lines each, one turned out to
be implemented already, and **one shipped as nothing but a measurement** -- both versions of the
cold-start fix were built and both were measured to be no improvement (§17.5).

### 17.1 The criteria

`--criterion` on `discover`, a `<select>` on the Discover screen, and `autocircuit criteria` to
explain the choice. **The default moved from AICc to AIC**, which is a change to published
numbers: `AICc - AIC = 2k(k+1)/(n-k-1)`, which on a 71-point spectrum is 0.29 at k = 4 and 1.36
at k = 9. It is monotone in k, so the order *within* one parameter count cannot move and only
comparisons across counts can. **Every measured front recorded in `docs/` before 2026-08-16 was
taken under AICc and is still labelled that way.**

- **`Statistics` now carries all six scores plus `p_waic`**, always, and `fit --json` writes them
  all. `fit.WIRE_VERSION` is **2** for that; `BRIDGE_VERSION` is **5**, because a search carries a
  criterion and every results row carries every score plus the one that ranked it.
- **The criterion changes the ranking, the Pareto axis and the shortlist. It does not change
  `recommended`.** That is the parsimony rule, and it is about identifiability rather than about
  a penalty term (§3 of this file: minimum-AICc selected a 9-parameter circuit with two
  parameters whose standard errors exceeded their own values). Choosing BIC does not make that a
  different kind of mistake. `DiscoveryResult.by_criterion` is what the criterion picks, and the
  report prints both lines whenever they differ.
- **WAIC is computed analytically under a Laplace approximation, not sampled**, and the
  approximation is named in the docstring, in `autocircuit criteria` and in the README. The
  posterior is the covariance `_covariance` already computes and the residual is linearised
  through the same Jacobian, which makes every integral Gaussian; `_covariance` therefore also
  returns the leverage, off the SVD it was already doing. It reduces to `deviance + 2*rank` in
  the small-leverage limit — the *effective* parameter count where AIC has the nominal one —
  which is the only reason to offer it here. [measured] Against a Monte-Carlo WAIC drawn from the
  same Laplace posterior, 100,000 draws on a fitted `R1-p(R2,C1)`: **waic −1098.551 against
  −1098.538, and p_waic 2.660 against 2.666**. That check is what says the closed forms are the
  integrals they claim to be; it says nothing about the linearisation being a good model of the
  fit, and neither does anything else here.
- **The F-test is not a score and was not made into one.** It ranks by AIC — a test between two
  models provides no axis — and then walks the Pareto front, stepping up only where the extra
  sum of squares is significant at 0.05. **It assumes each row is nested in the next and Pareto
  rows generally are not**, which the report says on the line that gives the answer rather than
  in a footnote. The p-value comes from `scipy.special.betainc` and not `scipy.stats`: `special`
  is already imported by `core/elements.py`, and `scipy.stats` is a second heavy import on a page
  whose start-up is §17.5.
- **Screening cannot compute two of the seven.** WAIC needs the leverage, which needs the
  Jacobian, which is the expensive half of a full fit and exactly what tier 1 skips; an F-test
  needs two models. Both fall back to AIC in `_screening_score`, under the constant
  `SCREENING_FALLBACK` so it is a stated fallback rather than whatever an attribute lookup
  returns. That decides *who gets refitted*, never who wins.
- [measured] The browser matches the CLI on all six, digit for digit, on the Randles sample
  through `R1-p(C1,R2-W1)`: AIC −1311.19, AICc −1310.89, BIC −1299.36, CAIC −1295.36,
  HQC −1306.38, WAIC −1311, effective parameters 4.02 of 4. That is gate W1 again, on numbers it
  had not been measured on.

### 17.2 The header's build line is gone

`bridge v4 · fit v1 · spectrum v1 · validate v1` and the reader list were one strip carrying two
different things. The four versions were a **developer's** diagnostic, and the diagnosis they
support is already automatic and louder: `bridge.worker.ts` compares its own `BRIDGE_VERSION`
against what Python answers and refuses to run, naming both numbers. They are a `console.info`
line from `worker/client.ts` now. The reader list answers a real user question — "what can I
drop here?" — which was being answered in the page header on every screen instead of at the drop
zone; it is on the drop zone.

### 17.3 Tab order, and the hand-off that justified it

`Data, Fit, Discover, Report` → `Data, Discover, Fit, Report`. Fit came first because the
dependency ran that way and **still does**: the circuit drawn on the Fit screen is what a
constrained search asserts as its skeleton. What changed is that Discover now hands a topology
forward ("Fit this circuit"), which makes the forward direction the common one.

**It hands over the topology and not the fit.** The discovered values are not carried across as a
starting guess, because this fitter has none — refitting on the Fit screen re-runs the same
global search from the same data-derived interval and lands in the same place — and carrying
numbers would make a screen that says "these do not seed the fit" look as though they did.

### 17.4 The selected front row is drawn

`ParetoTable` rows are selectable (the recommended one on arrival) and `CircuitPreview` draws the
selection above the table with the *same* `CircuitCanvas` the Fit screen edits, behind a new
`readOnly` prop. A second renderer would be a second chance for the picture beside a result to
disagree with the editable one, and `npm run schematic` checks the geometry once. It asks the
bridge to parse the string, because no JavaScript here parses a circuit.

### 17.5 Cold start: measured twice, changed nothing, and that is the result

`web/dist` is 41 MB and **17 of them are the numpy and scipy wheels, which `loadPackage` cannot
ask for until `loadPyodide()` has resolved** — and that call first fetches the 9.6 MB wasm and
the 7.1 MB stdlib. So 41% of the bytes sit behind a barrier they do not depend on. That is a real
observation and the obvious fix from it is wrong twice over. **Nothing about the cold start ships
from this session; what ships is the reason not to try it again.**

- **A document's preload cache does not serve a Web Worker's fetch.** [measured] A
  `<link rel="preload" as="fetch">` in `index.html` left `loadPackage` unsatisfied: Chrome
  downloaded all 17 MB a second time and logged "preloaded … but not used" for both wheels. No
  attribute fixes that; the document and the worker are different fetch contexts.
- **Doing it inside the worker works, and makes the total worse.** [measured, deployed site,
  fresh Edge profile per run] Prefetching in `bridge.worker.ts` and answering `loadPackage` from
  the result took the packages stage from **7.84 / 4.39 s to 1.67 / 1.80 / 2.75 / 1.66 s** --
  and the total to a ready worker did not follow it down. Four readings each way, two of the
  "without" taken after the revert so both sides span the same evening: **12.72 / 13.52 / 15.24 /
  20.31 s without (median 14.4) against 15.75 / 16.56 / 22.27 / 30.60 s with (median 19.4)**. The
  spread is wide, and the prefetched side is higher throughout with a best reading worse than the
  other side's median. The load is **bandwidth-bound**, so the wheels do not overlap the boot,
  they compete with it: the wasm the boot blocks on arrives later. The time moved between stages and a little was lost.

**The methodological point is the one to keep: the stage breakdown said this was a large win and
the total said it was a loss.** Do not accept a per-stage improvement as a cold-start
improvement, and do not measure this on `localhost`, where the transfer is ~100 ms and there is
nothing to overlap.

What follows from it: **reordering transfers cannot help a bandwidth-bound load; only sending
fewer bytes before the page is usable can.** So the two items below are unchanged in status, and
the first is now the only lever left worth its disruption.

- **Deferring scipy** — 14 MB of the 17, and the Data screen does not need it.
  `core/elements.py` imports `scipy.special` at module scope and `core/fit.py` imports
  `scipy.optimize`, so `from autocircuit.web import handle` pulls scipy in before any operation
  runs. It would mean lazy imports in three core modules and a bridge that can answer some
  operations and not others, which the front end would have to model — trading the "one handle,
  no decisions" property that made the browser agree with the CLI digit for digit.
- **A service worker** is still refused, for §6's reason.

### 17.6 Dragging an element onto the circuit was already implemented

`ElementPalette` has set `draggable` and `CircuitCanvas`'s slots have handled `dragover`/`drop`
behind a private MIME type since step 3 (§10). What was missing was the affordance: a slot looked
the same whether or not it would accept what was under the pointer. Two changes, both about that
rather than about the mechanism — every target lights up while a drag is in progress
(`cc--dragging`, driven from a window-level `dragenter`, because the drag starts in the palette
and `dragstart` does not reach the canvas), and an element may now be dropped **onto an existing
symbol** to place the new one in parallel with it, which is where a drag aimed at a symbol was
aiming. [measured, Chrome] Both paths produce the circuit the click path produces:
`p(R1,C1)-R2` + CPE onto the end slot gives `p(R1,C1)-R2-CPE1`, and + L onto `R2` gives
`p(R1,C1)-p(R2,L1)-CPE1`.

### 17.7 State of the suite

[measured] `python -m pytest tests -q`: **712 passed, 19 skipped, 2 failed** in 718 s, and both
failures were understood before anything was changed.
`test_web_bridge.py::test_bridge_version_is_bumped_for_the_new_operations` pins the number and
had to be bumped to 5 — which is the test doing its job.
`test_discover.py::test_time_limit_stops_the_search` failed at **65 s inside the full run and
passed at 37 s in isolation a minute later**, which is the third occurrence of the thermal
pattern §4 describes. Do not widen that bound. `tests/test_criteria.py` is new: 20 tests, 15 s.

## 18. What a Pareto row says about fit quality

The front carried a score and `chi2_reduced` and nothing a reader could judge on sight. Both are
computed from the **weighted** residuals, so their scale is the weighting's, not the data's: on
`web/public/samples/maxwell-wagner.csv` a two-element `p(R1,C1)` reports `chi2_red 0.237` against
the four-element truth's `9.01e-05`. Nothing in "0.237" says that model is 68% away from the
measurement. The Fit screen had the number that does -- `RMS |dZ|/|Z|` -- and the search did not,
so a row and a manual fit could not be compared at all.

- **`FitResult.relative_error` is now a stored field, not a method taking a spectrum.** It has to
  be: a Pareto row crosses a worker boundary as a `Candidate`, and by the time the table is drawn
  the spectrum is not there. Storing it also removes the way the method could be misused -- it
  accepted *any* spectrum, including one the result was not fitted to. `core/fit.relative_error()`
  stays as the module function, because the browser's pre-fit preview still computes it from a
  curve that has no `FitResult` (see section 10).
- **It is the objective, read in a different unit, and there is a test that says so.** Under
  modulus weighting the weighted residual is `(Z_model - Z_data)/|Z_data|` split into halves, so
  `sum of squares == sum of |dZ|^2/|Z|^2` and the reported RMS is exactly `sqrt(SSR / n_points)`
  (`test_relative_error_is_the_objective_the_fit_minimised`). Note the denominator: `chi2_reduced`
  divides the same sum by `2*n_points - k`, so neither is derivable from the other without the
  parameter count, and the two columns are not a number and its square root.
- **It is the only fit-quality number a change of weighting leaves alone.** [measured] `C1-R1-L1`
  against a five-decade spectrum: `chi2_reduced` is `7.87e-05` under modulus and `5.99` under unit,
  four orders of magnitude apart on the *same data* and neither one "worse" -- they are sums over
  different divisors. The RMS is 1.24% and 19.3%, which ranks them the way a person would.
- **It is not a ranking and must not read as one.** It falls monotonically with element count, so
  the bottom row of the front is always the best-fitting one and routinely not the recommendation.
  That is what the score's penalty and the parsimony rule exist for; `to_csv` therefore writes it
  as a fraction rather than a pre-multiplied percentage, and the column sits beside `chi2_reduced`
  rather than replacing it.
- **The old label named the wrong quantity.** `FitResult.summary()` said `RMS relative |Z| error`,
  which reads as a disagreement in magnitude. The numerator is the complex deviation -- the
  distance between two points on the Nyquist plane -- so the line now says `RMS |dZ|/|Z|`.
- **`FitResult.summary()` and `DiscoveryResult.summary()` no longer take a spectrum.** It was only
  ever used for this one line. `DiscoveryResult.summary()` consequently always prints the
  recommended model's detail, where before it printed it only when a caller happened to pass the
  data; every caller in the CLI and the bridge did.

[measured, CLI and browser, same file and seed] The front agrees digit for digit across the two:
`68.467% / 59.901% / 1.326%`. The four exact reparameterisations of the truth all report `1.326%`,
which is the column behaving correctly -- it invents no distinction where the data has none.

`BRIDGE_VERSION` is **7** and `fit.WIRE_VERSION` is **3**.

### 18.1 A bug found on the way, in `_expand_statistics`

Fixing a parameter silently deleted four of the six criteria. `_expand_statistics` re-indexes the
two per-parameter arrays onto the full parameter list, and it rebuilt the whole `Statistics`
field by field to do it -- so a rebuild written before CAIC, HQC and WAIC existed carried AIC,
AICc and BIC across and left the rest at their NaN defaults, with `rank` at 0. Any fit under
`--fix` reported a criterion menu with four blanks in it and no indication why. It is
`dataclasses.replace` now, which cannot drop a field added later.

### 18.2 State of the suite

[measured] `python -m pytest -q`: **723 passed, 19 skipped** in 427 s, five of them new here.
An intermediate run of the same suite failed `test_discover.py::test_time_limit_stops_the_search`
at 65 s and it **passed in isolation at 39 s a minute later** -- the fourth occurrence of the
thermal pattern section 4 describes, and again not a bound to widen. `npm run check` and
`npm run smoke` both pass.

## 19. Three questions from the deployed site: the hand-off, moving an element, and the start-up

`docs/STARTUP_AND_EDITING_PLAN.md` is the whole of it, gates and corrections included. What a
reader coming here later needs to know without opening it:

### 19.1 The Discover -> Fit hand-off still carries the topology and not the fit

That decision stands and nothing here reopens it (`docs/SCREEN_STATE_PLAN.md` section 3.B). What
was wrong was its premise. The note under *Fit this circuit* promises that refitting there "re-runs
the same global search and lands in the same place", and that is only true while the Fit screen's
weighting, restart count and seed are the ones the search refitted under -- which the Discover
screen lets the user change and which travelled nowhere.

`discover_report` now carries `weighting`, `seed` and `refit_restarts`, taken from the job rather
than from the browser's copy of what it asked for, and `App.fitCircuit` writes them into
`FitState`. **[measured]** A search at `proportional` weighting and seed 3 recommends `C1-L1` at
AIC -51.0323 / chi2_red 0.68841; the Fit screen after the hand-off reports the same digits. The
same topology under the Fit screen's *old* defaults -- modulus, seed 0 -- reports AIC -306.097 and
a capacitance 2.6x different. The score disagreeing was the visible half; the parameter value
disagreeing is the half that mattered.

### 19.2 An element already on the canvas can now be dragged somewhere else

`core/circuit.move_subtree` and the bridge's `edit` action `move`. **The target path addresses the
tree before anything moved**, which is the reason it is one operation: a caller cannot know what
that path becomes once the source is torn out, and working it out in TypeScript would be the second
implementation of the tree operations this front end refuses to have.

It works by swapping the source for a unique marker node, building the new connection through the
same `series`/`parallel` builders an insert uses, then finding the marker **by object identity**
(`is`, not `==`: equal `ElementNode`s are indistinguishable by value) and deleting it through
`remove_subtree`. Two edge cases fall out rather than being special-cased -- dropping an element on
itself, and moving one into a new branch of the block it is already in, both return the circuit
unchanged -- and the collapse rule for a two-branch parallel block is `remove_subtree`'s own.

The moved element **keeps its label**, so a value the parameter table holds under `L1.L` still
belongs to it afterwards. That is the difference from delete-and-reinsert, which renumbers.

On the canvas: an element is a drag source under its own MIME type, every existing drop target
takes both kinds, and there is a click path (a move tool arms the element, the next slot receives
it) because dragging is unavailable from a keyboard. The two arms are mutually exclusive -- a slot
does one thing when clicked.

### 19.3 The load is two stages, and the first one is numpy only

**scipy is 18.3 MB of the 41 MB a first visit fetched, and nothing on the Data screen uses it.**
So: stage A boots Pyodide, installs numpy, unpacks the package archive and numpy's bytecode
overlay, and imports the data path; stage B installs scipy, unpacks its overlay and imports the
rest. Stage B starts on its own when stage A lands and nothing waits for it -- a request that needs
the fitter waits *inside the worker*, so the main thread never has to know which side of the line
an operation is on.

Four things this required, and one it forbids:

- `core/weighting.py` holds `Weighting` and `weight_vectors`, moved out of `fit.py` (which
  re-exports them) because `validate.py` was importing the whole fitter for two numpy functions.
- `core/stats.py` imports `scipy.special.betainc` inside the F-test rather than at module scope.
- `autocircuit/__init__.py` and `core/__init__.py` re-export through PEP 562 `__getattr__`. A
  package's `__init__` runs before any of its submodules, so eager re-exports meant
  `import autocircuit.io` pulled in the element registry and with it `scipy.special`.
- `web/light.py` holds `BRIDGE_VERSION`, the JSON envelope and the four operations that need no
  scipy, and looks everything else up in `web/bridge.py`, importing it on first use. One `handle`,
  one envelope, one dispatch, completed lazily.
- **Do not fold the two stages back into one, and do not prefetch.** Nothing here is fetched
  earlier than it used to be; scipy is fetched *later*. The prefetch that was measured and rejected
  in `docs/METRICS_AND_UX_PLAN.md` section 1.5 moved bytes *earlier*, and the cold start is
  bandwidth-bound, so it competed with the wasm the boot blocks on and made the total worse.

`web/scripts/precompile.mjs` writes **two** overlays, `pyodide-bytecode-numpy.zip` and
`pyodide-bytecode-scipy.zip`, and each goes on *after* its own wheel. [measured] Laying scipy's
`__pycache__` into site-packages before `loadPackage("scipy")` leaves the package unimportable:
`cannot import name 'loggamma' from 'scipy.special' (unknown location)`. The split is taken between
the two imports rather than by top-level package -- see the plan's section 6 for why the obvious
version of it silently produced a 22-byte scipy overlay.

`Plot.tsx` imports Plotly with a dynamic `import()`, which takes the app bundle from 1.42 MB to
284 kB (gzip 468 -> 88 kB); the chart library arrives with the first plot, which cannot happen
before a spectrum has been read anyway.

**[measured, Chromium, localhost, warm]** usable for data 5.27 s -> **1.48 / 1.53 s**; usable for
fitting 5.27 s -> 4.94 / 5.07 s. Bytes before the page can read a file: 41.0 MB -> 22.1 MB.

### 19.4 And the examples load from the first paint

The drop zone and the sample buttons are never disabled now. `BridgeClient.readFile` already waited
for the runtime; what was missing was the page saying so, so a file chosen early gets a named
pending row instead of a control that refuses. **[measured]** A Load clicked 45 ms after the first
paint is read at 1.29 s, as soon as stage A lands.

`BRIDGE_VERSION` is **8**.

### 19.5 State of the suite

[measured] `python -m pytest tests -q`: **742 passed, 19 skipped** in 352 s, nineteen of them new
here — eight on `move_subtree`, three on the bridge's `move` action, and eight in
`tests/test_web_light.py`, which asks in a subprocess with `scipy` made unimportable whether the
data path still imports. That last one is the only kind of test that can ask it: in the main
process, twenty other tests have already imported scipy.

`npm run check`, `npm run build` and `npm run smoke` all pass; the smoke run now drives both load
stages in the order the worker does.

[measured] On `ubuntu-latest` the Tests workflow ran **761 passed in 585 s** -- the same suite plus
the nineteen ngspice round-trip tests that skip on this machine -- with `ruff` and `mypy` green.

### 19.6 On the published site

[measured] Two cold visits in a **fresh browser context** each — empty HTTP cache, so first visits
rather than reloads — to <https://toshihiroiguchi.github.io/AutoCircuit/> after the deploy: usable
for data at **21.67 s / 18.01 s**, usable for fitting at **68.65 s / 36.16 s**. The second stage's
spread is the link's: the same 19 MB took 45.04 s on one visit and 16.30 s on the other, minutes
apart. Timed on their own from the same origin, the scipy wheel is 14.01 MB in **21.06 s** and its
overlay 5.00 MB in **2.84 s** — about 24 s of transfer that used to sit in front of the first
usable moment.

An example clicked **0.40 s** after navigation, before Python existed, appeared at **18.08 s**, 70
ms after the data stage landed. The version handshake passes (published core 8, published bundle
8), and a drag-to-move on the live page turned `C1-R1-L1` into `L1-C1-R1`.

A third visit, on the build that is live now (after the redeploy that took the light-operation list
out of the worker): data at 16.12 s, the spectrum read at **16.16 s** and its **Lin-KK verdict at
16.41 s** with the second stage still running, fitting at 26.49 s.

**No comparison against the old build's 21 s is available and none is claimed.** That reading is
from an earlier day; today's link delivers roughly half the throughput it implies, so the two
cannot be subtracted. What was measured in one sitting is what is claimed: 22.1 MB before the page
works instead of 41.0 MB, and 24 s of measured transfer moved out of the way.

## 20. The genetic search gets a gate — steps 1–3 of `docs/EVOLVE_SEARCH_PLAN.md`

**This section describes work that is in progress.** Steps 1–3 of six are done and measured;
4–6 are not started. Read the plan before continuing — the four measurements in its §1 are the
reason the work exists and are not repeated here in full.

### What was wrong

`mode="auto"` is exhaustive to five elements and genetic above that. The exhaustive half has G1–G3
behind it. The genetic half had **no quality gate at all** — G5 asked only that a fixed seed give
the *same* answer, which is a regression test — so above five elements this project made no
measured claim, and `auto` routes there exactly when the exhaustive front looks under-fitted.

Worse, `_evolve` broke the rule `discover.py` states at its own top ("every number that reaches
the user comes from the tier-2 refit"): it merged its unrefitted archive back into the report.
[measured] **82% of the reported Pareto rows (23 of 28) carried screening-grade χ², standard
errors and `free?` marks**, with nothing in the report able to say which. That is this
repository's characteristic failure sitting inside the reporting path.

### What is now true

- `benchmarks/discovery_v2.py` has an eighth mode, `evolve-gate`, and a **separate**
  `LARGE_REFERENCES` list of three 6–7 element truths. They are separate on purpose: every other
  mode iterates `REFERENCES` and assumes a truth the five-element stage can reach.
- `_evolve` reports **tier-2 only**, shortlisting through `_quota_by_size`, which both searches
  now share. Gate EV2 passes: 0/5 tier-1 rows where it was 3/4, all 34 reported candidates at
  full budget. The front *gained* a row the old top-8-by-score rule never refitted.
- Gate EV5 passes: an exhaustive-mode fingerprint is **byte-identical** before and after. The
  probe is committed as `benchmarks/ev5_fingerprint.py` since §23 and no longer rebuilt by hand.
- Step 2's deadline was **reopened and fixed in §23**: it had no refit *order* behind it, and a
  first-ranked candidate went unreported because of it.
- Step 4's first half landed in §25: `_breeding_pool` bounds what the search breeds from, and
  EV1 went 1/9 → **6/9** reported on the baseline's own references and seeds.
- G5 of `docs/DISCOVERY_V2_PLAN.md` is withdrawn, with the reason written beside it.

### Three things not to re-derive, from step 2

1. **Extracting the quota rule dropped a tiebreak, and the suite did not notice.** The old
   `_shortlist` sorted `(score, cost, text)` tuples whole; the extracted helper first sorted on
   score alone. Ties are **not rare here** — an exact reparameterisation is exactly a tie — so
   `Ranked` now carries an explicit `tiebreak`. All 744 tests passed with the bug in place. Only
   the EV5 fingerprint caught it. Fingerprint the exhaustive path before touching the shortlist.
2. **`time_limit` never governed the refit, and the obvious fix is wrong.** It bounds the
   evolutionary loop only. Harmless at eight fits; under the per-size quota it is 35–70 full fits
   and a 5 s budget spent **222 s** in the refit. Bounding the refit at `time_limit` itself makes
   a run report **nothing at all** having done all the work, because the loop has usually already
   passed that mark — which is what the EV1 baseline's own settings would have produced. Hence
   `REFIT_HEADROOM = 1.5`, the first candidate always attempted, and `refit_progress` (which
   existed for this and had no producer in the library until now).
3. **`REFINE_DEFAULT["evolve"]` cannot be swept.** The quota is
   `max(MIN_REFINE_PER_SIZE, n_refine // sizes)` and a genetic archive spans ~7 sizes, so 8, 16
   and 30 all collapse to 5. The floor is the knob. The constant carries this note.

### The EV1 baseline, completed, and the bar written from it

**9 runs, three references × three seeds, 600 s each: truth reported 1/9, on the front 1/9, the
recommendation 0/9.** The full table is in §4 of the plan. Three things it settles: the best
relative error on every front sits at or above the noise floor (so the search finds circuits
that describe the data and they are not the truth — a search problem, not a fitting one); the
failure is worst where the search is slowest (Randles managed **5–6 generations** of a
population of 40, so what was measured there was mostly the random initial population); and
§1.4's defect was systematic, 23 of 28 reported rows carrying screening-grade numbers before
step 2 and 0 of 36 after it.

**EV1's bar is a ratchet plus a ceiling, because 1/9 cannot support a pass fraction.** No step
may report fewer than 1/9 reported, 1/9 on-front, 0/9 recommended on the same references, seeds
and budget; and 1/9 is also the largest claim this project may make for `mode="auto"` above five
elements. The exhaustive stage passes G1 30/30 and the fallback recovers one truth in nine —
those are never one capability.

### Step 3: the parent's parameters travel to the child

`_inherited_values` carries a parent's fitted values onto a child by **structural** correspondence
— per element code, leaves zipped in evaluation order — because `simplify` drops labels before
anything is fitted. `_Evaluator` became two-stage (polish from the inherited values, global
search only when there is nothing to inherit or the polish lands too far off the best cost at
that complexity) and its cache became **best-wins**. `WARM_ACCEPT_FACTOR` is the knob;
`warm_accept=0` restores the pre-step-3 search exactly and is the control arm.

**EV3 passes both halves. [measured]** Maxwell-Wagner, 10 seeds, 600 s, arms interleaved:
truth reported **3/10 → 6/10**, on-front 3/10 → 4/10, recommendation 2/10 → 4/10, topologies
550 → 709 (up in 9/10), wall-clock 12.8 → **5.2 min**. On the ratchet's own 9-run set:
reported 1/9 → 3/9, nothing fell, topologies 434 → 751 (**+117%, up in 9/9**). EV5 re-measured
and **byte-identical**.

### Four things not to re-derive, from step 3

1. **The polish must run at the screening local budget, not the publication one.** `fit()`'s
   trust-region stage is `xtol=ftol=1e-14, max_nfev=20000` because reported standard errors are
   read off the Jacobian there; `screen()` has always used `1e-12 / 2000`. Routing the warm
   polish through `fit()` gave it the publication budget, i.e. **an unbounded refinement inside
   a screen**. [measured] Polish against the global search it replaces: 21% in the median, and
   **16.6 s and 13.1 s** in two of ten cases against global searches of 14.9 s and 14.6 s. That
   tail is invisible at 120 s and decisive at 600 s — the first EV3 read **+39% at 120 s and +7%
   at 600 s** because of it. `LocalBudget`/`PUBLISH_LOCAL`/`SCREEN_LOCAL` in `fit.py` name the
   two settings that were already there as duplicated literals.
2. **`WARM_ACCEPT_FACTOR` has no useful middle setting.** [measured] 1.5, 3 and 10 all sit inside
   the run-to-run spread and 1.5 is *below* the control: a strict factor pays for the polish and
   runs the global search anyway. The knob is nearly binary; the default is `math.inf`.
3. **A gate failed on a statistic with no resolving power has not been failed.** After the
   polish fix, six paired runs still gave on-front 1/6 → 0/6 — one event against zero. Ten seeds
   on the one reference that recovers anything reversed the sign on every count. The response to
   "my bar cannot decide this" is more seeds, never a reworded bar.
4. **The evolve budget is wall-clock, so a control must run beside its arm, never on another
   day.** `warm_accept=0` is a behaviourally exact restoration of the old search, yet the
   interleaved control does not reproduce §4's baseline row for row. Interleave seed by seed.

### What step 3 exposed for step 4

**All ten warm runs hit the 30-generation cap in 5.2 minutes**, leaving over half of a 600 s
budget unspent: the search is no longer bounded by fitting time but by `generations`, a default
nobody has measured. Step 4 changes what a generation *is*, so it would be measured against a
search that stops early for an unrelated reason. Raise or measure the cap before EV4.

### Environment

Two long-running background jobs were lost before §4's rule was found again — **a backgrounded
shell command is killed after ten minutes; detach with `Start-Process`** — and one produced no
output because its prints were still buffered, hence `flush=True` per unit of work. A third run
was lost to a machine restart 9 of 12 runs in, which is why long sweeps are now split one
invocation per reference. And **two benchmarks at once is not free**: this is a Core 7 150U with
2 performance cores, and the fast test subset went 4 s → 118 s while two evolve runs were going.
Run one at a time.

## 21. Reading a fit as internal structure -- `core/interpret.py`

`CLAUDE.md`'s purpose point 2 is that the circuit is a means and what is inside the part is the
end. Until now the pipeline stopped at parameters with units. This module is the step after, and
it is reachable as `autocircuit fit --interpret` (also `interpretation` in `--json`) and as
`autocircuit.core.interpret`.

**Everything it reports is geometry-free, by decision rather than by omission.** `Z(f)` fixes a
capacitance and cannot fix a permittivity: the two differ by `A/d`, which the spectrum does not
contain. So there is no permittivity, conductivity, diffusion coefficient or thickness anywhere
in the output -- but note `Ws1.D_over_L2`, which comes straight out of a finite-length Warburg's
own time constant. The rule takes absolute quantities away and leaves ratios.

### The split the module is built around

Every :class:`Quantity` is marked `invariant` or not, and that flag is the whole design:

* **invariant** -- computed from `Z`, so every member of the equivalence class gives it
  identically: `r_dc`, `r_inf`, `r_polarisation`, `self_resonant_frequency`,
  `esr_at_resonance`, `z_min`, `capacitance_at_f_min`, `tan_delta`, `q_factor`, and the poles
  and zeros of `Z(s)`.
* **form-dependent** -- computed from a block of the tree: a relaxation's `tau`, its share of
  the polarisation, an R-CPE effective capacitance, `capacitance_ratio`.

**The part that gets guessed wrong: characteristic time constants are invariant.** Identical `Z`
means identical poles. What is form-dependent is the *habit* of reading a time constant off as
`R*C` of a block. So when the circuit is R/L/C only, `modes_of()` gives time constants every
member of the class agrees on -- built as an exact rational function of `s` and rooted, not
estimated from samples. When a CPE or a Warburg makes `Z` non-rational there are no poles at
all, and the module says so and points at the DRT, which is computed from the data and therefore
form-independent by construction.

### Gate I1 has two halves, and the second one is the one that can fail

`tests/test_interpret.py` runs it on the pair `docs/HANDOFF.md` section 3 already records as
fitting the same data to 1.2e-15, with the correspondence written down exactly rather than
fitted, so the gate tests the interpretation and not the optimizer:

    R1' = R1 + R2        R2' = R1(R1+R2)/R2        C1' = R2^2 C1 / (R1+R2)^2

Half one: every invariant quantity agrees to 1e-9, and so does every pole and zero. Half two:
`R1-p(R2,C1)` shows **one** relaxation block and its exact equivalent `p(R1,C1-R2)` shows
**none**. Same data, same `Z`, different answer to "how many relaxations does this circuit
show" -- which is why the flag means something. Without half two the cheapest way to pass I1 is
to mark everything form-dependent.

### Five things not to re-derive

1. **The grid is angular, and the first version of it was not.** `_omega_grid` resamples in
   rad/s because that is what every `impedance()` here takes; the first draft passed Hz
   straight in and the self-resonant frequency came out as 4.47e7 Hz where the closed form says
   7.118e6 -- a factor of 2*pi, large enough to be wrong and plausible enough to read as a
   number. It was caught by the pole/zero path disagreeing with the crossing search, which is
   an argument for computing the same quantity two ways.
2. **A limit that is numerically zero must be reported as zero, and the threshold is the
   *smallest* measured |Z| and not the largest.** A two-block network is a short at high
   frequency and comes back as `r_inf = 5e-13 ohm +/- 2.9e-15`, which dresses a rounding
   artefact up as a measurement. Taking the threshold from the top of the range instead would
   erase a real 0.01 ohm ESR on a 5000 ohm spectrum. Hence `NEGLIGIBLE_FRACTION` against
   `min|Z|`.
3. **An apparent capacitance and a loss tangent are defined where the part is not a capacitor,
   and are meaningless there.** A plain `R-p(R,C)` reads 15.9 F and tan delta 11 at 1 Hz. Both
   are now gated on `-Im Z > Re Z` (`CAPACITIVE_PHASE_RATIO`) and simply do not appear
   otherwise.
4. **Standard errors propagate exactly for a power product, and the covariance has to be taken
   back into log space to do it.** `log_covariance` rebuilds cov(ln x) from the reported
   standard errors and correlation matrix -- the inverse of the map the fitter already applied
   (section 3) -- and `_propagate` is a central-difference delta method in that space. For
   `tau = R*C` the finite difference is exact, and the test pins `sigma_tau/tau = sqrt(2)*0.1`
   for two uncorrelated 10% parameters. For the poles no standard error is attempted, because
   root ordering is not a smooth function of the parameters.
5. **The 2%-polarisation block is not recoverable at 1% noise even when the topology is
   asserted.** `p(R1,C1)-p(R2,C2)` at 100/5000 ohm was the first round-trip case; the fit of the
   *true* circuit returns `R1 = 0.09 ohm` and a time constant of 3e-15. That is an
   identifiability limit of the data, not something the interpretation can read around -- the
   round-trip test uses 100/500 instead, and says why. Worth remembering next to section 3's
   DRT entry, which is about detecting that same small block from the data.

### What is not done

~~The discovery report does not carry an interpretation.~~ **Done in §27**, and the
equivalence-class caveat turned out to be the substance of it rather than a footnote. The
browser does not show one. And the `model`/`interpret` objective split that `CLAUDE.md` now
defines is written down but not wired anywhere; gate O1 (both objectives produce a byte-identical
`DiscoveryResult`) is unimplemented.

## 22. The default pool stops being a decision about the part -- `core/descriptors.py`

`CLAUDE.md` required the automatic path to take frequency and impedance and nothing else, and
the default pool `("R", "C", "L", "CPE")` was a standing violation of it: "this is not an
electrochemical cell", written into a default the target user will never change, and never
mentioned by the coverage sentence. `--pool auto` is now the CLI default and
`discover(pool=None)` the API one. The full argument is `docs/POOL_FROM_SPECTRUM_PLAN.md`; this
section is what must not be re-derived.

### The exclusion was real, and one quarter of it was not

[measured] 1% noise, 61 points, 0.01 Hz to 100 kHz. `Ws`, `Wo` and `G` are transmission lines,
so no finite tree of R, C, L and CPE reproduces one: the best four-parameter default-pool answer
is 7.80%, 23.56% and 5.35% relative error against a 1.4% noise floor, and buying that down to
1.75-2.71% takes *seven* parameters against the truth's three.

**`W` is the exception and it is the one that looks most like the missing feature.** A
semi-infinite Warburg *is* a CPE at `n = 0.5`. On an `R1-W1` spectrum the truth fits to 1.3344%
and `R1-CPE1` fits to 1.3344% -- the same five figures -- so `W` is in the pool already under
another name, and `WIDENING_CANDIDATES` deliberately excludes it. The same fact is why an
`R1-W1` spectrum comes out right by a route worth following: the shape reading fires on it
loudly (it *is* a 45-degree spectrum) and the residual reading does not (+0.00, since the pool
can already express it), so the widening runs, the band admits only `W`, and **nothing is
added**. Two independent facts agreeing.

### Two readings, and **neither one is sufficient** -- do not delete either

Both instruments were tried as the sole trigger and both were rejected by measurement, on
*different* spectra. `choose_pool` widens when either asks. A version of this feature with one
of them removed passes every other gate and silently loses a class of answer; gate C6 in
`tests/test_descriptors.py` pins the two failure cases for exactly that reason.

**The shape reading** is the longest stretch, in decades, where the spectrum runs at 45 degrees.
Two corrections were needed before it measured anything and both must survive any rewrite: the
phase of `Z` is the wrong quantity, because `Ws`, `Wo` and `G` are 45-degree at their
*high*-frequency end -- exactly where a series resistance dominates -- and a detector built on
`arg Z` misses `R1-Wo1` and `R1-G1` completely, so the quantity is the local Nyquist angle
`atan2(dIm/dln w, -dRe/dln w)` where the additive constant differentiates away; and the sign is
the direction of travel, since a Nyquist plot is traversed towards *decreasing* frequency, and
taken the other way every case reports no branch at all.

[measured, 3 seeds x 2 noise x 4 grids] It fires 24/24 on `R1-Ws1`, `R1-Wo1` and `R1-G1`, 17/24
on `R1-p(R2,C1)-Ws1`, and **0/24 on `R1-p(R2,CPE1)-Wo1`** -- 0.20 to 0.60 decades, inside the
diffusion-free range, because a depressed arc's own tangent sweeps through 45 degrees on its way
round and a second process in the same decade blends the two. Against eight diffusion-free
truths it fires **0 times in 192 trials**, so the threshold `DIFFUSION_RUN_DECADES = 0.75` sits
between a measured 0.50 maximum and a measured 1.00 minimum.

**The residual reading** asks the search: `_best_runs_z` on the best base-pool fit, against
`POOL_WIDENING_RUNS_Z`. [measured, every truth at three noise seeds, production element limit]

| truth | runs z | fires at -1.5 | shape fires |
|---|---|---|---|
| `R1-Ws1` | -2.07, -0.77, -1.03 | 1/3 | **24/24** |
| `R1-Wo1` | -0.77, -2.07, -1.29 | 1/3 | **24/24** |
| `R1-G1` | -0.77, **+0.77**, -0.26 | **0/3** | **24/24** |
| `R1-p(R2,C1)-Ws1` | -2.58, -2.07, -2.07 | **3/3** | 17/24 |
| `R1-p(R2,CPE1)-Wo1` | -5.42, -4.39, -3.87 | **3/3** | **0/24** |

**The residual works on the composite truths, 6 of 6, and fails on the single-element ones, 2 of
9 -- and the shape reading is the exact mirror image.** `R1-G1` is the sharpest case: its three
residuals sit *inside* the diffusion-free distribution, so no residual threshold whatever could
separate it. That is not two noisy instruments averaging out; it is two instruments looking at
different things. The shape reading sees an unobstructed diffusion branch; the residual reading
sees the misfit a diffusion branch causes *when something else obscures it*. Exactly what hides
one is what reveals the other, which is why the union covers a set neither does.

The single-element cases fail because given five elements the default pool builds an
eight-parameter CPE stack (`p(p(R1-CPE1,CPE2)-C1,R2)`) reaching 1.385-1.577% against a 1.4%
floor: what separates the models there is parsimony, three parameters against eight, and the
runs test does not see parsimony. Note also that `R1-Wo1` read -4.39 at `exhaustive_limit=4` and
-0.77 at 5 -- these numbers are **not** comparable across limits.

### The trap beside the residual reading

**A systematic residual has two causes and the runs test cannot tell them apart** -- the pool is
too narrow, or the element limit is too low. That is a conflict rather than a nuisance: widening
the pool *costs* an element level (below), so answering a size-starved search by widening its
vocabulary makes the real problem worse. [measured] At `exhaustive_limit=4` the diffusion-free
`R1-p(R2,C1)-p(R3,C2)` fires at 24.191% -- correctly underfitted, wrongly attributed. At the
production limit of 5 it is at -0.26 and the ambiguity is gone. The three spectra that must not
fire sit at -0.26, -0.26 and +0.00, so `RUNS_Z_LIMIT = -3.0` is not wrong about them; it is the
Kramers-Kronig validator's constant, chosen where a false positive tells a user their
*measurement* is bad, and it sits on the wrong side of the ones that must fire. Hence a separate
constant, at -1.5.

**Both bars are set on the cheap side on purpose, and the implementation is what makes that
safe**: the widening *keeps* the base pool's candidates and merges them, so a false positive
costs a second search and changes no reported number, while `base_complete_up_to` still records
that every topology up to five elements from `R,C,L,CPE` was evaluated. A false negative returns
an eight-parameter stand-in for a three-parameter Warburg that no statistic in the report flags.
[measured] The empirical false-positive rate at -1.5 is **0 of 15** -- five truths the pool
covers exactly, three seeds each: `R1-W1` +0.00/+0.00/+0.52, `R1-p(R2,C1)` -0.26/-0.26/+0.52,
`R1-p(R2,C1)-p(R3,C2)` -0.26/+0.26/+1.03, `C1-R1-L1` **-1.29**/-0.77/+0.26, `R1-p(R2,CPE1)` at
`n = 0.80` -0.77/+1.29/+0.52. Closest approach 0.21; the nearest value that must fire is -2.07,
0.57 the other way, so the bar leans towards the cheap error by design.

**Do not raise the bar towards -3.0 on the theoretical rate.** The runs z is standard normal
when the signs are random, so `1 - (1 - Phi(t))^2` predicts 12.9% spurious widenings at -1.5
against 4.5% at -2.0 and 0.27% at -3.0 -- and the measurement beats that by an order of
magnitude, because eight of the fifteen values above are *positive*: fitting absorbs structure
and pushes the signs towards alternating, so a well-fitted spectrum is not a null draw. What
-1.5 buys over -3.0 is exactly one case and it is the weakest one: `R1-p(R2,C1)-Ws1` is 3/3
below -1.5, 0/3 below -3.0, and is the only truth the shape reading fails to cover completely
(17/24). At -3.0 it falls through both instruments on the 7/24 the shape misses.

### The report carries both readings, and derives the verdict

`PoolChoice` stores `diffusion_decades` and `residual_runs_z` and computes `triggered` from
them. That is not tidiness: an earlier version stored the verdict as its own field and a test
promptly built a `"yes"` whose two readings both said no, so the sentence and the flag described
different runs. `"unasked"` wins over a firing shape reading, because it is the genetic search,
which never completes a pool -- half the evidence is missing whatever the other half says, and
the sentence reports the shape reading separately.

### Why it cannot simply add all four codes

[measured] Topologies up to five elements, before the feasibility screen: pool of 4 gives 2,976,
5 gives 11,550, 6 gives 31,712, 8 gives 143,156. After the screen at `max_candidates = 20000` on
an `R1-Ws1` spectrum: `R,C,L,CPE` covers 5, `+Wo` covers 5, `+Ws,G` covers **4**, all four covers
4. One added code is affordable; two are not. And `Ws` and `G` are **not** substitutes -- swapping
them costs 3.3x to 3.6x in relative error (`R1-Ws1` fits at 1.333%, `R1-G1` at 4.334% on the same
data) -- so when the band admits both, both go in and the fifth level goes.

Which codes is decided by `EndpointBehaviour.low_band`, the same interval the feasibility screen
already trusts to *drop* topologies: `Ws`, `Wo` and `G` differ only in their DC limit (0, -1, 0).
[measured] The true code is in the admitted set in 138 of 144 trials; the six misses are all
`R1-p(R2,CPE1)-Wo1` on grids whose lowest frequency sits above the blocking region.

### Two smaller things

**`final_restarts=5` is not always enough once diffusion is in the pool.** [measured]
`R1-p(R2,C1)-G1` at 1% noise, fitted with its own generating topology, returns 15.055% relative
error at `restarts=5, seed=1` and 1.313% at `restarts=20` for both seeds tried -- and at 5
restarts the *wrong* topology `R1-p(R2,C1)-Ws1` scored better (2.599%) than the right one. Five
is `discover`'s default.

**mypy does not check `tests/`** (`packages = ["autocircuit"]` in `pyproject.toml`). Changing
`choose_pool`'s `triggered` from `bool` to a three-state literal left the tests passing `True`
and `False`, which silently took the *non*-triggered branch -- so gates C1 and C3 were exercising
nothing on the path they exist for, and the suite was green. Caught by reading, not by a tool.

### What is not done

~~The browser is unwired.~~ **Done in §26**, and it was the two-stage flow inside
`DiscoveryJob` that made it more than a one-line change.

`R1-p(R2,C1)-Ws1` is the weakest case in the table and neither instrument is comfortable on it:
the shape covers it 17/24 and the residual reads -2.58 at one seed, unmeasured across seeds. If
this feature ever needs a third instrument, that is the case to build it against.

The widening is not disabled under a skeleton and should work, since `_exhaustive` takes both;
nothing tests it. And `CC`, `HN`, `SKINF` and `SKINW` are outside `WIDENING_CANDIDATES` because
nothing has measured whether the default pool already expresses them -- the same unmeasured
guess this section removes, one level up, named rather than left implicit.


## 23. A report that walked away from the answer -- the refit order

The shortlisting round (`docs/SEARCH_ALGORITHM_SCREENING.md`) ended with one row of its §4.6
marked as a defect rather than a measurement, and this section is that row confirmed, diagnosed
and fixed. It came first, ahead of every search improvement on that document's list, for the
reason the list gives: **no search improvement is worth anything while the report can drop a
first-ranked candidate.**

### The defect, and it was not either of the two suspects

[measured] `_evolve` on the three-block Maxwell-Wagner reference, pool `R,C,L`, element cap 9,
seed 0, 180 s, `warm_accept=0`: the truth's equivalence class was reached, its best member
**ranked 1 of 270 in the archive**, four verified class members were shortlisted, and **none of
them were reported**.

The handoff named `_shortlist_candidates` and `_refine` as the two candidates. Neither was
wrong. The per-size quota kept the answer and `REFIT_HEADROOM` did what it was written to do.
What was missing is that **a tier that can stop early needs an order to stop in**, and nobody
had ever said what it was: `_quota_by_size` returns its selection grouped by element count, the
groups in whatever order the archive first mentioned them. That is correct for the exhaustive
stage, which refits every one of them. Under a deadline it decides what the user sees. The
rank-1 member sat at position 53 of a 73-candidate shortlist whose cut fell at 40; sizes 6 and 8
were never attempted at all, so the report carried no six-element row while the best thing the
search had found was one.

`_refine` now walks `_refit_order`: a round robin over the size groups, best of every size
before any size's second, ordered within a round by score. Its two properties are the quota's
own two, extended to a list that gets cut -- the best-scoring candidate is never cut, and a
truncated front still spans the complexities instead of collapsing to whichever sizes fitted
inside the clock. [measured] Same run, same seed, same 40 fits: **4 of 4 shortlisted class
members reported**, the rank-1 member refitted first.

### Four things not to re-derive

1. **An instrument that can see "not reported" cannot see *where*.** `evolve_probe.py` reports
   visited-versus-reported and had already established both halves; it took a second probe
   (`benchmarks/screening_round/report_probe.py`, which wraps both stages and prints each class
   member's archive rank, its shortlist position and where the deadline cut fell) to separate
   *shortlisted and dropped* from *never shortlisted*. The two-suspect hypothesis in the handoff
   was wrong in a way no amount of reading the code produced -- the answer was a third thing,
   the interaction between them.
2. **The class must come from `targets.py`, and `targets_rcl7.json` is enough.** Membership is a
   response test, never cost proximity (that over-counts 7.6x and has already flipped a verdict
   once). The committed file covers the class only up to seven elements, so it is a *superset*
   test for a drop: good enough to prove a member was lost, not to count how many exist.
3. **The fix must not touch the exhaustive path, and saying so is EV5's job.** It is confined to
   `_refine`, which only `_evolve` calls -- but that is exactly the kind of reasoning the lost
   tiebreak survived, so it was measured: `benchmarks/ev5_fingerprint.py`, three references,
   `mode="exhaustive"` and `mode="auto"`, `exhaustive_limit=4`, 486,846 bytes **byte-identical**
   between `HEAD`'s sources and the changed ones. Extract the "before" side with `git archive
   HEAD src | tar -x -C <dir>` and point `PYTHONPATH` at it; do not stash. Identity across two
   separate processes is also what re-establishes that the path is deterministic at `workers=4`,
   which the comparison silently depends on.
4. **Both new tests were shown to fail against the code they replace.** A test written after a
   fix proves nothing until the fix is reverted under it. The deadline test catches the old
   `for candidate in candidates`; the order test catches a plain global score sort, which is the
   other obvious way to write `_refit_order` and the one that throws the per-size spread away.

### State of the suite

[measured] **916 pass, 19 skip in 7 min 32 s** (`python -m pytest -q`, whole suite, machine
otherwise idle), up two tests from the previous count. `ruff check .` and `mypy src` are clean.
The skips are still the ngspice round-trip.

### What is not done

The next items are `docs/SEARCH_ALGORITHM_SCREENING.md` §5 in its own order: **B**, bounding
`_evolve`'s breeding pool (120/120 against 87/120 on the frozen landscape, a few lines around
`_next_generation`'s caller, and EV5 must be re-run because the point of the gate is to confirm
that `_next_generation` really is unreachable from the exhaustive stage); then NSGA-II only if B
is not enough; then pool staging, which must not be adopted until it is measured on a truth that
genuinely needs a CPE.

Two things this section deliberately did not do. It did not change *which* candidates the quota
selects -- only the order they are refitted in -- because the two questions have different
evidence behind them and mixing them would leave neither measured. And it did not touch
`REFIT_HEADROOM`: a 73-candidate shortlist against 40 affordable fits is a real budget shortfall,
and now that the cut takes the least valuable rows the shortfall is visible in `refit_progress`
rather than silently fatal.


## 25. The search stops breeding from its whole history -- `_breeding_pool`

Step 4's first half of `docs/EVOLVE_SEARCH_PLAN.md`, and the first item on
`docs/SEARCH_ALGORITHM_SCREENING.md` §5's adopt list. `_evolve` bred from its entire archive, so
`_tournament` drew 3 of N with N growing every generation and the best-known candidate's chance
of being picked fell 8.2x over twelve generations (§1.2 of the plan). It now breeds from
`_breeding_pool` -- the Pareto front plus the best `population` by score -- and nothing else
about the search changed.

### What it is worth, and which measurement says so

**The gate-grade comparison is the frozen landscape, not the wall clock.** [measured] 120 seeds
on the 21,057-topology `R,C,L,CPE` arena, budget counted in **fits**: **120/120 [0.97,1.00] at a
median of 308**, against the incumbent's **87/120 [0.64,0.80] at 451**. The arm was re-pointed at
the shipped function -- `arms.py` calls `discover._breeding_pool` rather than restating it -- and
returned the same two figures, so the two differences the library introduced (the archive is not
truncated; equal scores break on the canonical form) changed nothing.

**[measured] EV1, the real search, three references x seeds 0-2, 600 s each: 6/9 reported, 4/9
on the front, 3/9 recommended**, against a ratchet of 1/9, 1/9, 0/9 and against the nearest
same-code control (EV3's interleaved `warm on` arm, same references and seeds) of 3/9, 1/9, 1/9.
Three-block Maxwell-Wagner went 3/3 on all three counts; capacitor + interfacial went 0/3 -> 3/3
reported while staying 0/3 recommended, which is what that reference's own note predicts for a
10 mOhm ESR at 1% noise; Randles stayed 0/3 but its best relative error went 2.09-5.42% ->
1.24-1.65%, so it now returns a good fit of the wrong topology rather than neither.

**That EV1 run is not an interleaved comparison and must not be read as one.** No same-day
control arm was run beside it, the budget is wall-clock, and this machine drifts by a factor of
two within an hour (§4). The recovery counts are absolute floors, which is exactly why EV1's bar
was written as absolute floors; *topologies evaluated* and *minutes* from that run are indicative
only.

### EV4 fails on one clause, and the step ships saying so

[measured] `benchmarks/ev4_diversity.py`, three-block Maxwell-Wagner, seeds 0-2, 600 s, arms
interleaved, the control made by neutralising `_breeding_pool` rather than by an old copy of the
code. The per-generation cache-hit rate goes **38% -> 65% (mean, +26 points)** bounded against
**38% -> 44% (+5.7)** unbounded, so **EV4's first clause is failed**. Its second passes by 13x --
the best-known candidate's chance of entering a late tournament is 0.065 against 0.005, which is
the decay this step exists to stop -- and its third passes, since EV1 rose.

Two things the measurement adds that are *not* reasons to reword the clause, and it was not
reworded. The **control fails it too**, so "the hit rate does not rise" was never a bar only the
new code had to clear. And the **outcome it stands proxy for moved the other way**: the bounded
arm fits *fewer* distinct topologies (541-594 against 692-722) and recovers the truth far more
often (3/3 against 1/3 on this reference). Under a best-wins cache a re-proposal is refinement,
not a stall -- and the counts still vary with the seed, so nothing has closed one neighbourhood.
The gate stands as written, recorded as open, with islands (step 4's second half) and adaptive
parsimony (step 5) named as the remedies. Precedent for shipping this way rather than reading a
gate down: `docs/WEB_UI_PLAN.md` §2.7.

One incidental cross-check worth keeping: the probe's bounded arm evaluated 541, 562 and 594
topologies on seeds 0-2 -- the same three numbers EV1's run produced -- so the instrument is
driving the real search rather than a copy of it.

### Three things not to re-derive

1. **EV5 must be re-run for a change in `_evolve`, and it passed.** `_next_generation` should be
   unreachable from the exhaustive stage, and confirming that is the gate's job rather than the
   author's: `benchmarks/ev5_fingerprint.py`, 486,846 bytes, byte-identical.
2. **The archive is not truncated, and that is a deliberate difference from the arm.** The
   screening-round arm assigns its bounded pool back over the history, which is free when there
   is no report to produce. Here the archive is what `_shortlist_candidates` selects tier 2 from,
   so keeping it is what lets the search be bounded *and* the report be drawn from everything
   fitted. Measured to search the same: same 120/120, same median.
3. **The scaled tournament in §3.4's sketch is now unmotivated, not merely unbuilt.** A
   tournament of 3 from a set that no longer grows is already a constant pressure, and
   `TOURNAMENT_FRACTION` never had a measurement behind it.

### An environment fact, and a failure mode worse than the one it fixes

**[measured] The harness's own background mode survives a long job**: a 25-minute probe ran to
completion and reported its exit, and the 48-minute EV1 run did too. §4's older advice -- "a
backgrounded shell command is killed after ten minutes" -- is about a *shell*-backgrounded
command, and `nohup ... &` inside one is worse still: the wrapper exits, the child goes with it,
and the log file is never even created. That unblocks every gate in this repository that costs
more than nine minutes.

**But the notifications those jobs produce cannot be trusted, and this session lost work to it.**
Six per-seed EV1 results, a summary line and two "task completed" notifications arrived for runs
that had not happened; the output file and the process table said two runs were done and the
process was still alive. Numbers from them were reported to the user and had to be retracted,
along with a hypothesis (the search had lost its diversity) built on top of them. §4.7 records
the mirror image -- a finished run declared dead on a stale log line. **The file is the
measurement. A notification is a hint that it might be worth reading the file.** The same rule
that already applies to a subagent's report applies here.

### State of the suite

[measured] **918 pass, 19 skip in 7 min 34 s**; `ruff check .` and `mypy src` clean.

### What is not done

Islands (step 4's second half) and step 5 are untouched. Of `docs/SEARCH_ALGORITHM_SCREENING.md`
§5's list, NSGA-II is the next search change worth considering and is now less urgent than it
looked -- its advantage over this one on the frozen landscape is a median of 256 fits against
308, for a rewrite of the selection mechanism. Pool staging inside `_evolve` remains blocked on
an arena for a truth that genuinely needs a CPE.


## 26. The browser stops asking what kind of part this is

`docs/POOL_FROM_SPECTRUM_PLAN.md` §8, which is the section to read; this is what a later session
needs on top of it.

The deployed site had a **Pool** menu offering `default`, `component`, `electrochemical` -- the
question `CLAUDE.md` rules out asking, because a non-expert's wrong answer to it silently narrows
the search -- and `web/bridge.py` turned an absent choice into `DEFAULT_POOL`, so the browser
could never widen. It now defaults to *auto -- the spectrum chooses*, passes **no** pool, and
runs the same two-stage search the CLI runs.

### Four things not to re-derive

1. **The pool question can only be asked after tier 2, so the job needed a second pass.** The
   evidence `choose_pool` reads is the base pool's *own completed fit*. `DiscoveryJob` therefore
   re-enumerates and re-opens both tiers when the answer adds anything, and merges the first
   pass's candidates with `_unique_best` exactly as `discover` does -- they were fitted against
   the same data at the same budget, and dropping them would lose the sizes the wider
   enumeration can no longer afford.
2. **The driver had to learn that tier 2 running out is not the end.** `discover_refit` answers
   `more`. A driver that stops at the first `tasks: null` reports the narrow pool, silently, with
   a healthy-looking report -- which is what the browser did before, and what one of the new
   tests pins.
3. **`npm run dev` packages the Python once, at start-up.** Editing `src/autocircuit/web/` while
   the server runs leaves the worker on the old bridge. This cost a white screen, and note the
   part that matters: **`BRIDGE_VERSION` did not catch it**, because the version bump was in the
   edit the packaging had already captured. Restart the dev server after touching the Python.
4. **The gate is not "the browser also widens".** `tests/test_web_job.py` drives the whole search
   through `bridge.handle` and asserts the browser's report equals `discover(pool=None)`'s row
   for row -- same widened pool, same lost completeness level, same AICc, same sentence -- and
   asserts the spectrum really does ask for a wider pool, so the test cannot pass vacuously.

### Verified in a real browser

[measured] Chrome against the dev server, thin-layer-cell example, three-element limit: the
control reads *auto -- the spectrum chooses*; the first pass screens 75 topologies; the notice
appears; the second pass screens 244 with the level table updating 2/12/61 -> 2/24/218; the
report's coverage sentence carries runs z -5.74, a 0.90-decade 45-degree branch, `Ws, G` added,
and `Wo` and `W` left out with a reason each. No console errors.

### State of the suite

[measured] **921 pass, 19 skip**; `ruff check .`, `mypy src`, `npm run check` and `npm run smoke`
all clean. The wall-clock time of that run (22 min against the usual 9.5) is not a regression in
the tests: a Playwright Chrome with the app and its Pyodide workers was still open beside it,
which is §4's two-benchmarks-at-once rule showing up somewhere new. Close the browser before
timing anything.

### What is not done

The Fit screen has no pool control and needs none. What the browser still cannot do is show the
*structured* `pool_choice` -- it is on the wire and in the downloaded JSON, but the UI reads the
sentence only, which is the honest minimum rather than the whole of it.


## 27. The discovery report says what is inside the part -- and what the class will not let it say

`CLAUDE.md`'s purpose point 2 -- the circuit is a means and the inside of the part is the end --
reached only `autocircuit fit --interpret`, which is the mode where the user already wrote the
circuit down. Discovery, the mode this project is actually for, stopped at a Pareto front.
`autocircuit discover --interpret` now reads the recommended circuit as internal structure, and
`interpretation` is in the `--json` report.

### The equivalence class is the substance, not a caveat

Interpreting the recommendation and stopping would have been the obvious build and it would have
been wrong, for the reason `CLAUDE.md`'s Objectives section gives: under `interpret` the classes
*are* the question, because whether a resistance is a grain boundary or an electrode interface is
exactly a difference of form. So `interpret_class` reads the recommendation **and every other
topology the data cannot tell it apart from**, and *measures* which numbers the class agrees on
instead of asserting the invariant flag. Each quantity carries a `spread`
(`max|v - median| / |median|` over the members) and a `reported_by` count.

[measured] Two independently fitted members of one class -- `R1-p(R2,C1)` and `p(R1,C1-R2)`, same
noisy data, separate global fits -- agree on every invariant quantity to **2e-11**. That is gate
I1's first half re-established on *fits* rather than on exact algebra, which is the case a
discovery report actually holds.

And the second half is what the report now says out loud. On the `p(R1,C1)` reference at a
three-element limit the recommendation is `p(R1-C1,R2)`, which shows **0** relaxations, while the
topology beside it in the same class shows **1**:

```
they do not agree on how many relaxations this part shows: p(R1-C1,R2) says 0,
p(R1,C1)-R2 says 1 -- that count is a property of the form, not of the measurement
```

"How many processes does this part have" is the single most misleading thing a non-expert can
take out of a discovery report, and it is form-dependent. A class of one says so instead of
claiming agreement with itself.

### Two things not to re-derive

1. **`interpret_class` takes the class, it does not find it.** Deciding what an equivalence class
   is belongs to the search (`DiscoveryResult.equivalents_of`, by response), and putting that
   rule in the interpretation module would be a second implementation of it.
2. **A tooling hazard that cost three edits, this section included.** A backslash-n written
   inside a `python - <<'EOF'` heredoc through the Bash tool arrives as a *real newline*, which
   silently breaks any string literal containing one. Build such a literal with `chr(10)`/`chr(92)`, or use the Write tool.
   §4's note about heredocs and apostrophes is the same family.

### The browser shows it too

`discover_interpret` (`BRIDGE_VERSION` 9 -> 10) answers the structured reading *and* the rendered
`summary`, and the Report screen's `InterpretationPanel` shows both: a table of the quantities
with a "Holds for" column, and the CLI's own text behind a disclosure. The sentences are not
re-composed in TypeScript, for the same reason `completeness` is not.

Two things the panel has to get right, and both were wrong in the first version until a browser
showed them:

* **A class of one must not report agreement with itself.** The table said "all 1 agree to 0.0%",
  which is the vacuous claim the whole module is arranged against. It now says "unchecked: only
  one form found", and the heading says there is no second form to disagree with it.
* **The disagreement is the headline, not a footnote.** When the members differ on how many
  relaxations the part shows, that is an alert above the table, naming each form and its count.

[measured, in Chrome] Tissue (Cole) at a three-element limit: the panel reads "checked against
the 1 other topology this search could not tell apart from it", warns that `p(R1,CPE1)-R2` says 1
relaxation and `p(R1-CPE1,R2)` says 0, and reports the four invariant quantities as agreeing to
2e-9 to 5e-9 percent. No console errors.

### What is not done

The Fit screen shows no interpretation -- a manual fit has no equivalence class to check against,
so it would be the weaker half of the same panel, and the command line already covers it. Since
section 28 the way to ask for this reading is `--objective interpret` on either front end, and
the panel described above is one half of the two the Report screen now offers.


## 28. The objective gets wired, and gate O1 is a structural claim before it is a byte claim

`CLAUDE.md`'s "Objectives" section has been asking for this since it was written: there are two
reasons to bring a spectrum here -- a circuit to simulate with, and a reading of what is inside
the part -- and they want different reports out of the *same* analysis. `core/objective.py` is
that reporting layer, `--objective {model,interpret}` reaches it from `fit` and `discover`, and
`autocircuit objectives` explains the axis. `docs/OBJECTIVE_PLAN.md` is the plan document.

### The invariant is held by construction, and that is the half of O1 that matters

Gate O1 is stated as a byte comparison: both objectives, same spectrum and seed, byte-identical
`DiscoveryResult` wire payload. That is worth measuring and it is *not* what holds the property.
What holds it is that `discover()` and `fit()` take no objective and neither module imports the
reporting layer, so the value cannot reach a search that might act on it. A byte comparison
passing while the parameter existed would say only that two runs happened to agree on the three
spectra it was given -- which is the same shape as every screening-budget failure in section 3:
the report looks healthy and the claim underneath it is weaker than the sentence.

So `benchmarks/o1_objective.py` checks both, and fails with exit status 1 rather than printing a
table. [measured, `--limit 3`] structural pass; payload identical and report differs on all three
references (capacitor, Maxwell-Wagner, Randles). A cheap copy runs in the suite
(`tests/test_cli.py::test_the_objective_changes_the_report_and_not_one_number`), so a leak fails
CI instead of waiting for a benchmark nobody runs.

### Four things not to re-derive

1. **`--objective` defaults to `None`, not to `model`.** With a real default argparse cannot tell
   *asked for model* from *asked for nothing*, and `--interpret --objective model` -- two answers
   to one question -- was accepted silently, the alias winning. Resolving `None` in
   `_objective_of` is what makes the conflict visible at all.
2. **A payload comparison drops clocks recursively.** Every candidate carries its own
   `elapsed_s`, so popping the top-level one leaves dozens of differences that have nothing to do
   with the objective. `_stable` in the benchmark and `_without_clocks` in the test both walk the
   whole tree. A gate that fails for a reason it is not about is a gate that gets reworded.
3. **The `model` report's licence is checked, not asserted.** Its numbers are printed under
   "properties of Z, so every equivalent topology agrees", and that sentence is true only because
   every name in `MODEL_READOUTS` is marked `invariant` in `core/interpret.py`. A test asserts it.
   The failure mode -- a form-dependent number under an invariant heading -- is invisible in the
   output, which is precisely what `interpret.py` exists to prevent.
4. **ESL is the apparent inductance at the top of the band, not the model's `L`.**
   `inductance_at_f_max` is `Im Z / omega` at `f_max`, gated on the response being inductive
   there; for a series R-L-C that is `L - 1/(omega^2 C)` and approaches `L` only well above
   resonance. Reporting the parameter would be reporting the form under an invariant heading.

The "standard error exceeds the value" rule moved from `core/discover.py` to `core/stats.py` as
`unresolved_mask` on the way past: three readers now ask that same question of one fit -- the
Pareto table's `free?` column, the skeleton's "the data does not test this part of your
assertion", and the `model` objective's warning that a value carries no information on its own.

### What the two reports say

`model` leads with the deliverable and its limit: the circuit, the band it is valid over (the
measured one -- outside it the model is extrapolation and nothing has tested it), the agreement
inside that band, the invariant readouts, and `Re Z` sampled across it. Its equivalence-class note
is the interesting one, because under this objective the class is a *non-problem* and saying so is
still honest work: the members have the same terminal Z over the band, so they export and simulate
identically, and they are free to differ outside it -- which is why the band is part of the
deliverable and not a footnote.

`interpret` is the `ClassInterpretation` of section 27, now reached by `--objective interpret`
(`--interpret` is kept as its older spelling), plus the sentence that everything above is
conditional on the reported form. The DRT, when it was computed beside the search, now feeds its
model-free relaxation count into the cross-check; it remains advice and changes no candidate and
no number.

### The browser asks the same question, and a bug the wire had been hiding

`discover_interpret` became `discover_objective` (`BRIDGE_VERSION` 10 -> 11): the objective
travels with the request for a *report*, and no search operation takes one. The Report screen's
`ObjectivePanel` switches between the two with two buttons; switching re-fetches and cannot
re-run anything, which is the structural claim made visible.

[measured, in Chrome] Tissue (Cole), three-element limit. Under `model`: `p(R1,CPE1)-R2` over
10 Hz - 1 MHz, RMS |dZ|/|Z| 1.28%, worst point 2.37%, and the note that the one other topology
in the class exports and simulates identically over that band. Under `interpret`: the
relaxation-count alert (1 against 0) and the four invariant quantities agreeing to 1.9e-9 to
4.6e-9 percent. No console errors.

Building it turned up something older. `ClassSpread.spread` divides by the median, and its
zero-median guard returned `inf` -- so a quantity every member reports as *the same zero*
(`r_inf` of a network that is a short at the top of the band, which `interpret.py` reports as
exactly zero on purpose) came out as infinite disagreement. Because the browser's wire is
strict JSON, that one value made the **whole response undeliverable**: the reader got "Out of
range float values are not JSON compliant" where a report should have been.
[measured] `p(R1,C1)` and `p(C1,R1)` as one class: spread `inf`, `json.dumps(allow_nan=False)`
raises. Both halves are now fixed and both were needed -- exact agreement reads 0 whatever the
median is, and every objective payload leaves through `wire.encode_payload`, so no report can be
lost to a non-finite value it merely mentions.

### State of the suite

[measured] **942 pass in 10 min 15 s** (`--ignore=tests/test_spice_ngspice.py`, which needs the
ngspice in WSL); `ruff check .` and `mypy` clean; `npm run check` and `npm run smoke` pass.

### What is not done

The Fit screen still shows no report of either kind; `fit --objective` covers mode 1 on the
command line. The multi-condition fit -- several sweeps at different temperature or bias, fitted
to one circuit -- was built and its gates measured passing, then withdrawn on a scope decision
(`docs/IMPACT_PLAN.md` §3): relating a part's parameters across experimental conditions via a
named physical law is the analyst's own judgement to make outside this software, not a
narrowing this software should offer.

## 29. The breeding pool loses its width, and the islands lose their case

`docs/EVOLVE_SEARCH_PLAN.md` §3.4.3 and §3.4.4. Section 25 above shipped `_breeding_pool` as
*the Pareto front plus the best `population` by score*, and §3.4.2 then split that pool across
islands. Neither had measured the one number both were built on: how wide the pool should be.
`population` was the width because `population` was the argument already in scope.

### What ships

**The front, and nothing added to it.** `BREEDING_EXTRA = 0`, a module constant with its
measurement in its docstring. It stays a parameter of `_breeding_pool` (so the two benchmarks
that measured it can re-walk the ladder) and it is deliberately not a parameter of `discover()`:
a search internal the target user cannot set correctly is not a knob, which is also why the
`--islands` CLI flag that had been added should never have been offered.

**The islands are gone** -- `islands`, `MIGRATION_FRACTION`, `_island_sizes`, `_island_streams`,
`_migrants`, `_with_migrants`, the CLI flag and five tests. `arm_islands` stays in
`benchmarks/screening_round/arms.py` with its own copies of the three helpers, for the same
reason `arm_nsga2` and `arm_map_elites` are there: an arm that recorded a rejection has to stay
runnable, or the rejection is a claim and not a measurement.

### The numbers, on the 21,057-topology frozen arena

[measured] 120 seeds, `population` 40, AICc; raw output in
`benchmarks/screening_round/results_pool_bound.txt`.

| breeding pool | hit @150 fits | hit @250 fits |
|---|---|---|
| front + 40 (what section 25 shipped) | 7/120 [0.03,0.12] | 38/120 [0.24,0.40] |
| front + 10 | 30/120 | 93/120 |
| front + 3 | 64/120 | 110/120 |
| **front alone** | **65/120 [0.45,0.63]** | **112/120 [0.87,0.97]** |
| 4 islands x (front + 10) | 18/120 [0.10,0.22] | 68/120 [0.48,0.65] |

`pool_bound = 0` and `pool_bound = 1` are **the same arm on every seed** -- identical medians,
identical best AICc, identical histograms. That is an identity, not a coincidence: the
best-scoring candidate cannot be dominated, so it is already on the front. The ladder therefore
ends at a rule with no width in it.

Islands under that same rule: two islands 302/480 against one pool's 282/480, McNemar p = 0.216
-- indistinguishable; four islands 233/480, p = 0.0020 -- worse; four islands with migration
switched off 27/120 against 65/120 -- far worse.

### Four things not to re-derive

**A saturated arena ranks nothing, and it looks like a result.** At the 900-fit budget section 25
used, all eleven arms reach 120/120, so only median fits separates them -- and read that way the
islands beat the incumbent, 239 to 308, p = 0.0000. They lose to a single pool of their own width
at 194. Same shape as `SEARCH_ALGORITHM_SCREENING.md` §4.2 and the opposite direction: check that
the arena still has somewhere to fail before believing a ranking from it.

**A cache hit costs no budget and does cost wall time.** `Table.evaluate` returns a known
topology without incrementing the fit counter, so a tighter pool re-proposes what it knows,
burns generations for free, and runs *far longer in wall clock while spending fewer fits*. A
tight arm that looks hung is not. Fits are the right unit for the comparison and the wrong unit
for an ETA.

**`pool_bound or population` folded the deciding arm into the default.** The arm that settled the
question is the one whose bound is 0, and `or` silently ran it at 40. It produced a plausible
number rather than an error. `is None`.

**The paired table in `arms.py` could not test a hit rate.** It compares fits-to-hit and drops
every seed either arm missed, which at an unsaturated budget is the whole signal, so the hit-rate
column had never been tested by anything. An exact McNemar on the discordant seeds is printed
above it now, and it demoted the two-island reading from 77-against-65 to p = 0.216.

### Three readings withdrawn, with the numbers that withdrew them

* *"Islands help."* Measured at a saturated budget; they lose to one pool of their own width.
* *"The ladder turns around at a pool of one."* A 3-seed smoke run said 131 fits against 222; at
  120 seeds the two rungs are 146 and 148.
* *"Two islands beat one pool."* 77/120 against 65/120 at 120 seeds; p = 0.216 at 480.

### The gates, and the one that got worse

**EV5 passes.** `mode="exhaustive"` and `mode="auto"` produce a **byte-identical 487,364-byte**
fingerprint across the change -- `diff` returns nothing at all. Run both sides with the *same*
copy of the probe: the first attempt diffed on the header line alone, because the "before" side
had used the probe as it stood at HEAD, which did not yet echo the genetic-path parameters. That
is a difference in the instrument and it would have had to be explained away in prose; copying
the current probe into the `git worktree` and re-running is a few minutes and leaves nothing to
explain.

**EV1 does not regress, measured against a same-day interleaved control** —
`evolve-gate --breeding-extra 40,0`, three references x seeds 0-2, 600 s each. The shipped rule
reaches 5/9 reported, 5/9 on the front, 3/9 recommended against the previous width's 4/9, 3/9,
2/9, and clears EV1's floors of 1/9, 1/9, 0/9. It does that while fitting a third fewer distinct
topologies (1,115 against 1,675 on the reference that separates them) and running **536
generations against 260** in the same wall clock -- both figures from that run rather than
borrowed from EV4's. Nine runs cannot make 4/9 against 5/9
significant; what EV1 licenses is *no regression*, which is how its bar is written. Do not read
this table against the 6/9 in section 25 -- that one was taken at the 30-generation cap with no
control, and says so.

**EV4 fails a second clause, and the step ships saying so.** Clause 2 -- P(best) does not fall --
passed for the front-plus-forty rule (0.0654 -> 0.0635) and **fails for the front alone**
(0.3763 -> 0.2750, a 1.37x fall). The mechanism section 1.2 named is absent: that is an archive
growing without bound, which the unbounded arm still shows at 8.3x with N reaching 2,104, while
the front's N goes 5 -> 10 as it acquires one more complexity level -- and it falls from a level
4-6x higher than the arm that passes. Clause 1 fails for all three arms; the front's +3.0 points
is the smallest rise measured and is not good news, because its hit rate is **92% in the first
third** and has nowhere to rise to. The clauses are recorded as failed with those mechanisms
beside them and are not reworded, for the reason section 25 gives.

### One unrelated flake fixed on the way

`tests/test_web_job.py`'s gate-O1 test compares two readings of one finished job with
`_without_clocks`, which dropped every `elapsed_s` key and missed the same clock spelled out in
the rendered summary ("Evaluated 6 distinct topologies in 1.2 s"). The two readings disagree
whenever they land either side of a tenth of a second. The string is scrubbed in the test, not in
the renderer -- a report that tells the user how long the search took is right to.

## 30. Two tuning knobs measured, neither moved, and the round finds it had only ever asked one question

`docs/EVOLVE_SEARCH_PLAN.md` §3.5. Step 5 was the plan's last piece of *tuning* — adaptive
parsimony in selection, and the mutation weights, which were the only constant in `discover.py`
carrying no **[measured]** note. Both were built exactly as specified. **Neither default moved,
and that is the result rather than a failure to find one.** What the step actually produced is a
hole in the instrument the previous four steps were measured with.

### What ships

**`PARSIMONY_SCALING = 0.0`** and **`MUTATION_WEIGHTS = (0.35, 0.25, 0.25, 0.15)`** — the two
values the step started with, now with the measurement in their docstrings. Both are module
constants reachable from the benchmarks and from nothing else, the shape `BREEDING_EXTRA` and
`WARM_ACCEPT_FACTOR` already have; `mutate` and `_next_generation` take them as keywords so the
sweep drives the real operator, and `discover()` does not, because "how much should the search
prefer deleting an element" is exactly the search internal CLAUDE.md says is not a knob.

**The crowding term stays in `discover.py` even though it is off** — a different disposal from
the islands of §29, deliberately. Those were measurably *worse* and their arm owned its own
generation loop, so moving them to `arms.py` cost nothing. This is a keyword on `_tournament`,
and deleting it would force the arm that records the rejection to reimplement
`_next_generation`, which is the one thing `benchmarks/screening_round/arms.py`'s docstring says
an arm may not do.

**A second and a third reference for the frozen-landscape round** (`landscape.py --reference
series`, `targets_series_rcl6.json`, `targets_series_rcl7.json`), and the raw output of both
sweeps in `results_parsimony.txt` and `results_mutation_weights.txt`.

### The thing worth more than either verdict

**Every arena this round had ever built freezes the same truth.** `land_rcl6`, `land_rcl7` and
`land_rclcpe6` are three spaces around one circuit — `p(R1,C1)-p(R2,C2)-p(R3,C3)`, five of whose
six elements are joined in parallel. `SEARCH_ALGORITHM_SCREENING.md` §2.1 lists that as a
limitation on *transfer*; step 5 is where it became a confound on *results*.

The mutation sweep's strongest arm moves weight from insert-series to insert-parallel and beats
the shipped tuple 308/480 to 282/480, McNemar p = 0.018. It is not a better search. On a truth
that is four series elements and one parallel block it *loses*, 281/480 to 306, p = 0.0001, and
the mirror arm reverses both signs. [measured] The reversal holds when the element cap is raised
from six to seven, so it is a property of the truth's shape and not of one arena.

So the sweep's answer is not a new tuple; it is that **the insert-series and insert-parallel
weights must stay equal**, which the shipped tuple already does and which nothing had ever
checked. An asymmetric setting is the software deciding what kind of part this is, reached from
inside the search rather than from the CLI.

### The parsimony ladder, and a 77-against-65 for the second time

[measured, `results_parsimony.txt`] Scaling 0.5 through 1e6 on the 21,057-topology arena, 120
seeds at 150 fits: everything below 300 is inert (the penalty is at most `scaling`, and front
members' scores differ by hundreds of AICc), everything above wanders between 57/120 and 78/120
with no ordering, and the degenerate limit — where the term outranks fitness entirely — is the
*worst* arm on the ladder.

**`pars1000` read 77/120 against `ga_front`'s 65/120 at p = 0.029.** Those are the same counts,
against the same control, with the same p, as the two-island arm of §29 that 480 seeds demoted.
At 480 seeds this one is 293/480 against 282/480, p = 0.32, and p = 0.92 on the second reference.
Twice now this round has produced a 77-against-65 that did not survive; the number to remember is
that a 120-seed ladder of eight arms hands one of them a p below 0.05 about whenever it is asked.

### Four things not to re-derive

* **A crowding count over the breeding pool is a no-op**, and not for any reason to do with
  adaptive parsimony. Step 4 left the pool equal to the Pareto front, which holds about one
  member per complexity by construction. The frequency has to be taken over the **archive**,
  where 58% of a run's fits land at five and six elements. The plan's own wording implies the
  pool; following it would have measured nothing and blamed PySR.
* **PySR's multiplicative form is wrong for this criterion.** It scales the loss by
  `exp(scaling x frequency)`; AICc here is usually negative (the arena optimum is −1682), so a
  factor above one *rewards* the crowded level. Additive, in units of the criterion.
* **`targets.py --max-checks` truncated the band from the cheap end and silently dropped the
  truth.** The band is sorted by screening cost and the truth sits at its expensive end by
  construction, so an arena whose band exceeds the cap returns a target set that does not contain
  the answer — and a 0-target run reads exactly like an arena with no equivalents. Found on the
  n <= 7 series arena: band 761, default cap 400, 250 rows in and still zero. The truth row is now
  appended unconditionally and a truncated band prints a warning.
* **Calibrate the budget for every new arena.** The series arena is 12x denser in targets than
  the CPE one (1.06% against 0.085%), so the 150 fits that leave the CPE arena at 59% leave this
  one saturated at 40/40. Budget 40 puts it at 64%. This is the README's "a budget everything
  clears is a budget that ranks nothing", applied to the arena instead of the arm ladder.

### One arm that never lost, and was still not taken

`mut_del_lo` cuts the delete weight 0.15 → 0.05: 316/480 (p = 0.017), 312/480 (p = 0.61),
321/480 (p = 0.10) across the three arenas. Significant on one of three, and the obvious mechanism
— deleting is nearest to waste when the truth is already as large as the search may go — was
confounded with how the arenas were built, since their truths sit at the cap and one below it.
The third arena is that confound measured out: same truth, same data, same budget, cap 6 → 7. It
did not separate. `mut_uniform` is the mirror case, flat on two arenas and significant on the
third, and it is declined for the same reason. **Significant on one arena of three, in a sweep
where the real effects are significant on all three and reverse sign on cue, is not a result.**

### The gates

* **EV5 re-measured: 487,364 bytes, byte-identical.** Step 5 touches only operators the
  exhaustive path never calls, which is the argument and not the evidence — and §3.2.1 records the
  whole suite agreeing with that kind of argument while a bug was in place. The evolve path has
  its own check and it is sharper: `arms.py --arms ga_front` over 120 seeds returns the same
  65/120, the same median 113 fits, the same best AICc −1676.14 and the same size histogram
  before and after.
* **EV1's ratchet is not re-run and does not need to be**: no default changed, so the search is
  the one EV1 already measured at 5/9, 5/9, 3/9.
* **EV4 clauses 1 and 2 stay open.** Adaptive parsimony was the remedy most directly aimed at
  clause 1 — keeping every complexity populated is what it exists for in PySR — and it is
  measured as doing nothing. Both remedies the plan named have now been built and measured, and
  neither closed a clause. They are not reworded.

### State of the suite

`pytest`: **946 passed, 19 skipped**. Three tests added, all in `tests/test_discover.py`: the
weights reach the operator, neither knob is reachable from `discover()`, and the crowding term
changes which parent breeds while leaving every reported score exactly as it was. `ruff check`
and `mypy` clean. `npm run check` untouched — no browser path uses evolve.

One existing test needed a one-line change: the spy in
`test_the_search_breeds_from_a_bounded_pool_however_long_it_runs` replaces `_next_generation` and
now has to forward the keywords `_evolve` passes it.

### What is not done

* ~~Step 6, the documentation pass that marks the plan implemented, is still open.~~ **Done, §31.**
* EV4's two failing clauses, and the question §29 left: whether a re-proposal under a best-wins
  cache is a cost at all.
* The two EV1 references where `mode="evolve"` scores 0/3 still cannot be put on a landscape.
  The series reference added here is a *reduction* of one of them (`LARGE_REFERENCES[1]` with the
  CPE and skin-effect element replaced by their plain counterparts) chosen so that its space can
  be enumerated — it varies the shape of the truth, which is what step 5 needed, and it does not
  relieve §2.1's limitation about the two hard references themselves.

## 31. The documentation pass, which found three docs describing a search that no longer exists

`docs/EVOLVE_SEARCH_PLAN.md` step 6, the last of the six. It moves no code and adds no
measurement; what it does is make the written record agree with the six steps and the five
gates that came before it, and the reason it is worth a section is that **three separate
documents were still describing the genetic search as it was designed rather than as it was
measured** — each of them in a place a future session would have read as authoritative.

### What the plan now says about itself

`EVOLVE_SEARCH_PLAN.md` is marked **implemented (2026-08-29), all six steps**, and its status
line leads with the part that is easy to lose: EV1's ratchet, EV2, EV3 and EV5 pass, and **EV4
ships with two of its three clauses failed**. `CLAUDE.md`'s "Start here" entry 10 now opens with
the number the fallback is allowed to claim — **5/9 reported, 3/9 recommended** against a 1/9,
1/9, 0/9 baseline — together with the sentence that keeps it honest: it may never be reported in
the same breath as the exhaustive stage's 30/30, and one of the three references is still 0/3.

### The three stale places, which are the actual find

* **`DISCOVERY_V2_PLAN.md` §5.1** gave `REFINE_DEFAULT["evolve"]` as **8** and justified the
  split from exhaustive's 30 by "which gate G5 forbids" — a clause step 2 had *withdrawn* in the
  same round that set the constant to 30. A reader following that bullet would have restored a
  value the code no longer holds, on the authority of a gate that no longer exists. Both halves
  are corrected, with the arithmetic that says the split never bought anything: the quota is
  `max(MIN_REFINE_PER_SIZE, n_refine // sizes)` and an archive spans about seven element counts,
  so 8, 16 and 30 all reduce to a quota of 5.
* **`IMPLEMENTATION_PLAN.md` §6** still specified selection as "regularized evolution (age-based)
  with island populations". Neither survived: the islands were **built and removed** (§29), and
  the bound on the breeding set turned out not to be a width at all — the Pareto front alone
  ships. This is the bullet that would have sent someone to re-implement the very thing 480 seeds
  demoted.
* **`IMPLEMENTATION_PLAN.md`'s "[measured] Current capability of the genetic search"** was a
  two-minute, 113–257-topology reading from before this round, sitting under a **[measured]**
  tag with nothing to say it had been superseded by a 600 s nine-run gate. It is kept — §6.1 was
  written against it and deleting it would orphan that argument — but it is now dated and points
  at the new **§6.3**, which states EV1's ceiling, EV2's fix, EV4's two open clauses and EV5.

### `benchmarks/README.md` could be run from but not read from

The evolve-gate *commands* had been in its header since step 1; the **results had never been
written down anywhere but the plan**. It now carries `evolve-gate` (EV1 and EV3),
`ev4_diversity.py` (EV4) and `ev5_fingerprint.py` (EV5) as results sections beside G1, P1 and
P2 — including the four things EV1's table is *not*, which is the part that matters in a file
whose other tables are all budgeted in fits or in candidates rather than in wall-clock.

### Two things not to re-derive

* **The 6/9 in §25 and the 5/9 quoted everywhere else are not the same measurement and their
  difference is not a regression.** §25's arm is the pool at its first width (the front plus
  about forty), run uncontrolled and stopped at the 30-generation cap; the 5/9 is the shipped
  front-only arm, interleaved seed by seed against a same-day control of that same earlier width,
  which read **4/9** beside it. So the pair to compare is 5/9 against 4/9, and §29 already says
  not to read its table against §25's number. The doc pass did not reconcile the two into one
  figure: they are measurements of different quality, and averaging them would destroy the only
  information the pair carries — that a wall-clock budget on this machine moves a recovery count
  by as much as a change to the search does.
* **The failed EV4 clauses stay in the present tense.** The temptation a documentation pass
  creates is to write a completed plan as a success story, and the two clauses are the one place
  this round has to resist it: the arm that ships re-proposes what it already knows 92–95% of the
  time and its best candidate's tournament probability falls 1.37× across a run. Both remedies were
  built and measured away. A future session may close them with a measurement; it may not close
  them with a sentence.

### State of the suite

Unchanged — no code was touched: `pytest` **946 passed, 19 skipped**, `ruff` and `mypy` clean,
`npm run check` untouched.

### What is not done

* EV4 clauses 1 and 2, still open and still unremedied.
* The two EV1 references at 0/3, and `EVOLVE_SEARCH_PLAN.md` §6's live clause: `mode="auto"`
  above five elements may yet be better served by reporting an under-fitted exhaustive front than
  by handing off at all. Nothing in this round decided that, and this section does not either.

## 32. Running the tool this project had only ever cited, and the defect that turned up here

`docs/AUTOEIS_COMPARISON_PLAN.md` was the plan; `docs/AUTOEIS_COMPARISON.md` is what happened.
AutoEIS had been cited in four places since the beginning and **never run**. It has now been run.

**The result has no winner.** On arena C's five- and six-element truths, at both tools' defaults,
one referee applied to both: this project 2/7 with a truth-equivalent anywhere in its candidate
list, **0/7 as its recommendation, 0/7 on its own front**; AutoEIS 0/7 on all three. Paired, 2
discordant runs both this way, p = 0.50 against `d` = 6 — indistinguishable at this seed count.
All fourteen runs are `ok`: no crash, no `filtered`, no empty result. They are searches that
finished and returned the wrong circuit.

**The round was stopped at 7 of 20 pre-registered pairs, after the result was seen**, on the
user's decision. §2.1 of that document records it as a departure from its own stopping rule rather
than as a machine-time stop, because the direction being null rather than significant does not
change the mechanism.

### What must not be re-derived

- **`generations` is 0 on all forty runs — the genetic fallback never ran.** Its trigger is
  `_is_underfitted`, a runs test at `z < RUNS_Z_LIMIT = -3.0`, and the recorded residual z on the
  six-element truths is −0.45 and +0.67, on the five-element ones 0.00 and +0.22. A five-element
  answer reproduces these spectra to within what 1% noise hides. **`EVOLVE_SEARCH_PLAN.md`'s
  measured 5/9 for the fallback was never the limit here — the fallback was never asked.** If the
  six-element behaviour is to be improved, the trigger's sensitivity is the thing to work on, not
  the genetic search.
- **Below six elements this project does not search for the truth, it enumerates it.** 30 of 40
  runs have the truth inside `complete_up_to`. Any comparison pooled across sizes is quoting the
  arena's construction; report per size.
- **The identifiability screen took three versions and the first two passed truths nothing could
  recover.** Standard errors alone let through an inductance fitted at 1.2 H against a true
  9.4e-8 H at 1.3% relative error with every parameter "resolved"; adding a value-matched
  deviation check did not fix it, because for a parameter the data does not contain the deviation
  of one fit is a lottery. What works is asking directly: perturb each parameter and require the
  spectrum to move by more than the noise (`arena.py`, `parameter_leverage`).
- **AutoEIS facts, measured from version 0.0.44 rather than read from its docs**: vocabulary
  `R, C, L, P` and **no Warburg**; default `terminals="RLP"` excludes the ideal capacitor and
  `capacitance_filter` deletes any circuit keeping one; `ohmic_resistance_filter` requires a
  series ohmic R, which alone removes ~85% of the shared topology space; **the default parallel
  path does not honour its seed** (two runs at seed 1 returned disjoint sets); `seed=0` falls back
  to the clock; `perform_full_analysis()` raises `NotImplementedError`; its ranking rule is
  `WAIC (sum)` ascending; its preprocessing deletes 6–37% of a sweep before its search sees it;
  and **a clean `pip install autoeis` today produces a build whose last stage crashes**, because
  the package requires `arviz` unbounded and 1.x removed `az.waic` — pin `arviz==0.23.4`.
- **AutoEIS's parallelism is Julia `Distributed`, one `julia.exe` per physical core.** The parent
  Python process shows almost no CPU. That is normal and is not a stall — it was diagnosed as one
  twice (§0.3 of the comparison). **Judge a run when it finishes or fails; the process table can
  say what is running, never that nothing is progressing.** Related: a `nohup ... &` launch from a
  Bash tool call does not survive its shell and fails silently, and killing a producer by process
  *name* misses it when the interpreter is named differently — twice that left two producers
  writing to one file.

### Environment

The AutoEIS install is **outside this project** at `C:\Users\toshi\python\autoeis-env` (Python
3.12.10, because `autoeis` declares `requires_python <3.13`). Julia 1.10.12 and
EquivalentCircuits.jl 0.3.1@master come from `juliapkg`. Nothing of it may reach `pyproject.toml`.
`benchmarks/autoeis_round/README.md` has the commands; `run_round.ps1` runs the three steps
unattended and every step resumes by re-issuing the identical command.

## 33. Six elements and up — the growth stage, and two defects it uncovered on the way

`docs/TOPOLOGY_6PLUS_PLAN.md` is the plan and the results; this is the part a reader needs before
touching the code. The round asked one question — can this project recover a topology of six
elements or more from the spectrum alone — and the honest first answer was that "six elements does
not work" is **four** independent problems, not one:

* **(I) information** — does the spectrum distinguish six elements from five at all;
* **(S) search** — where it does, is the class reached;
* **(P) parameters** — is it fitted well enough to *score*;
* **(R) reporting** — is it then recommended.

Fixing any one alone changes nothing, which is what happened to `EVOLVE_SEARCH_PLAN.md`: it fixed
(S) and the user-visible number did not move.

### What was built

* **A growth stage above the exhaustive limit.** `discover(growth_width=...)`, `--growth-width`,
  and `growth_plan()` in `core/discover.py`. Above `DEFAULT_EXHAUSTIVE_LIMIT` the search stops
  enumerating and grows: every one-element extension of the best `GROWTH_WIDTH` topologies of the
  last completed level, screened, best `GROWTH_WIDTH` kept, repeat. It runs **between** the two
  tiers because it needs the tier-1 ranking of a completed level — which `_exhaustive` used to
  compute and throw away — and both stages then feed one shortlist under one per-size quota.
* **`growth_plan` is a generator, for the reason `screen_plan` is.** It yields `ScreenTask`
  batches and receives costs, so `_grow_all` (in-process and pooled) and `DiscoveryJob`
  (the browser, across Web Workers) are two *drivers* of one set of decisions rather than two
  searches. `DiscoveryJob.next_screen` hands out growth batches once the enumeration is
  exhausted, so JavaScript never learns there are two phases.
* **A restart lever on the tier-1 screen.** `fit.screen(..., restarts=)`, `ScreenBudget.restarts`,
  `discover(screen_restarts=)`. **The default is unchanged at 1**, deliberately — see below.
* **`benchmarks/six_plus/`**: `truths.py` (nine pre-registered truths), `oracle.py` (X8),
  `order.py` (X9), `recovery.py` (X4, end to end), `build_arenas.py`.
* **`tests/test_discover_growth.py`**, whose subject is mostly what the report may *claim*.

### What must not be re-derived

- **`complete_up_to` describes the enumeration and growth may never raise it.**
  `DiscoveryResult.grown_to` is the separate, weaker number, and `completeness()` prints the two
  as two sentences with "That is not a completeness claim" between them. This is not decoration:
  the browser's `DiscoveryJob` derives coverage from the length of its screened list, growth
  appends to that list, and the first version of that code therefore reported a **higher**
  completeness than it had earned. `DiscoveryJob._enumerated` exists only to stop that, and
  `tests/test_discover_growth.py` pins it from both front ends.
- **The tier-1 screen's verdict is a basin lottery for a minority of topologies, and budget does
  not fix it.** [measured] `p(p(R1,C1)-R2,C2)-R3` screens at 0.0141 or at 33.78 depending only on
  the seed — a factor of 2400, with the good value being the right one — and raising `popsize`
  8 to 40 and `maxiter` 40 to 400 moves *neither* number. Across 360 sampled topologies from three
  spectra: one seed is within 1% of the best of five for 72–80% of them, more than 2x off for
  8–12%, more than 100x off for up to 1.7%. Mean ratio to best-of-five: **37.7 and 41.4 at one
  seed, 1.06 and 1.16 at two.** The median is 1.0000 throughout — the damage is entirely in the
  tail. So the remedy is another *draw*, not a longer one, and `SCREEN_RESTARTS` stays at 1 until
  a recovery measurement says the doubled tier-1 cost buys truths: every number in this repository
  was taken at 1, and raising it moves all of them.
- **The feasibility filter assumes the measurement window reaches the model's asymptote.**
  [measured] A five-element truth `C1-R1-L1-p(R2,C2)` whose inductive asymptote lies above the top
  of its own sweep is **deleted before any fitting**: its reachable high-frequency band is (0, +1)
  and the measured edge slope is −1.15, because the shunt capacitance is still falling faster than
  the series inductance is rising at 1 GHz. It survives at `feasibility_budget=2`. Gate G3 of
  `DISCOVERY_V2_PLAN.md` was measured on references whose windows *do* reach their asymptotes, so
  this is a gap in the gate rather than a contradiction of it. Nothing was changed in the filter;
  what changed is that `benchmarks/six_plus/truths.py` now refuses to admit a truth the filter
  deletes, because such a truth measures the filter and not the search.
- **The publication fitter converges on seven of eight cases and fails badly on the eighth, and
  the eighth is a reference this project gates on.** [measured, 12 fitter seeds per cell, true
  topology given, noise-free data, so the optimum is exactly zero] `restarts=5, popsize=20,
  maxiter=400` is **12/12** from 4 elements / 4 parameters up to 8 elements / 8 parameters --
  and **2/12** on `R1-L1-p(CPE1,R2-Wo1)-p(R3,C1)`, which is `LARGE_REFERENCES[2]`. Twenty
  restarts take that to 12/12; four times the population-generations product takes it nowhere.
  So the axis is **draws, not budget**, and gate EV1's arena has a second defect on top of the
  under-determined parameter in each reference. The tier-1 screen is worse on the same case in
  the same direction (1/12). None of it is indexed on element count or parameter count: 8
  elements passes where 7 fails, and the two nine-parameter cases differ only in vocabulary.
  Reading the first seven rows as an all-clear is a mistake this round made and corrected;
  `TOPOLOGY_6PLUS_PLAN.md` section 5.6 keeps both readings.
- **Rational-approximation order estimation does not survive noise, and the implementations are
  not to blame.** [measured, `benchmarks/six_plus/order.py`] `scipy.interpolate.AAA`, a
  hand-rolled Loewner pencil and a stabilisation diagram all return the exact relaxation count on
  dense noise-free data (1, 2, 3, 4 on the RC ladders). At **0.1%** noise — ten times finer than
  these spectra are measured at — AAA returns 22–34 poles for a one-relaxation truth and the
  Loewner gap rule returns 90–101 of a 91-point sweep. Exact-recovery at 1% noise and 10
  points/decade: AAA 0.12, Loewner-threshold 0.04, Loewner-gap 0.20, stabilisation 0.16. The
  stabilisation diagram is the only one that does not explode, and it under-counts. **No
  production code follows from this**; what does survive is that a fractional element announces
  itself on clean data (22–27 poles for a CPE or Warburg against 1–4 for any RC ladder), which is
  not yet measured under noise.
- **Every truth in `LARGE_REFERENCES` carries a parameter the data does not contain.** [measured]
  Weakest leverage at each reference's own window against 1% noise: three-block Maxwell-Wagner
  `C3.C` 0.700%, capacitor+block `R1.R` 0.634%, Randles+ESL+block `C1.C` 0.758% — one parameter
  below the noise in each. All three *small* references are clean (worst 1.551%). This matters
  because `DiscoveryResult.recommended` prefers candidates with no unresolved parameter, so on
  those references the parsimony rule disprefers the truth by design. Gate EV1's 5/9 is a number
  about that arena and must be quoted with it.
- **The tuner that picks the new truths' values maximises the weakest parameter's leverage, and
  that is not sufficient on its own.** [measured] `ser6`'s first tuned set scored 9.903% and then
  failed the fit outright — the tuner had driven `R2` to 296 kOhm, opening the parallel branch, so
  the circuit collapses to a plain series R-C-L whose two capacitances are determined only by
  their series combination. Every parameter still moves the spectrum alone; nothing can separate
  them. `truths.py::tune_until_screened` therefore tunes *and checks*, and raises rather than
  returning the least bad.
- **X4 is complete (54/54), and growth is a shape-dependent effect, not a uniform win — which is
  exactly why `GROWTH_DEFAULT` stays 0.** [measured, `benchmarks/six_plus/x4_recovery.json`] On
  `par6`, `mix6`, `par7`, `mix7` growth is total: `base` is 0/12 reported at 28–34% residual
  against a 1% noise floor, `grow` is 12/12 reported *and* recommended at 1.2–1.5%. On `ser6` and
  `ser7` growth changes nothing that matters: `base`'s five-element residual is already 1.4–1.7%
  — inside the noise floor, on a topology with one fewer element than the truth — so `grow`'s
  numerically better six/seven-element fits (1.2–1.5%) never clear parsimony's bar, landing 0/6
  recommended and `ser7` 0/3 even reported. This is not a search failure; it is the sixth element
  being genuinely unresolved by that spectrum, and it is the reason a global default would be
  dishonest for series-shaped parts. Full table in `TOPOLOGY_6PLUS_PLAN.md` §5.9.
- **X6: the genetic fallback (`_evolve`) had no `workers`, where `_exhaustive` already did — every
  evolve measurement in this repo before commit `d10046d` ran single-threaded.** [measured,
  `benchmarks/six_plus/x6_workers.py`, `TOPOLOGY_6PLUS_PLAN.md` §5.11] With `generations` set high
  enough that `time_limit` (300 s) binds instead of the iteration cap, `workers=8` bought 39–48%
  more generations than `workers=1` at *lower* wall clock on both `par6` and `ser6` — a real win,
  and nowhere near an 8x one (~5–6% scaling efficiency per core, likely because each generation
  dispatches two sequential batches, polish then search, each well under `population=40` once the
  cache-hit majority `EVOLVE_SEARCH_PLAN.md` §1.3 already measured is subtracted out).
  **It changed no recovery outcome**: `par6` was already reported/on-front/recommended at
  `workers=1`, and `ser6` stayed off the front and unrecommended at `workers=8` despite the extra
  generations and 413 distinct topologies fitted — the same reading §5.9/§5.10 already gave that
  shape, that its obstacle is the five-element residual already sitting inside the noise floor,
  not search reach. So the asymmetry was real and worth fixing (a fallback should not carry a
  handicap the exhaustive stage does not), but it was never why any six-element truth went
  unrecovered. `workers` now flows through `discover()` to `_evolve` exactly as it already did to
  `_exhaustive`; `workers=1` (default) is byte-identical to the loop it replaces.
- **X2 (the identifiability ladder) is complete, 6 of 6 truths / 72 of 72 cells [measured,
  `benchmarks/six_plus/identifiability.py`, `TOPOLOGY_6PLUS_PLAN.md` §5.12]; X3 (a trigger for
  when the sixth element is real) is not done — the reason `GROWTH_DEFAULT` stays 0 rather than
  becoming automatic.** X2 is a noise × points-per-decade × truth grid (§4.3) that no published
  curve answers (§3.4): `par6`, `mix6`, `par7` and `mix7` never leave the tens-to-tens-of-thousands
  range at any of their 48 cells (worst 24.2x), while `ser6` and `ser7` sit at or near `gain≈1`
  across most of the grid and cross into "not distinguishable" at or near the project's standard
  1%-noise/10-ppd configuration (`ser6` 1.258x, `ser7` 1.012x) — **shape predicts the crossing far
  more than element count does**, and the seventh element made the series shape's crossing worse,
  not better. §5.9's `par6`/`mix6`/`par7`/`mix7` (30% → 1.3% residual) versus `ser6`/`ser7`
  (residual already at 1.4–1.7%, inside the noise floor) is the same finding read off recovery
  rate rather than cost ratio, and is still the design lead for X3, which needs the ROC over this
  now-complete grid: a trigger built only from the four non-series truths would fire on the other
  two as well, and grow toward an element the data does not support. No candidate rule has been
  built or scored yet.

### Environment

**`python` on PATH is now 3.12 and has no numpy.** The project interpreter is `py -3.13`
(3.13.14, numpy 2.5.1, scipy 1.17.1). The 3.12 install is the one `autoeis` needs (section 32).
Every command in this section is `py -3.13 ...` for that reason, and a
`ModuleNotFoundError: numpy` from a script that worked yesterday means the wrong interpreter, not
a broken environment.

`scipy.interpolate.AAA` exists here (scipy >= 1.15) and is dependency-free, so the rational route
was admissible under the numpy/scipy-only rule; it was measured and rejected, not skipped.
