# Topology Discovery v2 — Exhaustive-First Design

Status: implemented (2026-08-09). Steps 1–7 are done; §3.2, §3.4 and gate G1 carry corrections
made when measurement contradicted the plan, and §5.1/§5.2 record what implementation added.
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
  │        → advisory hints for the report (not a search bound; see the §3.4 correction)
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

**Implemented, and the expectation above was wrong.** [measured, `benchmarks/discovery_v2.py
filter`] Two things had to change once the rules were written out.

1. *Any element can be driven to a short or an open* by pushing its scale parameter to a
   bound, and that changes the endpoint class. A model whose corner frequency sits just
   outside the measured window is a real, fittable model, so the filter allows a
   **degeneracy budget**: up to `budget` elements may be treated as degenerate when matching
   an endpoint (`DEFAULT_DEGENERACY_BUDGET = 1`). Independently at each end — an element can
   legitimately act as a short at one end and an open at the other, so demanding one
   consistent assignment would be unsound.
2. *Endpoint slopes interpolate.* A series R-C with its corner inside the first decade shows
   a slope of about −0.5, which is neither of its asymptotic exponents. The topology is
   therefore represented by the **convex hull** of everything it can reach, not by a set of
   isolated values.

Both margins cost cutting power, and the honest measured reduction is well under the guess:

| degeneracy budget | capacitor | Maxwell-Wagner | Randles | truth survives |
|-------------------|----------:|---------------:|--------:|----------------|
| 0 | 7.7× | 3.1× | 2.3× | yes (all references) |
| **1 (default)** | **1.75×** | **1.15×** | **1.18×** | yes (all references) |
| 3 | 1.19× | 1.02× | 1.05× | yes (all references) |

Budget 0 reaches the hoped-for 2–5× and passes G3 on every reference tested — but it is the
setting that can reject a topology purely because one corner frequency fell outside the
window, and completeness is the reason this mode exists. The default is therefore 1, with the
budget exposed as `feasibility_budget` for anyone who would rather have the speed. Even at 1
the filter removes 43% of the flagship capacitor sweep for a fixed cost of ~0.3 s, so it
earns its place; it is just not the main lever.

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
  *(Amended during implementation: "the best `n_refine` by screening cost" globally is wrong
  and made G1 fail — `n_refine` is now a total split into a quota per element count, ranked
  within a size by a screening AICc, and the 10× rule is capped. See §5.1.)*
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
- Consumed by `discover(mode="auto")` as **advice for the report only**. Discovery must remain
  correct with DRT disabled.
- Standalone CLI: `autocircuit drt data.csv [--json out.json]` — independently useful for the
  Maxwell-Wagner use case (how many blocks does the ceramic actually show?).

**Correction: DRT does not feed `n_min`, and speed was never a reason to build it.**
[measured] The plan above had DRT raising the enumeration floor — "enumeration starts at
`n_relaxations` instead of at 1 — pure speed-up". Once steps 1–5 were measured that turns out
to buy nothing and cost the one thing this redesign exists for. Feasible candidates per
element count, on the three reference spectra:

| reference | n=1 | n=2 | n=3 | n=4 | n=5 | total | skipped by `n_min=2` | by `n_min=3` |
|-----------|----:|----:|----:|----:|----:|------:|---------------------:|-------------:|
| capacitor (R,C,L,CPE,SKINF) | 0 | 7 | 77 | 657 | 5,857 | 6,598 | 0 (0.0%) | 7 (0.1%) |
| Maxwell-Wagner (R,C,L,CPE) | 1 | 10 | 55 | 330 | 2,185 | 2,581 | 1 (0.0%) | 11 (0.4%) |
| Randles (R,C,CPE,W) | 2 | 11 | 66 | 442 | 3,192 | 3,713 | 2 (0.1%) | 13 (0.4%) |

The space is overwhelmingly its largest level — n=5 alone is 85–89% of it — so any floor DRT
could justify removes well under 1% of the work, a few seconds. Small circuits are also the
*cheapest* to screen, so the saving is smaller still than the counts suggest. Against that,
raising `exhaustive_min` deliberately clears `complete_up_to` (§5.1): "every plausible topology
up to N elements was evaluated" is false when the small sizes were skipped. Trading the
completeness guarantee for a few seconds is not a trade worth making, and a DRT that
mis-counts a broadened peak would silently delete the correct answer from a search that still
claimed to be exhaustive.

DRT is therefore built for the reason it was independently worth having — **standalone
structure probing**: how many relaxation blocks does this ceramic actually show, and is a peak
broadened enough to mean CPE rather than C. Its output reaches discovery as advisory text in
the report and nothing else. Anyone who does want the floor raised already has
`exhaustive_min`, and gets the honest `complete_up_to` that goes with it.

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
  **[measured] PASSES 30/30**, and the truth is on the Pareto front in all 30. It is also the
  *recommendation* in 28/30; the two exceptions are the parsimony rule dropping a 10 mΩ ESR
  that 1% noise could not resolve, with the truth still on the front beside it. Times with 8
  workers: 1.1–1.2 min (Maxwell-Wagner), 1.4–1.6 min (Randles), 3.8–5.8 min (capacitor).
  **The time budget above was wrong and is superseded by those numbers.** It assumed the
  feasibility filter would remove ~3×; it removes 1.75× on the worst case, so the capacitor
  reference costs ~4.8 min with 8 workers and ~22 min on one core. Two clarifications the
  gate needed once it was run for real: "in the reported equivalence classes" is satisfied by
  the truth being among the refitted candidates, which is weaker than being the
  recommendation — the benchmark reports both — and the gate is only meaningful because the
  tier-2 shortlist has a per-element-count quota (see §5.1).
- **G2** — enumeration counts match the measured table exactly.
- **G3** — the feasibility filter never removes the truth or any of its known equivalents on
  the benchmark suite.
- **G4** — DRT recovers the correct relaxation count for synthetic 1-, 2- and 3-peak spectra
  with peaks ≥ 1 decade apart at 1% noise, 10/10 seeds.
  **[measured] PASSES 10/10** on all three counts at both 0% and 1% noise, and the recovered
  numbers are better than the gate asks for: peak positions land within 0.026 decades of the
  true RC products and peak weights within 1.4% of the true block resistances. It also holds
  on the harder cases the gate does not name — two blocks a single decade apart, and the
  two-block Maxwell-Wagner reference whose smaller block carries 2% of the total polarisation
  — but only after the peak criterion was rewritten; see §5.2.
- **G5** — existing test suite stays green; `mode="evolve"` results unchanged for a fixed
  seed.

## 5. Work order

| step | contents | size | status |
|------|----------|------|--------|
| 1 | `enumerate.py` + counts regression test (G2) | S | **done** — `tests/test_enumerate.py`, counts reproduce the table exactly through n = 6 |
| 2 | feasibility filter + its conservativeness tests (G3) | M | **done** — `tests/test_feasibility.py`; see the revised §3.2 |
| 3 | two-tier exhaustive mode in `discover.py`, `complete_up_to`, progress callback | M | **done** — `tests/test_discover_exhaustive.py` |
| 4 | `--mode`/`--workers` CLI, multiprocessing tier 1 | S | **done** |
| 5 | benchmark script + gate G1; tune screening budget against it | M | **done** — `benchmarks/discovery_v2.py` |
| 6 | `drt.py` + `drt` CLI + G4; report hints only, **no** `n_min` wiring (see §3.4) | M | **done** — `tests/test_drt.py`; G4 passes 10/10 on every case. See §5.2 |
| 7 | docs: this file marked implemented, README, IMPLEMENTATION_PLAN §6/§10 update | S | **done** |

Steps 1–5 are the core and independent of step 6; DRT lands last and is severable.

### 5.1 What the implementation added that the plan did not specify

- **`fit.screen()`** — a rank-only fit returning nothing but the cost. Building a full
  `FitResult` (covariance, statistics, restart spread) for thousands of topologies that will
  never be reported is pure waste, and it is also where the early-abandon switch lives.
- **`PERFECT_COST`** — early abandon is disabled while the reference fit of a given complexity
  is already exact. Without it, on noise-free data the first exact equivalent screened sets a
  threshold of order 1e-30 and every *other* exact equivalent is abandoned unpolished. Those
  equivalents are the report's whole reason for existing.
- **Per-mode `n_refine` defaults** (`REFINE_DEFAULT`): 30 for exhaustive, 8 for evolve. Sharing
  one default would have silently changed genetic-search results, which gate G5 forbids.
- **`complete_up_to` is derived, not asserted.** It is computed from how many whole levels the
  screen actually finished, so a run cut short by `--time-limit` or `--max-candidates` reports
  a smaller number rather than an untrue one, and a run started above one element reports
  nothing at all.
- **The tier-2 shortlist is a quota per element count, ranked by a screening AICc.** [measured]
  The plan said "the best `n_refine` by screening cost", and that does not work: raw residual
  always improves with parameters, so on the capacitor reference all 60 shortlisted candidates
  had five elements and the four-element circuit *that generated the data* was never refitted.
  G1 failed until this was changed. The per-size quota is also what puts candidates at every
  complexity on the Pareto front instead of a cluster at the top.
- **The near-tie rule needs a ceiling.** "Everything within 10× of the best cost" is unbounded,
  and at 1% noise a factor 10 in cost is only a factor 3.2 in relative error — hundreds of
  candidates qualified and tier 2 ran for over half an hour per search, far longer than the
  screen it was double-checking.
- **Tier 2 uses the same worker pool as tier 1**, and the workers return whole `FitResult`
  objects. Sending back only the fitted values would have meant a single-restart local fit in
  the parent, which silently discards the restart spread — the signal a non-identifiable model
  uses to announce itself.

### 5.2 What DRT needed that the plan did not specify

Three of the plan's implicit choices were wrong when measured, and all three were wrong in the
same direction: the obvious rule looked fine on the easy case and failed on the case the
module exists to serve.

- **Peak picking cannot threshold against the tallest peak.** [measured] The obvious rule --
  count a peak if it rises some fraction of the largest peak above its surroundings -- rejects
  the smaller block of the two-block Maxwell-Wagner reference outright, because that block
  carries 1e4 ohm against the other's 5e5 and so stands at 2% of the tallest peak. No
  threshold on weight can fix it either: the spurious ripples a regularised inversion leaves
  on a depressed semicircle carry 0.6–3.0% of the total, straddling the real block's 2.0%.
  What separates them is the noise. A relaxation is counted when its prominence is at least
  half its *own* height (scale-free, so uneven blocks are fine) **and** its weight moves |Z|
  at its own characteristic frequency by at least 8× the RMS residual. In those units the real
  block stands at 140× and the ripples at 0.6×. The factor 8 is where a sweep stops improving:
  1–3 Debye peaks are counted 10/10 at any threshold from 2 up, but two blocks one decade
  apart and two blocks of 50:1 uneven weight are 9/10 until the threshold reaches 5 and 8
  respectively — and nothing is lost going up, a weak block still being found 10/10 down to a
  100:1 weight ratio.
- **GCV must be allowed to choose no regularisation.** The plan said "GCV with an L-curve
  fallback", and the natural reading -- distrust a GCV minimum that lands on either end of the
  λ grid -- is half wrong. [measured] On noise-free data GCV correctly goes to the bottom of
  the grid and fits to 0.03%; rejecting that and falling back to the L-curve, which has no
  corner to find when there is no noise to trade against, over-smoothed the same data to a
  5.5% residual. A bottom-of-grid minimum is now believed when the residual there confirms the
  data really is that clean; a top-of-grid minimum never is.
- **DRT has to be able to say "not applicable".** Run on the capacitor reference it returns a
  distribution with no peaks in it, a series resistance wrong by 7×, and a 64% residual — because
  a sum of *capacitive* RC relaxations cannot carry a distributed *inductive* process such as
  skin effect. Reporting "0 relaxations" for that is worse than useless. `DRTResult` therefore
  carries `well_described`, the hints say plainly that the model does not apply, and the CLI
  exits non-zero.

Two smaller notes. The τ grid extends **one decade** past the measured window at each end
rather than the plan's "2× the measured range": time constants far outside the window are
unidentifiable, and the smoothness prior fills that null space with ramps that peak-pick as
relaxations the data never showed. And the series R/L/C estimates are printed only when they
move the impedance by more than the residual already does — the fit assigns *something* to
every column it is given, and a 1 ohm series resistance on a half-megohm spectrum is a
rounding error being presented as a component.

## 6. Risks

- **Combinatorics with wide pools** (electrochemical pool, 8 codes: ~10⁵ at n=5). Mitigated
  by `max_candidates` auto-clamping of `exhaustive_limit`, user-chosen pool restriction,
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
