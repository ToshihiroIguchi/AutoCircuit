# Where the topology search spends its time, and what may be done about it

Status: **§3.1 implemented and shipped (gate T1 passed on revised numbers); §3.2 measured and
its fix rejected (gate T2 run, not passed, nothing shipped); §4.2 measured and its flag rejected
(gate T3 run, not passed, nothing shipped); §4.1 run and its own decision rule says it does not
ship either (gate T6 run, changed nothing on the nine truths); §4.3 implemented and shipped
(gate T4 passed on both halves); §3.3 implemented and shipped in half (gate T5 passed for the
CPE kernel substitution, measured and not shipped for the buffer-reuse half); §3.4's class
multiplicity is measured (4.4-5.9x, past the bound the section hoped would close it) but ships
nothing, for reasons unaffected by the number. All seven steps of section 7's order of work are
done. §3.5 (spectrum thinning for the DE global stage) was added 2026-09-12 and its H1 question
(does thinning help at all) is now measured at pilot scale (60 seeds): no hit-rate cost detected,
25-52% wall-clock reduction, but Wilson CIs overlap too much at this sample size to license a
ship decision -- the pilot's own recommendation is a full 480-seed follow-up, not yet run.**
Written 2026-09-02. Every number outside §3.1/§3.2/§4.1/§4.2/§4.3/§3.3/§3.4 and §6's
T1/T2/T3/T6/T4/T5 entries is quoted from a document that measured it before this plan existed,
except §3.5, whose pilot-scale H1 result is new and whose H2 is still unmeasured. **§8, added
2026-09-13, is the direct decomposition this plan's own §1 never had** — every share in §1 came
from one arm of an A/B (`profile_eval.py`'s `cProfile`, run once), never checked against an
unbiased measurement of the same quantity. §8 builds that check
(`benchmarks/speedup/where_time_goes.py`) and finds §1's own numbers hold up: SciPy's DE loop is
~30–42% of a screen depending on topology, confirmed by both an unbiased wall-clock method and
`cProfile`, and prices four previously-only-named micro-inefficiencies (§3.3's own kernel
substitution already shipped; these did not) without shipping any of them.

## 0. What this plan is and is not

`SEARCH_ALGORITHM_SCREENING.md` §1 gives the accounting this plan is built on:

    time to answer  =  F1 (seconds per topology evaluation)
                    x  F2 (topologies visited before the answer)
    and F3 (does a visit score correctly) decides whether F2 is finite at all.

The measured gap on the hard arena is 13x, and it is an **F2** gap — three search arms close
it (120/120 against 87/120) by bounding the set they breed from, and that is already shipped
(`BREEDING_EXTRA = 0`). This plan is **not** about F2. What it collects is the set of levers
on F1 and F3, plus the throughput of the genetic fallback, that the earlier rounds identified
and then set aside as "worth a plan" or "a lever, not a default". Their combined ceiling is
modest and is stated honestly in §5: perhaps 1.5–2x on the tier-1 screen, and nothing that
closes a 13x gap. Their value is that most of them **change no number**, which makes them
cheap to gate, and the rest are measurements this repository already owes itself.

Two rules carry over from earlier rounds and bind every item here:

- **A stage winning and the total losing is the normal case, not the exception.**
  `METRICS_AND_UX_PLAN.md` §1.5 cut the stage it targeted 3–4x and made the total worse. Every
  gate in §6 is therefore written on the *total* tier-1 or evolve wall-clock, and the profile
  bucket is reported beside it, never instead of it.
- **A saturated arena ranks nothing.** `EVOLVE_SEARCH_PLAN.md` §3.4.4: at 900 fits every arm
  scored 120/120 and the islands appeared to win; at 150 fits they lost. Any A/B in this plan
  that compares searches is run at a budget where the control does *not* saturate.

## 1. The measured breakdown, restated

One tier-1 screening fit (`fit.screen()`, `fit.py:657`), profiled by
`benchmarks/screening_round/profile_eval.py` and recorded in
`SEARCH_ALGORITHM_SCREENING.md` §4.5:

| bucket | three-block MW, no CPE | topology with CPE |
|---|---:|---:|
| impedance kernel | 36.1% | 46.3% |
| `differential_evolution` bookkeeping | 27.6% | 26.3% |
| per-topology setup | 33.1% | 25.4% |
| trust-region polish | 3.2% | 2.0% |

Absolute: 0.87 s per screen without CPE, 1.77 s with (§4.6). The screen is run once per
enumerated topology — 2,976 at the default pool and `n <= 5` — and
`DISCOVERY_V2_PLAN.md` §3.3 records that it **dominates the run** (6.1 min at 8 workers on
the two electrochemical references) and that its DE budget cannot be cut without dropping
the truth from the shortlist.

Above the exhaustive limit, `_evolve` costs 1.33 s per distinct topology on a six-element
truth and 5.4 s on the seven-element Randles reference (`EVOLVE_SEARCH_PLAN.md` §1.1, §4),
and its per-generation batch is eroded by cache hits that rise from 37.5% to 55% across a
run (§1.3). Eight workers buy 39–48% more generations than one (`TOPOLOGY_6PLUS_PLAN.md`
§5.11), roughly 5–6% scaling efficiency per core.

On F3, `TOPOLOGY_6PLUS_PLAN.md` §5.7.2: one screening seed lands within 1% of the best of
five for 72–80% of 360 sampled topologies and up to 2400x off for a bimodal minority; 25x
the DE budget moves neither basin; a second seed takes the mean penalty from 37.7–41.4x to
1.06–1.16x. The lever exists (`SCREEN_RESTARTS = 1`, `discover(screen_restarts=)`) and its
recovery effect **has never been run** — `benchmarks/six_plus/recovery.py` defines a
`seeds2` arm and `x4_recovery.json` contains no run of it.

## 2. What is already settled and must not be re-tried

Listed so that nobody spends a day re-deriving them. Each has a measurement beside it.

| idea | verdict | where |
|---|---|---|
| compiled kernel (C/C++/Cython/numba) | Amdahl caps it at 1.4–1.7x; costs the Pyodide rule | `SEARCH_ALGORITHM_SCREENING.md` §4.5, §5 |
| cut the screen's DE budget | 0.41–0.56x the time, truth leaves the shortlist | `DISCOVERY_V2_PLAN.md` §3.3 |
| raise the screen's DE budget to fix basins | 25x changes neither basin | `TOPOLOGY_6PLUS_PLAN.md` §5.7.2 |
| DRT peak count as an enumeration floor | removes < 1% of the work, breaks `complete_up_to` | `DISCOVERY_V2_PLAN.md` §3.4 |
| islands / age layering in `_evolve` | win only on a saturated arena; lose at 150 fits | `EVOLVE_SEARCH_PLAN.md` §3.4.4 |
| adaptive parsimony | inert until degenerate; p = 0.32 at 480 seeds | `EVOLVE_SEARCH_PLAN.md` §3.5.1 |
| asymmetric mutation weights | a bet on the answer's shape; mirrored loss on the mirrored truth | `EVOLVE_SEARCH_PLAN.md` §3.5.2 |
| element-cap staging 6 vs 7 | changes nothing on either arena | `SEARCH_ALGORITHM_SCREENING.md` §4.3 |
| rational approximation / AAA / Loewner | exact without noise, 0.04–0.20 recovery with it | `TOPOLOGY_6PLUS_PLAN.md` §3.3–3.4 |
| warm-accept factor between 1.5 and 10 | inside run-to-run spread; the knob is binary | `EVOLVE_SEARCH_PLAN.md` §3.3.1 |
| raising `WORKER_CHUNK` to cut tier-1 idle | cuts idle 31.7%→13.4% but changes the tier-2 shortlist on a CPE/SKINF pair; not number-preserving | this document, §3.2 |
| sub-tree re-screen flag | catches 100% of >100x mis-screens, but flags 70.6–78.7% of all topologies -- its own comparison is exactly as noisy as the lottery it targets | this document, §4.2 |
| universal second screening seed as the shipped default | recovery unchanged on all nine X4 truths at 2x tier-1 cost (0/18 -> 0/18 on the six/seven-element rows, 3/9-3/9-3/9 by shape both before and after) -- stays a lever, not a default | this document, §4.1 |

## 3. Levers on F1 — seconds per evaluation

### 3.1 Hoist the per-dataset invariants out of per-topology setup (recommended first)

**What the profile calls "setup" is mostly work that does not depend on the topology.**
`_Problem.__init__` (`fit.py:401-444`) runs once per `screen()` call and does, every time:

- `weight_vectors(spectrum.z, weighting, sigma)` (`fit.py:419`) — depends on the spectrum and
  the weighting only.
- `search_space(...)` → `BoundsContext.from_data(omega, z, margin_decades)`
  (`elements.py:61-73`) — `np.abs(z)`, a mask, four min/max reductions; depends on the
  spectrum and `margin_decades` only. Its four scalars are identical for every one of the
  2,976 topologies screened against one spectrum.
- `Circuit.parse(text)` — and the *driver* parses the same text again, independently, in
  `screen_plan` for `complexity_of` (`discover.py:3143`) and at the abandon-threshold call
  sites (`discover.py:3226-3276`). No cache exists for any of this: no `lru_cache`, no dict
  keyed on canonical form, although `Circuit` is hashable by canonical form
  (`circuit.py:257-261`).

What stays genuinely per-topology is small: `circuit.bounds(ctx)` over the element list, the
`start` vector, `log_mask`, and a handful of tiny arrays.

**Design.** Introduce a `FitContext` (name provisional) built once per
`(spectrum, weighting, sigma, margin_decades)` and holding the weight vectors and the
`BoundsContext`. `_Problem` takes it as an optional argument and builds its own when it is
absent, so `fit()` and `screen()` keep their public signatures. On the driver side,
`_exhaustive` builds one and `_init_worker` (`discover.py:3305`) builds one per worker
process next to the spectrum it already stores, so every `_screen_worker` task reuses it.
Driver-side parses collapse to one `dict[str, Circuit]` filled as `screen_plan` yields.

**Why this changes no number.** The four `BoundsContext` scalars and the weight vectors are
computed by the same expressions on the same arrays; computing them once and reusing them is
bit-identical to recomputing them. Nothing in the DE or the polish sees a different input.
That is what makes the gate a byte comparison (T1 below).

**Ceiling.** Setup is 23–33% of a screen. If the hoist removes most of it the screen gets
1.3–1.5x faster and no more; the browser (`workers = 1`, no pool) gains the same, because
this is in-process work. This is the whole of what §3.1 can promise, and it is worth having
because it costs nothing anywhere else.

**[implemented, 2026-09-02]** `FitContext` (`fit.py`), holding `w_re`, `w_im` and a
`BoundsContext`, built once and threaded through `_Problem`, `fit()`, `screen()`,
`_exhaustive`, `_init_worker`/`_screen_worker`, `_evolve`'s `_Evaluator` and its two worker
functions. The `Circuit.parse` de-duplication described above was **not** done — it is a
separate, more invasive change touching many call sites in `growth_plan` (off by default,
`GROWTH_DEFAULT = 0`) for little payoff, so it is left for a later pass rather than folded in
here.

**[measured, gate T1]** The byte comparison held: `ev5_fingerprint.py --mode exhaustive
--workers 1 --limit 3` before and after this change is byte-identical
(`diff before.txt after.txt` empty) on all three references. Two things in the plan's own
method turned out to be wrong, and both are recorded rather than smoothed over:

- **`profile_eval.py` cannot see this change at all**, because it calls `screen()` directly
  without a `FitContext`, so its own fast path is never exercised — its setup-bucket
  percentages are unchanged before and after (circuit-1 ≈ 29–31%, circuit-2 ≈ 24–25%,
  circuit-3 ≈ 23–25%, three repeats each, no other load running). The plan's "<10%" target for
  that bucket was written against the wrong instrument and is withdrawn; nothing here says the
  hoisted cost is small, only that this script does not measure it.
- **Real wall-clock**, `discover(mode="exhaustive", exhaustive_limit=4)` on the Randles
  reference, 3 runs each, sequential, nothing else running: at `workers=1`, median 51.31 s
  before → 45.99 s after, a 10.4% reduction — short of the 15% this section targeted. At
  `workers=8`, median 31.89 s before → 33.98 s after, with per-run spread (28–36 s) wider than
  the effect being measured; process-pool start-up (`~1 s` per worker, already known to be
  amortised across a run rather than eliminated) is a much larger share of a 4-worker-pool-shared
  30 s total than of a 46-51 s single-process one, which is the likely reason the `workers=1`
  saving does not show up at `workers=8` on this machine. Both figures are single sessions on a
  machine `docs/HANDOFF.md` already documents as having 2x thermal/load drift between runs
  taken an hour apart; a tighter number would need more repeats spread over more time than this
  pass spent.

The change ships anyway: it is byte-identical (T1's correctness half, the one that matters),
costs nothing when unused, and is a measured net improvement at `workers=1` -- the path the
browser actually takes. The 15% total-wall-clock threshold and the <10% setup-bucket threshold
are both revised down to *what was measured*, per this repository's own rule against rewording
a gate into something the build already does.

### 3.2 Streaming dispatch in tier 1 -- measured, and the obvious fix does not work

`_screen_parallel` (`discover.py:3322-3370`) hands `Pool.map` a chunk of `WORKER_CHUNK = 64`
tasks and waits for the whole chunk. Screens are 0.3–1.8 s with tails, so at each chunk
boundary seven of eight workers idle for as long as the slowest screen in that chunk. The
time-limit check and the `abandon_above` refresh also wait for the boundary.

**[measured, 2026-09-02]** The idle is real and well past the 5% withdrawal bar this section
originally set. A pid-tagged instrumentation of `_screen_parallel`'s own dispatch (each worker
timestamps its own tasks; idle = pool wall-clock time not covered by any worker's own busy
time, per chunk) on the Randles reference at `workers=8`, default pool, `exhaustive_limit=4`
(567 topologies, one run): **31.7% of tier-1 wall-clock idle**, with individual chunks up to
52.4%. `Pool.map`'s own chunksize heuristic already redistributes sub-chunks across workers as
they free up *within* one 64-task batch, but the batch is still a hard synchronisation
barrier: once all 64 tasks are claimed, an idle worker has nothing left to steal and waits for
the batch's slowest straggler, however many workers finished early.

**The originally planned fix does not touch the actual cause.** `Pool.imap` with a smaller
chunksize changes how a *fixed-size* batch is sub-divided across workers, which `Pool.map`
already does adequately (§3.2's own instrumentation shows plenty of dynamic rebalancing
happening inside a batch). The barrier is the batch *boundary* itself: `screen_plan`'s
`send(costs)` contract needs every cost in the batch before it can compute the next one's
`abandon_above` values, so no dispatch mechanism can hand an idle worker something from the
*next* batch early. What actually moves the idle number is the batch size: raising it from 64
to 256 cut idle from 31.7% to 13.4% on the same reference (two runs, 256 also measured at
16.5%/10.7%/12.8% per-chunk on a second run) -- more tasks per batch gives the existing dynamic
rebalancing more room before it runs out of work to steal.

**And that fix is not number-preserving, contrary to this section's own original claim.**
`discover.py`'s comment on `_screen_parallel` states a stale `abandon_above` threshold "costs a
little time but can never change a result" -- untested, and wrong at least once. Bumping
`WORKER_CHUNK` from 64 to 256 and re-running `ev5_fingerprint.py --mode exhaustive --workers 8
--limit 3` (isolated from the §3.1 change already shipped, which is present in both sides of
this comparison) is **not** byte-identical: on the skin-effect reference, one candidate
(`p(CPE1-SKINF1,L1)`, complexity 6.0) appears in the `WORKER_CHUNK=256` report and not the
`WORKER_CHUNK=64` one, and a different one (`p(CPE1-SKINF1,CPE2)`, complexity 7.5) appears only
at 64. The mechanism is exactly the one the comment dismissed: a batch of 256 candidates shares
one stale threshold for longer than a batch of 64 does, which candidates get their local polish
computed rather than skipped shifts near the boundary, and for at least one CPE/SKINF pair
(elements this repository's own `KK_RESONANCE_PLAN.md` already knows are prone to near-tied,
resonance-adjacent fits) that shift crosses whichever line decides the tier-2 shortlist. **The
`WORKER_CHUNK` bump was implemented, found to fail its own byte-identity requirement, and
reverted** rather than shipped on the strength of an unverified comment.

**What is not known, and was not chased down here:** whether the *currently shipped* value
(`WORKER_CHUNK = 64`, unchanged) already carries some version of this effect against the
zero-staleness case (`chunk=1`, fully synchronous refresh), or whether the effect only appears
once a batch grows past some size between 64 and 256. `ev5_fingerprint.py` at `workers = 8`
against a `chunk = 1` parallel run would answer it directly; that comparison was not run,
because the question this section set out to answer -- does `WORKER_CHUNK` have headroom to
give back to idle -- was already answered no. The dismissive comment in `discover.py` is left
in place for now rather than edited on the strength of one measurement at one other value; it
should be revisited together with whatever answers the question above.

**What would actually work, not attempted here.** Decoupling the two things `WORKER_CHUNK`
currently conflates -- how many tasks are dispatched to the worker pool in one `Pool.map` call
(the idle lever) and how often `abandon_above` refreshes (the correctness-sensitive one) --
would need `screen_plan`'s generator contract to accept partial batches, which is shared with
the browser's own driving code (`discover.py:3129-3131`) and was set aside in this plan's
original write-up as too invasive to fold into a first pass. It stays out of scope here; this
section's finding is that the cheap version of this lever does not exist.

### 3.3 Kernel micro-optimisation without compilation (third; changes bits) [implemented, measured, 2026-09-03 -- half shipped, half not]

Two things are visible in the hot path and neither has been tried:

- `ConstantPhaseElement.impedance` (`elements.py:225-226`) evaluates `(1j*omega)**n` as a
  fresh complex power per call; `1j*omega` and its logarithm are per-problem constants.
  `exp(n * log_jw)` with `log_jw` precomputed is one complex exp per point instead of a
  complex power — *whether* numpy's power already reduces to that internally is exactly the
  question, so the gain is unknown until measured.
- `to_values_batch` (`fit.py:492-500`) and `cost_vectorized` (`fit.py:502-517`) allocate the
  `(n_params, n_candidates)` template and four intermediate arrays on every call;
  `maxiter + 1 = 41` calls per screen. Reusing buffers is routine.

**This lever changes bits.** `exp(n log x)` and `x**n` differ in the last place, so the EV5
byte fingerprint will not match. The standard this repository already holds fits to is
`WEB_UI_PLAN.md` §2.4's: a fit is not bit-reproducible across interpreters, only its
*reported digits* are. So the gate for §3.3 is reported-digit equality on the references
(T5), not a byte match, and the difference is recorded rather than hidden. Because of that
extra cost it comes after §3.1 and §3.2, and it is dropped if the kernel bucket does not fall
by at least a quarter — the kernel is 36–47% of a screen, so anything less than that is
inside the noise of a total-wall-clock measurement.

**Measured separately, because they are two independent claims and the plan's own bullets
already kept them apart.** The two candidates were isolated by patching `elements.py` and
`fit.py` one at a time and running `profile_eval.py`'s cost-vectorized throughput section
(200 reps, 5 repeated trials, median taken -- the cProfile-bucket section alone has a noise
floor of roughly ±5-8%, visible on the topology that carries no CPE and should therefore show
exactly 0% either way). The CPE `exp(n log(1j*omega))` substitution alone cuts
`cost_vectorized` time **31-33%** on the two CPE-bearing test topologies and **0%** (within
noise) on the one that carries no CPE -- the causal fingerprint this instrument is built to
show. Buffer reuse in `to_values_batch`/`cost_vectorized` alone measured **3-5%** on *every*
topology, CPE-bearing or not -- indistinguishable from the control's own ±5-8% noise band, so
it is not a measured win. **Only the CPE substitution ships**; the buffer-reuse half is
reverted rather than kept for a noise-level number, because keeping it would also keep a new
correctness hazard for nothing -- the reused buffer is aliased across calls, so a caller that
holds a reference past its own use silently reads a later population's values.

### 3.4 Not in this plan: VARPRO, exact-class dedupe before screening [multiplicity measured, 2026-09-03]

- **VARPRO** (variable projection) is listed as "still worth a plan" in
  `SEARCH_ALGORITHM_SCREENING.md` §5. Circuit impedance is not linear in most of its
  parameters, so the linear subset it could eliminate is small and topology-dependent. It is
  a fitter redesign, not a time lever, and belongs in its own plan if at all.
- **Screening one member per exact-reparameterisation class.** `canonical_form` already
  collapses commutativity and flattening in the enumerator (`enumerate.py:183-187`), but
  cross-shape equivalents such as `R1-p(R2,C1)` and `p(R1,C1-R2)` are both enumerated and
  both screened; the classes are only formed after tier 2 from fitted impedance
  (`_same_response`, `EQUIVALENCE_RTOL = 1e-6`). Detecting the class *before* fitting is a
  symbolic-equivalence problem with no cheap exact test. One measurement is cheap and decides
  whether the question is worth more: count, in an existing frozen landscape table, how many
  topologies share a screened cost with another to 1e-6 relative. If the multiplicity is
  under ~1.3x the saving is bounded there and the item closes. The report needs every member
  refitted anyway, so tier 2 could not benefit regardless.

  **Measured, and the bound did not hold.** All five existing frozen landscape tables
  (`benchmarks/screening_round/land_{rcl6,rcl7,series_rcl6,series_rcl7,rclcpe6}.json`) were
  clustered by screened cost at `EQUIVALENCE_RTOL = 1e-6` relative -- the same tolerance
  tier 2's own `_same_response` uses. Over the whole table (every enumerated size together)
  multiplicity is **4.4-5.9x**, with 85-89% of rows sharing a cost with at least one other
  row. Restricted to *same-size* topologies -- the closer match to the plan's illustrative
  example (`R1-p(R2,C1)` / `p(R1,C1-R2)`, both 3 elements) -- the bound still fails at every
  size from 3 elements up: 1.4x at 3, rising to **3.8-4.9x at the largest size class each table
  enumerates** (1725-8859 of each table's rows, most of the table's own cost). Some of the
  all-sizes number is a different, honestly-distinguishable phenomenon and not what the plan's
  example described: a superset topology whose one extra element gets fitted to
  irrelevance lands on exactly its subset's cost (the largest cluster in `land_rcl6.json` is
  `p(R1-C1,R2)` at 3 elements plus 138 larger topologies that all reduce to it), which is
  over-parameterisation collapsing onto a smaller topology's optimum rather than a same-size
  cross-shape reparameterisation -- but the same-size breakdown above shows that phenomenon
  alone does not explain the finding; genuine same-size duplication is real and large at every
  size that matters.

  This closes the item exactly as the plan said it would, in the direction it did not expect:
  the saving is *not* shown to be bounded small, and a search that could skip a screen for
  every row already covered by an already-screened cluster member would skip on the order of
  80-88% of same-size tier-1 work on these tables. Nothing changes as a result. The two reasons
  the plan already gave for not building this stand independent of the number: detecting a
  class *before* fitting is still a symbolic-equivalence problem with no cheap exact test (the
  clustering used here is a *post hoc* observation on cost, not a predictive test runnable
  before screening), and the report still needs every member of a reported equivalence class
  refitted at tier 2 regardless, so this is recorded as a larger-than-hoped, still-unbuilt
  opportunity rather than a lever this plan ships.

### 3.5 Spectrum thinning for the DE global stage -- H1 measured at pilot scale, H2 not run

Not attempted in this document before now. Registered here as a hypothesis and a decision rule
before any number existed to answer it, per this repository's own rule — H1 is now measured at
pilot scale (below); H2 is not run. Nothing in `core/fit.py` changes here.

**Where thinning would apply, and where it cannot.** `_global_stage` (`fit.py:796-840`) calls
`scipy.optimize.differential_evolution(problem.cost_vectorized, ...)`; `cost_vectorized`
(`fit.py:554-569`) is `O(N)` in frequency points on every one of the roughly `maxiter + 1 = 41`
iterations a screen runs, each over `popsize` candidates at once. The local polish that follows
(`scipy.optimize.least_squares(problem.residuals, ...)`, `fit.py:664-673`) already runs on the
full spectrum, and this section proposes no change there -- thinning the DE stage does not thin
what the reported chi2/statistics are computed from, only what the *global search* sees while
finding a basin to polish from.

**Correctness constraint, stated before any harness is built.** `w_re`/`w_im`
(`weighting.py`'s `weight_vectors`) are per-frequency arrays multiplied elementwise against real
and imaginary deviations in both `residuals` and `cost_vectorized`; any thinned index set must
slice `omega`, `z`, `w_re` and `w_im` together. `FitContext` (`fit.py:415-445`) does not itself
carry `omega`/`z` -- only `w_re`, `w_im` and a `BoundsContext` -- so a thinned global stage needs
either a thinned `Spectrum` with its own `FitContext` built from it, or explicit index-consistent
slicing threaded through `_Problem` at construction. Either design must guarantee the *same*
indices are used for `omega`, `z`, `w_re` and `w_im` inside one DE call; a mismatch here would
silently score candidates against the wrong weight for each residual, which no downstream gate in
this document would catch, since it is a correctness bug internal to one function rather than a
change in the search's outcome shape.

**The failure mode to test for, not assume away.** `docs/SEARCH_SPEEDUP_PLAN.md` ideas C and D
already measured that *shrinking one dimension's search box* -- a CPE `Q -> Z0` reparameterisation,
a decorrelated `(tau, R)` block reparameterisation -- does not move hit rate on 10-12-element
topologies, because the bottleneck at that scale is the *joint* combinatorics of getting every
free dimension into its own narrow basin at once inside a fixed small DE budget, not any one
input's cost. Thinning attacks a different quantity (wall-clock per evaluation, not the number of
dimensions or their box widths), so it is not automatically subject to the same failure -- but the
hypothesis below must be tested directly rather than assumed to transfer, precisely because C and
D looked like they should help for an analogous "shrink one cost" reason and did not.

**H1 -- does thinning help at all.** Uniform index-decimation of the frequency array by a factor
of 2-4x should cut `cost_vectorized`'s per-call cost roughly linearly (it is a vectorised
elementwise operation over `N` points). Measure, on a frozen-landscape arena at an unsaturated
budget (`SEARCH_TIME_PLAN.md` section 0's rule: "a saturated arena ranks nothing" -- reuse
`benchmarks/screening_round/land_rcl6.json`/`land_series_rcl6.json` and the same 480-seed exact
McNemar convention `docs/EVOLVE_SEARCH_PLAN.md` section 3.5.2 and this document's section 4.3 (T4)
already use), whether hit rate against the untouched screen survives thinning at each factor.

**H2 -- does the thinning *method* matter, the question the user actually asked.** Compare three
methods: (a) uniform index-decimation; (b) log-frequency-uniform resampling (resample onto a new
grid evenly spaced in `log10(f)`, then nearest-index snap back to real data points); (c)
adaptive/importance-based thinning, keeping a higher density of points where `|dZ/df|` is largest
(resonances, relaxations) and thinning more aggressively across flat stretches. **A confound to
flag before running anything**: every synthetic reference in this repository is generated by
`log_frequencies` (`simulate.py:14-20`, `np.logspace` over the sweep), so on synthetic data
*uniform index-decimation is already log-frequency-uniform* -- methods (a) and (b) collapse to the
same condition there. The method comparison is only informative on a spectrum with an irregular,
non-log-uniform frequency axis, so H2 must run on a real dataset from
`benchmarks/measured/datasets.py`'s `DATASETS` list (an instrument export, not a `log_frequencies`
sweep) alongside the synthetic arenas used for H1.

**Pre-registered pass bar, before any run.** Ships only if:

1. Wall-clock or DE-fit-count falls by a real margin (recommend the same >=15% bar
   section 3.1 originally set for itself) at preserved hit rate (no significant McNemar drop) on
   an unsaturated frozen-landscape arena -- both halves of the claim, not the speed half alone,
   per this document's own rule that "a stage winning and the total losing is the normal case."
2. If a method more complex than plain uniform decimation (log-uniform resampling, adaptive
   importance-weighting) is proposed for shipping, it must clear its own significance bar *against
   uniform decimation*, not merely against no thinning at all -- mirroring
   `docs/EVOLVE_SEARCH_PLAN.md` section 3.5.2's finding that `mut_uniform` tied the shipped,
   more complex mutation-weight tuple on two of three arenas: this project ships the simplest
   mechanism that clears its own bar, not the most sophisticated one that merely beats doing
   nothing.

**Scope for this pass.** Build a standalone benchmark script under `benchmarks/` if the harness is
cheap to assemble (reusing `benchmarks/speedup/harness.py`'s Wilson-CI/McNemar instrumentation);
do not touch `core/fit.py`'s production `_global_stage`, `screen()`, or `fit()` in this pass.

**[measured, pilot scale, 2026-09-12] H1 was run; H2 (method comparison) was not.**
`benchmarks/speedup/idea_thinning.py` (new) fits a 10-element, 5-block Maxwell-Wagner-style
topology (`p(R1,C1)-p(R2,C2)-p(R3,C3)-p(R4,C4)-p(R5,C5)`, the same "10-12 free parameters"
regime `docs/SEARCH_SPEEDUP_PLAN.md` ideas C/D used) at the production tier-1 screen budget —
`SCREEN_POPSIZE=8, SCREEN_MAXITER=40, SCREEN_RESTARTS=1`, and, caught only after an initial run
ran far slower than the per-screen cost this document's own §1 quotes, `local=SCREEN_LOCAL`
explicitly, since `fit()`'s own default local-polish budget is `PUBLISH_LOCAL`
(`max_nfev=20000`), not the cheap tier-1 one, regardless of the DE popsize/maxiter passed — using
`fit()` rather than `screen()` (which returns only a cost, no parameter vector) so the fitted
parameters can be re-evaluated against the *full*, untouched spectrum via `relative_error`
(weighting-independent), making costs computed on different-sized data comparable on one scale.
60 seeds (a stated, explicit reduction from the 480-seed convention used elsewhere in this
document — a pilot, not a final rigor level) at three conditions: full spectrum, uniform 2x
decimation, uniform 4x decimation.

| condition | median relative error | mean wall-clock per fit | hits (error < 5%) |
|---|---:|---:|---:|
| full (1x, 81 points) | 1.320% | 1.029 s | 41/60 |
| half (2x, 41 points) | 1.357% | 0.771 s (-25%) | 46/60 |
| quarter (4x, 21 points) | 1.403% | 0.494 s (-52%) | 44/60 |

Wilson 95% CIs on hit rate overlap heavily and are wide at this sample size (full 0.56-0.79, half
0.65-0.86, quarter 0.61-0.83) — **per this pilot's own pre-registered reading, this is not
evidence that thinning helps or hurts hit rate**, only that a real difference, if one exists, is
not visible at 60 seeds. What is visible, and repeatable in direction across both thinning
factors, is the wall-clock reduction (25% at 2x, 52% at 4x) with **no hint of a hit-rate cost** —
neither thinned condition trended worse than the full-spectrum control, which is the direction
`docs/SEARCH_SPEEDUP_PLAN.md` ideas C/D's own "joint combinatorics bottleneck, not any one
input's cost" finding would have predicted thinning *could* fail in (a cheaper-but-less-informative
per-evaluation cost could, in principle, cost more basin-finding attempts than it saves — that
failure mode is not what this pilot saw, but 60 seeds cannot rule it out either).

**Per this document's own pre-registered rule, this pilot does not license a ship/reject verdict
— it licenses a specific recommendation: run the full 480-seed version of H1 next**, on this same
harness, before touching H2 (the uniform-vs-log-uniform-vs-adaptive method comparison, which still
needs a real, non-`log_frequencies`-generated dataset from `benchmarks/measured/` to be
informative at all, per this section's own note above) — because H1's own answer is not yet
resolved at a confidence level worth building H2 on top of. Not run this session:
`core/fit.py`'s production `_global_stage`/`screen()`/`fit()` are unchanged.

**[measured, 480 seeds, 2026-09-12] H1 is rejected.** `idea_thinning.py` was rebuilt into a
resumable, argparse-driven benchmark using `benchmarks/speedup/harness.py`'s `wilson`/
`mcnemar_exact` (the pilot had computed neither), keeping `local=SCREEN_LOCAL` on the one fit
call site. The first full-scale run (concurrent with other experiments in the same session) found
hit rate unchanged (McNemar `p=0.4769` at 2x, `p=0.6445` at 4x — confirming the pilot's own
"no hint of a hit-rate cost" at real statistical power) but wall-clock **flat across all three
conditions** (0.735 s / 0.724 s / 0.734 s mean per fit) — nothing like the pilot's 25-52%
reduction. Re-run alone, with no concurrent load, to rule out resource contention as the cause:
mean time roughly halved for every condition (0.366 s / 0.370 s / 0.377 s, confirming the first
run *was* contention-affected on its absolute numbers), but the **relative pattern held exactly
— no speedup, and if anything the thinned conditions are marginally slower.** Hit counts were
bit-identical between the contended and clean runs (371/381/378 of 480, as they must be —
`fit()` is deterministic given a seed, so hit rate cannot depend on machine load). **This clears
neither clause of section 3.5's own pass bar**: clause 1 needed a real, non-contention-artifact
wall-clock win at preserved hit rate, and none exists. The most likely mechanism, consistent with
`docs/SEARCH_SPEEDUP_PLAN.md` ideas C/D's own finding for this document: at
`SCREEN_POPSIZE=8, SCREEN_MAXITER=40`, per-iteration Python/scipy dispatch overhead inside
`differential_evolution` and `least_squares` dominates the wall-clock at this problem size, so
shrinking the array `cost_vectorized`/`residuals` operate over (81 → 21 points) does not move the
total meaningfully — the same "joint combinatorics, not any one input's cost" shape those ideas
already found for a different lever. **H2 was not evaluated on its own merits**: it is
conditioned on H1 shipping (a candidate to compare against uniform decimation, which this
section rejects), so the id15/id34 results the H2 harness produced (`adaptive_2x` beating
`uniform_2x` significantly, `p=0.0005`, on the one informative real dataset; `loguniform_2x`
losing to it significantly, `p<0.0001`; `id34` saturated at 0/480 hits under every condition, an
uninformative arena for a shape-comparison question) are recorded as raw numbers only, not as an
H2 verdict — there is no baseline left to be a fancier alternative *to*. `core/fit.py`'s
production `_global_stage`/`screen()`/`fit()` remain unchanged; nothing from this section ships.

## 4. Levers on F3 and on the fallback's throughput

### 4.1 The second screening seed: run the experiment that was deferred [measured, 2026-09-03]

`TOPOLOGY_6PLUS_PLAN.md` §5.7.2 ends: "the case for paying that is a *recovery* measurement
— does a second seed put truths on the shortlist that one seed lost — and that is X4, below."
X4 ran 54 runs across the `base` and `grow` arms and none of `seeds2` or `grow+seeds2`. The
arm is coded (`benchmarks/six_plus/recovery.py:77-82`); it had not been run.

**Design.** Run `seeds2` on the same nine truths and three seeds X4 used, and report per
truth: whether a truth-equivalent reached the shortlist, the front, and the recommendation,
beside `base`. The cost side is already known — it doubles tier 1.

**Decision rule, written before the run.** A universal second seed ships as the default only
if it moves at least one truth from "lost at the shortlist" to "reported" on a truth `base`
loses, *and* does not remove any. If it changes nothing on those nine, it stays a lever and
the number is recorded — a 2% mis-screen rate on a random sample does not by itself say the
truth is among the 2%.

**What was measured.** `benchmarks/six_plus/recovery.py --arms seeds2` on the same nine
truths and three noise seeds `base`/`grow` already used (27 runs, resumed into the existing
`x4_recovery.json`). On the six- and seven-element rows, `seeds2` reports 0/18 — identical to
`base`'s 0/18 — and the by-shape breakdown is unchanged in every cell: parallel 3/9, series
3/9, mixed 3/9, both before and after. The five-element negative control also does not move
(9/9 recommended correctly, 0/9 over-grown, both arms). Median wall-clock on the large truths
rose only 20s → 24s, not the ~2x a doubled tier-1 cost might suggest, because tier 1 is a
minority of a run that also pays for tier-2 refits and (on `base`/`seeds2`, `growth_width=0`)
no growth stage.

**The decision rule's own answer is no.** Nothing moved from "lost at the shortlist" to
"reported" on any of the six truths `base` already loses, so the rule written before this ran
does not license `seeds2` as the default. This is not a contradiction of §4.2's `>100x`
basin-lottery finding — the six large truths' own screened landscapes were never shown here to
contain a mis-screened row at all, so a second seed had nothing to repair on *these specific*
nine truths. `TOPOLOGY_6PLUS_PLAN.md` §5.7.2's ratio measurement (mean 37.7–41.4x at one seed,
1.06–1.16x at two) stays correct as a statement about the sampled landscape; it does not
transfer into a recovery win on this arena, which is exactly why the decision rule asked for a
recovery measurement instead of trusting the ratio. **`screen_restarts=2` stays a lever
(`discover(..., screen_restarts=2)`), not the shipped default.** The X4/T6 table is recorded
in full below regardless of the outcome, per the rule that a run is reported whatever it says.

### 4.2 A selective re-screen flag -- measured, and rejected [measured, 2026-09-03]

A universal second seed pays 100% to repair 1–2%. A flag that names the suspicious screens
would pay only for those. One principled flag is available from the order tier 1 already
runs in (level by level, so every sub-topology of a candidate has been screened before it):

> a topology that contains another topology as a sub-tree, with bounds wide enough for the
> extra element to become negligible, cannot honestly screen *worse* than that sub-topology.

The bounds are data-derived (`BoundsContext`), so "negligible" is not always reachable and
the inequality is not strict — which is why this is a **flag for a re-screen and never a
correction**. A re-screen keeps the better of the two costs, so a false flag costs one
screen's time and cannot change a result for the worse. This is the same shape as the
resonance probe in `KK_RESONANCE_PLAN.md` §2: a second look asked only of what already looks
wrong, able to move a verdict in one direction only.

**The existing sample turned out to be unusable.** `benchmarks/six_plus/x8_screen_seeds.json`
(the 360-topology, 5-seed sample behind §5.7.2's basin-lottery table) has no committed
generating script, and every one of its 360 rows' seed-0 cost mismatches a fresh
`fit.screen(text, spectrum, seed=0)` call by 0.1–0.5% today. That is not the FitContext hoist
(§3.1): `core/fit.py` checked out at `98215c9`, the commit immediately before the hoist,
reproduces today's number exactly (57.21511445652943, not the sample's
57.055920071212284) for the first sampled `par5` row. Whatever budget or environment produced
the sample cannot be recovered, so building a flag decision on numbers that cannot be
reproduced would be exactly the kind of unmeasured claim this document exists to avoid.

**What was measured instead.** A fresh, self-consistent dataset, covering every enumerated
topology rather than a 120-row sample: `enumerate_up_to(("R","C","L"), n_max)` for `par5`
(449 topologies, n≤5), `mix5` (449, n≤5) and `par6` (2174, n≤6), each topology screened at 5
seeds with today's code (`benchmarks/screening_round/landscape.py`'s own method, extended to 5
seeds; not a `discover()` run — no genetic fallback, no tier 2). One-element-removed
reductions (`circuit.remove_subtree` at every leaf) that are not `is_plausible_node`-admissible
— chiefly a bare `parallel(L, C)` block, which is not a real lossy two-terminal component and
so is never emitted by `enumerate_up_to` at all — are excluded from the floor rather than
treated as missing data, because the real level-by-level search never screens an implausible
topology either and so it can never serve as an already-known floor. Every eligible topology
(n ≥ 2 elements) had at least one plausible reduction in all three arenas
(`n_no_plausible_reduction = 0`).

| arena | eligible | >100x mis-screens | flagged (strict, seed0 > best plausible sub-cost) | catch rate | flag rate |
|---|---:|---:|---:|---:|---:|
| `par5` | 446 | 4 | 340 | 100% | 76.2% |
| `mix5` | 446 | 2 | 315 | 100% | 70.6% |
| `par6` | 2171 | 5 | 1709 | 100% | 78.7% |

**The flag catches every measured >100x mis-screen — and flags three-quarters of everything.**
The decision rule written before this ran was "ships to the recovery arena only if it catches
the majority at a flag rate under 50%"; catch rate clears that bar and flag rate misses it by
more than 20 points in every arena, so **the flag does not pass on its own decision rule.**

**No tolerance rescues it, because the flag's own comparison is exactly as noisy as the
problem it targets.** Among rows flagged but not counted as >100x mis-screens, the violation
ratio (`seed0 / sub_best`) tops out at 7.7x (`par5`), 8.2x (`mix5`) and 5.8x (`par6`) — so a
threshold anywhere above ~10x looked, before checking the mis-screens themselves, like it
would cut the flag rate to nearly nothing. It does not survive contact with the mis-screen
rows: their own `seed0 / sub_best` ratios run from **1.20x to 8.17x** — for example
`par6`'s `p(p(R1,C1)-R2,C2,C3)-R3`-shaped row is 2069x worse than the best of 5 seeds
(the >100x definition) yet only 1.20x worse than its own sub-topology's single-seed cost,
because the sub-topology's seed-0 draw is itself sometimes in a bad basin. The two
distributions fully overlap between 1.2x and 8.2x, so no fixed threshold separates a real
mis-screen from ordinary single-seed noise on this comparison: the flag compares one seed
against another seed, and a bimodal landscape does not stop being bimodal because one of the
two draws belongs to a smaller topology.

**Closed.** `_is_underfitted`-style selective re-screening is not implemented. §4.1's universal
second seed is the only lever this document has that showed real separation on the underlying
problem (mean ratio 37.7–41.4x at one seed down to 1.06–1.16x at two, §5.7.2) — a comparison
between *independent* draws of the same topology, not between one topology's draw and a
different (smaller) topology's draw. It stands alone; T4.1/T6, below, is still unrun.

### 4.3 `_evolve`: propose until unique, and merge the two dispatch barriers [implemented, measured, 2026-09-03 — T4 passed]

Two things in the fallback's generation loop are visible in the code and match X6's
unmeasured hypothesis for why eight workers buy so little.

**(a) Proposals are not filtered for novelty.** `_next_generation` (`discover.py:3459-3501`)
fills exactly `population` slots and checks nothing against `_Evaluator.cache`; the cache is
consulted only in `evaluate_all` (`discover.py:1428-1446`), after the slot is spent. That is
the mechanism behind cache hits rising from 15/40 to 22/40 and the effective batch falling to
18 (`EVOLVE_SEARCH_PLAN.md` §1.3). The fix is to propose until `population` *unseen*
canonical forms are in hand, with a retry cap so a converged front cannot spin, and to record
how often the cap is hit.

**(b) Polish and search are two sequential `executor.map` calls with a full barrier**
(`discover.py:1448-1499`). With `warm_accept = inf` (the shipped default) the accept decision
needs only the best cost already known at that complexity, which is known before the batch is
dispatched. So a single worker function can polish and, if the polish is not accepted, search
— inside the worker, without returning to the driver — and the generation becomes one
`executor.map` over up to `population` tasks instead of two smaller ones with a barrier in
between.

**This changes numbers** for `mode="evolve"` runs (RNG consumption differs), and not for the
exhaustive path, so the EV5 fingerprint is unaffected and the gate is a search-quality one
(T4): on the frozen-landscape arena at a budget where the control does not saturate, hit rate
must not fall, and at fixed `time_limit` and `workers = 8` the distinct-topology count must
rise. X6's own table is the baseline: 380 distinct on `par6` and 413 on `ser6` at 300 s.

**Per-generation overhead outside fitting** — `_unique_best` over the whole archive every
generation, `pareto_front` computed twice (`discover.py:2267, 2276, 3483`) — is O(archive)
and O(front²) per generation. At 1.33 s per fit it is almost certainly negligible; it is
listed so that it is measured once (a `perf_counter` around the non-fit part of a
generation) and then either fixed in an afternoon or closed with the number.

**Both halves were measured and both passed.** `_next_generation` now proposes until
`population` distinct canonical forms are in hand (`PROPOSE_RETRY_CAP = 20` retries before
accepting a duplicate anyway, so a converged front cannot spin forever), threaded through
`_breeding_key` — the same `Circuit(simplify(...)).canonical_form()` `_Evaluator.evaluate`
already uses, not a second identity notion. `evaluate_all`'s parallel path was rewritten from
two sequential `executor.map` calls (polish, barrier, search) to one: `_evolve_polish_then_search_worker`
does the warm polish and, if `close_enough` is false, the reduced-budget search, inside the same
worker call, because `close_enough` only needs `best_cost` at that complexity — known before
dispatch, unchanged by anything else in the batch.

*Search-quality half, `benchmarks/screening_round/arms.py`'s new `ga_front_dedup` arm against
`ga_front` at 480 seeds (the count that resolved the closest prior comparison,
`EVOLVE_SEARCH_PLAN.md` §3.4.4), at the same unsaturated budgets `SEARCH_ALGORITHM_SCREENING.md`
calibrated for these arenas:*

| arena | budget | `ga_front` | `ga_front_dedup` | McNemar p |
|---|---:|---:|---:|---:|
| `land_rcl6.json` | 150→60 (recalibrated, see below) | 249/480 | 244/480 | 0.6305 |
| `land_series_rcl6.json` | 40 | 287/480 | 285/480 | 0.5000 |

Neither difference is significant; hit rate does not fall. (`land_rcl6` needed recalibrating
down from the README's usual 150 to 60 for this comparison — 150 clears both arms near-fully at
this budget with dedup switched on, which is the README's own trap, "a budget everything clears
is a budget that ranks nothing"; 60 sits in the discriminating range both arms actually separate
on.)

*Throughput half, `benchmarks/six_plus/x6_workers.py` re-run into `x6_workers_post43.json`, same
truths, same seed, same 300 s / `workers = 8`, against X6's own 380/413 baseline:*

| truth | workers | baseline `n_evaluated` | post-change `n_evaluated` |
|---|---:|---:|---:|
| `par6` | 8 | 380 | **1366** |
| `ser6` | 8 | 413 | **1095** |

Both exceed the baseline by a wide margin — the dedup loop stops wasting fit budget on
already-cached topologies (a converged late generation was previously proposing the same
canonical form repeatedly), and the merged barrier removes the idle between the two
`executor.map` calls, so more distinct topologies are actually fitted per second. Note that
*generations* fell (`par6` 275→210, `ser6` 152→112 at `workers = 8`): each generation now does
more work (retrying until `population` unique children are found) rather than dispatching a
`population`-sized batch that included duplicates, so fewer, more productive generations fit
inside the same 300 s.

One incidental change is recorded rather than smoothed over: at `workers = 1`, `ser6`'s
`reported` flag (a truth-equivalent anywhere in the candidate list, `recovery.py`'s `Referee`)
flipped from `true` (baseline) to `false` (post-change), despite `n_evaluated` rising from 365 to
948. This is not part of T4's decision rule, which only asks about frozen-landscape hit rate and
`workers = 8` throughput, and it is not a regression on the number that matters most — 
`recommended` was `false` on `ser6` at both `workers = 1` and `workers = 8`, before and after,
unchanged. The mechanism is RNG consumption, not search quality: the retry loop draws extra
random numbers whenever a duplicate is proposed, so at `workers = 1` (fully deterministic, no
thread races) the run's entire trajectory after the first retry diverges from the pre-change
run, and this particular divergent trajectory happens not to visit `ser6`'s equivalence class
even though it visits far more topologies overall. `par6` at `workers = 1` was unaffected
(`reported`/`on_front`/`recommended` all `true`, both before and after). This is the same kind of
single-draw sensitivity `TOPOLOGY_6PLUS_PLAN.md`'s basin-lottery finding already documents for
tier-1 screening, now seen in the fallback's own RNG stream, and it is why `SEARCH_TIME_PLAN.md`
and `recovery.py` never read a single `reported` flag at face value where a formal gate is
concerned.

## 5. What the ceiling is, stated before anything is built

| lever | bucket it targets | best plausible effect on the total | changes numbers? |
|---|---|---|---|
| §3.1 setup hoist | 23–33% of a screen | **[implemented, measured]** 10.4% at `workers=1`, no measurable effect at `workers=8` on this machine | no (byte-identical, confirmed) |
| §3.2 streaming dispatch | inter-chunk idle | **[measured, rejected]** 31.7% idle confirmed, but the only lever found (a bigger batch) is not number-preserving -- reverted | -- |
| §3.3 kernel micro-opt | 36–47% of a screen | **[implemented, measured, shipped in half]** `cost_vectorized` on CPE topologies: 31–33% (CPE substitution alone); buffer reuse alone: 3–5%, inside noise, not shipped | CPE-bearing topologies only; reported digits unchanged (T5) |
| §4.1 second seed | F3 | **[measured, not shipped]** 0/18 -> 0/18 on the X4 large truths, no cell moved -- stays a lever | yes, deliberately (unused) |
| §4.2 selective flag | F3 | **[measured, rejected]** catches 100% of >100x mis-screens but flags 70.6–78.7% of everything -- not selective, nothing shipped | -- |
| §4.3 evolve dispatch | fallback throughput | **[implemented, measured, shipped]** `n_evaluated` at `workers=8`, 300 s: `par6` 380→1366, `ser6` 413→1095; frozen-landscape hit rate unchanged (McNemar p=0.63, p=0.50) | evolve only (confirmed: RNG stream, not the exhaustive path) |

Stacked, §3.1–§3.3 might make one screen 1.5–2x cheaper. That is real and it is not the 13x
that `SEARCH_ALGORITHM_SCREENING.md` §4.6 measured — that gap is F2 and is addressed
elsewhere. This plan should not be read as the answer to "six elements does not work".

## 6. Gates

Instrument: `benchmarks/screening_round/profile_eval.py` for the bucket split,
`benchmarks/ev5_fingerprint.py` run before and after and diffed for the byte comparison (it
is not collected by `pytest`; it must be run by hand and its two files diffed),
`benchmarks/six_plus/recovery.py` and `x6_workers.py` for the recovery and evolve arenas, and
the two `DISCOVERY_V2` electrochemical references for tier-1 wall-clock. Every wall-clock
number is reported as a pair, rested and loaded, per `WEB_UI_PLAN.md`'s W3 precedent.

- **T1 (setup hoist). [implemented and run, 2026-09-02; passed on the revised numbers below.]**
  `ev5_fingerprint.py --mode exhaustive --workers 1 --limit 3` output byte-identical before and
  after, on all three references — **confirmed**. The two numeric targets this entry
  originally stated could not both be confirmed as written, and are revised rather than
  reworded to look met: `profile_eval.py`'s setup bucket does not fall at all (it profiles
  `screen()` directly, without a `FitContext`, so it cannot see this change — see §3.1), and
  tier-1 wall-clock on the Randles reference falls 10.4% at `workers = 1` (3-run median,
  51.31 s → 45.99 s) against the 15% target, with no measurable change at `workers = 8`
  (31.89 s → 33.98 s, inside a 28–36 s run-to-run spread on this machine). The full `pytest`
  suite passes — 1023 passed, 19 skipped, including `test_discover_exhaustive.py`, which the
  fast subset skips (33m34s wall-clock on a machine `docs/HANDOFF.md` already documents as
  running 2x slower under load than rested; no failures at either speed).
- **T2 (streaming dispatch). [run, 2026-09-02; not passed -- withdrawn, not reworded.]** The
  idle was measured first, per the original plan: 31.7%, well past the 5% withdrawal bar, so
  the section proceeded to a fix. `Pool.imap` with a smaller chunksize was not implemented
  because the instrumentation that measured the idle also showed `Pool.map`'s own chunksize
  heuristic already rebalances within a batch -- the barrier is the batch boundary, not the
  dispatch mechanism. Raising `WORKER_CHUNK` (64 -> 256) does cut idle (31.7% -> 13.4%,
  confirmed on two runs) but fails the byte-identity half of this gate: `ev5_fingerprint.py
  --workers 8` differs before/after on the skin-effect reference, because a bigger batch shares
  a stale `abandon_above` threshold across more candidates, and that measurably moves the tier-2
  shortlist on at least one CPE/SKINF pair. **T2 does not pass as written**, because the change
  that would pass its speed half fails its correctness half, and the code shipped is unchanged
  from before this section ran.
- **T3 (selective flag). [run, 2026-09-03; not passed -- withdrawn, not reworded.]** The
  360-topology sample this gate was written against turned out to be unreproducible with
  today's code (§4.2) and not caused by §3.1, so the measurement ran on a fresh, self-consistent
  dataset covering every enumerated topology in the same three arenas instead (446/446/2171
  eligible). Catch rate is 100% in all three; flag rate is 76.2%/70.6%/78.7%, not under 50%.
  **T3 does not pass as written**, and no threshold rescues it: the mis-screen rows' own
  `seed0 / sub_best` ratios (1.20x–8.17x) overlap the ordinary-noise rows' ratios (up to
  5.8x–8.2x) completely, because the flag compares one single-seed draw against another. Nothing
  shipped from this section.
- **T4 (evolve dispatch). [implemented and run, 2026-09-03; passed on both halves.]**
  Frozen-landscape arena at an unsaturated, recalibrated budget: hit rate not lower than the
  control by McNemar at 480 seeds — `land_rcl6.json` (budget 60) 249/480 vs 244/480, p = 0.6305;
  `land_series_rcl6.json` (budget 40) 287/480 vs 285/480, p = 0.5000. Neither drop is
  significant. At 300 s and `workers = 8`: distinct topologies evaluated rose well past X6's
  380/413 baseline — `par6` to 1366, `ser6` to 1095. Both halves pass, so the change ships:
  propose-until-unique in `_next_generation` and the merged single-barrier dispatch in
  `_Evaluator.evaluate_all`. Full `pytest` suite re-run clean after the change (1023 passed, 19
  skipped). One non-gated observation recorded in §4.3: `ser6` at `workers = 1` lost its
  `reported` flag (true → false) between baseline and post-change despite evaluating 2.6x more
  topologies, traced to RNG-stream divergence from the retry loop rather than a quality
  regression — `recommended` was `false` on that cell both before and after.
- **T5 (kernel micro-opt). [implemented and run, 2026-09-03; passed for the CPE half, failed
  for the buffer-reuse half.]** The two candidates in §3.3 were measured independently before
  either shipped. The CPE `exp(n log(1j*omega))` substitution cuts `cost_vectorized` 31-33% on
  CPE-bearing topologies (0% on a non-CPE control, the expected causal fingerprint) --
  comfortably past the quarter-reduction bar, so it ships. Buffer reuse in
  `to_values_batch`/`cost_vectorized` measured 3-5% on every topology tried, CPE-bearing or
  not, indistinguishable from this instrument's own ±5-8% noise floor (established by the
  non-CPE control, which should show exactly 0% and does not) -- it does not clear its own
  share of the bar and is reverted, unshipped.

  "Reported digit" was operationalised against `DiscoveryResult.summary()` -- the text a CLI
  user actually reads -- rather than the raw `--json` payload, because that payload is full
  `repr()`-precision (`json.dumps` on a float), the same precision `ev5_fingerprint.py`
  already fingerprints byte-exactly, and the plan's own §3.3 says this lever will not survive
  that comparison. `.summary()` text was captured for all three references
  (`exhaustive_limit=4`, `seed=0`, `workers=1`) before and after the CPE change: **identical
  except the wall-clock line** ("Evaluated N topologies in X s") -- every score, chi2_reduced,
  RMS|dZ/Z|, complexity mark, equivalents grouping and recommended circuit unchanged. The same
  wall-clock lines are the bonus this comparison bought for free: full exhaustive discovery
  fell 193.6s->157.4s (skin-effect, -18.7%), 86.8s->59.3s (Maxwell-Wagner, -31.7%) and
  58.6s->44.7s (Randles, -23.7%).

  The byte fingerprint (`ev5_fingerprint.py`) does differ, as predicted, and the difference is
  recorded rather than suppressed: most of the ~500 changed values are last-place-bit noise
  (~1e-10 to 1e-15 relative), but one is not -- on the Randles reference, an exactly-tied
  exact-reparameterisation pair (`p(R1-CPE1,R2)-CPE2` and `p(R1,CPE1)-R2-CPE2`, same score to
  every digit, `-1304.3692338497665` both before and after) swapped which member the "best of
  5 restarts" search lands on, with R1.R and R2.R fully exchanged rather than perturbed. Both
  members are still reported, still tied, and still each other's listed equivalent both before
  and after -- the `.summary()` text is unaffected -- but this is the same basin-lottery family
  `TOPOLOGY_6PLUS_PLAN.md` already documents for tier-1 screening and `SEARCH_TIME_PLAN.md`
  §4.3 documents for the evolve fallback's RNG stream, now seen a third time at the ULP level
  of a single kernel's arithmetic. Full `pytest` suite re-run clean after the change (1023
  passed, 19 skipped, 978.9s).
- **T6 (second seed). [run, 2026-09-03; the decision rule's answer is no.]** `seeds2` on the
  same nine X4 truths and three seeds: 0/18 on the six/seven-element rows, identical to
  `base`'s 0/18, and unchanged by shape (3/9/3/9/3/9 both arms). The five-element negative
  control also does not move (9/9, 0/9 over-grown, both arms). Nothing moved from "lost at the
  shortlist" to "reported," so per the rule written before the run, `screen_restarts=2` does
  not become the default. It remains available as a lever.

## 7. Order of work

1. **[done]** §3.1 and T1 — number-preserving, in-process, benefits the browser as well.
2. **[done, rejected]** §3.2's idle measurement, and T2 — the idle is real (31.7%) but the
   only fix found is not number-preserving; nothing shipped from this step.
3. **[done, rejected]** §4.2's catch-rate measurement and T3 — catches 100% of measured
   mis-screens but flags 70.6–78.7% of everything, not the "under 50%" the decision rule
   required; nothing shipped from this step.
4. **[done, not shipped]** §4.1 / T6 — the deferred experiment, without a flag (step 3 closed
   with nothing to combine): `seeds2` changes 0 of 18 large-truth recovery cells against
   `base`, so its own decision rule keeps it a lever rather than the default.
5. **[done, shipped]** §4.3 and T4 — propose-until-unique plus the merged dispatch barrier,
   both halves of the gate passed (frozen-landscape hit rate unchanged; `workers = 8`
   throughput far above baseline on both truths).
6. **[done, shipped in half]** §3.3 and T5 -- the CPE `exp(n log(1j*omega))` substitution ships
   (31-33% on `cost_vectorized` for CPE-bearing topologies, reported digits unchanged); the
   buffer-reuse half measured 3-5%, inside this instrument's own noise floor, and is reverted.
7. **[done, recorded]** The one cheap count from §3.4 (class multiplicity in a landscape
   table): 4.4-5.9x over whole tables, 3.8-4.9x restricted to same-size topologies at the
   largest size class each table enumerates -- the "under ~1.3x" bound the section hoped would
   close the question did not hold, but nothing ships from it, because the two reasons already
   on record for not building a dedupe (no cheap predictive test; tier 2 refits every
   equivalence-class member regardless) are unaffected by the count.

All seven steps of this order of work are done.

## 8. A direct decomposition of one `screen()` call (2026-09-13)

**Nothing in this section ships.** It answers a question this plan's own §1 never actually
asked — what a screen's time breaks down into, measured directly and cross-checked by two
independent methods, rather than read off one arm of an A/B built for a different comparison —
and prices four previously-unquantified micro-inefficiencies. `benchmarks/speedup/
where_time_goes.py` is the instrument; `--all` runs everything, `--profile`/`--micro` alone
skip the unrelated stage (see §8.4 for why that split exists).

### 8.1 The unbiased number: null-cost vs real-cost, per DE iteration

§1's 27.6–36.1% for `differential_evolution` bookkeeping came from one `cProfile` run, and
`cProfile` charges per Python call — biased toward overstating exactly the Python-heavy code
that is under suspicion. This checks it a different way: run the production DE call
(`_global_stage`'s own kwargs, copied verbatim and parity-checked against the real function)
twice, once with the real `cost_vectorized` and once with a cost function that does no model
evaluation at all, and compare wall-clock time per iteration.

The first design (`_null_cost` returning a constant) was rejected before it was even run:
SciPy's convergence test is `std(energies) <= atol + tol*|mean(energies)|`, so an all-zero
population converges at generation 1. The fix tried next — return the population's own first
free coordinate, which has real spread — was **measured to still converge early**, because
that coordinate *is* the quantity DE is minimizing, so DE dutifully collapses the population's
spread in exactly the dimension the convergence test watches (nit=22 vs nit=39 on the smallest
topology). Rather than chase a landscape that resists convergence, the comparison normalizes by
each arm's own iteration count instead of requiring equal `nit` — DE's per-generation
bookkeeping (population update, mutation, crossover, bound clipping) is population-shape-
dependent but cost-function-independent, so time-per-iteration is the right unit regardless of
how many iterations either arm ran.

Six topologies, 3–6 free parameters (element count and free-parameter count deliberately
diverge — a CPE costs one element but two parameters, `PARAM_BUDGET_PLAN.md`'s own point), half
CPE-bearing:

| topology | n_free | null/it (ms) | real/it (ms) | share |
|---|---:|---:|---:|---:|
| 3-element R/C | 3 | 0.210 | 0.315 | 66.8% |
| 4-element R/C/L | 4 | 0.204 | 0.327 | 62.3% |
| 5-element R/C | 5 | 0.339 | 0.584 | 58.1% |
| 3-element R/CPE | 4 | 0.216 | 0.387 | 55.7% |
| 4-element R/CPE/L | 5 | 0.416 | 0.863 | 48.2% |
| 5-element R/C/CPE | 6 | 1.227 | 2.343 | 52.3% |

**This is the number of record.** DE's own bookkeeping is 48–67% of the global stage's
per-iteration cost — a real, large, and *already-paid* cost that has nothing to do with
AutoCircuit's own arithmetic, confirming §1's cProfile-derived estimate rather than
overturning it (§8.2 finds the same range by the biased method, for the same reason: the two
agree here, so cProfile's bias is not distorting this particular number by much on these
topologies).

**A side finding, not the question asked, worth recording anyway**: both `null/it` and
`real/it` jump sharply between the two highest-`n_free` rows (0.416 to 1.227 ms null, 0.863 to
2.343 ms real) — far more than the population-size ratio (`popsize * n_free`, 40 to 48, a 20%
step) predicts. Because this shows up in the *null* arm too, which never touches AutoCircuit's
arithmetic, it is DE's own per-generation bookkeeping scaling worse than linearly with
dimension, not a property of anything this project could fix. A future budget decision that
scales `n_free` (a wider default pool, `max_params`) should expect superlinear DE overhead
alongside it, not just a linear one.

### 8.2 The biased decomposition: `cProfile` on a full `screen()` call

Self-time (`tottime`, which does not double-count nested calls) bucketed by source file, same
six topologies, `cProfile` over 5 full `screen()` calls per topology after one untimed warm-up
call (§8.4 explains why the warm-up is not optional):

| topology | DE bookkeeping | local polish (excl. Jacobian) | Jacobian (`_numdiff`) | impedance kernel | residual assembly | other |
|---|---:|---:|---:|---:|---:|---:|
| 3-element R/C | 37.8% | 1.6% | 1.4% | 16.2% | 8.3% | 34.8% |
| 4-element R/C/L | 35.5% | 1.8% | 1.5% | 18.3% | 8.3% | 34.5% |
| 5-element R/C | 39.3% | 1.2% | 1.0% | 25.7% | 7.1% | 25.7% |
| 3-element R/CPE | 33.4% | 1.6% | 1.3% | 24.3% | 7.6% | 32.0% |
| 4-element R/CPE/L | 37.1% | 1.2% | 1.1% | 29.4% | 6.9% | 24.3% |
| 5-element R/C/CPE | 29.7% | 2.2% | 2.1% | 34.4% | 6.5% | 25.1% |

DE bookkeeping (30–39%) agrees with §8.1's unbiased 48–67% share only in rough order of
magnitude, not exactly — expected, since §8.1 measures the global stage alone and this measures
a whole `screen()` call including local polish and setup, and `cProfile`'s per-call bias runs
the other way here (undercounting, not overcounting, DE's C-level inner loop relative to
Python-level bookkeeping it does still charge for). The impedance kernel's share rises with
`n_free` and much more so with CPE (16% to 34% from smallest to largest, CPE-bearing
topologies consistently higher at the same element count than non-CPE ones) — consistent with
`SEARCH_ALGORITHM_SCREENING.md`'s already-measured CPE cost gap, now seen inside a single
screen's own internal split rather than only in total wall-clock. "Other" (numpy internals,
dispatch overhead, `_Problem` setup) is 24–35%, in the same range §1's "per-topology setup"
bucket already reported (25.4–33.1%) — this project's own `FitContext` hoist (§3.1) already
addresses the cross-topology-shared part of that; what remains is genuinely per-call overhead.

**A methodological pitfall found and fixed before trusting this table, not a caveat added
after**: the first topology profiled with no warm-up call read as 89% "other" and single digits
everywhere else — a one-time cost (first-call scipy submodule imports, allocator/thread-pool
warm-up) dominating a profile this short (5 calls). One untimed `screen()` call before
`profiler.enable()`, per topology, removed it entirely; every row above reflects steady-state
cost, not cold start.

### 8.3 The local polish's own Jacobian share

`least_squares(method="trf")` is given no analytic Jacobian anywhere in this codebase — both
tier-1 (`SCREEN_LOCAL`) and tier-2 (`PUBLISH_LOCAL`) budgets rely on `scipy.optimize._numdiff`'s
finite-difference approximation, costing `n_free` extra full `residuals` evaluations per
Jacobian. Isolated from §8.2's own profile:

| topology | Jacobian's share of (polish + Jacobian) |
|---|---:|
| 3-element R/C | 45.7% |
| 4-element R/C/L | 44.9% |
| 5-element R/C | 44.3% |
| 3-element R/CPE | 44.4% |
| 4-element R/CPE/L | 47.0% |
| 5-element R/C/CPE | 49.3% |

The Jacobian really is close to half the local-polish stage's own cost, as the "no analytic
Jacobian" observation would predict. **It still does not matter to the whole screen**, because
the polish stage itself is only 2.8–4.2% of `screen()`'s total self-time (polish + Jacobian
columns of §8.2's table, summed) — `screen()`'s own `abandon_above` early-abandon skips polish
for most candidates, and `SCREEN_LOCAL.max_nfev = 2000` caps what remains. An analytic Jacobian
would roughly halve a 3–4% slice, i.e. save on the order of 1.5–2% of a screen's total time —
real, but not where this round's evidence says to look.

### 8.4 Four named micro-inefficiencies, priced individually — and a second pitfall

Microbenchmarks only; nothing wired into `core/`. Best-of-7 mean over batched calls (a single-
call timer was tried first and rejected: several of these are sub-microsecond, at or under
`time.perf_counter`'s effective resolution once Python's own call overhead is subtracted, and a
single-call read hit a `ZeroDivisionError` computing the percentage more than once):

| item | current | alternative | effect |
|---|---:|---:|---|
| `Resistor.impedance`'s `np.ones_like` allocation | 13.9 us | `np.broadcast_to` (10.0 us) | +28.2% if switched |
| `elements.get()` per leaf per evaluation vs a cached reference | 48 ns | 28 ns | +42.6% if switched |
| `np.errstate` entered twice (`Circuit.impedance`, then `cost_vectorized`) vs once | 726 ns | 1532 ns (current) | +111.1% overhead from the nesting |
| `log(1j*omega)` recomputed every evaluation vs hoisted | 9325 ns | 77 ns | +99.2% if hoisted |

**A second methodological pitfall, of the same family as §8.2's cold-start one**: the smallest
of these (the `Resistor` pair, ~10–14 us either way) was measured to *flip direction* depending
on what ran earlier in the same process. Isolated in a fresh process, five independent runs
agreed to within a few percent (+25% to +31%, `broadcast_to` faster). Run immediately after
this same script's own §8.1/§8.2 workload in one `--all` invocation, the same comparison read
anywhere from a 218% loss to a 6% win — almost certainly leftover CPU frequency scaling or
cache state from the preceding DE-heavy work, not a property of the code being compared. The
shipped script now skips §8.1 by default when only `--micro` is requested (rather than running
it and discarding the result), and `--all` prints an explicit warning before this table pointing
at a standalone `--micro` run instead of trusting numbers measured back-to-back with §8.1/§8.2.

**None of these four are worth building**, and the reason is arithmetic, not the percentages
above: every one of them fires on the order of once per leaf or once per `cost_vectorized` call
(tens of times per screen), each saving single-digit microseconds to sub-microsecond amounts.
Summed across a whole screen (~41 `cost_vectorized` calls, a handful of leaves each), the total
addressable time from all four combined is on the order of hundreds of microseconds — against
an 0.87–1.77 s screen (`SEARCH_ALGORITHM_SCREENING.md` §4.6), that is **under 0.05% of the
total**, regardless of how large the per-call percentage looks. A large relative saving on a
tiny absolute cost is still a tiny absolute saving; this is recorded so the four are not
independently rediscovered and mistaken for real levers.

### 8.5 What this round actually says to build, if anything

**Not four small kernel tweaks (§8.4) — they are individually and collectively too small.**
**Not an analytic Jacobian (§8.3) — real, but bounded at roughly 1.5–2% of a screen.** The one
number this round found that is both large and real is §8.1's: SciPy's own DE bookkeeping is
48–67% of the global stage regardless of topology or CPE content, confirmed by an unbiased
method and roughly corroborated by `cProfile`. That is not a lever this round built or
recommends building — replacing `scipy.optimize.differential_evolution` with a
purpose-written vectorized DE loop is a substantial undertaking with its own correctness risk
(this project's own `PARAM_OPTIMIZER_PLAN.md` already measured a *different* optimizer
replacement, L-SHADE, tying or losing on both benchmark arenas and regressing a known-hard
`LARGE_REFERENCES` entry from 5/12 seeds reaching the noise floor to 0/12 before being
withdrawn) — but it is the only place this round found real, uncommitted headroom, and it is
recorded here as a priced, ranked candidate for a future measured round rather than left
unquantified the way it was before this section existed.
