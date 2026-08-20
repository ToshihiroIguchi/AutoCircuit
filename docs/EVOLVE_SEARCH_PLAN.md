# The Genetic Search — Making the Fallback Answerable

Status: steps 1-2 implemented (2026-08-20); steps 3-6 planned. §3.2.1 records what step 2
needed that this plan did not specify, and §4 records EV1's baseline as far as it was measured.
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

### 3.4 Step 4 — bound the archive, and add islands

For §1.2 and §1.3, in that order of importance.

- **Bounded selection pool.** Breeding draws from a fixed-size population (current generation
  plus the Pareto-front elite, oldest evicted) rather than from the whole history. The
  `_Evaluator` cache stays global — dedup must not be thrown away with the archive.
- **Selection pressure held constant.** Tournament size scales with the pool
  (`max(3, round(TOURNAMENT_FRACTION * len(pool)))`) so that §1.2's 8.2× decay cannot recur if
  the pool size is later changed.
- **Islands.** `populations: int`, each with its own RNG stream derived from `seed`, exchanging a
  fraction of members per generation. Note one thing this port gets for free that PySR does not:
  the evaluator cache is shared across islands, so two islands converging on the same topology
  cost one fit, not two.

Measured target: cache-hit rate per generation stops rising, and EV1 does not regress. Both, not
either.

### 3.5 Step 5 — adaptive parsimony, and the mutation weights

Last, because they are tuning and the steps above are structure.

- **Adaptive parsimony.** PySR tracks how crowded each complexity level is and penalises the
  crowded ones, which is what keeps every complexity populated. `_next_generation` approximates
  this with Pareto elitism (`front[:max(2, population // 6)]`, `discover.py:2239`). Add a
  frequency term to the **selection** score only. It must never reach `Candidate.score`: the
  criterion the user chose is what ranks the report (`DiscoveryResult.criterion`), and a
  breeding heuristic that leaked into it would change the published ranking for a reason the
  report cannot state.
- **Mutation weights.** `[0.35, 0.25, 0.25, 0.15]` (`discover.py:864`) has no measurement behind
  it — the only constant in this module that carries no **[measured]** note. Sweep it in the
  benchmark and either justify it or replace it. A sweep that finds nothing is a result and gets
  written down as one.

## 4. Gates

- **EV1 — recovery above five elements.** On the three references of §3.1, `mode="evolve"`
  reports the truth or an exact equivalent, over 10 seeds, within a stated wall-clock budget.
  *The pass fraction and the budget are written from step 1's baseline run* (§3.1); until then
  EV1 is a measurement, not a bar. Reported alongside: on-front and is-recommendation, which are
  strictly harder and tracked separately, exactly as G1 does.

  **[measured, partial] The baseline ran 4 of its 9 runs before the machine stopped it, twice.**
  Three-block Maxwell-Wagner, 3 seeds, 600 s each: truth reported **1/3**, on the front 1/3, the
  recommendation **0/3**, 18–26 generations, 413–596 topologies, 10.6–11.5 min. Capacitor +
  interfacial block, seed 0 only: FAIL, recommending `p(CPE1,R1)-C1-SKINF1-SKINF2`. Randles is
  unmeasured. Two things the partial run already settles. The best relative error on every front
  was 1.24–1.34%, i.e. **at the 1% noise floor** — the search finds circuits that describe the
  data and they are not the truth, which is a search problem and not a fitting one. And §1.4's
  defect was systematic rather than incidental: **23 of 28 reported front rows (82%)** carried
  screening-grade numbers, against the 3/4 one run had suggested.

  **The bar cannot be written from a partial run**, and step 2 moved the quantity it measures:
  reporting tier-2 only makes `reported` a claim about the *refitted* list, which is strictly
  smaller than the archive the baseline counted over. That was a reason to expect step 2 to cost
  recovery. **[measured] It does not.** Controlled before/after, same reference, same 2 seeds,
  same 120 s budget, the only difference being `discover.py` stashed or current:

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
- **EV5 — nothing else moved.** **[measured] PASSES.** An exhaustive-mode fingerprint (every
  candidate's circuit, AICc and reduced χ² to 12 figures, the Pareto front, the equivalence
  classes, the coverage sentence) is **byte-identical** before and after the refactor, captured
  by running the same probe against the stashed and the current `discover.py`. This is what
  caught the lost tiebreak in §3.2.1; the test suite passed with that bug in place.
- **EV2 — provenance.** Every candidate in `DiscoveryResult.candidates` and `.pareto` from
  `mode="evolve"` was refit at full budget. A test, not an inspection: it asserts on the
  returned object, so the §1.4 table cannot come back.
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
- **EV4 — diversity.** Per-generation cache-hit rate does not rise across a run, and the
  best-known candidate's probability of entering a tournament does not fall with generation
  number. EV1 must not regress.
  (EV5 is stated above, next to the baseline it corrects.) Its full form: `mode="exhaustive"`
  and `mode="auto"` below the fallback threshold produce identical results for a fixed seed
  before and after every step; the full test suite stays green; `npm run check` is untouched
  because no browser path uses evolve. This replaces the withdrawn G5.

## 5. Work order

| step | contents | size | depends on | status |
|------|----------|------|-----------|--------|
| 1 | 6–7 element references + `evolve-gate` benchmark mode; run it; write EV1's bar from the result | M | — | **done, baseline partial** — mode and references landed and measured; 4 of 9 runs completed before the machine stopped them twice (§4) |
| 2 | tier-2-only reporting in `_evolve`; shared per-size quota helper; `REFINE_DEFAULT["evolve"]`; EV2 test; withdraw G5 in `DISCOVERY_V2_PLAN.md` | M | 1 | **done** — EV2 and EV5 both measured; see §3.2.1 |
| 3 | structural parameter inheritance, two-stage evaluation, best-wins cache; sweep `WARM_ACCEPT_FACTOR`; EV3 | L | 2 | planned |
| 4 | bounded selection pool, scaled tournament, islands with shared cache; EV4 | M | 3 | planned |
| 5 | adaptive parsimony in selection only; mutation-weight sweep | M | 4 | planned |
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
