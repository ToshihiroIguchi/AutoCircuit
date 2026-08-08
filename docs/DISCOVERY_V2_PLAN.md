# Topology Discovery v2 — Exhaustive-First Design

Status: approved plan, not yet implemented (2026-08-08).
Prerequisite reading: `docs/IMPLEMENTATION_PLAN.md` §6 and the **[measured]** notes there.

## 1. Why redesign

Discovery v1 is a genetic search. Two measurements made after it shipped change the picture:

1. **The effective search space is small.** After canonical deduplication, exact-redundancy
   simplification and the plausibility filter, the number of distinct series-parallel
   topologies with **≤ 5 elements** is:

   | pool | ≤ 4 elements | ≤ 5 elements | ≤ 6 elements |
   |------|-------------:|-------------:|-------------:|
   | R, C | 20 | 56 | 170 |
   | R, C, L | 100 | 449 | 2,174 |
   | R, C, L, CPE | 453 | 2,976 | 21,057 |
   | R, C, L, CPE, SKINF | 1,336 | 11,550 | 107,534 |

   Practical passive-component models almost always fit in ≤ 5 elements. A space of a few
   thousand candidates does not need a stochastic search — it needs an enumerator.

2. **The degeneracy is bounded and countable.** Fitting *every* same-size topology to
   noise-free reference data showed 1–4 exact equivalents per truth (`C-R-L` is unique among
   all 56 three-element RCL topologies; the two-block Maxwell-Wagner has 4 equivalents among
   80). So exhaustive evaluation does not drown in equivalents; it enumerates them, which is
   exactly what the equivalence-class report needs.

Meanwhile the GP failed its own benchmark: within a 2-minute budget it evaluated only
113–257 topologies and did not reliably surface the textbook form for multi-relaxation
spectra. That is a coverage problem, not a fundamental one — and enumeration solves coverage
by construction.

**Decision: make exhaustive search the primary mode. The GP remains only as a fallback for
> 5 elements or user-expanded pools. Add DRT as an optional prior and standalone analysis.**

What exhaustive-first buys that no tuning of the GP can:

- a **completeness guarantee** — the report can state "every plausible topology with ≤ N
  elements from this pool was evaluated", turning "the search didn't find X" into
  "X does not fit this data";
- **complete equivalence classes** up to N elements;
- determinism and trivial reproducibility;
- embarrassing parallelism.

## 2. Pipeline

```
spectrum
  │ Lin-KK (exists)                        — is the data worth fitting at all?
  ▼
Stage A  Structure probing (new, optional) — DRT: how many relaxations? series R? series L/C?
  │        → n_min, endpoint behaviour, suggested pool restriction
  ▼
Stage B  Enumeration (new)                 — all plausible topologies, n = 1 .. n_exh (≤ 5)
  │        → structural feasibility filter kills candidates before any fitting
  ▼
Stage C  Two-tier fitting (new)            — cheap screening fit for all survivors,
  │                                          full-budget refit for the shortlist
  ▼
Stage D  GP fallback (exists, retuned)     — only for n > n_exh, seeded with stage-C winners
  ▼
Stage E  Reporting (exists, extended)      — Pareto front, equivalence classes, parsimony
                                             recommendation, completeness statement
```

## 3. New modules and changes

### 3.1 `core/enumerate.py` (new)

- `enumerate_topologies(pool, n) -> Iterator[Node]`: all distinct series-parallel networks
  with exactly `n` elements. Algorithm: integer partitions of `n`, Cartesian products of
  smaller levels, series/parallel composition, canonical-form deduplication — the prototype
  from the hardness measurement, made lazy (generator) and memoised per `(pool, n)`.
- Applies `simplify()` and drops candidates that collapse below `n` (they were already
  enumerated at their true size), then `is_plausible()`.
- Must reproduce the measured counts above; those counts become the regression test.

### 3.2 Structural feasibility filter (new, in `enumerate.py`)

Cheap symbolic screen run *before any fitting*. For each topology, derive by tree recursion
its limit-behaviour class at ω→0 and ω→∞ — one of `{finite-R, capacitive (|Z|→∞ as ω^-m),
inductive (|Z|→0→∞ as ω), shorted}` — and compare with the data's endpoint log-log slopes and
Im-sign. A capacitor spectrum (capacitive tail at LF, inductive rise at HF) is incompatible
with any topology whose DC impedance is finite, which eliminates most of the pool without
evaluating a single fit. Rules:

- series node: DC class = "max divergence" of children; HF class likewise;
- parallel node: DC class = "min divergence" of children;
- element leaves have fixed classes (R finite, C capacitive, L inductive/shorted-at-DC,
  CPE capacitive with exponent n, W capacitive-with-n=0.5, Ws/Wo/G finite at DC, SKINF
  inductive at HF, zero at DC...).

Data side: fit the first/last decade of log|Z| vs log f for slopes, take the Im(Z) sign.
Tolerance bands, not exact matching — a slope of −0.93 is "capacitive-ish", compatible with
both C and CPE. When in doubt, keep the candidate (the filter must be conservative: it may
only remove topologies that provably cannot match; completeness depends on this).

Expected effect (to be measured, not assumed): 2–5× reduction. The filter gets its own tests:
for each benchmark spectrum, the true topology and all its known equivalents must survive.

### 3.3 `core/discover.py` (refactor)

- New entry `discover(spectrum, *, mode="auto", ...)`:
  - `mode="exhaustive"`: stages B–C only.
  - `mode="evolve"`: current GP (kept for comparison and > n_exh).
  - `mode="auto"` (default): exhaustive up to `exhaustive_limit` (default 5, clamped down
    automatically if the filtered candidate count exceeds `max_candidates`, default 20,000);
    then GP for larger sizes **only if** the exhaustive front's best χ² still looks
    under-fitted (systematic residuals by the runs test — reuse `_runs_z`).
- **Two-tier fitting.** Tier 1 screening: `fit(restarts=1, popsize=8, maxiter=40)` — enough
  to rank, not to publish. Tier 2: current full budget (`restarts=5`) for the best
  `n_refine` (default 30) by screening cost *plus* everything within 10× of the best cost
  (so near-ties are never dropped by a sloppy screen). All published numbers come from
  tier 2; tier-1 results are never reported.
- **Early abandon:** during tier 1, skip the local polish when the DE stage already exceeds
  100× the best cost seen at the same complexity.
- **Parallelism:** `workers=N` fans tier-1 fits across `multiprocessing.Pool`
  (spawn-safe: the worker function takes `(canonical_string, spectrum arrays)` and re-parses;
  no shared state). `workers=1` stays Pyodide-safe.
- `DiscoveryResult` gains `mode: str` and `complete_up_to: int | None` — the report's
  completeness statement ("all plausible ≤ N-element topologies from pool P were evaluated").
- Progress callback `on_progress(done, total, best_so_far)` — consumed by the CLI for a
  stderr progress line now, by the web worker later.

### 3.4 `core/drt.py` (new) — distribution of relaxation times

Purpose here is *structure probing*, not a rival analysis method:

- Model: `Z(ω) = R∞ + jωL + Σ_k γ_k / (1 + jωτ_k)` on a fixed log-τ grid (2× measured
  range, ~10 points/decade) with **Tikhonov regularisation** on the second derivative of γ;
  λ chosen by Generalized Cross-Validation, with an L-curve fallback. Linear least squares —
  no initial values, deterministic, fast. (This is the Lin-KK machinery plus a smoothness
  prior; the column-scaling lesson from `validate.py` applies verbatim.)
- Output `DRTResult`: γ(τ), peaks (position, polarisation weight, width) via prominence-based
  peak picking, `n_relaxations`, series R and L estimates, and a `broadened: bool` per peak
  (width vs the ideal Debye width ⇒ suggests CPE/CC rather than pure C).
- Consumed by `discover(mode="auto")` as **bounds, never as truth**: `n_min = n_relaxations`
  (enumeration starts there instead of at 1 — pure speed-up), and a hint list for the report.
  Discovery must remain correct with DRT disabled.
- Standalone CLI: `autocircuit drt data.csv [--json out.json]` — independently useful for the
  Maxwell-Wagner use case (how many blocks does the ceramic actually show?).

### 3.5 CLI

- `discover` gains `--mode auto|exhaustive|evolve` (default auto), `--exhaustive-limit`,
  `--workers`, `--no-drt`; keeps every existing flag. Report header states mode and the
  completeness line.
- New `drt` subcommand as above.

## 4. Performance budget

Measured baselines (this machine, CPython 3.13): screening-grade fit ≈ 0.3–0.7 s for 3–6
parameter circuits; full fit 0.5–2.8 s. Therefore, single-core estimates:

| scenario | candidates after filters | tier-1 time (est.) |
|----------|-------------------------:|-------------------:|
| R,C,L ≤ 5 (capacitor work) | ≤ 449, feasibility ~÷3 → ~150 | ~1–2 min |
| R,C,L,CPE ≤ 5 | ≤ 2,976, ~÷3 → ~1,000 | ~8–12 min |
| same, `--workers 8` | ~1,000 | **~1–2 min** |

Acceptance gates (hard, in the benchmark script, not aspirations):

- **G1** — on the three reference spectra (capacitor `C-R-L`+SKINF, two-block
  Maxwell-Wagner, Randles), `mode=exhaustive` places the true topology **or an exact
  equivalent** in the reported equivalence classes, 10/10 seeds, single core,
  ≤ 15 min each (≤ 3 min with 8 workers).
- **G2** — enumeration counts match the measured table exactly.
- **G3** — the feasibility filter never removes the truth or any of its known equivalents on
  the benchmark suite.
- **G4** — DRT recovers the correct relaxation count for synthetic 1-, 2- and 3-peak spectra
  with peaks ≥ 1 decade apart at 1% noise, 10/10 seeds.
- **G5** — existing test suite stays green; `mode="evolve"` results unchanged for a fixed
  seed.

## 5. Work order

| step | contents | size |
|------|----------|------|
| 1 | `enumerate.py` + counts regression test (G2) | S |
| 2 | feasibility filter + its conservativeness tests (G3) | M |
| 3 | two-tier exhaustive mode in `discover.py`, `complete_up_to`, progress callback | M |
| 4 | `--mode`/`--workers` CLI, multiprocessing tier 1 | S |
| 5 | benchmark script + gate G1; tune screening budget against it | M |
| 6 | `drt.py` + `drt` CLI + G4; wire `n_min` into auto mode | M |
| 7 | docs: this file marked implemented, README, IMPLEMENTATION_PLAN §6/§10 update | S |

Steps 1–5 are the core and independent of step 6; DRT lands last and is severable.

## 6. Risks

- **Combinatorics with wide pools** (electrochemical pool, 8 codes: ~10⁵ at n=5). Mitigated
  by `max_candidates` auto-clamping of `exhaustive_limit`, pool restriction via DRT hints,
  and honest reporting of `complete_up_to` (completeness up to 4 elements is still a far
  stronger statement than the GP ever made).
- **Feasibility filter too aggressive** ⇒ silent loss of completeness. Mitigated by G3, by
  keep-on-doubt semantics, and by `--no-feasibility-filter` escape hatch.
- **Windows `multiprocessing` spawn cost** per worker (~1 s import). Amortised: one pool for
  the whole run, chunked task submission.
- **DRT regularisation choice is a rabbit hole.** Contained: DRT is advisory only; GCV with
  fixed grid; anything fancier is out of scope here.
- **Browser**: tier-1 sweep at n=5/CPE pool is minutes-not-seconds under Pyodide. The web
  default will be `exhaustive_limit=4` + progressive result streaming via the progress
  callback; documented, revisited in the web phase.

## 7. Out of scope

- Symbolic/algebraic equivalence proof of topologies (we detect equivalence numerically).
- Mutual-inductance, transmission-line and 3-terminal networks.
- Bayesian posterior sampling per candidate (AutoEIS-style) — possible later refinement of
  the tier-2 statistics; not needed for the completeness goal.
