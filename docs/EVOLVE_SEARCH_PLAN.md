# The Genetic Search — Making the Fallback Answerable

Status: steps 1-3 implemented (2026-08-22); steps 4-6 planned. §3.2.1 and §3.3.1 record what
steps 2 and 3 needed that this plan did not specify; §4 carries EV1's completed baseline, the
pass bar written from it, and EV3's verdict.
Prerequisite reading: `docs/DISCOVERY_V2_PLAN.md` §1 and §3.3 (why enumeration took over from the
genetic search, and the measurement that says a cheaper screen trades the answer for the clock).

## 1. Why

`discover(mode="auto")` is exhaustive up to five elements and genetic above that
(`discover.py:1172`). The exhaustive half has gates G1–G3 behind it and passes them 30/30. The
genetic half has **no quality gate at all**: G5 of `DISCOVERY_V2_PLAN.md` asks only that
`mode="evolve"` produce *the same* answer for a fixed seed, which is a regression test, not
evidence that the answer is any good. So above five elements this project currently makes no
measured claim whatsoever, and `mode="auto"` routes to that unmeasured code exactly when the
data says the exhaustive front is under-fitted — that is, when the user needs it most.

Four measurements taken while writing this plan say the situation is worse than "unmeasured".

### 1.1 A six-element truth is not recovered

[measured] One instrumented `_evolve` run, three-block Maxwell-Wagner
`p(R1,C1)-p(R2,C2)-p(R3,C3)` (6 elements, 1% noise, pool R,C,L,CPE, population 40,
12 generations, seed 0):

| gen | archive | new topologies | cache hits / 40 | best AIC |
|----:|--------:|---------------:|----------------:|---------:|
| 0 | 32 | 40 | 0 | −1583.75 |
| 3 | 98 | 22 | 18 | −1583.75 |
| 7 | 187 | 25 | 15 | −1633.41 |
| 11 | 263 | 18 | 22 | −1678.43 |

263 distinct topologies in 349 s (1.33 s each). **The truth was never evaluated.** For
comparison, the exhaustive stage screens thousands of topologies in the same order of time,
because a screening fit is 0.3–0.7 s against the genetic search's full-ish 1.33 s.

### 1.2 Selection pressure decays as the run proceeds

`_evolve` never retires anything: `alive = _unique_best(scored, ...)` (`discover.py:1523`) is the
**entire history**, and `_tournament` (`discover.py:2255`) draws 3 members from it. So the
probability that the best-known candidate is even considered as a parent is about `3/N`, and
`N` grows every generation. [measured, same run] 3/32 = 9.4% at generation 0, 3/263 = 1.1% at
generation 11 — an **8.2× fall in selection pressure over 12 generations**. The search gets more
random the longer it runs. This is the exact failure PySR's age-regularized evolution exists to
prevent, and it is a property of the archive, not of the operators.

### 1.3 More than half of each generation re-proposes something already evaluated

[measured, same run] Cache hits rise from 15/40 (37.5%) at generation 1 to 22/40 (55%) at
generation 11, so effective new evaluations per generation fall 40 → 18. The hits are free
(`_Evaluator.cache`, `discover.py:915`) but they are also information-free: a single population
with no migration converges onto a handful of trees and then re-derives them.

### 1.4 Reported numbers come from the screening budget — which the module forbids

`discover.py:89-91` states the rule this codebase runs on:

> Tier-1 screening budget. Enough to rank thousands of topologies, nowhere near enough to
> publish: **every number that reaches the user comes from the tier-2 refit.**

`_exhaustive` honours it — `_refit_shortlist` returns only refit candidates. `_evolve` does not:

```python
refined = _refine(alive[:n_refine], ...)           # discover.py:1535  top 8 only
merged  = _unique_best(refined + alive, criterion) # discover.py:1536  mixed with the rest
...
pareto=pareto_front(merged, criterion)             # discover.py:1541
```

[measured] `mode="evolve"` on the Randles reference (6 generations × 16, `n_refine=8`,
`final_restarts=5`), reading provenance off `FitResult.n_restarts`:

| Pareto row | n_restarts | AICc |
|---|---:|---:|
| `R1` | **1** | −172.95 |
| `p(R1,W1-R2)` | **1** | −433.84 |
| `p(R1,p(W1,C1)-R2)` | **1** | −660.03 |
| `p(p(R1,W1,C1)-W2,R2-C2)` | 5 | −1306.11 |

**3 of 4 reported front rows carry screening-grade numbers.** Their χ²_red, their standard
errors and therefore the `free?` column of `summary()` all come from a fit with
`restarts=1, popsize=12, maxiter=30`. The report does not say so, and cannot be told from an
exhaustive one by looking at it. That is this project's characteristic failure
(`docs/HANDOFF.md` §3) sitting inside the reporting path itself. (The same run also recommended
a six-element `p(p(R1,W1,C1)-W2,R2-C2)` with the four-element truth absent from the front
entirely — §1.1 again, on a smaller circuit.)

### 1.5 One suspicion that measurement demoted

`crossover` (`discover.py:892`) has no size limit, so `_next_generation` discards children that
exceed `max_elements` (`discover.py:2250`). It looked like a silent waste of work worth fixing.
[measured] 4000 proposed children on the same archive: **3853 kept, 96.3%**. A 3.7% discard rate
is not worth a code change, and it is recorded here so nobody re-derives the suspicion and acts
on it. It is left alone.

## 2. What this is and is not

**This is not a rewrite of discovery.** The exhaustive stage has passing gates and is not
touched: no change in this plan may alter `_exhaustive`, `screen_plan`, `refit_plan`,
`enumerate_candidates`, `_shortlist`, or anything the browser drives. `mode="evolve"` is
CLI-only (`cli/main.py:517`; there is no occurrence of `evolve` anywhere under `web/`), so the
Web UI, the Pyodide bridge and gates W1–W6 are out of the blast radius by construction.

**This is not an attempt to make the genetic search beat enumeration below six elements.** It
cannot, and it should not try. Its job is the range enumeration cannot reach: 6–7 elements,
where the space is 10⁵ candidates and rising.

**The one non-negotiable is §1.4.** Everything else here is an optimisation whose value has to
be measured; the provenance defect is a correctness bug in the report and is fixed first,
regardless of what the rest of the plan measures.

## 3. Changes

### 3.1 Step 1 — measure the baseline before changing anything (`benchmarks/`)

New references in `benchmarks/discovery_v2.py`, sized for the range that is actually the genetic
search's job. All three are beyond exhaustive reach. They go in a **separate `LARGE_REFERENCES`
list**, not into `REFERENCES`: every other mode in that file iterates `REFERENCES` and assumes a
truth the five-element exhaustive stage can reach, so a six-element truth there would make `gate`
fail by construction and would move the counts `DISCOVERY_V2_PLAN.md` records.

| label | circuit | elem | params | pool | window (Hz) |
|---|---|---:|---:|---|---|
| three-block Maxwell-Wagner | `p(R1,C1)-p(R2,C2)-p(R3,C3)` | 6 | 6 | R,C,L,CPE | 1e-2 – 1e7 |
| capacitor + interfacial block | `C1-R1-L1-SKINF1-p(R2,CPE1)` | 6 | 8 | R,C,L,CPE,SKINF | 1e2 – 1e9 |
| Randles + ESL + second block | `R1-L1-p(CPE1,R2-Wo1)-p(R3,C1)` | 7 | 9 | R,C,L,CPE,W,Wo | 1e-2 – 1e7 |

**A reference has to be identifiable before it can be a gate, and two of these were not when
first written down.** [measured] Fitting each truth to its own spectrum at 0% and 1% noise and
counting the parameters whose standard error exceeds their own value:

- *Three-block Maxwell-Wagner* — 0/6 unresolved, kept as first drafted. Its time constants are
  1e-6, 0.01 and 0.04 s, so the last two sit **0.6 decades apart**, which is deliberately the
  hard case; the truth still recovers, worst block deviation 24.1% at 1% noise. Note that this
  circuit has a **permutation symmetry** — three parallel RC blocks in series are exchangeable —
  so comparing fitted to true parameters by name reports nonsense (2400% off) and any check on
  this reference must match blocks before comparing.
- *Capacitor + interfacial block* — first drafted with `R2 = 5 kΩ, CPE1.Q = 1e-9`, which is
  **unusable**: the block then swamps the capacitor across the whole window and **3 of 8
  parameters** — the ESR and both skin-effect parameters — come back unresolved at 1% noise. The
  reference would have asked the search to find a circuit the data cannot confirm. At
  `R2 = 5 Ω, CPE1.Q = 5e-6` it is 0/8. The ESR is still the marginal parameter (0.0176 fitted
  against a true 0.01, stderr/value 0.275), which is the same 10 mΩ effect G1 already documents,
  so this reference is expected to pass `reported` while sometimes failing `is_recommendation`.
- *Randles + ESL + second block* — first drafted with the window ending at 1e5 Hz, which puts the
  ESL's L/R corner at 3.18e7 Hz, **outside it**. The inductance then moves |Z| by 0.3% at the very
  top, under the noise, and the full-budget fit of the *known truth* returned `L1` off by **+811%**
  at 2.65% RMS against a 1.3% noise floor. Widening to 1e7 Hz gives ωL/R = 0.314 at the top and
  every parameter within 4.0%, 0/9 unresolved. Three alternatives were measured and rejected:
  f_max 1e6 (`Wo1.tau` off 99.9%, 2 unresolved), L1 = 1e-6 at 1e6 (wrong basin, `CPE1.Q` +628%),
  L1 = 1e-5 at 1e5 (2 unresolved). The parameter is also `Wo1.R`, not `Wo1.A`.

New benchmark mode `evolve-gate`, alongside the existing seven, reporting per reference and per
seed: whether the truth or an exact equivalent was reported, whether it reached the Pareto
front, whether it is the recommendation, distinct topologies evaluated, wall-clock, and — new,
because §1.4 makes it necessary — **how many reported rows came from tier 2**.

It needs its own verdict rather than reusing `_truth_verdict`. That function finds the truth by
canonical form and, failing that, returns "not reported" — it can only reach
`equivalents_of(truth)` once the truth itself is in the list. EV1 asks for "the truth **or an
exact equivalent**", and above five elements an exact reparameterisation is *more* likely to be
what comes back, not less; scoring that as a failure would measure the wrong thing. So the truth
is looked up by **response**: fit the true circuit once at full budget, then match reported
candidates against its fitted `z_model` under the same `EQUIVALENCE_RTOL` rule `_same_response`
uses. This also means the references need no hand-listed `equivalents`, which at six and seven
elements nobody has enumerated.

**Gate EV1's pass bar is written from this run, not before it.** The house rule
(`WEB_UI_PLAN.md` §2.5, `PARTIAL_TOPOLOGY_PLAN.md` §3.2) is that a threshold invented in advance
gets quietly reinterpreted later; §1.1 is one data point on one reference and one seed, and a
bar set from it would be a guess wearing a number.

### 3.2 Step 2 — `_evolve` reports tier-2 numbers only

The fix for §1.4. `_evolve` shortlists by the **same per-element-count quota rule** the
exhaustive stage uses, refits that shortlist at full budget, and **returns only the refit
candidates** — so `candidates`, `pareto`, `recommended`, `to_csv` and `to_dict` describe one
kind of fit, exactly as they do in exhaustive mode.

`_shortlist` (`discover.py:1742`) takes `(cost, text)` pairs, which `_evolve` does not have; it
has scored `Candidate`s. Rather than duplicate the rule, factor the *quota* out of `_shortlist`
into a helper both call, so that the reason the quota is per size — [measured] ranking globally
puts nothing but the largest circuits on the shortlist and G1 failed until it was changed
(`DISCOVERY_V2_PLAN.md` §5.1) — has one implementation and one docstring.

`REFINE_DEFAULT["evolve"]` was 8. **Implemented: it is now 30, the same as the other two, and
the sweep this plan asked for turned out to be unrunnable in principle.** The quota is
`max(MIN_REFINE_PER_SIZE, n_refine // sizes)` and a genetic archive spans about seven element
counts (`{1:4, 2:11, 3:20, 4:45, 5:48, 6:72, 7:63}` in §1.1), so 8, 16 and 30 all reduce to the
same quota of 5: below `MIN_REFINE_PER_SIZE * sizes` this constant has **no effect at all**.
That is arithmetic, not a measurement, and the sweep would have reported three identical rows.
The floor is the knob; the constant now carries that note so nobody runs the sweep looking for
a difference that cannot appear.

Two alternatives were considered and rejected:

- *Mark provenance on `Candidate` and print it.* Keeps more rows, but produces a report whose
  rows make two different kinds of claim, and a `provisional` column the exhaustive path would
  never set. `_with_refit_note` (`discover.py:530`) already exists for the one case where a
  report is legitimately partial — a *stopped* run — and that is the shape a per-row flag would
  quietly compete with.
- *Refit whatever lands on the front.* Circular: the front is drawn from the scores, so refitting
  it changes the scores and can change its membership, and the iteration has no fixed point
  worth defending.

Two things implementation added that this section did not anticipate, both recorded in §3.2.1.

Consequence, stated rather than absorbed: **G5 of `DISCOVERY_V2_PLAN.md` ("`mode="evolve"`
results unchanged for a fixed seed") is superseded by this plan and withdrawn.** It was written
to stop the exhaustive work from silently perturbing the genetic search; steps 2–5 change the
genetic search on purpose, and a gate that forbids the change cannot also be the thing that
validates it. Its replacement is EV5, which pins the *exhaustive* results instead.

#### 3.2.1 What step 2 needed that this plan did not specify

- **The quota rule needs an explicit tiebreak, and factoring it out lost one.** The original
  `_shortlist` sorted `(score, cost, text)` tuples whole, so ties broke alphabetically on the
  topology string. The extracted `_quota_by_size` first sorted on the score alone, which breaks
  ties by insertion order instead. That is not a nicety here: **two candidates scoring exactly
  alike is the normal case**, because it is what an exact reparameterisation looks like and
  surfacing those is what the equivalence-class report is for. `Ranked` therefore carries an
  explicit `tiebreak` field. Caught by the EV5 fingerprint comparison, not by the test suite —
  which passed with the bug in place.
- **`time_limit` had to grow a second half.** It has always governed the evolutionary loop and
  not the refit after it, which was harmless while the refit was a fixed eight fits.
  [measured] Under the per-size quota it is 35–70 full fits, and a run given a 5 s budget spent
  **222 s** in the refit alone — caught by an existing test whose comment already said the limit
  governs only the loop. The obvious fix, bounding the refit at `time_limit` itself, is wrong:
  the loop has usually already passed that mark, so the deadline would be spent before the tier
  began and the run would report **nothing at all** having done all of the work — which is
  exactly what the EV1 baseline's own settings would have produced. The refit gets its own share
  on top (`REFIT_HEADROOM = 1.5`), the first candidate is always attempted so that a report is
  never empty, and a tier that does run out reports through `refit_progress`, which already
  existed for this and had no producer in the library until now.
- **And a tier that stops early needs an *order* to stop in — which the quota does not supply.**
  Found afterwards, by `docs/SEARCH_ALGORITHM_SCREENING.md` §4.6, and it is the two bullets above
  interacting. `_quota_by_size` chooses *which* candidates deserve a refit and returns them
  grouped by element count, the groups in whatever order the archive first mentioned them —
  which is exactly right for the exhaustive stage, whose tier 2 refits all of them. Under
  `REFIT_HEADROOM`'s deadline it decides what is *reported*. [measured] `_evolve` on the
  three-block Maxwell-Wagner reference at element cap 9, pool `R,C,L`, seed 0, 180 s: the truth's
  equivalence class was reached, its best member **ranked 1 of 270 in the archive**, and it sat
  at **position 53 of a 73-candidate shortlist whose deadline cut fell at 40**. Sizes 6 and 8
  were never attempted at all, so the report carried no six-element row while the best thing the
  search had found was one; four verified class members were shortlisted and **none were
  reported**. Nothing was wrong with the search, the criterion or the shortlist — the report
  walked away from the answer. `_refine` now walks `_refit_order`: a round robin over the size
  groups, best of every size before any size's second, ordered within a round by score. The same
  run then reports **4 of 4** shortlisted class members, the first-ranked candidate first, at the
  same 40 fits. The properties are the quota's own two, extended to the case where the list is
  cut: the best-scoring candidate is never cut, and a front that is cut still spans the
  complexities instead of shrinking to whichever sizes fitted inside the clock. Fixed by
  `benchmarks/screening_round/report_probe.py`, which separates *shortlisted and dropped* from
  *never shortlisted* — `evolve_probe.py` could see only that the class was not reported.

### 3.3 Step 3 — inherit the parent's parameters (the largest expected win)

§1.1 measures 1.33 s per topology. That cost is a global optimisation
(`fit.py:682`, `differential_evolution` + TRF polish) run **from scratch for every child**, even
when the child differs from its parent by one inserted element. PySR never does this: its
constants live inside the expression and travel through mutation, with an explicit `optimize`
mutation to polish them. Borrowing that is the one change with an obvious factor behind it.

`fit()` already supports both halves — `initial=` accepts a *partial* dict (`fit.py:543-549`
overrides named entries on `problem.template`), and `global_search=False` turns the call into a
pure local refinement (`fit.py:506, 539`).

**The correspondence cannot be keyed on labels.** `simplify()` discards them —
`circuit.py:301-302` returns `ElementNode(node.code)` with no label — and `_Evaluator.evaluate`
calls `Circuit(simplify(node))` before anything else (`discover.py:919`). This is also why
crossover children never collide on labels, which is worth knowing before someone "fixes" the
stripping. So inheritance is structural: for each element code, zip the parent's leaves of that
code in leaf order with the child's, carry the parameter values across, and leave the extras at
the template default.

Evaluation becomes two-stage:

1. local polish from the inherited start (milliseconds);
2. the existing reduced-budget global stage, **only** when the polish lands worse than a factor
   `WARM_ACCEPT_FACTOR` off the best cost known at that complexity.

The cache (`discover.py:915`) changes from first-wins to best-wins: a cache hit with a *new*
warm start runs the polish only — which is nearly free — and keeps the better of the two. That
removes the path dependence a warm start would otherwise introduce, and it turns §1.3's 55%
cache-hit rate from wasted generations into cheap refinement.

**This step is only safe after step 2**, and the ordering is the argument: warm starting makes
the fitness *inconsistent* between candidates — some polished, some globally searched — so a
warm-started child can outrank a topology that was searched properly. As a shortlist signal that
is acceptable. As a published number it is not, and today it would be published (§1.4).

`WARM_ACCEPT_FACTOR` is swept in the benchmark, and the gate is two-sided (EV3): more topologies
evaluated **and** recovery not worse. A one-sided speed gate is how `DISCOVERY_V2_PLAN.md` §3.3
nearly lost the truth to a cheaper screen, and how `METRICS_AND_UX_PLAN.md` §1.5 got a stage
3–4× faster while making the total worse.

#### 3.3.1 What step 3 needed that this plan did not specify

- **The polish inherited the *publication* local budget, and that alone decided the step.**
  `fit()`'s trust-region stage runs at `xtol=ftol=1e-14, max_nfev=20000`, because everything
  downstream of a reported fit -- the covariance, the standard errors, the `free?` column -- is
  read off the Jacobian where the parameters stopped moving. A tier-1 polish has no such
  obligation, and `screen()` already knew that: it has always used `1e-12 / 2000`. Going through
  `fit()` gave the warm start the wrong one of the two, so **an unbounded refinement was running
  inside a screen**. [measured] The cost is cheap in the median and catastrophic in the tail --
  10 children of a seven-element parent, polish against the reduced global search it replaces:

  | | median | tail |
  |---|---:|---|
  | polish | 0.037 s | **16.6 s**, **13.1 s** |
  | global search | 0.175 s | 14.9 s, 14.6 s |
  | polish as a fraction | **21%** | **111%**, **90%** |

  Two of ten polishes cost as much as the search they were meant to save. That tail is rare
  enough to be invisible in a two-minute run and decisive in a ten-minute one, which is exactly
  the shape the first EV3 measurement had: **+39% topologies at 120 s and +7% at 600 s**, with
  three of six pairs *slower*. The fix is not a new constant but the one that already existed:
  `LocalBudget`, `PUBLISH_LOCAL` and `SCREEN_LOCAL` name the two settings this module already
  had as duplicated literals, and the polish asks for the screening one. Tier 1's *global* path
  deliberately keeps the budget it had -- changing it would move every number the control arm is
  measured against, and a comparison whose control moved measures nothing.
- **Where the rest of the saving goes, counted rather than assumed.** [measured, one 150 s run,
  MW seed 1] 240 proposals, 74 cache hits (31%), 133 polishes, **73 accepted (55%)**, 84 global
  searches. So **45% of polishes are paid on top of a global search that ran anyway** -- the
  polish landed too far off the best cost at its complexity to be believed. With the polish
  bounded, the same 150 s went from 166 to **220 distinct topologies (+33%)** and 6 to 8
  generations, with the acceptance rate essentially unchanged (55% → 51%): the gain came from
  the tail, exactly where the measurement above said it was.
- **The sweep found only one arm that does anything, and it is the permissive one.** [measured]
  Three-block Maxwell-Wagner, seeds 0 and 1, 120 s each, arms interleaved seed by seed:

  | `warm_accept` | seed 0 | seed 1 | mean topologies | vs control | truth reported |
  |---|---:|---:|---:|---:|---:|
  | 0 (control, inheritance off) | 114 | 183 | 148 | — | 1/2 |
  | 1.5 | 115 | 160 | 138 | −7% | 1/2 |
  | 3 | 159 | 179 | 169 | +14% | 1/2 |
  | 10 | 136 | 162 | 149 | +1% | 1/2 |
  | ∞ (accept any polish once a yardstick exists) | 160 | 252 | 206 | **+39%** | 1/2 |

  Only ∞ beats the control on **both** seeds (+40%, +38%); 1.5, 3 and 10 are inside the
  run-to-run spread and 1.5 is below the control. The mechanism says why, and it is worth
  stating because it is not what the plan assumed: the polish is a saving only when it lets the
  global stage be *skipped*, so a strict factor pays for the polish **and** the global search on
  almost every child. There is no gentle middle setting — the knob is nearly binary.
- **Recovery did not move anywhere in the sweep** (1/2 in every arm, the same seed, and it was
  the recommendation in every arm too). Two seeds on one reference is far too little to call
  that "recovery is not worse"; it is what EV3's 600 s runs are for, and it is the reason the
  default was not set from the sweep alone.
- **The correspondence had to skip the elite, or the search would re-polish its own answers.**
  The Pareto elite are re-proposed unchanged every generation with themselves as parent, so
  `_inherited_values` returns exactly the values the cached fit already has. `_warm_start`
  detects that case and returns nothing rather than paying for a polish that cannot move.
- **A crossover child names one parent: the tree that was grafted *onto*, not the donor.** The
  child is a modification of that tree, so it is the one most of the inherited values still
  belong to. Inheriting from both would need a correspondence across two unrelated leaf orders,
  which is a different feature and not one this measurement asks for.
- **Two fits of one topology are compared by residual cost, not by `Candidate.score`.** They
  share a topology, hence `k` and `n`, so every criterion is monotone in the cost — which lets
  the evaluator keep the better of a polish and a global search without knowing which criterion
  the run was asked for. Comparing by score would have made the cache's contents depend on
  `criterion`, and the cache is a search structure, not a report.
- **`warm_accept=0` is a supported setting, not a debug flag.** It is the control arm EV3 needs,
  and it lets the before/after be measured in one interleaved run rather than by stashing
  `discover.py` — which is how step 2's before/after had to be done, and which cannot interleave
  arms at all.

### 3.4 Step 4 — bound the archive, and add islands

For §1.2 and §1.3, in that order of importance.

- **Bounded selection pool. [implemented]** Breeding draws from `_breeding_pool` — the Pareto
  front plus the best `population` by score — rather than from the whole history. **It costs diversity and the cost is measured**: the per-generation cache-hit rate rises 26 points across a run against the control's 6, which is EV4's first clause failed (see §4). The
  `_Evaluator` cache stays global; so, and this is a change from the sketch below, does the
  **archive**. The screening-round arm assigned its bounded pool back over the history, which is
  free there because a table walk has no report to produce; here the archive is what
  `_shortlist_candidates` draws tier 2 from, and it costs nothing to keep, because the pool
  provably contains the whole history's front and its top `population` anyway. So the search
  breeds from a bounded set and the report still selects from everything that was fitted.
- **Selection pressure held constant. [not done, and now unmotivated as written]** The sketch
  scaled the tournament with the pool (`max(3, round(TOURNAMENT_FRACTION * len(pool)))`). With
  `len(pool)` no longer growing, a fixed tournament of 3 *is* a fixed pressure, and
  `TOURNAMENT_FRACTION` has no measurement behind it. [measured] On the frozen landscape the
  bounded arm's pressure goes 0.103 → 0.065 over a run where the incumbent's goes 0.103 → 0.003:
  the 8.2× collapse §1.2 measured becomes 1.6×. Left alone unless something measures a need.
- **Islands. [built, measured, removed]** `islands: int`, each with its own RNG stream derived
  from `seed`, exchanging a fraction of members per generation. It was implemented and it does
  not ship: §3.4.4 is the arena round that removed it, and §3.4.2 is kept as the record of what
  was built, because four of its decisions are the ones anyone rebuilding this would have to
  make again. The short version is that islands' apparent win was the narrowing they came
  wrapped in, and narrowing one pool directly is both simpler and better.

Measured target: cache-hit rate per generation stops rising, and EV1 does not regress. Both, not
either.

#### 3.4.1 What the bounded pool is worth, and where that number comes from

The evidence is `docs/SEARCH_ALGORITHM_SCREENING.md`, whose whole point is that this question
cannot be afforded at gate prices: `evolve-gate` costs 2.5–3 h per arm because its budget is
wall-clock and it fits as it goes. The round screens every topology in the space *once* into a
frozen table, after which a topology search is a lookup-table walk budgeted in **fits**, and 120
seeds are free.

**[measured] 120/120 [0.97,1.00] at a median of 308 fits, against the incumbent's 87/120
[0.64,0.80] at 451** — the truth's verified equivalence class, 21,057-topology `R,C,L,CPE` arena,
900 fits per run, `benchmarks/screening_round/arms.py --arms current,ga_bounded`. The intervals
do not touch. Two things about that number:

* **It was re-measured against the shipped rule rather than inherited.** `arm_ga_bounded` now
  calls `discover._breeding_pool` instead of restating it, so the arm cannot drift from the
  library — the same reason the incumbent arm drives `_next_generation` directly. The two
  differences that introduced (the archive is no longer truncated; equal scores break on the
  canonical form rather than on insertion order) moved neither figure: 120/120 and 308 again.
* **It is not a gate and does not claim to be.** The frozen landscape abstracts the tier-1 fit
  away, so it measures the *topology search* and nothing else. What it predicts transferred once
  already (§4.6 of that document), and EV1 below is where it is asked to transfer again.

Two of the round's other arms also reach 120/120 — NSGA-II at a median of 256 fits and a
MAP-Elites archive at 418 — and what all three share is not their operators but that they bound
the set they breed from. This is the smallest of the three, so it goes first; NSGA-II is worth
its selection rewrite only if this is not enough. **ALPS age layering must not be added**: on top
of MAP-Elites it measured 24/30, the one addition in the round that made things worse.

#### 3.4.2 What the islands needed that this plan did not specify

**This describes code that was built and then removed (§3.4.4).** It is kept for two reasons:
the arm that recorded the rejection still runs, in `benchmarks/screening_round/arms.py`, and
these four decisions are not obvious — anyone who reaches for islands again will have to make
them, and getting the first one wrong makes the comparison meaningless rather than merely wrong.

Four decisions, none of them in the sketch, all of them load-bearing.

* **`population` is split across the islands, not multiplied by them.** PySR names a
  `population_size` *per* population; here `population` stays the size of a **generation**, so
  four islands are four pools of ten rather than four pools of forty. That is what makes the
  arms comparable at all: a generation costs the same number of fits either way, so a
  difference in what the search finds is a difference in how it breeds and not in how much it
  was given. `_island_sizes` is the split and it raises rather than rounds to zero when there
  are fewer members than islands.
* **Island 0 keeps the single-population random stream.** `_island_streams` returns
  `default_rng(seed)` itself for the first island and derived streams for the rest, so
  `islands=1` is the shipped search bit for bit rather than merely equivalent-looking. Spawning
  all of them would have been just as reproducible and would have moved every result of the
  default configuration — the drift EV5 exists to catch. [measured] EV5's probe, extended to
  fingerprint `mode="evolve"` (five generations, population 10, `max_elements=4`, three
  references), is **byte-identical** across this change: 181,321 bytes before and after.
* **Migration is transient, and it is the neighbour's best.** Island *i* breeds from its own
  bounded pool *plus* the best `round(fraction * size)` members of island *i-1* — for that
  generation only. Permanent adoption is the obvious alternative and it defeats the point: after
  one lap of the ring every island holds every other island's best, which is the single shared
  pool this step exists to split, reached more slowly. Nothing is lost by keeping the archives
  apart, because the *report* is drawn from their union and the evaluator's cache is shared, so
  a topology two islands both reach is fitted once.
* **A positive fraction always moves at least one member.** `round(0.1 * 5)` is 0, so an island
  sweep at a fixed fraction would silently turn migration *off* at the higher island counts and
  neither result would say what it had measured. The floor is `max(1, ...)`, and `fraction = 0`
  stays available as the fully isolated arm.

One thing the islands fixed on the way past, which is a defect in the bounded pool rather than
in them: **a topology now has one fitness**. The evaluator's cache is best-wins, so a second
island arriving at a known topology with a better warm start improves the fit and holds the
improved candidate, while the first island's archive still holds the object it was handed. Each
island's archive is therefore resolved through the cache (`_Evaluator.best_known`) before it
breeds. A topology is a genotype and its fit is that genotype's evaluation; one genotype with two
fitnesses is not a search, and nothing in a report could have shown it.

#### 3.4.3 How wide the bounded pool should be, measured all the way down

Neither §3.4.1 nor §3.4.2 asked how wide the pool should be. `_breeding_pool` was given
`population` because `population` was the number already in the argument list, and the islands
inherited that width without questioning it. The ladder that asks the question --
`ga_tight20`, `ga_tight10`, `ga_tight5`, `ga_tight3`, `ga_tight1`, `ga_front` in
`benchmarks/screening_round/arms.py` -- runs down to a pool of **one, and then to none**, on
purpose: a bound that keeps improving all the way there is not a well-chosen neighbourhood, it is
hill climbing wearing a population, and the two are told apart only by measuring the end of the
ladder rather than a point on it.

Three runs, all on the 21,057-topology `R,C,L,CPE` arena with 18 verified targets (0.085%), 120
seeds, `population` 40, AICc. Raw output in
`benchmarks/screening_round/results_pool_bound.txt`.

**[measured] At 900 fits the arena is saturated and ranks nothing.** All eleven arms reach
120/120 [0.97,1.00], so only the median fits separates them: `ga_bounded` 308, tight20 240,
tight10 194, tight5 168, tight3 146, tight1 148, and every islands configuration 223-246 -- 2,
4 and 8 islands alike, with migration 0.5 / 0.75 / 1.0 giving 239 / 246 / 243, which is to say
the migration rate changes nothing measurable. **A round that had stopped here would have
reported that islands beat the incumbent**: 239 against 308, paired 88 faster / 32 slower,
p = 0.0000. That is true and it is not the finding, because a *single* pool of the same width
beats both at 194. §4.2 of `SEARCH_ALGORITHM_SCREENING.md` again, in the other direction: an
arena everything passes ranks nothing, and the win islands appeared to have was the narrowing
they came wrapped in.

**[measured] Unsaturated, tightening the pool multiplies the hit rate 9.3x and costs nothing.**
Budgets 150 and 250 put hit rate back on the discriminating axis:

| arm | pool width | hit @150 | hit @250 | pressure, first third -> last |
| --- | --- | --- | --- | --- |
| `ga_bounded` (shipped) | front + 40 | 7/120 [0.03,0.12] | 38/120 [0.24,0.40] | 0.103 -> 0.068 |
| `ga_tight20` | front + 20 | 24/120 [0.14,0.28] | 66/120 [0.46,0.64] | 0.137 -> 0.119 |
| `ga_tight10` | front + 10 | 30/120 [0.18,0.33] | 93/120 [0.69,0.84] | 0.240 -> 0.186 |
| `ga_tight5` | front + 5 | 47/120 [0.31,0.48] | 110/120 [0.85,0.95] | 0.365 -> 0.266 |
| `ga_tight3` | front + 3 | 64/120 [0.44,0.62] | 110/120 [0.85,0.95] | 0.444 -> 0.318 |
| `ga_tight1` | front + 1 | 65/120 [0.45,0.63] | 112/120 [0.87,0.97] | 0.539 -> 0.386 |
| `islands4_m50` | 4 x (front + 10) | 18/120 [0.10,0.22] | 68/120 [0.48,0.65] | 0.259 -> 0.204 |

The intervals at the two ends do not touch at either budget. Two readings of that table, and the
second is the one that matters:

* Tightening does **not** trade reliability for speed, which is what a bound is usually suspected
  of. It buys both at once, and the reason is in the last column: the wider the pool, the more of
  it is made of candidates that are dominated, so the selection pressure that §1.2 measured
  collapsing is being diluted rather than spent.
* **The islands lose to the single pool of their own width.** `islands4_m50` is four pools of ten
  and reaches 18/120 where `ga_tight10` reaches 30/120; at 250 it is 68/120 against 93/120. Their
  entire apparent advantage at budget 900 was that splitting a pool of 40 four ways makes each
  neighbourhood narrower, and narrowing the pool directly is both simpler and better.

**[measured] The end of the ladder is not a bound at all.** `ga_front` (`pool_bound=0`, the
Pareto front and nothing else) and `ga_tight1` are **the same arm on every seed**: 65 tied at
budget 150 and 112 tied at 250, identical medians (113 and 143), identical best AICc (-1676.14
and -1680.82), identical size histograms and identical pressure. That is an identity rather than
a coincidence -- the best-scoring candidate is by definition non-dominated, so it is already on
the front, and "the front plus the best one" adds nothing. The ladder therefore terminates at a
rule with **no width parameter in it**: breed from the Pareto front. Adding anything back is
measurably worse (front+3 is 64/120 and front+5 is 47/120 against front's 65/120 at budget 150),
and the front is naturally bounded at roughly one member per complexity level, which is why the
pressure stops collapsing without anyone choosing a number.

Two readings this measurement **withdrew**, kept here because both looked settled at the time:

* *"Islands help."* Withdrawn. See the two paragraphs above; the saturated arena said yes and was
  measuring the wrong thing.
* *"The ladder turns around at a pool of one."* Withdrawn. A 3-seed smoke run had tight3 at 131
  fits against tight1's 222 and that shape is exactly what a too-narrow pool would look like. At
  120 seeds they are 146 and 148 -- indistinguishable. Three seeds cannot resolve a median, and
  the smoke reading should never have been carried as one.

Two facts about running this round that cost an evening each:

* **`pool_bound or population` folds a bound of zero into the default.** The arm that decided the
  whole question is the one whose bound is 0, and it silently ran at 40 until the `is None` check
  replaced it. It produced a plausible number rather than an error.
* **A cache hit costs no budget and does cost wall time.** `Table.evaluate` returns a known
  topology without incrementing the fit counter, so a tighter pool re-proposes what it already
  knows, burns generations for free and takes *far longer in wall clock while spending fewer
  fits*. A run that looks hung at the tight end of the ladder is not hung. Budget in fits is the
  right unit for the comparison and the wrong unit for the ETA.

#### 3.4.4 The islands, measured out

§3.4.3 changed the rule the islands were written against, which meant the comparison they had
been losing was no longer the comparison to make: the ladder's winner breeds from the Pareto
front alone, and an islands arm still breeding from front-plus-ten would lose for the reason the
ladder had already measured rather than for anything to do with islands. So `arm_islands` was
given the same `pool_bound` knob and re-run under the front-only rule. **Removing an
implementation on the strength of a comparison run under the losing configuration is not a
measurement, it is a conclusion arriving early.**

**[measured] Islands never help, and four of them hurt.** 120 seeds, same arena, migration 0.5
except where noted:

| arm | hit @150 | hit @250 |
| --- | --- | --- |
| `ga_front` (one pool, the front) | 65/120 [0.45,0.63] | 112/120 [0.87,0.97] |
| `islands2_front` | 77/120 [0.55,0.72] | 112/120 [0.87,0.97] |
| `islands4_front` | 60/120 [0.41,0.59] | 108/120 [0.83,0.94] |
| `islands4_front_iso` (no migration) | 27/120 [0.16,0.31] | 68/120 [0.48,0.65] |

The isolated arm is the control that says the ring is doing something rather than nothing — cut
migration and four islands fall to 27/120 — and it is also the clearest statement of the cost:
four independent narrow searches are much worse than one. Two islands at budget 150 is the only
cell that looks like a win, and **at 120 seeds that question cannot be answered**, so the
response was more seeds rather than a softer reading of the bar (§3.3.1 records the last time
this project nearly got that backwards).

**[measured] At 480 seeds the two-island win is noise and the four-island loss is real.** The
paired hit/miss test is McNemar, exact, on the discordant seeds — which is also a gap this round
found in the harness: the fits table drops every seed where the two arms disagree about hitting
at all, which at an unsaturated budget is the entire signal, so a hit-rate difference had never
been tested by anything.

| arm | hit @150 | both hit | only `ga_front` | only this arm | McNemar p |
| --- | --- | --- | --- | --- | --- |
| `ga_front` | 282/480 [0.54,0.63] | — | — | — | — |
| `islands2_front` | 302/480 [0.59,0.67] | 174 | 108 | 128 | **0.216** |
| `islands4_front` | 233/480 [0.44,0.53] | 136 | 146 | 97 | **0.0020** |

Neither arm differs in fits-to-hit (p = 0.45 and 0.55). So: two islands is indistinguishable
from one pool, four islands is significantly worse, and isolated islands are far worse. **The
implementation is removed** — `islands`, `MIGRATION_FRACTION`, `_island_sizes`,
`_island_streams`, `_migrants`, `_with_migrants`, the `--islands` CLI flag and the five tests
that pinned them. `arm_islands` stays in the screening round, carrying its own copies of the
three helpers, for the same reason `arm_nsga2` and `arm_map_elites` do: an arm that recorded a
rejection has to stay runnable, or the rejection is a claim rather than a measurement.

One thing the islands paid for on the way out. The `--islands` flag should never have been
offered at all: CLAUDE.md's rule is that a search internal the target user cannot set correctly
is not a knob, and "how many sub-populations" is exactly that. `BREEDING_EXTRA` is the shape the
replacement takes — a module constant with its measurement in the docstring, reachable by the
benchmarks that measured it and by nothing else.

Three readings this step withdrew, all of them after they had looked settled:

* *"Islands help."* Measured at a saturated budget, where they beat the incumbent 239 fits to
  308 and lost to a single pool of their own width at 194.
* *"The ladder turns around at a pool of one."* A 3-seed smoke run; at 120 seeds the two rungs
  are 146 and 148.
* *"Two islands are better than one pool."* 77/120 against 65/120 at 120 seeds; 302/480 against
  282/480 with McNemar p = 0.216 at 480.

### 3.5 Step 5 — adaptive parsimony, and the mutation weights

Last, because they are tuning and the steps above are structure.

- **Adaptive parsimony.** PySR tracks how crowded each complexity level is and penalises the
  crowded ones, which is what keeps every complexity populated. `_next_generation` approximates
  this with Pareto elitism (`front[:max(2, population // 6)]`). Add a
  frequency term to the **selection** score only. It must never reach `Candidate.score`: the
  criterion the user chose is what ranks the report (`DiscoveryResult.criterion`), and a
  breeding heuristic that leaked into it would change the published ranking for a reason the
  report cannot state.
- **Mutation weights.** `[0.35, 0.25, 0.25, 0.15]` has no measurement behind
  it — the only constant in this module that carries no **[measured]** note. Sweep it in the
  benchmark and either justify it or replace it. A sweep that finds nothing is a result and gets
  written down as one.

**Both were built as written, both were measured, and neither moved a default.**
`PARSIMONY_SCALING = 0` and `MUTATION_WEIGHTS = (0.35, 0.25, 0.25, 0.15)` — the same two values
the step started with, and what changed is that they now carry the measurement that says so. What
the step actually produced is in §3.5.1 to §3.5.3, and the middle one is the one worth the reading
time: it is the first time this round has varied *what circuit it is looking for*, and the
strongest effect in the whole sweep turned out to be a property of the reference rather than of
the search.

#### 3.5.1 Adaptive parsimony: measured, and it does nothing

The implementation is one keyword on `_tournament` plus `_complexity_frequencies`, and two
decisions inside it are worth stating because neither is PySR's.

*The frequency is taken over the **archive**, not over the pool.* Step 4 left the breeding pool
equal to the Pareto front, which holds about one member per complexity by construction — a
crowding count over it is 1 everywhere and ranks nothing. What is unevenly populated is the
history: [measured] 58% of a run's fits land at five and six elements. Written against the pool,
as the plan's own wording implies, the term would have been a measured no-op for a reason that has
nothing to do with adaptive parsimony.

*The term is additive, not multiplicative.* PySR scales the loss by `exp(scaling × frequency)`.
The criterion here is AICc and it is usually **negative** (this arena's optimum is −1682), so
multiplying by a factor above one *rewards* the crowded level. Additive also puts the constant in
a unit the sweep can be reasoned about in: one AICc is one parameter's worth of evidence.

**[measured] The ladder, 21,057-topology arena, 120 seeds at 150 fits.** Scaling 0.5 → 65/120,
2 → 64, 5 → 64, 10 → 64, 20 → 65, 100 → 63, 300 → 63, **1000 → 77**, 3000 → 71, 1e4 → 78,
1e6 → 57, against the shipped rule's 65/120. Nothing below 300 changes anything — the penalty is
at most `scaling × 1` and a front member's score differences run to hundreds of AICc — and above
300 the ladder wanders between 57 and 78 with no ordering at all. The top rung is the limit rather
than a rung on the way to one: at 1e6 the term outranks every score difference, so the tournament
is "take the least-crowded complexity, fitness as a tiebreak", and that arm is the *worst* of the
eleven.

**[measured] At 480 seeds the two apparent winners are noise.** McNemar, exact, on the discordant
seeds:

| arm | hit @150 | both | only `ga_front` | only this arm | McNemar p |
| --- | --- | --- | --- | --- | --- |
| `ga_front` | 282/480 [0.54,0.63] | — | — | — | — |
| `pars1000` | 293/480 [0.57,0.65] | 236 | 46 | 57 | **0.32** |
| `pars1e4` | 289/480 [0.56,0.64] | 195 | 87 | 94 | **0.66** |

and on the second reference of §3.5.2, 480 seeds at its own budget, `pars1000` is 308/480 against
306/480 (p = 0.92). **At 120 seeds `pars1000` was 77/120 against 65/120 — the same counts, the
same control and the same p = 0.03 as the two-island arm of §3.4.4 that 480 seeds also demoted.**
Twice now this round has produced a 77-against-65 that did not survive. The number to remember is
not 77; it is that a 120-seed ladder of eight arms will hand one of them a p below 0.05 about
whenever it is asked to.

One reading survives, stated at the weight it deserves: the *fits-to-hit* sign test is marginally
in `pars1000`'s favour on both arenas (p = 0.048 and p = 0.029), in the same direction each time.
That is the test the benchmark's own README warns about — it drops every seed the two arms
disagreed on, which at an unsaturated budget is most of the signal — and the median difference it
reports is **zero fits**. It is not a reason to turn anything on.

`PARSIMONY_SCALING` stays 0 and the implementation stays in `discover.py`, which is a different
disposal from the islands of §3.4.4, deliberately. The islands were measurably *worse* and their
arm already owned its own generation loop, so moving them to `arms.py` cost nothing. The crowding
term is a keyword on `_tournament`; removing it would force the arm that records its rejection to
reimplement `_next_generation`, which is exactly what `arms.py`'s docstring says an arm may not
do. So it lives where `BREEDING_EXTRA` and `WARM_ACCEPT_FACTOR` live: a module constant whose
*value is the measurement*, off by default, reachable by the benchmarks and by nothing else.

#### 3.5.2 The mutation weights, and the second reference this round had never had

Nine weightings, the shipped tuple among them under another name as its own control. The first
120-seed pass on the 21,057-topology arena looked like a table of results — 78/120, 77, 75, 72
against the shipped 65, and 52 at the bottom. Escalated to 480 seeds, three of them survive:

| arm | retype / +series / +parallel / delete | hit @150 | McNemar p |
| --- | --- | --- | --- |
| `mut_ship` | 0.35 / 0.25 / 0.25 / 0.15 | 282/480 | — |
| `mut_par_hi` | 0.35 / **0.15** / **0.35** / 0.15 | **308/480** | **0.018** |
| `mut_series_hi` | 0.35 / **0.35** / **0.15** / 0.15 | **248/480** | **0.0012** |
| `mut_del_lo` | 0.39 / 0.28 / 0.28 / **0.05** | 316/480 | 0.017 |
| `mut_uniform` | 0.25 / 0.25 / 0.25 / 0.25 | 283/480 | 1.00 |

**Then look at what the arena's truth is.** `p(R1,C1)-p(R2,C2)-p(R3,C3)`: five of its six elements
are joined in parallel. The arm that wins is the one that inserts in parallel more often, the arm
that loses by a comparable margin is its mirror image, and the effect sits on the one axis of the
tuple that encodes *the shape of the circuit being looked for*. Every arena this round had built —
`land_rcl6`, `land_rcl7`, `land_rclcpe6` — freezes that same truth in a different space. **The
round had never once varied the shape of the answer**, which is exactly the confound that cannot
be seen from inside a single reference.

So a second reference was built: `C1-R1-L1-p(R2,C2)`, a capacitor with its ESR and ESL and one
interfacial block — `LARGE_REFERENCES[1]` with the CPE and the skin-effect element replaced by
their plain counterparts, which is the same physics in a pool small enough to enumerate. Four of
its five elements are in series where five of the Maxwell-Wagner's six are in parallel.
[measured] Fitting it to its own 1% data leaves 0/5 parameters unresolved and the worst parameter
deviation is 0.7%, so a failure there is a failure to find the topology rather than a truth the
data cannot support.

**[measured] The sign reverses, and both directions are significant.** 480 seeds,
`land_series_rcl6` (2,174 topologies, 23 targets, 40 fits — a budget calibrated to 64% so that
the arena still has somewhere to fail):

| arm | Maxwell-Wagner truth (parallel) | ESR/ESL + interface truth (series) |
| --- | --- | --- |
| `mut_ship` | 282/480 | 306/480 |
| `mut_par_hi` | **308/480, p = 0.018 better** | **281/480, p = 0.0001 worse** |
| `mut_series_hi` | **248/480, p = 0.0012 worse** | **319/480, p = 0.015 better** |

Which settles the question the sweep was asked. **The insert-series and insert-parallel weights
must stay equal, and that symmetry is now the one property of this tuple with a measurement behind
it.** Any asymmetric setting is a bet on the shape of the answer: it pays on truths of that shape
and costs about as much on truths of the other. The software is not allowed to make that bet — it
is the same thing as asking the user what kind of part this is, reached from inside the search
instead of from the CLI, and CLAUDE.md rules it out in the one place it is hardest to notice.

Two further readings, both smaller than they looked:

* *`mut_uniform` ties on both of these arenas* — 283/480 (p = 1.00) and 308/480 (p = 0.92) — and
  wins on the third of §3.5.3 (p = 0.0095). So the *level* of the shipped tuple, retype at 0.35
  rather than 0.25 and delete at 0.15 rather than 0.25, is not something these arenas can
  distinguish from choosing nothing at all. The tuple is not wrong; on this evidence it is
  arbitrary in every respect except its symmetry.
* *`mut_del_lo` is the one arm that never lost*, and it is still not taken. §3.5.3 is why, and it
  is a confound measured rather than a caveat left standing.

#### 3.5.3 The delete weight, and the confound both arenas shared

`mut_del_lo` cuts the delete weight from 0.15 to 0.05, and it was the one arm in the sweep that
never lost: 316/480 against 282 on the Maxwell-Wagner arena (p = 0.017) and 312/480 against 306
on the series one (p = 0.61). The obvious mechanism is that deleting is nearest to pure waste
when the truth is already as large as the search is allowed to go — and **both arenas are built
that way**, with truths at the element cap and one below it (6 of 6, 5 of 6). A weight tuned in
that regime is tuned to the arenas, which is the same mistake §3.5.2 had just caught on the other
axis of the same tuple.

So the regime was varied the cheapest way there is: **the same truth, the same pool, the same
data, the same budget — only the cap moves.** `land_series_rcl7` is the five-element series truth
enumerated to seven elements (11,033 topologies, 82 targets), so its truth sits *two* below the
cap instead of one.

**[measured] Three arenas, 480 seeds each, McNemar exact against the shipped tuple.**

| arm | Maxwell, cap 6 | series, cap 6 | series, cap 7 |
| --- | --- | --- | --- |
| `mut_ship` | 282/480 | 306/480 | 307/480 |
| `mut_del_lo` | 316/480, **p = 0.017** | 312/480, p = 0.61 | 321/480, p = 0.10 |
| `mut_uniform` | 283/480, p = 1.00 | 308/480, p = 0.92 | 330/480, **p = 0.0095** |
| `mut_par_hi` | 308/480, **p = 0.018** | 281/480, **p = 0.0001** | 289/480, **p = 0.0003** |
| `mut_series_hi` | 248/480, **p = 0.0012** | 319/480, **p = 0.015** | 337/480, **p < 0.0001** |

**Significant on one arena of three is what both remaining candidates are, and in opposite
places.** `mut_del_lo` wins on Maxwell and is flat on both series arenas; `mut_uniform` is flat on
Maxwell and both caps of the series truth except the widest, where it wins. Neither survives the
company it is in — the two arms that *are* real reverse their sign with the truth's shape and hold
it across the cap change, which is what an effect looks like here when there is one. So
`MUTATION_WEIGHTS` does not move, and the reason is on the record rather than in a preference.

One thing the third arena settles beyond the delete question: **the series/parallel reversal is
not an artefact of the small arena.** Raising the cap five-fold in topologies leaves both signs
and both p-values where they were. That is the finding §3.5.2 rests on, and it now rests on two
independent arenas rather than one.

## 4. Gates

- **EV1 — recovery above five elements.** On the three references of §3.1, `mode="evolve"`
  reports the truth or an exact equivalent within a stated wall-clock budget. Reported
  alongside: on-front and is-recommendation, which are strictly harder and tracked separately,
  exactly as G1 does. *The pass fraction and the budget are written from step 1's baseline run*
  (§3.1), and the run is now complete.

  **[measured] The baseline: 9 runs, three references × three seeds, 600 s each, one at a time
  on a quiet machine.**

  | reference | elem | truth reported | on the front | is the recommendation | topologies | min | best err |
  |---|---:|---:|---:|---:|---:|---:|---:|
  | three-block Maxwell-Wagner | 6 | **1/3** | 1/3 | 0/3 | 413–596 | 10.6–11.5 | 1.24–1.34% |
  | capacitor + interfacial block | 6 | **0/3** | 0/3 | 0/3 | 443–479 | 15.1–15.2 | 1.26–1.32% |
  | Randles + ESL + second block | 7 | **0/3** | 0/3 | 0/3 | 155–178 | 14.4–15.2 | 2.09–5.42% |
  | **all three** | | **1/9** | **1/9** | **0/9** | | | |

  Three things this settles, none of them comfortable.

  *The best relative error on every front is at or above the noise floor.* 1.24–1.34% against a
  1% floor on the six-element references — the search finds circuits that describe the data and
  they are not the truth, which is a search problem and not a fitting one. On Randles it is
  worse than that: 2.09%, 3.20% and 5.42% against a ~1.3% floor, so on the seven-element
  reference the search does not even return a *good fit*, let alone the right topology.

  *The failure is worst exactly where the search is slowest.* Randles evaluated 155–178
  topologies in fifteen minutes — 5.4 s each, against 1.3 s on the six-element Maxwell-Wagner
  — and got through **5–6 generations** of a population of 40. A genetic search that completes
  six generations has barely started; what EV1 measures there is mostly the random initial
  population. This is what step 3 aims at, and it is why the per-topology cost is the first
  thing to attack rather than the operators.

  *§1.4's defect was systematic rather than incidental*: **23 of 28 reported front rows (82%)**
  carried screening-grade numbers in the pre-step-2 half of this baseline, against the 3/4 one
  run had suggested. Every run since step 2 reports **0** such rows, over 36 further front rows.

  **The bar EV1 gets, written from that.** A pass fraction of "the truth in *N* of 10 seeds"
  cannot be written from a baseline of 1/9 without inventing *N*, and this project does not
  invent thresholds — so EV1 is a **ratchet plus a ceiling**, both of them measured:

  - *Ratchet.* On the same three references, the same seeds and the same 600 s budget, no step
    of this plan may report fewer than **1/9 truth-reported, 1/9 on-front, 0/9 recommended**.
    Steps 3–5 are changes to a search that is nearly blind here; the one thing they must not do
    is make it blinder while looking faster.
  - *Ceiling.* **The baseline's 1/9 is also the largest claim this project may make for
    `mode="auto"` above five elements** — a number that moves only when a measurement moves it,
    and it has: see the step-4 reading below, which raises the ceiling to **6/9 reported and 3/9
    recommended**. The shape of the rule does not change with the number. The exhaustive stage
    passes G1 30/30; the fallback it hands off to now recovers six truths in nine and recommends
    three. Those two must never be reported as one capability, and §6's clause — that the honest
    outcome may be for `auto` to report an under-fitted exhaustive front rather than hand off at
    all — stays live, because one of the three references is still 0/3.

  **[measured] Step 4's first half — the bounded breeding pool — on the same three references,
  the same seeds 0–2 and the same 600 s.**

  | reference | elem | truth reported | on the front | is the recommendation | topologies | min | best err |
  |---|---:|---:|---:|---:|---:|---:|---:|
  | three-block Maxwell-Wagner | 6 | **3/3** | 3/3 | 3/3 | 541–594 | 3.7–4.5 | 1.24–1.34% |
  | capacitor + interfacial block | 6 | **3/3** | 1/3 | 0/3 | 648–734 | 5.3–11.7 | 1.25–1.33% |
  | Randles + ESL + second block | 7 | **0/3** | 0/3 | 0/3 | 725–737 | 11.4–12.4 | 1.24–1.65% |
  | **all three** | | **6/9** | **4/9** | **3/9** | | | |

  **The ratchet holds on all three of its clauses** (1/9, 1/9, 0/9 floors) and every one of them
  rises. Against the nearest same-code control — the interleaved `warm on` arm of EV3's ratchet
  check, which is this search one step earlier on these exact references and seeds — reported
  goes **3/9 → 6/9**, on-front **1/9 → 4/9**, recommended **1/9 → 3/9**. The capacitor reference
  went 0/3 → 3/3 reported, and its own note in `LARGE_REFERENCES` predicted exactly the shape it
  now has: reported without being recommended, because a 10 mΩ ESR at 1% noise is a parameter
  the parsimony rule is right to decline.

  **Two things this run may not be read as saying.** It was **not interleaved against a same-day
  control**, and the budget is wall-clock on a machine §4 measures as drifting by a factor of two
  within an hour — so the recovery counts stand (they are absolute floors, which is why the bar
  was written as absolute floors) while *topologies evaluated* and *minutes* are indicative only.
  The gate-grade comparative evidence for this change is not here at all: it is
  `docs/SEARCH_ALGORITHM_SCREENING.md` §5's 120 seeds counted in **fits**, where the arms cannot
  measure the machine. And Randles is still **0/3** — its best relative error improved from
  2.09–5.42% to 1.24–1.65%, so the search now returns a *good fit* of the wrong topology where it
  used to return neither, but on the seven-element reference the truth is still not found.

  Step 2 moved the quantity EV1 measures, which is why the two halves of the baseline are
  comparable at all: reporting tier-2 only makes `reported` a claim about the *refitted* list,
  which is strictly smaller than the archive the first runs counted over. That was a reason to
  expect step 2 to cost recovery. **[measured] It does not.** Controlled before/after, same
  reference, same 2 seeds, same 120 s budget, the only difference being `discover.py` stashed
  or current:

  | | before step 2 | after step 2 |
  |---|---:|---:|
  | truth reported | 1/2 | 1/2 |
  | on the Pareto front | 1/2 | 1/2 |
  | it is the recommendation | 1/2 | 1/2 |
  | **tier-1 rows reported** | **12/15 (80%)** | **0/6** |
  | mean topologies evaluated | 126 | 136 |
  | mean minutes | 3.3 | 3.0 |

  Recovery is unchanged, provenance is fixed, and the run is no slower. What did change is the
  *size* of the report — the fronts went 7→2 and 8→4 rows. Fewer rows, all of them publishable,
  is the trade this step was for. Note also that the seed-1 hit is an **exact equivalent**
  (`p(C1,p(CPE1-R1,C2,R2)-R3)`) rather than the truth's own canonical form, which is the case
  §3.1 says `_truth_verdict` would have scored as a failure.
- **EV5 — nothing else moved.** **[measured] PASSES, re-measured after step 3.** An
  exhaustive-mode fingerprint (every candidate's circuit, AICc, reduced χ² and relative error to
  12 figures, the restart count, the Pareto front, the equivalence classes, the coverage
  sentence and the recommendation, over three references) is **byte-identical** before and
  after, captured by running the same probe against the stashed and the current sources. Step 3
  touched `fit.py` as well as `discover.py` — `LocalBudget` names two settings that were
  duplicated literals — so this run is what says the publication path's numbers did not move a
  digit. This is what
  caught the lost tiebreak in §3.2.1; the test suite passed with that bug in place.
  **Re-measured after the refit-order fix, and the probe is now committed** as
  `benchmarks/ev5_fingerprint.py` rather than being rebuilt by hand each time: three references,
  `mode="exhaustive"` and `mode="auto"`, `exhaustive_limit=4`, every float at `repr` precision
  and every clock stripped — 486,846 bytes, **byte-identical** between `HEAD`'s sources and the
  changed ones.

  **[measured] Re-run after step 5: 487,364 bytes, byte-identical.** Step 5 edits `mutate`,
  `_tournament` and `_next_generation`, none of which the exhaustive path calls — but that is the
  argument, not the evidence, and the argument is exactly the kind §3.2.1 records the test suite
  agreeing with while a bug was in place. A second fingerprint, cheaper than the reasoning, says
  the publication path did not move a digit. (The evolve path has its own check and it is
  sharper: `arms.py --arms ga_front` over 120 seeds returns the same 65/120, the same median of
  113 fits, the same best AICc of −1676.14 and the same size histogram before and after, which
  is what says the operator refactor changed no behaviour at the shipped defaults.) Identity across two separate processes also re-establishes that the publication
  path is deterministic at `workers=4`, which the comparison silently depends on.
- **EV2 — provenance.** Every candidate in `DiscoveryResult.candidates` and `.pareto` from
  `mode="evolve"` was refit at full budget. A test, not an inspection: it asserts on the
  returned object, so the §1.4 table cannot come back. **Two tests were added to it in the same
  shape** (`test_the_refit_order_takes_the_best_of_every_size_before_any_size_twice`,
  `test_a_refit_stopped_by_its_deadline_still_reports_the_best_candidate`), for §3.2.1's fourth
  bullet: an expired deadline makes tier 2 exactly one fit long, and *which* topology that is is
  the whole question. Both were shown to fail against the code they replace.
  **[measured] PASSES.** Re-running §1.4's exact case: tier-1 rows on the front **0/5, was 3/4**;
  all 34 reported candidates at `n_restarts=5`. The front also *gained* a row — a four-element
  `p(CPE1-W1,R1-C1)` that the old top-8-by-score shortlist never refitted — which is the per-size
  quota doing what §5.1 of `DISCOVERY_V2_PLAN.md` says it is for. Worth recording precisely
  because of what did **not** change: the three formerly tier-1 rows came back with the *same*
  AICc to two decimals (−172.95, −433.84, −660.03). On this run the old numbers happened to be
  right, and nothing in the report could have said so. That is the argument for the fix, not
  against it.
- **EV3 — the warm start pays, two-sided.** At equal wall-clock and equal seed, distinct
  topologies evaluated goes up, **and** EV1's recovery fraction does not go down. Either half
  alone fails the gate.

  **[measured] PASSES, on both halves.** Three-block Maxwell-Wagner, **10 seeds**, 600 s each,
  the two arms interleaved seed by seed, `warm_accept=0` being the search exactly as it was
  before step 3:

  | | warm off (control) | warm on |
  |---|---:|---:|
  | truth reported | 3/10 | **6/10** |
  | on the Pareto front | 3/10 | **4/10** |
  | it is the recommendation | 2/10 | **4/10** |
  | mean topologies evaluated | 550 | **709** (up in **9/10** paired seeds, +32%) |
  | mean wall-clock | 12.8 min | **5.2 min** |
  | runs that hit the 30-generation cap | 2/10 | **10/10** |

  The speed half is met on the whole set of six paired runs across all three references as well
  (+89%, up in 6/6), where the gain is largest exactly where the search was worst: Randles went
  161 → 627 and 270 → 849 topologies, +289% and +214%.

  **Two things about how this gate was nearly misread, both worth more than the result.**

  *The first measurement said it failed, and the reason was a defect rather than the idea.*
  +7% topologies with three of six pairs *slower*, and on-front 1/6 → 0/6. §3.3.1 has the
  cause: the polish was running at the publication local budget inside a screen, and its tail
  cost as much as the global search it replaced. A one-sided reading would have shipped a
  17-second polish as a speed-up; a "the idea does not work" reading would have deleted the
  step. Both were wrong, and only measuring *why* separated them.

  *The second measurement said it failed on a statistic that could not resolve it.* After the
  fix, six paired runs still gave on-front 1/6 → 0/6 — and that is one event against zero,
  across three references at two seeds each. The bar it violated is the ratchet written from
  EV1's own 1/9 baseline, so the honest response was neither to declare a pass nor to rewrite
  the bar, but to say that a bar built on single events cannot decide this and to run the seeds
  that would. Ten seeds on the one reference that recovers anything reversed the sign on every
  count. **A gate that fails on a statistic with no resolving power has not been failed; it has
  not been measured.** Reaching for the seeds rather than for the wording is what separates that
  from the failure `WEB_UI_PLAN.md` §2.5 records.

  **The ratchet, checked on its own set.** EV1's bar is written over the baseline's three
  references at seeds 0-2, so it is closed there rather than by extrapolation from the ten-seed
  run. [measured] warm off → warm on: reported **1/9 → 3/9**, on-front **1/9 → 1/9**,
  recommendation **1/9 → 1/9**, topologies **434 → 751 (up in 9/9 pairs, +117%)**, wall-clock
  14.0 → 8.7 min. Nothing fell.

  One thing that measurement makes plain, and which matters for every future comparison here:
  **the interleaved control is not identical to the baseline in §4's table** — it recommends 1/9
  where the baseline recommended 0/9, on the same code, because `warm_accept=0` is a
  behaviourally exact restoration of the pre-step-3 search but the *budget is wall-clock*. Two
  runs of the same search on the same seed evaluate different numbers of topologies depending on
  what else the machine was doing. So a step is compared against a control run beside it, never
  against a number recorded on another day; that is what the seed-by-seed interleaving is for,
  and it is why the baseline in §4 is a description of the search rather than a fixed point to
  diff against.

  **What the pass exposes next.** All ten warm runs hit the **30-generation cap in 5.2 minutes**,
  leaving more than half of a 600 s budget unspent — so the genetic search is no longer bounded
  by fitting time but by `generations`, a default nobody has measured. Step 4 changes what a
  generation *is* (bounded pool, islands), and it would be measured against a search that stops
  early for an unrelated reason. Raise the cap, or measure it, before EV4.
- **EV4 — diversity.** Per-generation cache-hit rate does not rise across a run, and the
  best-known candidate's probability of entering a tournament does not fall with generation
  number. EV1 must not regress.

  **[measured] Step 4's first half meets the second clause and the third, and FAILS the first.**
  `benchmarks/ev4_diversity.py`, three-block Maxwell-Wagner, seeds 0–2, 600 s, the two arms
  interleaved seed by seed with the control produced by neutralising `_breeding_pool` rather
  than by an older copy of the code. The hit rate is the mean of the first third of the
  generations against the mean of the last third:

  | arm | hit rate | set bred from | P(best enters a tournament) | unique topologies |
  |---|---|---|---|---|
  | unbounded (control) | 39→46, 38→42, 37→43 (**+5.7 pt**) | 25–32 → **596–636** | 0.091–0.115 → **0.005** | 692, 717, 722 |
  | bounded | 38→67, 39→67, 38→60 (**+26.3 pt**) | 25–32 → **45–46** | 0.091–0.115 → **0.065** | 541, 562, 594 |

  *Clause 2 passes by a factor of 13* — §1.2's decay is what this step was for, and at the end of
  a run the best-known candidate is 13x likelier to be drawn into a tournament than it was.
  *Clause 3 passes:* EV1 rose on all three counts (above). *Clause 1 fails:* two thirds of the
  bounded arm's late proposals are topologies it has already fitted, against a control that
  reaches 42–46%.

  **Two things that measurement says which are not in the clause, and neither is a reason to
  reword it.** The **control fails clause 1 as well** — every unbounded run also rises, by
  5.7 points — so "does not rise" was already unmet by the search this plan started from, and it
  cannot be a bar that only the new code has to clear. And the **outcome the clause is a proxy
  for moved the other way**: the bounded arm fits fewer distinct topologies (541–594 against
  692–722) and recovers the truth far more often (EV1 3/3 against a control of 1/3 on this same
  reference). Re-proposal under a bounded pool is refinement — the cache is best-wins, so a
  second visit improves that topology's fit — rather than the stall the clause assumes. The
  counts also still vary with the seed, so nothing has closed one neighbourhood and stopped.

  **So this step ships with EV4 open, and says so.** The clause is not withdrawn and not
  reinterpreted: it is recorded as failed, with the two measurements above beside it. One of the
  two remedies this paragraph named has since been measured and removed (islands, §3.4.4); the
  other is step 5. What a future session must not do is rewrite the clause to something the build
  already does; what it may do is measure whether a *cheap* re-proposal is a cost at all, which
  this run suggests and does not establish (541 fits in 5.5 min against 692 in 7.1).

  **[measured] Step 5 was the second remedy and it is not one either. EV4 clauses 1 and 2 stay
  open.** Adaptive parsimony is the mechanism that would have addressed clause 1 most directly —
  it exists in PySR to keep every complexity level populated, which is precisely what a 92%
  first-third hit rate says is not happening — and §3.5.1 measures it as doing nothing at any
  scaling that is not the degenerate limit, over 480 seeds on two references. The mutation-weight
  sweep does not touch either clause. So both remedies this plan named have now been built and
  measured, and neither moved the two clauses; what is left is the question §3.4.4 raised and
  did not answer, whether a re-proposal under a best-wins cache is a cost at all. **Nothing here
  licenses closing the clauses**, and the reason to say so plainly is that the search that fails
  them is also the search that passes clause 3 by the widest margin this plan has recorded.

  **[measured] Re-run for the front-only pool of §3.4.3, and it fails a second clause.** Three
  arms, three seeds, 600 s each, interleaved, generation cap 1000 so that the clock is what runs
  out. (**A first attempt was discarded rather than reported**, for the reason the paragraph
  above this one had already given: all 27 runs stopped at the 30-generation cap well inside
  their 600 s, so the arms shared a *generation count* and not a budget — and since the arms
  differ in what a generation costs, the shipped arm looked cheaper only because it had been
  handed less to do. Nothing from that run is quoted anywhere as a result.)

  | arm | generations | topologies evaluated | hit rate, first third → last | P(best enters a tournament) |
  |---|---|---|---|---|
  | unbounded | 117 | 2,473 | 41.7% → 51.7% (**+10.0 pt**) | 0.0139 → 0.0017 (**÷8.3**) |
  | bounded (front + 40) | 211 | 1,564 | 65.7% → 91.7% (**+26.0 pt**) | 0.0654 → 0.0635 (÷1.03) |
  | front (ships) | 479 | 1,039 | 92.3% → 95.3% (**+3.0 pt**) | 0.3763 → 0.2750 (**÷1.37**) |

  *Clause 1 fails for all three arms*, the front arm by the smallest margin of the three — and
  that number is not the good news it looks like, because its hit rate is **92% in the first
  third**. There is no room left to rise. The front arm re-proposes what it knows from the very
  first generations, which is the concentration clause 1 was written to detect, arriving so
  early that the clause's *shape* test cannot see it.

  *Clause 2 now fails too, and it passed for the rule this replaces.* This is the one to state
  plainly rather than soften: the shipped arm's P(best) falls by 1.37x across a run where the
  previous rule's was flat. What the clause was written to catch is nonetheless absent — §1.2's
  mechanism is an archive that grows without bound, and the unbounded arm shows it at ÷8.3 with
  N reaching 2,104. The front arm's N goes **5 → 10**, which is the front acquiring one more
  complexity level, and it falls *from a level 4–6x higher than the arm that passes*. The clause
  is not reworded to say that. It is recorded as failed with the mechanism beside it, and the
  reason the step ships anyway is clause 3.

  *Clause 3 passes, on the comparison that has a same-day control.* [measured] EV1's ratchet,
  `evolve-gate --breeding-extra 40,0`, three references x seeds 0–2, 600 s each, arms
  interleaved seed by seed:

  | | front + 40 | **front (ships)** |
  |---|---|---|
  | three-block Maxwell-Wagner | 2/3 reported, 2/3 on-front, 2/3 recommended | **3/3, 3/3, 3/3** |
  | capacitor + interfacial | 2/3, 1/3, 0/3 | 2/3, **2/3**, 0/3 |
  | Randles + ESL | 0/3, 0/3, 0/3 | 0/3, 0/3, 0/3 |
  | **total** | 4/9, 3/9, 2/9 | **5/9, 5/9, 3/9** |
  | mean topologies evaluated | 1,675 / 2,073 / 961 | 1,115 / 1,430 / 1,022 |

  Both arms clear EV1's floors of 1/9, 1/9, 0/9, and the shipped arm is ahead of its own
  interleaved control on every one of the three counts. **It is ahead while fitting a third
  fewer distinct topologies**, which is the same finding as the bounded pool's and one step
  further along: under a best-wins cache a re-proposal is a refit of a known topology, and 479
  generations of that beat 211 generations of breadth. Two things this table is *not*: it is not
  a comparison against the 6/9 recorded in `docs/HANDOFF.md` §25, which was measured at the
  30-generation cap and without a control (that section says so); and 4/9 against 5/9 on nine
  runs is not a significant difference — the claim EV1 licenses is **no regression**, which is
  what its bar was written as.
  (EV5 is stated above, next to the baseline it corrects.) Its full form: `mode="exhaustive"`
  and `mode="auto"` below the fallback threshold produce identical results for a fixed seed
  before and after every step; the full test suite stays green; `npm run check` is untouched
  because no browser path uses evolve. This replaces the withdrawn G5.

## 5. Work order

| step | contents | size | depends on | status |
|------|----------|------|-----------|--------|
| 1 | 6–7 element references + `evolve-gate` benchmark mode; run it; write EV1's bar from the result | M | — | **done, baseline partial** — mode and references landed and measured; 4 of 9 runs completed before the machine stopped them twice (§4) |
| 2 | tier-2-only reporting in `_evolve`; shared per-size quota helper; `REFINE_DEFAULT["evolve"]`; EV2 test; withdraw G5 in `DISCOVERY_V2_PLAN.md` | M | 1 | **done** — EV2 and EV5 both measured; see §3.2.1. **Reopened once**: the deadline this step added had no refit *order* behind it and lost a first-ranked candidate (§3.2.1, fourth bullet); fixed and re-gated |
| 3 | structural parameter inheritance, two-stage evaluation, best-wins cache; sweep `WARM_ACCEPT_FACTOR`; EV3 | L | 2 | **done** — EV3 passes both halves (§4); §3.3.1 records the polish budget that decided it, and the two readings that nearly got it wrong |
| 4 | bounded selection pool, scaled tournament, islands with shared cache; EV4 | M | 3 | **done, EV4 open on two clauses and saying so** — `_breeding_pool`: 120/120 against 87/120 (§3.4.1), and its *width* then measured down to zero, so what ships is the Pareto front alone (`BREEDING_EXTRA`, §3.4.3: 65/120 against 7/120 at an unsaturated budget). **Islands were built and removed** (§3.4.4): indistinguishable at two, significantly worse at four, far worse with migration off. The scaled tournament stays unmotivated once the pool is bounded. EV4's clause 1 fails for every arm and **clause 2 now fails for the shipped one**, both recorded rather than reworded; clause 3 passes with EV1 at 5/9, 5/9, 3/9 against an interleaved control's 4/9, 3/9, 2/9 (§4) |
| 5 | adaptive parsimony in selection only; mutation-weight sweep | M | 4 | **done, and neither default moved** — both built as specified and both measured (§3.5). Adaptive parsimony does nothing: the ladder is inert below scaling 300, unordered above it, and its best rung is 293/480 against 282/480 at p = 0.32 after looking like p = 0.03 at 120 seeds. The mutation sweep's two significant arms are the two that encode **the truth's shape**, which is what forced the round's first second reference (§3.5.2) and then a third to separate the delete weight from the element cap (§3.5.3). `PARSIMONY_SCALING = 0` and `MUTATION_WEIGHTS = (0.35, 0.25, 0.25, 0.15)` now carry the measurement that says so, and EV5 is byte-identical |
| 6 | docs: this file marked implemented with its corrections, `CLAUDE.md` "Start here" entry 10, `benchmarks/README.md`, `DISCOVERY_V2_PLAN.md` §4 G5 withdrawal note | S | 5 | planned |

Step 2 is severable and worth landing on its own even if 3–5 are never done: it is the only step
that fixes something wrong rather than something slow.

## 6. Risks

- **Step 3 changes what the fitness means.** Mitigated by ordering it after step 2 and by EV3
  being two-sided. This is the step most likely to look like a win on one reference and lose the
  answer on another — precisely the shape of `DISCOVERY_V2_PLAN.md` §3.3, where a 4× cheaper
  screen was free on the capacitor reference and dropped the Maxwell-Wagner truth to rank 19.
- **Step 2 makes evolve slower.** Real, and accepted: the alternative is a fast report that
  cannot say what its numbers are. The cost is measured and the default set from it, not assumed.
- **Scope creep into the exhaustive stage.** Forbidden by EV5, which is why EV5 pins bit-identical
  results rather than "no regressions".
- **The genetic search may simply not be the right instrument at 6–7 elements.** Possible, and
  step 1 is what would say so. If EV1's baseline is bad enough that steps 3–5 cannot plausibly
  close the gap, the honest outcome is to record the measurement and say `mode="auto"` should
  report an under-fitted exhaustive front rather than hand off to a search that does not work —
  a smaller claim, honestly made, in preference to a larger one nothing supports.
- **Pyodide and the browser.** Not affected; evolve is CLI-only. Any change that introduces
  `multiprocessing` into the evolve path would break that and is out of scope here.

## 7. Out of scope

- Replacing the genetic search with a different family (MCTS, Bayesian structure search,
  neural-guided proposal). Possibly the right long-term answer; not decidable before step 1.
- Any change to `_exhaustive` and the two-tier machinery, to DRT, to the skeleton mode, or to the
  Web UI.
- Parallelising the genetic search across processes.
- Exposing `mode="evolve"` in the browser.
