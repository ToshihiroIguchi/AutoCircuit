# Search and Optimisation Algorithms — Survey

Status: **survey only, 2026-08-23. Nothing here is implemented, decided or measured.**

This document exists because `HANDOFF_PROMPT.md` task E ("topology search algorithms") says a
plan document must be written before that work starts, and a plan needs a map of the options
first. This is the map. It is deliberately *not* a plan: it proposes no gates, commits to no
choice, and every claim about a candidate's benefit is an expectation rather than a
measurement. Read it as the input to the plan doc that task E still owes.

Three things bound every candidate below, and a candidate that fails any of them is not a
candidate:

1. **numpy and scipy are the only runtime dependencies** (`CLAUDE.md`), because that is what
   lets the same wheel run under Pyodide.
2. **No user-supplied initial values, ever** — that is mode 1's whole differentiator.
3. **Honest reporting outranks a satisfying answer.** A replacement that improves a number
   while removing a check the report depends on is a regression, not an improvement.

## 1. What is implemented today

### 1.1 Parameter optimisation — `core/fit.py`

| Stage | Mechanism | Where |
|---|---|---|
| Search space | `x = log10(p)` for every scale-type parameter | `_Problem.to_values` / `to_x` |
| Bounds | Derived from the data: R `[z_min, z_max]`, C `[1/(w_max z_max), 1/(w_min z_min)]`, L `[z_min/w_max, z_max/w_min]`, widened by `margin_decades = 3`; start = geometric centre | `elements.BoundsContext`, `fit.search_space` |
| Global | `scipy.optimize.differential_evolution`, `strategy="best1bin"`, `init="sobol"`, `popsize=20`, `maxiter=400`, `mutation=(0.4, 1.0)`, `recombination=0.9`, `tol=1e-8`, `polish=False`, `vectorized=True`, `updating="deferred"` | `fit._global_stage` |
| Local | `least_squares(method="trf")` under bounds; its Jacobian is also the covariance | `fit.fit` |
| Budgets | `PUBLISH_LOCAL` vs `SCREEN_LOCAL` (10x looser, 1/10 the evaluations) | `fit.LocalBudget` |
| Identifiability | `restarts=5` at `seed + i`; restarts within 1% of the best cost are compared, and a relative spread above 5% is reported as non-unique | `fit._restart_spread` |
| Ranking-only fit | `screen()`: one reduced global stage (`popsize=8`, `maxiter=40`, `tol=1e-4`) plus a `SCREEN_LOCAL` polish, with early abandon above `ABANDON_FACTOR = 100` times the best cost at that complexity | `fit.screen` |

Residuals are real and imaginary parts concatenated into one real vector; the weighting
(`modulus` by default) scales them. The population is evaluated in one array pass
(`cost_vectorized`), which is what makes the topology search affordable at all.

### 1.2 Topology search — `core/enumerate.py`, `core/discover.py`

**Exhaustive enumeration is the primary mode.** Three exact filters shrink the space — none of
them can discard a topology the data might have preferred:

1. canonical deduplication (`circuit.canonical_form`),
2. redundancy collapse (`circuit.simplify`),
3. structural plausibility (`enumerate.is_plausible_node`).

A fourth filter, `EndpointBehaviour`, measures the log-log slope band the two edges of the
spectrum admit and drops topologies that cannot reach it — before anything is fitted, and
switching itself off when the data is too short or too noisy to give a slope.

Trees are built from `integer_partitions`; levels below the requested size are memoised, the
requested level is streamed.

**Two-tier fitting**: `screen()` everything, shortlist by `_quota_by_size` (a per-element-count
quota, plus near-ties within `REFINE_COST_FACTOR = 10`, capped at `REFINE_CEILING_FACTOR = 2`
times the quota), refit only the shortlist at full budget. Every number that reaches the user
comes from tier 2.

**Genetic search** (`_evolve`, the fallback above five elements): tree individuals; mutation
`retype 0.35 / insert_series 0.25 / insert_parallel 0.25 / delete 0.15`; subtree-graft
crossover at p = 0.3; tournament selection (size 3); Pareto-front elitism of `population // 6`;
a best-wins cache keyed on canonical form; parameter inheritance from the parent
(`_inherited_values`, matched by element code in evaluation order because `simplify` strips
labels).

**`auto` orchestration**: exhaustive -> runs test on residual signs -> widen the pool
(`descriptors.choose_pool`, triggered by the OR of a shape reading and a residual reading) and
re-enumerate -> only then fall back to the genetic search.

**Reporting**: Pareto front over (complexity, criterion); equivalence classes by response
agreement to `EQUIVALENCE_RTOL = 1e-6`; criteria AIC / AICc / BIC / CAIC / HQC / WAIC (Laplace)
/ F-test, with `SCREENING_FALLBACK = "aic"` in tier 1 where WAIC and the F-test cannot be
computed. The recommendation rule is independent of the criterion.

Measured space sizes are in `DISCOVERY_V2_PLAN.md` section 1 (2,976 topologies at <= 5 elements
on `R,C,L,CPE`; 11,550 on the component pool).

## 2. Published algorithms this project already leans on

Cited with URLs in `IMPLEMENTATION_PLAN.md` section 11; repeated here only as an index.

| Algorithm | Reference | Used in |
|---|---|---|
| Gene-expression programming for ECM identification | Van Haeverbeke et al., IEEE T-IM 70 (2021); EquivalentCircuits.jl | Precedent cited at `discover.py:18-21`; this project uses direct tree GP instead |
| AutoEIS (KK validation + evolutionary ECM generation + physics filters + Bayesian inference) | Zhang et al., J. Electrochem. Soc. 170, 086502 (2023); JOSS (2024) | Source of the post-filtering and down-selection design. **Since run head to head** — `docs/AUTOEIS_COMPARISON.md` |
| Linear Kramers-Kronig test | Boukamp, JES 142, 1885 (1995); model order after Schoenleber, Klotz & Ivers-Tiffee, Electrochim. Acta (2014) | `core/validate.py` |
| Tikhonov + GCV + NNLS for the DRT | ridge-regression DRT literature (DRTtools lineage) | `core/drt.py` — lambda chosen on the *unconstrained* problem, gamma recomputed non-negative |
| RL ladder for the skin effect | Kim & Neikirk, IEEE MTT-S (1996) | `core/spice.py`, export only |
| RC ladder for a CPE | Valsa & Vlach, IJCTA (2013); Athanasiou et al., IJCTA (2018) | `core/spice.py` |
| Differential evolution | Storn & Price (1997) | `scipy.optimize.differential_evolution` |
| Trust-region reflective | Branch, Coleman & Li (1999) | `scipy.optimize.least_squares` |
| Regularised evolution + accuracy/complexity Pareto front | PySR / SymbolicRegression.jl — design borrowed, code explicitly not reusable (Julia, no WASM, wrong operator grammar) | `discover.py:7-16` |
| Information criteria | Akaike (1974), Schwarz (1978), Hurvich & Tsai (1989), Hannan & Quinn (1979), Watanabe (2010) | `core/stats.py` |

Two more have standing in the field and are **deliberately not used**:

- **Levenberg-Marquardt with hand-picked initial values** (LEVM, ZView, Gamry Echem Analyst) —
  this is the thing mode 1 exists to replace.
- **NUTS / HMC for parameter posteriors** (AutoEIS's Bayesian stage) — ruled out by the
  numpy+scipy-only rule, not by merit.

## 3. Candidates not currently used

Each entry says what it would replace and what it would cost. **None of this is measured.**

### 3.1 Topology side

**(a) Vector fitting into a Foster synthesis.** Gustavsen & Semlyen, IEEE Trans. Power Delivery
14, 1052 (1999). Fits `Z(s) = sum r_k/(s - p_k) + d + s h` by alternating a linear least-squares
solve with a pole relocation: no initial values, no local minima, deterministic, and writable in
plain numpy. The pole count *is* the number of distinguishable relaxations, which is exactly
what the `interpret` objective asks for, and `core/spice.py` already synthesises ladders from an
impedance function.
**Limit, and it is a hard one: CPE, Warburg and skin effect are not rational.** This can only
ever be a candidate generator or a lower bound on the relaxation count over the R/C/L
subspace — never a replacement for `enumerate_topologies`.

**(b) Over-complete ladder with a group-LASSO penalty.** Build a large RC ladder on a
logarithmic tau grid and switch branches off with an L2,1 penalty. This is `drt.py`'s linear
structure with a different regulariser, so the machinery exists. It is the only candidate that
makes topology *and* parameters one **convex** problem — global optimum guaranteed, no seed
dependence at all. Limit: the answer is a Foster ladder, not a general series-parallel tree.

**(c) Reversible-jump MCMC / nested sampling.** Green, Biometrika 82, 711 (1995). Samples
topology and parameters jointly and yields a posterior *over topologies*. The present
equivalence classes are a hard 1e-6 response test; this would put probabilities on them, which
is the most direct answer available to "the data cannot decide between these two forms". Limit:
convergence diagnostics replace the guarantee that a number always comes out, and whether it
fits a browser budget is unmeasured. A Metropolis-within-Gibbs version needs no new dependency.

**(d) MCTS over the circuit grammar.** Petersen et al., Deep Symbolic Regression (ICLR 2021);
TPSR (NeurIPS 2023). Beats GP on symbolic regression, and the tree-over-a-grammar structure is
identical to this problem. It would let *partial* trees carry value, where `_Evaluator.cache`
can only key on completed ones. A policy-free UCT version is pure numpy; a learned-policy
version would need a model file and is therefore out.

**(e) MAP-Elites / quality-diversity with ALPS age layering.** Mouret & Clune (2015); Hornby,
GECCO (2006). `_quota_by_size` is already half of a MAP-Elites archive with element count as
the behaviour descriptor. Completing it — making the archive the breeding population — attacks
the exact pathology `EVOLVE_SEARCH_PLAN.md` section 1 measured: an archive that is never retired,
so selection pressure falls 8.2x over 12 generations. **This is finishing an existing structure,
not importing a new algorithm**, which is why it is the cheapest thing on this list.

**(f) NSGA-II / SPEA2.** Deb et al., IEEE TEC 6, 182 (2002). The deliverable is a Pareto front,
but selection today is single-objective (tournament on one score) with Pareto elitism bolted on.
Non-dominated sorting plus crowding distance is about fifty lines.

**(g) Branch and bound over the enumeration.** The exhaustive stage prunes with exact filters
but uses no *bound*. A lower bound on the chi-squared an n-element topology can reach would let
the completeness level rise past five without weakening what the report may claim — the only
route to six or seven elements that does not cost the completeness guarantee.

### 3.2 Parameter side

**(h) Variable projection (VARPRO).** Golub & Pereyra, SIAM J. Numer. Anal. 10, 413 (1973).
Eliminates the parameters that enter linearly and searches only the rest. Series R, series L and
Foster residues qualify. Dropping a seven-parameter search to four would cut the population and
generation counts the global stage needs. `_Problem.free_idx` is already the machinery for
partitioning parameters. Limit: deeply nested series-parallel forms put most parameters in
denominators, so which topologies benefit is itself a measurement.

**(i) L-SHADE / JADE, or CMA-ES.** Tanabe & Fukunaga (CEC 2014); Hansen & Ostermeier (2001).
Today's `mutation=(0.4, 1.0)` is fixed dithering; L-SHADE adapts F and CR from a success history
and shrinks the population linearly. CMA-ES learns the covariance, which suits a problem where R
and C are tied through `tau = RC` even in log space. Both are a few hundred lines of numpy and
add no dependency, and the interface (`bounds -> x`) is identical to `_global_stage`, so the
existing benchmarks compare them directly.

**(j) DIRECT or shgo.** Jones, Perttunen & Stuckman, JOTA 79, 157 (1993). **Already in scipy**
(`scipy.optimize.direct`, `scipy.optimize.shgo`) and fully deterministic — reproducibility
would stop being conditional on recording a seed. **But it would remove the identifiability
detector**: `_restart_spread` reads non-uniqueness off the disagreement between independent
seeded restarts, and a seedless algorithm has none. Adopting this without (k) trades an honest
warning for a tidy one.

**(k) Profile likelihood, or bootstrap.** Raue et al., Bioinformatics 25, 1923 (2009). Today's
two identifiability tests — restart spread and relative standard error off the Jacobian — are
both local, and neither sees a parameter that can move three decades without moving chi-squared.
Profiling scans one parameter while refitting the rest, and `fit(fixed={...})` already exists,
so almost no new machinery is needed. It would let the `free?` column be read off the actual
likelihood shape rather than off local curvature.

**(l) Homotopy / band continuation.** Fit a narrow frequency band and widen it, tracking the
solution. Physically natural for EIS, where a low-frequency relaxation hides under a
high-frequency ESL. **No published precedent to hand — this is a suggestion, not a citation.**

## 4. Ranked replacement candidates

Ranked by (expected benefit) / (cost of finding out), which is not the same as by expected
benefit.

### Recommended first — same interface, measurable against an existing baseline

| Candidate | Replaces | Why this one first |
|---|---|---|
| **(e) MAP-Elites + ALPS** | `_next_generation` selection | Attacks the measured 8.2x pressure collapse; half of it already exists as `_quota_by_size`; baseline is EV1's 1/9 |
| **(i) L-SHADE / CMA-ES** | `_global_stage` | Drop-in signature, no new dependency, directly A/B-able with `benchmarks/discovery_v2.py` |
| **(h) VARPRO** | Reduces `_global_stage`'s dimension rather than replacing it | Reuses `free_idx`; the win is bounded by which topologies have linear parameters, which is the measurement |
| **(k) Profile likelihood** | `_restart_spread` as the identifiability test | `fit(fixed=...)` already exists; catches non-identifiability the local tests cannot see |

### Promising, but they change what the report claims

| Candidate | Relationship to the current design |
|---|---|
| **(a) Vector fitting** | Complement to enumeration, never a replacement (CPE/Warburg are not rational) |
| **(b) Group-LASSO ladder** | Convex, seedless, solves both halves at once — but only over Foster ladders |
| **(f) NSGA-II** | Aligns selection with the fact that the deliverable is a front |
| **(g) Branch and bound** | The only route to 6-7 elements that keeps the completeness sentence intact |
| **(c) RJMCMC** | Turns equivalence classes into posterior probabilities; browser budget unmeasured |

### Conditional or ruled out

| Candidate | Verdict |
|---|---|
| **(j) DIRECT / shgo** | Do not adopt alone — it deletes the identifiability detector. Only sensible paired with (k) |
| **(d) MCTS** | Viable policy-free; a full rewrite of `_evolve`, so it must be measured against EV1's 1/9 |
| **(l) Band continuation** | No precedent found; treat as an idea |
| **NUTS / HMC** | **Do not adopt.** The numpy+scipy-only rule is what makes the browser build possible |

### Must not be replaced

The four exact filters — canonical deduplication, redundancy collapse, plausibility, endpoint
feasibility — are what the completeness claim rests on. Approximate pruning here has already
been proposed once and rejected by measurement (`DISCOVERY_V2_PLAN.md` section 3.4: a DRT peak
count raising the enumeration floor would delete the right answer from a search still calling
itself exhaustive). Any future proposal of that shape starts from that rejection.

## 5. What this document does not contain

- Any measurement. Every "expected" above is expected.
- Any gate. Task E's plan doc owes those.
- Verified bibliographic detail for section 3. The references in section 2 are transcribed from
  `IMPLEMENTATION_PLAN.md` section 11 with URLs; the ones in section 3 are from recollection and
  their volume and page numbers have **not** been checked against the papers. Check them before
  any of them is cited in a plan.
