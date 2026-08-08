# Handoff — state of AutoCircuit as of 2026-08-08

Written at the end of the session that built the backend. Read this first, then
`CLAUDE.md`, then `docs/DISCOVERY_V2_PLAN.md` (the approved next task).

## 1. Where things stand

The command-line backend is **complete and verified**: 238 tests pass
(`python -m pytest tests -q`, ~3.5 min). Phases 0–5 of `docs/IMPLEMENTATION_PLAN.md` are done;
phase 6 (web UI) is untouched.

Working end to end today:

```powershell
$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"
python -m autocircuit elements
python -m autocircuit simulate -c "C1-R1-L1-SKINF1" -p C1.C=1e-6 -p R1.R=1e-2 `
    -p L1.L=5e-10 -p SKINF1.A=2e-5 -p SKINF1.n=0.5 --fmin 100 --fmax 1e9 --noise 0.01 -o cap.csv
python -m autocircuit validate cap.csv
python -m autocircuit fit cap.csv -c "C1-R1-L1-SKINF1" --spice cap.cir --json cap.json
python -m autocircuit discover cap.csv --pool component --time-limit 120
```

Module map (`src/autocircuit/`):

| module | role |
|--------|------|
| `core/elements.py` | 12 elements; broadcast-safe `impedance()`; data-derived bounds |
| `core/circuit.py` | series/parallel AST, canonical forms, `simplify`, value canonicalisation |
| `core/dsl.py` | parser for `R1-p(C1,R2-W1)` |
| `core/fit.py` | the no-initial-values fitter (log transform → DE → TRF polish → restarts) |
| `core/stats.py` | covariance, AICc, identifiability warnings |
| `core/validate.py` | Lin-KK data validation |
| `core/discover.py` | genetic topology search, Pareto front, equivalence classes |
| `core/spice.py` | netlist export + NNLS Foster-form ladder synthesis |
| `io/` | generic CSV, ZView/ZPlot, Touchstone, Keysight readers |
| `cli/main.py` | argparse CLI |

## 2. The next task

**Discovery v2, specified in `docs/DISCOVERY_V2_PLAN.md`.** Start at its §5 step 1
(`core/enumerate.py` + the counts regression test).

One-paragraph rationale, so it is not re-litigated: after the genetic search shipped, two
measurements changed the design. The filtered topology space at ≤ 5 elements is only ~10²–10⁴
candidates (see `benchmarks/README.md`), and exact degeneracy is bounded at 1–4 equivalents
per truth. So enumeration beats stochastic search outright — it is affordable *and* it can
state "every plausible topology up to N elements was evaluated", which the genetic search can
never claim. The GP drops to a fallback for > 5 elements.

The prototype enumerator that produced those counts is `benchmarks/topology_space.py`
(`enumerate_topologies`); `core/enumerate.py` is essentially that function made lazy, and its
measured counts are acceptance gate G2.

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

## 4. Environment quirks on this machine

- **No `uv`, no `typer`, and the package is not pip-installed.** Always set
  `$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"`. Run the CLI as
  `python -m autocircuit`. `numpy` 2.5.1, `scipy` 1.17.1, `pytest` 9.1.1, Python 3.13.
- **numpy and scipy are the only permitted runtime dependencies** — this is what keeps the
  Pyodide target viable. The CLI uses stdlib `argparse` for this reason.
- **PowerShell mangles quotes** in `python -c @'...'@`; heredocs lose `"` characters. Write a
  script into the scratchpad directory and run the file instead.
- **`python -` hangs** (stdin is the null device). Never pipe a script into Python.
- **`native.exe | Select-Object -First N` returns exit code 255** by closing the pipe early.
  That is not a program failure — re-run without the truncation before believing an error.
- **Background jobs redirected with `Out-File` buffer until completion.** To wait on one, use
  `Monitor` with an `until grep -q ...` loop (it runs bash), not chained sleeps.
- Full suite ~3.5 min; the fast subset is
  `python -m pytest tests -q -k "not test_fit and not test_discover"` (~1 s).

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

## 6. Open items after discovery v2

1. Web UI (phase 6) — the biggest remaining piece; see `docs/IMPLEMENTATION_PLAN.md` §9.
2. ngspice round-trip in CI. The test suite already proves the netlist is *electrically*
   right via its own nodal-analysis engine (`tests/test_spice.py`); a real simulator would
   also prove it is *dialect* right.
3. Gamry `.DTA` and BioLogic `.mpt` readers, once real files exist to test against.
4. Pyodide performance measurement — nothing has been run in a browser yet.
