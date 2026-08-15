# Handoff — state of AutoCircuit as of 2026-08-15

Written at the end of the session that built the backend, updated after discovery v2 steps
1–5, again after the skeleton-constrained mode (all of `docs/PARTIAL_TOPOLOGY_PLAN.md`), and
again after each step of `docs/WEB_UI_PLAN.md` (all seven now), and again after the ngspice
round-trip (§15). Read this first, then `CLAUDE.md`, then the plan for whichever part you are
touching.

## 1. Where things stand

The command-line backend is **complete and verified**: 712 tests pass
(`python -m pytest tests -q`, ~6 min rested — and that is one full run, not a union of subsets).
Nineteen of them are the ngspice round-trip (§15) and **skip on this machine**, because ngspice
does not run on Windows; `.github/workflows/tests.yml` installs it, and §4 says how to run them
here through WSL. [measured] On `ubuntu-latest` **all 712 run, in 417 s**, the round-trip among
them. Phases 0–6 of `docs/IMPLEMENTATION_PLAN.md` are done. Phase 6 (web UI) has **all seven steps built
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
- **Long benchmarks must be launched detached.** A backgrounded shell command is killed after
  ten minutes, and the G1 gate takes about two hours. Use
  `Start-Process python -ArgumentList ... -RedirectStandardOutput <file> -PassThru` and watch
  the file; set `$env:PYTHONPATH` first, the child inherits it.

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
4. Gamry `.DTA` and BioLogic `.mpt` readers, once real files exist to test against.
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
- **Both workflows carry a Node 20 deprecation annotation.** `actions/checkout@v4` and
  `actions/setup-python@v5` are being forced onto Node 24 by the runner and work; they will stop
  when GitHub drops the fallback. Not fixed here, and not urgent.

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
