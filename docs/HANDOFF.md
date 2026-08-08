# Handoff — state of AutoCircuit as of 2026-08-08

Written at the end of the session that built the backend, updated at the end of the session
that implemented discovery v2 steps 1–5. Read this first, then `CLAUDE.md`, then
`docs/DISCOVERY_V2_PLAN.md`.

## 1. Where things stand

The command-line backend is **complete and verified**: 387 tests pass
(`python -m pytest tests -q`, ~3.7 min). Phases 0–5 of `docs/IMPLEMENTATION_PLAN.md` are done;
phase 6 (web UI) is untouched.

**Discovery v2 is fully implemented** (see §2) and all five gates pass: G1 30/30 across the
three reference spectra, G2 exactly reproducing the measured counts table, G3 with the truth
and every known exact equivalent surviving the feasibility filter, G4 with DRT counting 1, 2
and 3 relaxations 10/10 at both 0% and 1% noise, and G5 with the whole suite green.

Working end to end today:

```powershell
$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"
python -m autocircuit elements
python -m autocircuit simulate -c "C1-R1-L1-SKINF1" -p C1.C=1e-6 -p R1.R=1e-2 `
    -p L1.L=5e-10 -p SKINF1.A=2e-5 -p SKINF1.n=0.5 --fmin 100 --fmax 1e9 --noise 0.01 -o cap.csv
python -m autocircuit validate cap.csv
python -m autocircuit fit cap.csv -c "C1-R1-L1-SKINF1" --spice cap.cir --json cap.json
python -m autocircuit discover cap.csv --pool component --workers 8 --progress
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
| `core/enumerate.py` | exhaustive topology enumeration + the structural feasibility filter |
| `core/drt.py` | regularised distribution of relaxation times; structure probing only |
| `core/discover.py` | exhaustive and genetic topology search, Pareto front, equivalence classes |
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

## 6. Open items

0. Nothing is left of `docs/DISCOVERY_V2_PLAN.md`: step 6 (DRT, gate G4) is done, so all seven
   steps and all five gates are in. One decision inside it is worth not reopening by accident:
   **DRT is not wired into the search and should not be.** [measured] It could only raise the
   enumeration floor, which removes 0.1–0.4% of the filtered space (n = 5 alone is 85–89% of
   it, and the small sizes are the cheapest fits), while raising `exhaustive_min` deliberately
   clears `complete_up_to` — "all topologies up to N" is not true when the smaller sizes were
   skipped. `exhaustive_min` stays available to anyone who wants that trade explicitly.
1. Web UI (phase 6) — the biggest remaining piece; see `docs/IMPLEMENTATION_PLAN.md` §9.
2. ngspice round-trip in CI. The test suite already proves the netlist is *electrically*
   right via its own nodal-analysis engine (`tests/test_spice.py`); a real simulator would
   also prove it is *dialect* right.
3. Gamry `.DTA` and BioLogic `.mpt` readers, once real files exist to test against.
4. Pyodide performance measurement — nothing has been run in a browser yet.
