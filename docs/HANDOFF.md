# Handoff — state of AutoCircuit as of 2026-08-14

Written at the end of the session that built the backend, updated after discovery v2 steps
1–5, again after the skeleton-constrained mode (all of `docs/PARTIAL_TOPOLOGY_PLAN.md`), and
again after step 1 of `docs/WEB_UI_PLAN.md`. Read this first, then `CLAUDE.md`, then the plan
for whichever part you are touching.

## 1. Where things stand

The command-line backend is **complete and verified**: 583 tests pass
(`python -m pytest tests -q`, ~5 min). Phases 0–5 of `docs/IMPLEMENTATION_PLAN.md` are done.
Phase 6 (web UI) has its **step 1 built and measured** — a lossless `FitResult` across a worker
boundary, so the browser fans out both tiers of the search (§8) — and no UI yet.

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
- **numpy and scipy are the only permitted runtime dependencies** — this is what keeps the
  Pyodide target viable. The CLI uses stdlib `argparse` for this reason.
- **PowerShell mangles quotes** in `python -c @'...'@`; heredocs lose `"` characters. Write a
  script into the scratchpad directory and run the file instead.
- **`python -` hangs** (stdin is the null device). Never pipe a script into Python.
- **`native.exe | Select-Object -First N` returns exit code 255** by closing the pipe early.
  That is not a program failure — re-run without the truncation before believing an error.
- **Background jobs redirected with `Out-File` buffer until completion.** To wait on one, use
  `Monitor` with an `until grep -q ...` loop (it runs bash), not chained sleeps.
- Full suite ~3.7 min (387 tests); the fast subset is
  `python -m pytest tests -q -k "not test_fit and not test_discover"` (~4 s) — note that the
  `not test_discover` filter also drops `test_discover_exhaustive.py`, which is where the
  exhaustive mode is covered.
- **Node 24 is available**, which is what `benchmarks/pyodide/` uses to run the package under
  WASM without a browser. Its `npm install` and the first `loadPackage` both need network.
- **`Compress-Archive` produces zips Python cannot unpack as a package.** It writes backslash
  path separators, so `zipfile` extracts files literally named `autocircuit\__init__.py` and
  the failure only shows up as `ModuleNotFoundError`. Build such archives with Python
  (`benchmarks/pyodide/make_zip.py`).
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
2. **Web UI (phase 6)** — the biggest remaining piece, and now the only one.
   `docs/WEB_UI_PLAN.md` steps 2–6 are a **draft awaiting approval**; its step 1 is built (§8).
   Nothing in the plan's architecture is open any more: orchestration stays in Python behind
   `discover.screen_plan()` and `discover.refit_plan()`, both tiers fan out across Pyodide
   workers, and the browser reproduces the CLI's discovery output to an AICc difference of 0.0
   in 123 s where it took 287 s. What is left is the UI itself — Vite/React scaffold, data
   import and plots, the circuit canvas (which is also the skeleton editor, so mode 2 rides
   along for the cost of one button), the discovery job screen, and the report.
3. ngspice round-trip in CI. The test suite already proves the netlist is *electrically*
   right via its own nodal-analysis engine (`tests/test_spice.py`); a real simulator would
   also prove it is *dialect* right.
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
eight) against a search of about a minute, and five elements is ~20 min single-core.

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

One thing this leaves for step 2: the *spectrum* still reaches each worker by being recomputed
there (`simulate(...)` in the worker's own bootstrap), which is fine for a benchmark whose data
is synthetic and wrong for a UI where the user loads a file. `encode_complex_array` is what that
wants; there is no new format to design, only a message to add.
