# Non-hardware speedups for topology search

Twenty proposals for cutting the cost of `discover()` without adding compute (no GPUs, no more
workers, no cloud) were brainstormed against the finding in `docs/SEARCH_TIME_PLAN.md` and
`docs/EVOLVE_SEARCH_PLAN.md` that the genetic fallback (`_evolve`) and CPE-bearing screening are
the two largest single costs. This document records each idea's hypothesis, method, and measured
verdict, in the style of `SEARCH_TIME_PLAN.md`: nothing ships on a plausible story, only on a
number.

## 0. Reference circuits built for this round

`benchmarks/six_plus/truths.py`'s nine truths top out at four series Maxwell-Wagner blocks
(`par8`, 8 elements, in `benchmarks/six_plus/depth8.py`) and never characterise more than one
self-resonant frequency. `benchmarks/speedup/truths.py` adds seven more, admitted through the
same four-part screen (leverage, feasibility, zero unresolved parameters, <=50% value-matched
deviation) as `six_plus/truths.py`, with every value found by maximising the truth's weakest
leverage (`differential_evolution`) rather than hand-picked:

| id | circuit shape | elements | weakest leverage |
|---|---|---:|---:|
| `mw5` | 5 series Maxwell-Wagner blocks | 10 | 8.02% |
| `mw6` | 6 series Maxwell-Wagner blocks | 12 | 7.28% |
| `mw4cpe` | 4 blocks, 2 of them CPE instead of ideal C | 10 | 8.64% |
| `srf2` | 2 parallel-tank resonances, 3 decades apart | 6 | 10.00% |
| `srf2_close` | same shape, 1 decade apart | 6 | 9.99% |
| `srf3` | 3 parallel-tank resonances, 2 decades apart each | 9 | 9.94% |
| `srf3_close` | same shape, 1 decade apart each | 9 | 9.91% |

**Two design mistakes, caught before any speedup idea was measured against these truths, are
worth recording so they are not repeated.** First, a single fixed separation for the SRF truths
would have been the same trap `docs/TOPOLOGY_6PLUS_PLAN.md`'s X2 identifiability ladder was built
to catch -- a result tuned on one point in a design space is the answer written into the question
-- so each SRF shape got a `_far` and `_close` sibling instead of one point. Second, the first
version of the SRF tuner fixed each block's resonant frequency at a hand-picked round number
(e.g. `1e4 Hz`); measured, this was arbitrary in the same sense hand-picked R/C/L values are
arbitrary, and the *first* attempt at it (letting the leverage-only tuner place resonances
freely) independently failed by pushing `srf2`'s high block to 0.47 decades from the window's top
edge and `srf3`'s high block 0.07 decades *past* it -- outside the sweep entirely. The shipped
tuner (`tune_srf` in `benchmarks/speedup/truths.py`) fixes only the *separation* between
resonances (the one thing each experiment below is actually studying) and leaves the absolute
placement in the window, the characteristic impedance of each tank, and every resistance to the
same leverage-maximising search as everything else in this file.

Shared measurement instruments (Wilson CI, `Counted` NFE tracking, exact McNemar, byte-identical
`stable()`/`fingerprint()`) live in `benchmarks/speedup/harness.py`, reused from
`benchmarks/screening_round/param_opt.py`, `benchmarks/autoeis_round/score.py` and
`benchmarks/ev5_fingerprint.py` rather than re-implemented.

## Phase 1 -- analytic ideas, no discover.py control-flow change

### C -- CPE analytic warm-start (Q -> Z0 reparameterisation)

**Rejected.** [measured, `benchmarks/speedup/idea_c_cpe_warmstart.py`]

The hypothesis behind the original idea -- "CPE's Q is searched over an absurdly wide generic
prior, narrow it" -- was already false before anything was run: `ConstantPhaseElement.bounds()`
(`src/autocircuit/core/elements.py:230-236`) already derives Q's search interval from the data via
`BoundsContext`, as the union of the capacitive extreme (n->1) and resistive extreme (n->0). What
remained testable was narrower: that union is wider than either extreme alone, so reparameterising
CPE's magnitude from `Q` to `Z0 = |Z_CPE(omega_ref)|` (the impedance magnitude at the sweep's
geometric-mean frequency, recovered as `Q = 1/(Z0 * omega_ref**n)` before the real `_Problem` ever
sees it) should shrink the effective search box for any interior `n`.

It does shrink the box: 22.27 decades (as shipped) -> 11.99 decades (Z0 reparam) on `mw4cpe`. It
does not measurably help. At the production tier-1 screening budget (`SCREEN_POPSIZE=8`,
`SCREEN_MAXITER=40`) on `mw4cpe` (10 elements, 2 CPEs), hit rate against the best cost either arm
reached across 120 seeds was baseline 1/120 (Wilson 95% CI [0.1%, 4.6%]) vs reparam 3/120 ([0.9%,
7.1%]) -- overlapping CIs, not significant, and both close enough to zero that `mw4cpe` is simply
outside what this budget can screen at all regardless of CPE's box width. The pre-declared decision
rule ("ships only if NFE-to-basin is significantly lower with non-overlapping CIs") is not met.

**Also recorded because it is itself informative**: DE at a fixed `(popsize, maxiter)` never
terminates early on this topology (`tol=1e-4` is never reached before the iteration cap), so
"NFE-to-basin" collapsed to a constant 5248 for every run regardless of arm or outcome -- the
only thing that varied was whether the fixed budget landed in the basin at all. A future idea
that wants an NFE-based rather than a hit-rate-based comparison needs an optimizer with a real
early-stopping criterion, not `differential_evolution`'s default convergence tolerance.

### D -- decorrelated (tau, R) reparameterisation

**Rejected.** [measured, `benchmarks/speedup/idea_d_decorrelated_reparam.py`]

Searching `(log10(tau), log10(R))` per `p(R,C)` block instead of `(log10(R), log10(C))`, with
`tau` bounded by the already-existing `BoundsContext.tau()` (data-derived from the frequency
window alone) instead of `C`'s own `ctx.capacitance()` bound, barely narrows the box -- 18.50 ->
17.00 decades on `mw5`, 19.35 -> 17.00 on `mw6` (much less shrinkage than idea C's CPE
reparameterisation saw, because `ctx.capacitance()` and `ctx.tau()` are both already
frequency-window-derived and close in width). At the production tier-1 screening budget, 60 seeds
each: `mw5` 1/60 (baseline) vs 3/60 (reparam), `mw6` 0/60 vs 2/60 -- all Wilson 95% CIs overlap
heavily and both arms sit under 15% regardless. Same conclusion as idea C: `mw5`/`mw6` are simply
outside what a single tier-1 screening budget can reliably reach (consistent with the basin-lottery
finding `docs/TOPOLOGY_6PLUS_PLAN.md` already records for six-plus-element topologies), and
reparameterising a two-parameter block does not change that. Pre-declared decision rule
(non-overlapping CIs, no regression) not met.

**A pattern is now visible across C and D worth stating before more ideas of this family are
tried**: both are "shrink one dimension's search box" ideas, both produce a real, verifiable box
shrinkage, and neither moves the hit rate outside noise, because the actual bottleneck at 10-12
elements is not any single parameter's box width -- it is the combinatorics of getting *all*
10-12 free dimensions simultaneously into their respective narrow basins within a fixed small
DE budget. A box-width idea can only ever pay off if the box it shrinks is a *large fraction* of
the total search volume in log space; for one parameter out of ten, even nearly halving that one
dimension's width barely moves the joint volume.

### B -- Hankel/SVD (Loewner) order estimation

**Rejected.** [measured, `benchmarks/speedup/idea_b_hankel_order.py`]

Not the same experiment as `docs/TOPOLOGY_6PLUS_PLAN.md` (d)'s AAA/Loewner reconstruction attempt
-- this only asks for the *count* of significant Loewner-matrix singular values, not the poles
themselves, and was sanity-checked first on trivial order-1 and order-3 circuits (exactly 1 and
exactly 3 singular values clearly above the double-precision floor, respectively -- the method
implementation is correct).

Two independent failure modes, both measured:

1. **Fails even at zero noise on the Maxwell-Wagner shapes.** `mw5`/`mw6`'s parameter values were
   tuned to maximise *worst-case leverage* (a local, weighted sensitivity), which is a different
   quantity from *SVD magnitude share* (a global, unweighted one) -- and produces R/C values that
   differ by many orders of magnitude across blocks (e.g. `mw5`'s `R2.R=0.14` vs `R3.R=5.4e4`).
   The weak blocks' poles are numerically invisible in the Loewner matrix's singular values even
   with exact, noise-free data: `mw5` (true order 5) shows only 4 singular values above the
   double-precision floor, `mw6` (true order 6) shows only 3. The resonant `srf*` truths do not
   have this problem at zero noise (correct order recovered 1/1 on all four), because a tank
   block's resonance peak contributes comparably to the SVD regardless of block-to-block scale.
2. **Fails at any nonzero noise level, on every truth, both shapes.** At the project's standard
   cell (1% noise, 10 points/decade) every truth scored 0/10 on both estimators except one
   incidental 3/10 (`srf3_close`, threshold estimator) -- indistinguishable from chance given the
   small sample. This reproduces, for the coarser order-only question, the exact "exact without
   noise and useless with noise" pattern `docs/TOPOLOGY_6PLUS_PLAN.md` (d) already measured for
   full reconstruction.

Pre-declared decision rule (correct order on a clear majority of truths at the standard cell) is
not met by either estimator. **Idea B is rejected outright**, not merely "not yet good enough":
failure mode 1 means it would also mis-count on exactly the composite, unevenly-scaled spectra
`docs/POOL_FROM_SPECTRUM_PLAN.md` §5 already flags as the realistic, hard case for any
shape-from-spectrum detector in this project.

### A -- algebraic equivalence-class dedup

**Confirmed as a proof of concept; full generalisation not built.**
[measured, `benchmarks/speedup/idea_a_algebraic_equivalence.py`]

`R1-p(R2,C1)` and `p(R1,C1-R2)` do **not** compute the same impedance for the same (R1,R2,C1) --
direct algebra shows different DC/HF limits and pole location as functions of the raw parameters.
What makes them an "equivalence class" is that both are universal realisations of the same
3-parameter family of first-order positive-real impedances (DC value, HF value, pole frequency),
so there is an exact, closed-form reparameterisation between them:

```
R1' = R1 + R2
R2' = R1*(R1+R2)/R2
C1' = R2**2 * C1 / (R1+R2)**2
```

Test 1 confirmed this is an exact algebraic identity, not a fitted coincidence (worst relative
error 5.8e-16 over 200 random-parameter, random-frequency trials -- floating-point noise, not a
real discrepancy). Test 2 asked the real question: fit `R1-p(R2,C1)` with the production `fit()`,
apply the closed form, and compare the prediction against an *independent* full `fit()` of
`p(R1,C1-R2)` on the same noisy data. Across 10 noise seeds, the predicted and independently
fitted parameters agreed to **0.000%** (the closed form's output and the independent optimum are
identical to the digits printed). The pre-declared decision rule (<=1% on every parameter) is met
with enormous margin.

**What this proves and what it does not.** For this specific structural pair, the second
topology's entire fit -- both tier-1 screen and tier-2 refit -- is provably redundant computation:
its answer is one closed-form evaluation away from the first topology's own fit, at zero
optimisation cost. This is a real instance of the >=4x same-cost duplication
`docs/SEARCH_TIME_PLAN.md` section 3.4 already measured across whole landscape tables. It does
**not** generalise automatically: this closed form was derived by hand for one specific pair of
first-order topologies, and a production dedup mechanism would need either (a) a cataloged rewrite
rule for every structurally-dual pair at every element count the pool can produce, or (b) a general
symbolic engine that derives such maps automatically from the tree structure. Neither was built --
that is a substantially larger project (network-theory rewrite rules or true computer algebra,
this repository's `numpy`+`scipy`-only rule notwithstanding for anything shipped in
`autocircuit.core`) than proving the mechanism works on one pair. Recorded as: **mechanism
confirmed, worth a follow-on project scoped around cataloguing first- and second-order rewrite
rules; not something this round can respond to with a shippable change.**

### A2 -- generalising idea A via Foster/Cauer duality

**Passes its three pre-declared checks at order 5-6 -- one order-N transform instead of a
per-pair catalogue, though "confirmed" should be read narrowly: see what each step actually
showed, including a mischaracterisation this section originally made and then corrected.**
[measured, `benchmarks/speedup/idea_a2_foster_cauer.py`]

Idea A's pair is not a star-delta (Y-delta) special case, the first hypothesis this round tried:
Y-delta is a 3-terminal identity and this project's `Node` grammar
(`src/autocircuit/core/circuit.py`, `ElementNode | Series | Parallel`) is strictly 2-terminal and
cannot represent one, and direct algebra confirms no 2-terminal reduction of a genuine Y-delta
identity reproduces idea A's actual pair. What the pair actually is: the classical
**Foster-form/Cauer-ladder duality** of a positive-real RC impedance function -- matching DC
value, HF value and pole frequency (idea A's own derivation) is the textbook statement that one
rational impedance has two canonical ladder syntheses, and this generalises to order N via
continued-fraction expansion of the numerator/denominator polynomials -- pure linear algebra, no
computer-algebra engine, consistent with `CLAUDE.md`'s `numpy`+`scipy`-only rule. `mw5`/`mw6`
(`benchmarks/speedup/truths.py`) are already exactly this Foster form (a sum of parallel-RC
blocks in series, no series R0/C0 term).

**Step 1 (element-count parity) passed at every order tested, 2 through 6** -- worked out by
hand for order 2 first (see the module docstring), then confirmed programmatically: the
transform's ladder always uses exactly N resistors and N capacitors, matching Foster's own count,
so the pair stays inside the same enumeration level `docs/SEARCH_TIME_PLAN.md` section 3.4's
same-size duplication is about.

**Step 2 found a real bug, and the first write-up of it here overstated what the bug was.** A
first implementation looped forever and was killed after two-plus hours. The original text in
this section attributed that to "`mw5`'s actual tuned values, orders-of-magnitude skewed by
construction" and drew a parallel to idea B's SVD failure on the same truths -- **that
attribution was never actually checked before being written down, and re-checking it afterward
shows it is wrong on both counts.** Re-running the unfixed loop with a hard safety cap (for
diagnosis only) shows: `mw5`'s real values converge in 4 iterations with no problem at all;
`mw6`'s do hang, but so does roughly half of an ordinary batch of *random, mildly-varying* test
draws having nothing to do with `mw5`/`mw6` -- 1/20 trials at order 2, 6/20 at order 3, 14/20 at
order 5, 12/20 at order 6, including a order-2 case whose values differ by only 36x and 61x (not
the 1e5-1e6-scale skew `mw5`/`mw6` were built with). The likely first failure in the original
2-hour run was one of these ordinary order-2 draws, encountered in the first few minutes, not
`mw5`/`mw6` at all. The actual mechanism has nothing to do with dynamic range: `np.trim_zeros`
only strips coefficients that are *exactly* `0.0`, and a polynomial subtraction designed to
cancel a leading term algebraically almost never lands on exactly `0.0` in floating point --
so the length of the array essentially never shrinks, `while len(den) > 2` essentially never
sees its exit condition, and enough accumulated iterations eventually overflow to inf/nan on top
of that. This is an ordinary control-flow bug (relying on exact equality with a float), not a
demonstrated numerical-conditioning weakness under wide dynamic range -- the comparison to idea
B's finding was a false analogy and is withdrawn. The fix is structural regardless of the cause:
replace the degree check with a hard iteration bound (this recursion needs exactly `n-1`
extraction steps *by construction*, so a loop counter decides when to stop, not a runtime check
of the data), and raise immediately on any non-finite intermediate value. With that fix, the
transform ran correctly on every case tried, `mw5`/`mw6` included: worst algebraic-identity
relative error 9.4e-16 on random draws at orders 2/3/5/6, and 6.5e-16 / 6.9e-16 on `mw5`/`mw6`'s
actual values. That is a real, useful number, but it should be read as "no problem was observed
on the cases tried" rather than "wide dynamic range was tested and shown safe" -- the tests run
do not isolate conditioning from the (now-fixed) control-flow bug, since fixing the loop bound
was necessary before conditioning could even be measured cleanly.

**Step 3 also produced a false alarm, and here the diagnosis holds up.** The originally-planned
test -- compare the transform's predicted Cauer-ladder parameters against an *independent*
from-scratch `fit()` of that same topology, the same method idea A's own Test 2 used -- showed
enormous disagreement on 2 of 10 seed/truth combinations (`mw5` seed 4: 5,719,285%; `mw6` seed 0:
2935%) while the other 8 agreed to 0.000%. Direct diagnosis (evaluating the *predicted*
parameters' own `relative_error` against the data, bypassing the independent fit) showed the
transform's prediction matches the original Foster fit's `relative_error` to every reported digit
in **both** flagged cases (`mw5` seed 4: 0.0142071 vs 0.0142071; `mw6` seed 0: 0.0135492 vs
0.0135492) while the *independent* fit of the identical topology landed on a far worse
`relative_error` (0.335 and 0.276). This part of the diagnosis is solid -- it does not merely
repeat step 2's algebraic-identity number, since it independently re-evaluates the predicted
parameters against the data through `Circuit.parse`'s own DSL round trip and caught a real,
separate bug on the way (an `omega`-in-Hz-instead-of-rad/s mistake in the first version of this
diagnostic, `Circuit.impedance`'s documented convention). The two flagged seeds are `fit()`'s own
from-scratch global search missing the optimum for a 10-12-parameter Cauer-ladder circuit -- the
same basin-lottery phenomenon `docs/TOPOLOGY_6PLUS_PLAN.md` already documents extensively for
six-plus-element topologies, here affecting the *test instrument* (an independent fit used as a
check) rather than the transform. The test was rebuilt around `relative_error` comparison, which
this failure mode cannot corrupt; by that measure the worst gap across all 10 combinations is
0.0000%. One consequence worth stating plainly rather than as a "bonus": since production use of
this transform would derive the second topology's parameters instead of independently fitting
it, it cannot inherit this specific failure mode of `fit()` -- not because the transform is
inherently more reliable in some general sense, but because it skips the step where that failure
happens.

**All three steps clear their pre-declared bar, with the two corrections above now on the
record.**

**Idea A2 overall: mechanism confirmed correct (Phase 1); no worthwhile `discover()` speedup
found (Phase 2); not shipped.** An earlier draft of this section, on seeing a disappointing
speed result, quietly substituted a different goal ("report completeness" instead of speed)
without saying so -- the user correctly rejected this. What follows is the speed question this
idea was scoped to answer, measured directly.

**Frozen-table confirmation, finished across all four `(R,C,L)` tables.** The `K=1,2,3` pairs
(2, 4, 6 elements -- the only orders reachable at `n_max<=7`) were checked on
`land_rcl6.json`/`land_rcl7.json` (built from a Foster-shaped truth) and
`land_series_rcl6.json`/`land_series_rcl7.json` (built from a non-Foster truth, `C1-R1-L1-p(R2,C2)`).
`K=1` and `K=2` match to 10+ significant figures on all four tables. `K=3` matches on
`land_rcl6/7.json` (0.016560247835634544 vs 0.016560247835634697) but **not** on
`land_series_rcl6/7.json` (20.500061628417477 vs 24.49508599702527, ~19% apart) -- the most
likely explanation is tier-1 screening's own already-documented basin lottery (these tables
store single-seed screening costs, not refit costs, and a 19% gap is well inside the range that
lottery is already known to produce), not a failure of the algebraic identity itself, which
Phase 1 verified directly at machine precision on both shapes. Same-cost clustering at `n=6`
(rtol 1e-6) finds 453 distinct clusters among 1725 rows -- the confirmed pair is 1 of 453
(~0.2%), consistent with (not contradicted by) the wall-clock number below.

**The speed question, measured directly rather than projected.** `K=1`/`K=2` sit inside the
*default* exhaustive limit of 5 elements (`DEFAULT_EXHAUSTIVE_LIMIT`, `discover.py`), so both
members of each pair are independently screened and refit on *every* default `discover()` call
with `R`,`C` in the pool -- guaranteed, not probabilistic. Timed directly: a full default-pool
(`R,C,L,CPE`) exhaustive run at `n<=5` (2976 candidates) takes 152.9s; screening plus fully
refitting just the one `K=2` Cauer-dual candidate a pattern-detector could skip costs
0.02s + 0.84s = 0.86s -- **about 0.56% of the total run**. Adding `K=1` does not change the
order of magnitude. This is far below every bar this document has used to decide something is
worth shipping (idea 2c's 33.6% was itself only "recommended for a follow-on," not yet shipped;
everything measured under ~15% elsewhere in this document was rejected).

**The growth-stage question (`K>=3`, where this project's actual cost problems live) is worse
for the idea, not better.** `discover(mode="auto", growth_width=4, max_elements=6)` was run on
`par6` (`benchmarks/six_plus/truths.py`, a truth `docs/TOPOLOGY_6PLUS_PLAN.md`'s own X4 already
found reliably recovered by growth) across 10 seeds, using `par6`'s own registered frequency
window. The exact Foster canonical shape appeared in 2/10 seeds, the exact Cauer-ladder dual in
0/10, and both together in 0/10. Cross-checking against X4's own recorded data
(`benchmarks/six_plus/x4_recovery.json`) explains why this looks worse than X4's "12/12" headline
number: X4's "recovered"/"recommended" fields do not require the literal Foster or Cauer
canonical shape -- `par6` seed 1's own `recommended_circuit` there is
`p(p(R1-p(C1,R2),C2)-R3,C3)`, a third structural shape, neither pure Foster nor pure Cauer,
that happens to fit the data just as well. Growth reliably finds *some* equivalent
low-residual 6-element topology for a parallel-shaped truth like `par6` -- that is X4's real
finding -- but the specific pair this transform targets is only two members of a larger, more
diffuse equivalence class at this element count, and landing on that *specific* pair is rarer
still than landing on *some* correct-sized answer. This makes the already-small guaranteed
saving even less likely to be realised in the regime where it would matter most.

**Verdict: not shipped.** The transform in `benchmarks/speedup/idea_a2_foster_cauer.py` is
correct and reusable if a future need for it appears, but no scale tested here turns "derive
the dual instead of fitting it" into a worthwhile `discover()` speedup -- negligible where the
pair is guaranteed to co-occur (`K<=2`), and rarer still where the saving would matter
(`K>=3`, growth). Two smaller, real observations surfaced along the way are recorded here
without being folded into this verdict, because neither is a speedup: (1) `fit()`'s own
independent optimisation can land in a materially worse basin for one member of an equivalent
pair while the other fits well (`mw5` seed 4, `mw6` seed 0), which today's `_same_response`
would not catch since it only compares already-independently-fitted spectra; (2) the search
often reports only one member of a Foster/Cauer pair, never both, at the element counts checked.
Both are report-completeness observations, not `discover()` speedups, and are left as an
unpursued, separately-scoped idea rather than a consolation prize for this one.

## Phase 2 -- search-loop algorithm changes

### 2a -- successive halving for tier-1 screening

**Rejected.** [measured, `benchmarks/speedup/idea_2a_successive_halving.py`]

Tested directly against `docs/TOPOLOGY_6PLUS_PLAN.md`'s basin-lottery finding, which predicts
successive halving should be unsafe: a cheap first-round probe should be at least as
seed-sensitive as the already-measured >1000x single-seed swings, so it should discard good
candidates before a doubled budget ever corrects it. Enumerated all 2523 five-element topologies
from pool `(R,C,L,CPE)`, screened each at the full tier-1 budget (`popsize=8, maxiter=40`) and at
a quarter budget (`maxiter=10`), one seed each, matching how the production screen actually runs.

**The overall Spearman rank correlation looks passable (rho=0.82) and is the wrong number to
read.** Most of 2523 candidates are structurally bad regardless of budget, so bulk agreement on
"these are all bad" inflates the aggregate correlation. The number that actually determines
whether successive halving is safe -- what fraction of the *true* top-20 (full budget) survive
being in the *cheap* round's top-40 -- is **25%**. Three of every four genuinely good candidates
would be discarded in the first, cheapest round, before any later budget-doubling could rescue
them. Pre-declared decision rule (>=90% preserved AND rho>0.8) fails on the preservation half by
a wide margin. **Rejected**, and the aggregate-correlation number is recorded specifically as a
trap: a future idea evaluated only by overall rank correlation on a landscape dominated by bad
candidates would look safe while being exactly as unsafe as this one.

### 2e/F -- subtree memoization

**Rejected.** [measured, `benchmarks/speedup/idea_2ef_subtree_memo.py`] Re-measured with an actual
implementation after an earlier draft of this section substituted citation of existing results
for a new measurement, which the user correctly rejected as not equivalent to running the planned
experiment.

**What is already shipped, found before anything was run.** `enumerate.py`'s `_level()` already
memoises whole materialised sub-network levels in a module-level `_LEVELS` dict keyed by
`(pool, size)`, so a smaller level is never re-enumerated once built. What is not cached is
`canonical_form(node)` itself, called once per candidate combination in `_compose`'s dedup loop.

**Measured attempt to cache it, on mw5's own pool `(R,C,L,CPE)` at n=4 and n=5:** a memoizing
wrapper around `canonical_form` did find real, substantial cache hit rates (34.7% at n=4, 40.8%
at n=5, 1672 and 11160 calls respectively) -- there is genuine redundant computation. But caching
it made enumeration **37-42% slower**, not faster, because a cache key exact enough to be safe
(`repr(node)`, after a first attempt using `hash(node)` was caught producing a **non-identical**
topology set from an undiagnosed collision or `__hash__`/`__eq__` mismatch -- itself a reminder
that a "fast" hash-based key is exactly the kind of shortcut this project's own discipline warns
against taking without checking) costs as much to compute as `canonical_form` itself, since both
require walking the same tree. **Rejected as measured**, with the correct scope for a real
attempt recorded rather than left implicit: an actual win would need the structural key computed
incrementally as each node is *built* (propagated bottom-up through `series()`/`parallel()`
themselves) rather than recomputed post-hoc from a finished tree, which is a change to the node
construction functions, not a wrapper around `canonical_form` -- not built or measured this round.

### 5b -- evolve archive retention

**Rejected.** [measured, `benchmarks/speedup/idea_5b_archive_retention.py`] Re-measured directly
on `mw6`/`srf3` after an earlier draft of this section substituted citation of
`docs/EVOLVE_SEARCH_PLAN.md` section 3.4's prior island/pool-width ladder for a new run, which the
user correctly rejected.

`_breeding_pool`'s `extra` parameter is bound as a default argument at function-definition time,
so patching the module constant has no effect; this instead replaced `discover._breeding_pool`
with a wrapper forcing `extra=population//2` (a wider pool than the shipped Pareto-front-only
`extra=0`), paired by seed against the baseline, 5 seeds each on `mw6` and `srf3`.

**Note on the script's own printed summary**: it is wrong and was not used for the verdict below.
It computed hit rate via `cost <= best_known * 1.1`, a threshold designed for positive SSR-like
costs; these are signed AICc-like `.score()` values, for which multiplying a negative
`best_known` by 1.1 makes the bar *stricter* rather than a tolerance band, silently producing
0/5 vs 0/5 on both truths. The verdict here instead uses a direct pairwise comparison of the raw
scores each seed produced:

| truth | wide wins | baseline wins | ties | McNemar p |
|---|---:|---:|---:|---:|
| `mw6` | 2 | 1 | 2 | 1.0000 |
| `srf3` | 2 | 3 | 0 | 1.0000 |

Both truths: no significant difference, and the win counts are close to evenly split in both
directions rather than trending either way. The individual swings are large (differences of
several hundred to over a thousand AICc-scale points on single seeds) but directionless --
exactly what pure seed-to-seed variance looks like, not a systematic effect of pool width. This
reproduces, on this round's own truths rather than by citation, the same conclusion
`docs/EVOLVE_SEARCH_PLAN.md` section 3.4 already reached: pool width is not where the evolve
fallback's quality comes from.

### E -- SPRT early stopping

**Rejected.** [measured, `benchmarks/speedup/idea_e_sprt_earlystop.py`, restored to its originally
planned scope (`mw6`/`srf3`, full `discover(mode="evolve")` comparison) after an unapproved
mid-run substitution to smaller truths was reverted on the user's explicit instruction.]

`discover(mode="evolve")` at a reduced generation budget (8) vs the default (24), same seed, on
`mw6` and `srf3`, 3 seeds each -- a single one of these twelve calls took as long as 471.9s, so
this measurement alone cost roughly 70 minutes of wall time.

| truth | canonical-form match | cost match |
|---|---|---|
| `mw6` | 1/3 | **3/3 exact** (-1998.88/-1998.88, -2015.94/-2015.94, -1998.69/-1998.69) |
| `srf3` | 1/3 | 1/3 exact, 1/3 near (-1649.89 vs -1651.8, ~0.1%), **1/3 badly diverged (-324.29 vs -1656.9, ~5x)** |

Overall canonical-form match: 2/6 (33%), decisively short of the pre-declared "clear majority"
bar. **Rejected** against that bar, and the more informative reading is not "sometimes it matches,
sometimes it doesn't" but that **safety is shape-dependent in exactly the dangerous direction**:
`mw6` (parallel Maxwell-Wagner blocks) plateaus early and reduced generations cost nothing, while
`srf3` (multiple resonances) is precisely the harder landscape where the missing generations
occasionally still buy a real, large improvement -- the one truth where an early-stopping rule
would most need to fire correctly is the one it would get wrong. The low canonical-form match rate
even on `mw6`'s 3/3-cost-identical seeds is not itself concerning -- `docs/SEARCH_TIME_PLAN.md`
section 3.3 already documents an exactly-tied equivalence-class pair swapping which member the
restart search reports, with `.summary()` unchanged; a cost-identical, form-different pair is that
same phenomenon, not a quality regression. No SPRT rule was built, since a fixed reduced budget --
the simplest possible version of the idea -- already fails on the truth that most needs more search.

### G -- frequency-band divide and conquer

**Rejected.** [measured, `benchmarks/speedup/idea_g_band_decomposition.py`]

Split the sweep into N equal log-decade sub-bands (N = number of series `p(R,C)` blocks), fit a
*lone* 2-parameter R||C block to each sub-band alone (cheap local least-squares, no global search),
assemble the N estimates into one initial guess for the full circuit, and run only a **local
polish** from it -- no `differential_evolution` at all -- against the production tier-1 screen
(full global DE + polish).

At 30 seeds it looked like a free win (`mw5` 6/30 vs 3/30, `mw6` 6/30 vs 4/30), which is exactly
why the pre-declared decision rule required checking it and the plan called for a larger-seed
confirmation before trusting it. At 120 seeds the apparent edge shrank into the same noise every
other Phase 1 idea hit: `mw5` 5/120 vs 3/120, `mw6` 4/120 vs 3/120 -- Wilson CIs overlap heavily
in both cases, and both routes sit under 10% regardless of method. **The 30-seed result was
small-sample variance, not a real effect**, recorded here specifically as the case where this
round's own significance discipline (recheck an apparent win at a larger seed count before
believing it) mattered and changed the verdict. Same underlying story as C/D/B: at 10-12 elements,
no single-stage trick (box width, reparameterisation, or replacing the global search with cheap
local pre-fits) beats the joint-combinatorics bottleneck a fixed small tier-1 budget faces.

## Phase 3 -- larger algorithm changes

### 2b -- surrogate-assisted GA

**Rejected.** [measured, `benchmarks/speedup/idea_2b_surrogate_ga.py`] The desk-analysis argument
below was checked directly (reusing idea 2a's 2523-topology, full-tier-1-budget dataset rather
than re-screening) after the user pointed out that citing the basin-lottery finding by analogy was
not an adequate substitute for measurement.

Seven cheap structural features (element count, per-code counts, tree depth, max branch width),
standardised, fed to (a) a from-scratch leave-one-out 1-NN classifier predicting whether a
candidate is in the cheaper half of the full-budget cost distribution, and (b) a plain linear
regression on log10(cost). Result: **70.7% leave-one-out accuracy** (clearly above the 50% chance
baseline -- there is a real, non-zero structural signal, contradicting the pure-noise-ceiling
version of the desk argument) and **R^2=0.455** in-sample for the linear fit (a moderate, not
strong, relationship). Both fall short of the pre-declared 80% bar. **Rejected**, but with a more
precise reason than "no signal exists": there is a real but weak structural signal, consistent
with a mix of the basin-lottery noise `docs/TOPOLOGY_6PLUS_PLAN.md` documents and *some* genuine
structure-cost relationship a more careful surrogate (more features, more seeds averaged into the
target to shrink the lottery noise in what is being predicted) might do better against -- a lead
for a follow-on attempt, not a closed question the way C/D/B/2a/2d were. `docs/PARAM_OPTIMIZER_PLAN.md`'s
from-scratch GP-EI optimiser (a related but distinct application, at the parameter level rather
than the topology level) tying or losing on both its arenas remains separately relevant context.

### 2c -- asynchronous / barrier-less evolve

**Confirmed as a real, substantial win; not yet integrated into `_evolve`.**
[measured, `benchmarks/speedup/idea_2c_async_evolve.py`] Re-measured directly after an earlier
draft of this section rested on citing `docs/SEARCH_TIME_PLAN.md` section 4.3 (gate T4) instead
of running the planned comparison, which the user correctly rejected.

T4 already merged evolve's two sequential per-generation dispatches (polish, then a full barrier,
then search) into one worker function per candidate -- that does not remove the *generation
boundary* barrier itself, only a second barrier that used to sit inside one generation. This
measures the boundary barrier directly: 64 topologies with genuine cost heterogeneity (32
CPE-bearing, 32 CPE-free, exploiting the already-measured ~2x per-fit cost gap between them)
dispatched at `workers=8` via (a) `ProcessPoolExecutor.map` in fixed batches of 8 (mirrors a
generation's synchronous barrier) and (b) `as_completed`-driven continuous dispatch (a worker
gets a new task the instant it frees, never waiting on a batch). **Continuous dispatch finished in
8.90s against batched's 13.40s -- a 33.6% speedup**, decisively past the pre-declared 15% bar.
This is a distinct saving from T4's (T4 cut what happens *inside* a generation for one candidate;
this cuts the idle time *between* generations caused by the slowest candidate in a batch) and the
mechanism -- CPE-bearing fits taking materially longer, so a synchronous batch runs only as fast
as its slowest member -- is exactly what the hypothesis predicted. **Recommended for a follow-on
integration into `_evolve`'s actual generation loop**, which this script does not attempt (it
tests the dispatch mechanism against the production `screen()` function directly, not the full
genetic loop's population/selection logic) -- the real change needed is replacing `_evolve`'s
per-generation `executor.map`-style batch with a continuously-fed worker pool, which changes the
population model materially (a candidate's parent selection would need to happen at proposal time
rather than at a fixed generation boundary) and was not built this round.

### 2d -- residual-guided search

**Rejected.** [measured, `benchmarks/speedup/idea_2d_residual_guided.py`] The desk-analysis
argument below was checked directly rather than left as an analogy, after the user pointed out
that a desk-only verdict was not an adequate substitute for measurement here.

Method: for each of `mw5`'s five series `p(R,C)` blocks, drop that block from the topology, fit
the resulting 4-block circuit to the *full* 5-block data, and check whether the frequency at
which the residual magnitude peaks lands within one decade of the dropped block's own true
relaxation frequency `1/(2*pi*R*C)` -- the concrete signal a "insert an element near the residual
peak" mutation operator would need. Across all 5 blocks x 5 noise seeds (25 pairs): **5/25 (20%)**
within one decade, decisively below the pre-declared 60% bar.

**A specific, informative reason, not just a low number.** The residual peak landed at exactly
the sweep's lowest frequency point in every single one of the 25 runs, regardless of which block
was actually dropped. Removing any one series block changes the circuit's total DC resistance,
and `|Z|` itself is largest at the low-frequency end of these truths' sweeps, so a *raw magnitude*
residual is dominated by that overall scale rather than by which relaxation is actually missing --
the naive version of this heuristic has no localizing signal at all, confirming the desk-analysis
concern (this is the same class of failure as `docs/POOL_FROM_SPECTRUM_PLAN.md` section 3's
diffusion-branch detector on composite spectra) rather than merely being analogous to it. A
relative or weighted residual measure might do better and was not tried; the decision rule is
failed regardless, and this is recorded so a future attempt does not repeat the same raw-magnitude
mistake.

### 1b -- CPE-as-RC-ladder linear approximation

**Rejected.** [measured, `benchmarks/speedup/idea_1b_cpe_rc_ladder.py`] Re-measured directly after
an earlier draft rested on citing `core/drt.py`'s existence instead of running the planned
comparison, which the user correctly rejected as not equivalent to measuring.

On `mw4cpe`'s own `CPE1` (Q=1.74346e-06, n=0.999326), fitting a fixed-tau-grid ladder
(`Z = sum_k w_k/(1+j*omega*tau_k)`, `tau_k` log-spaced across the data's own window, weights by
linear least squares) against the standard nonlinear 2-parameter fit: nonlinear mean relative
error 0.504% at 686 NFE; ladder mean relative error **275-554%** at M=4/8/16 branches -- 545-1099x
worse. A first attempt used plain unregularized least squares (935x worse) and was re-run with a
Tikhonov-regularized solve swept over 21 regularization strengths, picking the best against the
known true curve (fair only because this is a controlled synthetic test); essentially no better
(545x at best). Pre-declared decision rule (within 2x) fails by more than two orders of magnitude.

**The reason is not "the idea never works", and is worth recording precisely.** `mw4cpe`'s CPEs
were tuned to n=0.999 -- a *near-ideal capacitor* -- which is exactly the regime a finite-tau-grid
Debye/ladder basis is theoretically unsuited for: a pure capacitor's impedance is a single -1
log-log slope with no plateau anywhere, which no finite sum of bounded-window relaxation terms
(each with its own low-frequency plateau) can reproduce without branches far outside the measured
window. The ladder decomposition is the standard, well-founded tool for a genuinely *distributed*
process (n around 0.3-0.7, which is what DRT is built for) -- not for a CPE sitting near n=1. Since
`mw4cpe` -- the reference this round's plan named -- happens to be tuned near n=1 (a consequence of
the leverage-maximising tuner, not a deliberate choice against this idea), this measurement rejects
the approximation *for this reference and this n regime*; it does not settle the question for a
CPE with n well below 1, which was not tested this round.

## Phase 4 -- reformulation / research bets (feasibility-level only, per plan)

**Epistemic status warning, added after the user questioned it directly.** Every verdict below
except 1a is a desk argument, not a measurement -- no code was run to test 1c, 1d, 3a, 3b or 5a.
This is what the approved plan pre-declared for Phase 4 ("this round will likely only reach a
feasibility verdict"), but "not measured, argued against" is a different and weaker kind of
statement than the measured rejections in Phases 1-3 above, and is labelled that way in every
entry below rather than reusing the word "Rejected".

### 1a -- rational-function inverse synthesis

**Rejected by existing measurement, corroborated this round.** `docs/TOPOLOGY_6PLUS_PLAN.md` (d)
already measured vector-fitting/Loewner/stabilisation-diagram reconstruction as "exact without
noise and useless with noise" (0.04-0.20 exact-recovery at 1% noise). This round's idea B tested
the strictly weaker question (order only, not full reconstruction) with the same Loewner
machinery and found the identical qualitative pattern, plus a *second*, independent failure mode
at zero noise for imbalanced-residue Maxwell-Wagner shapes. Nothing in this round's evidence
weakens the existing rejection; full synthesis is not revisited.

### 1c -- supernet / continuous relaxation

**Not measured -- argued against on desk analysis, not built; do not read as a rejection on the
same footing as C/D/B/G/2a above, which were measured.** Unlike neural architecture search's edge-presence
gates, this project's discrete choice is *series vs. parallel structural nesting*, which has no
natural continuous relaxation the way an edge weight does -- there is no smooth interpolation
between "these two elements are in series" and "these two elements are in parallel." A supernet
would need a fixed hyper-topology (a generic ladder with many potential branches) with continuous
per-branch gates, inheriting NAS's well-known discretization gap (the continuous relaxation's
implied architecture often does not match what discretizing it to a clean topology actually
produces) on top of a domain where even the base relaxation is unclear. Also requires autodiff
machinery this project's numpy+scipy-only rule (`CLAUDE.md`) does not currently admit for anything
shipped in `autocircuit.core`. Not attempted.

### 1d -- compressed-sensing / sparse regression

**Not measured -- narrow applicability argued on desk analysis, not built.** A circuit's impedance is not a linear
function of "which branch is present" for the general series/parallel tree this project searches
-- nesting makes the map nonlinear -- so LASSO-style sparse selection over a large branch basis
does not apply generically. It *would* apply to one specific structural subclass: a Foster-form
network (independent parallel R-C sections summed in series), which is exactly the Maxwell-Wagner
shape `mw5`/`mw6` are. But making the weights linear there requires fixing a `tau_k` grid in
advance, which collapses this idea onto the same mechanism as idea 1b / `core/drt.py`'s existing
linear machinery rather than adding a distinct one. Not built separately from 1b's feasibility note.

### 3a -- learned spectrum-to-topology inference model

**Not measured -- a large, session-scale investment, not attempted, per the plan's own scoping.**
Feasibility is
plausible in principle (a small MLP's forward pass is pure `numpy`, so `CLAUDE.md`'s dependency
rule is not automatically violated for inference, only for a training pipeline that would live
outside the shipped package). The open risk is generalisation, not implementability: this
project's own repeated experience is that a detector built on clean, isolated examples fails on
composite spectra (`docs/POOL_FROM_SPECTRUM_PLAN.md` section 3's diffusion-branch detector is the
clearest instance), and a learned topology classifier faces the same risk at far larger scale and
training cost. Not attempted this round.

### 3b -- learned initializer for the global stage

**Not measured -- argued to have lower expected value than 3a, not attempted.** `search_space()` already gives
every parameter a data-derived starting point (the geometric centre of its bound), and this
round's ideas C and D already found that narrowing or re-centring individual parameters' search
boxes does not move hit rate on 10-12-element topologies, because the bottleneck is the *joint*
combinatorics across all free dimensions at once, not any single dimension's starting point.
Seeding a *whole population* intelligently (rather than one starting point) would need
infrastructure closer to 3a's scope than a small addition. Not attempted this round.

### 5a -- cross-session cache

**Not measured -- argued against on desk analysis, not built.** The premise -- that similar spectra recur often enough
across sessions for a cache to pay off -- is already in tension with why this tool exists: each
analysis targets one physically distinct, previously unmeasured part (`CLAUDE.md`'s stated
purpose), not a fleet of near-duplicate spectra. This project's own benchmark suite is
deliberately built for diversity (three shapes, multiple sizes, electrochemical and component
references, and now `mw5`/`mw6`/`mw4cpe`/`srf2`/`srf3` on top) rather than repetition, which is
itself weak evidence against the premise. No code was written to measure a hit-rate ceiling
because the qualitative case against the premise is strong enough on its own to not warrant the
engineering and privacy cost of a persistent cross-session store.
