# Computation-skipping in the genetic fallback

Status: **section 3.1 (idea 2c integration) built, measured, and shipped (2026-09-13) — the
broad, steady-state scope; section 3.2 built, measured, and rejected (2026-09-12); section 3.4's
cheap proxy count also ran (2026-09-12); section 3.3 remains plan-only.** Section 3.2
(early-abandon extension) was implemented, verified correct at reduced scale (3-seed A/B,
byte-identical `recommended`/Pareto front), measured for speed on a real 99-call batch (3.5%
wall-clock reduction, far short of a meaningful win), and **reverted** rather than shipped unused,
per its own pre-registered rule — see section 3.2 below for the numbers. Section 3.1 is the one
item of the original four that needed a genuine architecture change to `_evolve`'s dispatch/
population model, deliberately given its own session rather than attempted alongside the other
three: `evolve_plan` is now a true steady-state (overlapping-generation) proposer, both CLI and
browser drivers rebuilt on the new sliding-window protocol, both gates (480-seed McNemar quality,
`workers=8`/300s throughput) passed decisively (`par6`/`ser6` roughly doubled `n_evaluated`) — see
section 3.1 below for the full numbers. Section 3.3 (the dispatch-order proxy) still depends on
3.1's continuous-dispatch prototype per its own text, which now exists in production rather than
only as an isolated benchmark, and was not attempted this round either. Section 1 is a
survey of what already ships, verified against `src/autocircuit/core/discover.py` and
`src/autocircuit/core/fit.py` as they stand today (line numbers may drift further; re-locate by
symbol name if they no longer match). Section 2 restates, without re-measuring, what
`docs/SEARCH_SPEEDUP_PLAN.md` already settled about compute-skipping specifically, so this
document does not re-litigate closed items. Written 2026-09-12.

## 0. Scope

`docs/SEARCH_TIME_PLAN.md` §0 gives the accounting this document inherits:

    time to answer  =  F1 (seconds per topology evaluation)
                    x  F2 (topologies visited before the answer)
    and F3 (does a visit score correctly) decides whether F2 is finite at all.

This document is about **F1** for the genetic fallback specifically —
`core/discover.py`'s `_evolve`/`evolve_plan`, which `discover(mode="auto")` escalates to once the
element count passes `DEFAULT_EXHAUSTIVE_LIMIT = 5` (`discover.py:419`) and `_is_underfitted`
(`discover.py:2611`) finds the exhaustive stage's own result wanting. F2 levers for this same
fallback (bounding the breeding pool, the growth stage, mutation-weight tuning) are already
covered by `docs/EVOLVE_SEARCH_PLAN.md` and `docs/TOPOLOGY_6PLUS_PLAN.md` and are only cited here,
never re-argued. "Compute-skipping" means: doing less arithmetic to reach the same answer — a
cache that avoids a repeated fit, a dedup that avoids a repeated proposal, an early-exit that
avoids finishing a fit already known to be hopeless — as opposed to changing which topologies are
visited at all.

Two rules carry over from `docs/SEARCH_TIME_PLAN.md` §0 and bind every proposal in section 3:

- **A stage winning and the total losing is the normal case, not the exception.** Any proposal
  below that reports a stage-level saving must also report the total wall-clock or fit-count
  effect, never the stage number alone.
- **A saturated arena ranks nothing.** Every comparison below runs at a budget the control does
  not already clear near-completely, per `docs/EVOLVE_SEARCH_PLAN.md` §3.4.4's finding that all
  eleven arms tie at a 900-fit budget and separate at 150.

## 1. What the genetic fallback already skips

### 1.1 Canonical-form cache, best-wins, persists across generations

`_Evaluator` (`discover.py:1548-1801`) carries `cache: dict[str, Candidate | None]`
(`discover.py:1577`), keyed by `circuit.canonical_form()` (`discover.py:1594`, and again at
`discover.py:1733` in the parallel path). `evolve_plan`, the generator form the browser will
eventually drive the same way it already drives exhaustive search, keeps the identical structure
as a local variable rather than a dataclass field: `cache: dict[str, Candidate | None] = {}`
(`discover.py:2690`), looked up the same way at `discover.py:2716-2718`.

The cache is **best-wins, not first-wins**, which the class's own docstring calls "the half of
this that is easy to miss" (`discover.py:1557`): `_cheaper(a, b)` (`discover.py:1498-1511`)
compares two fits of the *same* topology by raw residual cost — not by `Candidate.score`, because
same topology means same `k` and `n`, so every criterion in `stats.CRITERIA` is monotone in cost
and the comparison needs no criterion at all — and keeps the lower-cost one. `evaluate`
(`discover.py:1613`) and `evaluate_all` (`discover.py:1794`) both fold every fresh fit through
`_cheaper(candidate, known)` before writing the cache back, so a topology re-proposed by a second
parent with a different warm start is not simply skipped: it is refit and the better of the two
results is kept. [`docs/EVOLVE_SEARCH_PLAN.md` §1.3] over half of each late generation re-proposes
an already-evaluated topology, which is what makes this cache load-bearing rather than incidental.

### 1.2 Propose-until-unique breeding with a bounded retry

`_next_generation` (`discover.py:4315-...`) does not accept whatever `mutate`/`crossover` hands
back. Each of the `population - len(elite)` remaining slots retries up to `PROPOSE_RETRY_CAP = 20`
times (`discover.py:306`, loop at `discover.py:4353`) against `known: AbstractSet[str]` — the
caller's `_Evaluator.cache` keys — using `_breeding_key` (`discover.py:4303-4312`), which computes
the *same* `Circuit(simplify(node)).canonical_form()` the evaluator's own cache key is, so the
breeding loop's notion of "already seen" and the cache's are never allowed to disagree
(`discover.py:4304-4305`). The elite carried over from the Pareto front are deliberately exempt
from this retry — re-proposing them unchanged is the free cache hit the evaluator is built to
expect, not the accidental duplicate this guards against (`discover.py:4342-4344`). The cap exists
because an unbounded retry can spin forever once a converged front has no unexplored one-mutation
neighbour left (`discover.py:303-305`).

This is not free of cost the way a pure cache lookup is — proposing costs cycles even when the
proposal is discarded — but it prevents a fit-shaped cost: without it, a slot spent on a duplicate
still reaches `_Evaluator.evaluate`/`evaluate_all`, which would re-fit or, at best, hit the cache
*after* the slot (and, in the parallel path, a dispatch round trip) was already spent on it. Before
this shipped, [`docs/SEARCH_TIME_PLAN.md` §4.3] "over half of each late generation re-proposes
something already evaluated" collapsed the effective batch to ~18 of `population = 40`. Measured
effect after shipping (`docs/SEARCH_TIME_PLAN.md` gate T4, `benchmarks/six_plus/x6_workers.py`,
300 s / `workers = 8`): distinct topologies evaluated rose from X6's own baseline of 380 to 1366
on `par6` and from 413 to 1095 on `ser6`, with frozen-landscape hit rate unchanged at 480 seeds
(McNemar p = 0.6305 on `land_rcl6.json`, p = 0.5000 on `land_series_rcl6.json`).

### 1.3 Two-tier screening — only tier-2 numbers are ever reported

The rule is stated three times in the module, in slightly different words, and quoted here rather
than paraphrased because it is the hard constraint every proposal in section 3 must respect:

> Tier-1 screening budget. Enough to rank thousands of topologies, nowhere near enough to
> publish: every number that reaches the user comes from the tier-2 refit.
> — `discover.py:124-125` (`SCREEN_POPSIZE`'s docstring)

> Both stages are tier 1 and neither is publishable: nothing this class returns reaches the user
> without `_refine` fitting it again at full budget.
> — `discover.py:1565-1566` (`_Evaluator`'s docstring)

> Only refitted candidates are reported, which is the rule `SCREEN_POPSIZE` states and the rule
> `_exhaustive` has always followed: every number that reaches the user comes from the
> full-budget refit. [measured, docs/EVOLVE_SEARCH_PLAN.md section 1.4] This search used to merge
> the unrefitted archive back in — `_unique_best(refined + alive)` — and 82% of the Pareto rows it
> reported then carried screening-grade chi-squareds, standard errors and therefore "free?" marks.
> — `discover.py:2929-2934`

Concretely: `_Evaluator._polish`/`_search` (`discover.py:1634-1653`) and the parallel worker
`_evolve_one` (`discover.py:1819-1901`) both call `fit()` at the reduced `SCREEN_POPSIZE` /
`SCREEN_MAXITER` budget and the `SCREEN_LOCAL` local-polish tolerance
(`discover.py:1673-1686`, `discover.py:1853-1863`, `discover.py:1879-1891`) — never
`PUBLISH_LOCAL`'s full tolerance for the tier-1 stage. Only after a generation's archive is
reduced to `_unique_best` and driven through `evolve_refit_plan` (`discover.py:2942-2944`) does
any candidate see the publication budget. Any compute-skipping idea in section 3 that touches
tier 1 changes only *which candidates survive to be refit*, never a number the report prints
directly — the same invariant `docs/SEARCH_TIME_PLAN.md` §4.3 leaned on for its own gate.

### 1.4 Warm-start / parameter inheritance with a "close enough" skip of the full search

`_inherited_values(parent, child)` (`discover.py:1451-1490`) carries a parent's fitted values onto
a child structurally — matched by element code and position after `simplify` has stripped labels,
never by label, because labels are renumbered from scratch on every `Circuit(simplify(node))`
call (`discover.py:1458-1464`). `_warm_start_for` (`discover.py:1514-1534`) wraps this with two
short-circuits: no parent or `warm_accept <= 0.0` skips warm-starting entirely
(`discover.py:1523-1524`), and a child whose inherited values are already *exactly* the cached
candidate's own values returns `None` — the common case of an elite re-proposed unchanged
(`discover.py:1528-1533`).

The expensive skip is `_close_enough` (`discover.py:1627-1632`, mirrored inline in `_evolve_one`
at `discover.py:1870-1874`): a warm-started local polish (`SCREEN_LOCAL`, no global stage,
`discover.py:1637-1647`) stands in for the reduced-budget global search entirely once its cost is
within `WARM_ACCEPT_FACTOR` of the best cost already known at that complexity. The shipped value
is `math.inf` (`discover.py:256`), which collapses the test to "is a reference cost known at all"
— once one is, the polish is trusted and the global search is skipped outright. [measured,
`docs/EVOLVE_SEARCH_PLAN.md` §3.3.1] the polish itself is 21% of the global search's cost in the
median at `SCREEN_LOCAL`, and the factor's own sweep (1.5, 3, 10, ∞) found no useful middle
setting — every finite value tested sat inside run-to-run spread, so "off" and "accept once there
is a yardstick" are the only two settings that mean anything (`discover.py:247-255`). [
`docs/SEARCH_TIME_PLAN.md` §4.3] this collapse is also what let the polish-then-search sequence
merge into one worker round trip without changing the accept decision's timing: at
`warm_accept = inf`, `_close_enough` needs only `reference`, known before dispatch, never the
polish's own outcome.

### 1.5 Breeding pool bounded to the Pareto front

`_breeding_pool` (`discover.py:4229-4285`) restricts what a generation may breed from to
`pareto_front(alive, criterion)` when `extra <= 0` (`discover.py:4268-4273`), and
`BREEDING_EXTRA = 0` (`discover.py:272`) is the shipped value. This is an F2 lever, not F1 —
it changes which topologies get bred, not how cheaply one evaluation runs — and is included here
only because it is a compute *reduction* by construction: bounding the pool below the whole
archive keeps `_tournament`'s draw-3-of-N cost from growing every generation
(`discover.py:4236-4240`). Already measured and shipped; see `docs/EVOLVE_SEARCH_PLAN.md` §3.4 for
the ladder (front alone 65/120 against front-plus-forty's 7/120 at an unsaturated budget) rather
than re-deriving it here.

### 1.6 No early-abandon exists in evolve's tier 1 — a verified asymmetry

The exhaustive path's screening function, `screen()` (`fit.py:716-820`), takes
`abandon_above: float = math.inf` (`fit.py:727`) and uses it to skip the local `least_squares`
polish outright when the global stage's raw cost already exceeds it (`fit.py:778-780`):

> `abandon_above` is the early-abandon switch: when the global stage alone already lands above
> that cost, the local polish is skipped and the raw global cost returned. A candidate that is
> two orders of magnitude worse than the best one of its size is not going to be rescued by a
> trust-region step, and skipping it is where most of the screening time is saved.
> — `fit.py:749-753`

`discover.py`'s own `ABANDON_FACTOR = 100.0` (`discover.py:169`) and `_abandon_at`
(`discover.py:4126-4136`) compute this threshold per complexity level, and it is threaded through
every exhaustive-path call site that screens: `ScreenTask.abandon_above`
(`discover.py:3950-3954`) is read by `_screen_one` (`discover.py:3909-3932`, passed at
`discover.py:3929`), and the same field is read again in the two parallel dispatchers,
`_screen_parallel` (`discover.py:4197`) and the growth-stage screening driver
(`discover.py:3864`), plus the skeleton mode's excluded-equivalents screen
(`discover.py:2555`). Every one of these five call sites is in the exhaustive, growth, or
skeleton screening path.

`_evolve_one` (`discover.py:1819-1901`) never calls `screen()` at all. It calls `fit()` directly,
twice — once for the warm polish (`global_search=False`, `discover.py:1853-1863`) and once for
the reduced-budget global search when the polish is not close enough
(`global_search=True`, `discover.py:1879-1891`) — and `fit()` (`fit.py:572-592`) has **no**
`abandon_above` parameter at all; it is not merely unpassed, it does not exist on that function's
signature. So this is not a case of a knob left at its default: early-abandon is structurally
unreachable from the evolve code path, because the function evolve calls (`fit()`) does not carry
the mechanism, and the function that does (`screen()`) is never invoked by `_evolve`,
`evolve_plan`, or `_Evaluator`. Confirmed by grepping every `abandon_above` reference in
`discover.py` and `fit.py`: none appears inside `_evolve`, `evolve_plan`, `_Evaluator`,
`_evolve_one`, or `_evolve_polish_then_search_worker`.

## 2. What `docs/SEARCH_SPEEDUP_PLAN.md` already settled about compute-skipping

Read in full before writing section 3, because it already measured (not merely argued) two ideas
directly on point for a genetic search, and this document does not repeat or re-run either.

**Idea 2e/F — subtree/canonical-form memoization. Rejected on measurement.**
(`docs/SEARCH_SPEEDUP_PLAN.md`, "Phase 2 — search-loop algorithm changes", idea 2e/F.) A
memoizing wrapper around `canonical_form` found real cache-hit rates (34.7% at `n=4`, 40.8% at
`n=5`, 1672 and 11160 calls respectively on `mw5`'s pool) and still made enumeration **37-42%
slower**, because a cache key exact enough to be correct (`repr(node)`, after a first attempt with
`hash(node)` was caught producing a non-identical topology set from a collision) costs as much to
compute as `canonical_form` itself — both walk the same tree. **Every new caching idea in this
document must budget for this exact risk before proposing to build anything**: a hit-rate number
alone is not evidence a cache will pay for itself; the cost of computing and comparing the key has
to be shown cheaper than what it replaces, not merely nonzero-hit.

**Idea 2c — asynchronous / barrier-less dispatch. Confirmed as a real win, not yet integrated.**
(`docs/SEARCH_SPEEDUP_PLAN.md`, "Phase 3 — larger algorithm changes", idea 2c.) 64 topologies with
genuine cost heterogeneity (32 CPE-bearing, 32 CPE-free, exploiting the ~2x per-fit cost gap
between them), dispatched at `workers=8` via a fixed-batch `ProcessPoolExecutor.map` (mirroring a
generation's synchronous barrier) versus `as_completed`-driven continuous dispatch: **33.6%
speedup, 8.90 s against 13.40 s**, past the pre-declared 15% bar. This is explicitly *not* the
same saving as `docs/SEARCH_TIME_PLAN.md` §4.3/T4 (section 1.2 and 1.3 above): T4 merged what
happens *inside* one candidate's dispatch (polish, then search, in one worker call instead of two
`executor.map` rounds); idea 2c targets the idle *between* generations caused by the slowest
candidate in a batch, a barrier T4 did not touch. **It was measured only at the level of an
isolated dispatch-mechanism test** — the script dispatches plain `screen()` calls, not the actual
`_evolve` population/selection loop — and was explicitly not integrated:

> the real change needed is replacing `_evolve`'s per-generation `executor.map`-style batch with
> a continuously-fed worker pool, which changes the population model materially (a candidate's
> parent selection would need to happen at proposal time rather than at a fixed generation
> boundary) and was not built this round.
> — `docs/SEARCH_SPEEDUP_PLAN.md`, idea 2c

This is the single most promising, cheapest-to-justify item for section 3: the mechanism's raw
speedup is already measured; what remains is the integration and a search-quality gate on the
real loop, not a re-derivation of whether asynchronous dispatch helps at all.

**Idea 5b — evolve archive/pool width. No effect measured.** Not a compute-skipping mechanism (it
changes which topologies breed, an F2 question), and already re-confirmed rather than merely
cited: wide (`extra=population//2`) against the shipped `extra=0` on `mw6`/`srf3`, 5 seeds each,
found no significant difference (McNemar p = 1.0000 both truths) — the same conclusion
`docs/EVOLVE_SEARCH_PLAN.md` §3.4 already reached. Mentioned here only so it is not mistaken for
an open compute-skipping question; it is closed and belongs to the F2 literature this document is
not about.

## 3. Proposed additions, not yet implemented

Ordered cheapest/highest-confidence first. None of these has been built or run. Every gate below
that references "480-seed McNemar" or a frozen-landscape table reuses the exact discipline
`docs/EVOLVE_SEARCH_PLAN.md` and `docs/SEARCH_TIME_PLAN.md` already established —
`benchmarks/screening_round/land_rcl6.json`/`land_series_rcl6.json` (or the same tables' `rcl7`/
`rclcpe6` siblings where a proposal needs CPE heterogeneity), the `ga_front`/`ga_front_dedup`-style
arm comparison in `benchmarks/screening_round/arms.py`, and an exact McNemar test at 480 seeds,
run at a budget recalibrated so the control does not already clear it (`docs/SEARCH_TIME_PLAN.md`
§4.3 recalibrated `land_rcl6` from 150 to 60 fits for exactly this reason — "a budget everything
clears is a budget that ranks nothing").

### 3.1 Integrate idea 2c into `_evolve`'s real generation loop

**Hypothesis.** `docs/SEARCH_SPEEDUP_PLAN.md` idea 2c measured a 33.6% dispatch-mechanism speedup
from replacing a fixed-batch `executor.map` with continuous, `as_completed`-style dispatch, on a
workload with the same CPE/non-CPE cost heterogeneity `_evolve`'s own population has. Today,
`_evolve` still dispatches one full generation at a time: `evolve_plan` sets
`item_chunk = population` when an executor is present (`discover.py:2862`), and `_evolve`'s main
loop calls `executor.map(_evolve_polish_then_search_worker, batch.tasks)` once per generation
(`discover.py:2912`), a synchronous barrier — the loop's own comment states "a generation, once
begun, always finishes" (`discover.py:2887-2892`) and the wall-clock deadline is checked only at a
generation boundary (`discover.py:2903`). If the same idle idea 2c measured in isolation is
present in this real loop — plausible, since the loop shares the exact mechanism idea 2c's test
targeted — replacing the per-generation barrier with continuous dispatch should raise
distinct-topologies-evaluated per unit wall-clock the same way `docs/SEARCH_TIME_PLAN.md` §4.3's
T4 change did for a different barrier.

**What "integrating" requires, concretely.** Idea 2c's own write-up names the obstacle: parent
selection currently happens once per generation, from the *completed* previous generation's
archive (`_next_generation(alive, ...)`, called only after `alive = _unique_best(scored, ...)`
at `discover.py:2781`/`2789` in `evolve_plan`). A continuously-fed pool needs a child proposed
and dispatched the instant a worker frees, which means `_tournament`'s draw has to read whatever
state (`scored`, `best_cost`) exists *at that instant* rather than at a generation boundary — a
change to the population model, not a wrapper around the existing dispatch call. The `workers=1`
/ `executor=None` path (`discover.py:2913-2917`) is unaffected by construction: there is nothing
to interleave with one process, and it must stay byte-for-byte the sequential loop it already is.

**Method.** Mirror `docs/SEARCH_TIME_PLAN.md` §4.3's own T4 gate, since this proposal is the same
shape of change (a dispatch-barrier removal that changes the RNG stream and therefore cannot be
gated by a byte fingerprint):

- *Search-quality half*: `land_rcl6.json` and `land_series_rcl6.json`, at the same recalibrated,
  unsaturated budgets T4 used (60 and 40 fits respectively), 480 seeds, comparing a
  `ga_front`-style control against a new continuous-dispatch arm in
  `benchmarks/screening_round/arms.py`, exact McNemar.
- *Throughput half*: `benchmarks/six_plus/x6_workers.py`'s own truths (`par6`, `ser6`), same seed,
  300 s / `workers = 8`, reporting `n_evaluated` in the same table format T4 used, against the
  current post-T4 baseline (`par6` 1366, `ser6` 1095 — `docs/SEARCH_TIME_PLAN.md` §4.3's own
  numbers, not X6's pre-T4 380/413).

**Decision rule, pre-registered.** Ships only if **both** halves pass: frozen-landscape hit rate
is not significantly lower than the current generation-synchronous implementation (McNemar at 480
seeds; a drop that is significant, or that trends the same direction on both tables, rejects this
regardless of the throughput number), **and** `n_evaluated` at `workers=8` / 300 s rises over the
1366 / 1095 baseline above on at least one of the two truths without falling on the other. If
either half fails — hit rate drops, or throughput does not rise — this does not ship, exactly as
`docs/SEARCH_TIME_PLAN.md` §3.2 did not ship the batch-size fix that broke byte-identity in a
different part of this same codebase for a different reason. Any RNG-stream side effect on
individual `reported` flags (the kind `docs/SEARCH_TIME_PLAN.md` §4.3 recorded for `ser6` at
`workers=1`) is recorded, not treated as part of this decision rule, unless it also moves
`recommended`.

**[measured, 2026-09-13] Shipped — both halves pass, decisively.** Built as the **broad** scope
the user chose over a narrower dispatch-only fix: `evolve_plan` is now a true steady-state
(overlapping-generation) proposer, not a discrete-generation loop with a faster dispatch call
bolted on. A new `_SteadyState` class (`discover.py`) proposes one individual at a time —
elite repeats first (the same `max(2, population // 6)` quota `_next_generation` already uses,
spent against the *true* `population` rather than the dispatch window's own width, which would
otherwise silently inflate the elite fraction in a small window) then tournament-bred children via
`_propose_child` (factored out of `_next_generation`'s own body so both share one implementation,
verified behaviour-preserving on its own before anything else changed) — recomputing the Pareto
front once per **virtual generation** (`population`-many proposals *handed out*, not necessarily
completed) rather than once per discrete batch. `evolve_plan`'s wire protocol changed to a
**sliding window**: `EvolveBatch.tasks` is now `list[_EvolveTask | None]`, a fixed-length window
where a slot is `None` once nothing remains to propose for it and otherwise holds whatever task
is currently assigned there; `send()` reports a slot's outcome as `None` to mean "still pending,
leave it assigned" or "already empty, nothing to report" — both mean the same thing to the
generator. Field names (`tasks`, `scored`, `generation`, `cache_size`) are unchanged, so
`on_progress`, `DiscoveryResult.generations` and `_with_evolve_note` needed no code changes at
all — only `generation`'s underlying meaning shifted, from "generations fully completed" to
"virtual generations whose proposal quota was exhausted," which coincides with the old meaning by
the same 0-indexing arithmetic the original loop's own `generation + 1` already relied on (traced
and fixed once: the first cut returned the bare vgen index and under-reported `generations` by
exactly one).

- **`workers=1` byte-identity — the non-negotiable gate — passed exactly.** Real `discover
  (mode="evolve")` calls at `workers=1`, four different `(max_elements, generations, population,
  seed)` combinations, compared field-for-field (including the full sorted candidate-text list)
  against the unmodified code at the prior commit (via a disposable `git worktree`, not a
  same-tree `git stash`, after an in-place stash was found to hang the process on an unrelated
  fingerprint script earlier the same session): identical on every field once the `generations`
  off-by-one above was fixed.
- **Quality gate**: a new `arm_ga_steady` in `benchmarks/screening_round/arms.py`, calling
  `_SteadyState` directly (the same discipline `arm_ga_bounded` already uses for
  `_breeding_pool`/`_next_generation` — an arm may not reimplement the library), 480 seeds against
  `ga_front`/`ga_front_dedup`. `land_rcl6.json` (budget 60): 245/480 hits against `ga_front`'s
  247/480, McNemar p = 0.9007. `land_series_rcl6.json` (budget 40): 253/480 against 254/480,
  p = 1.0000. Neither arena shows a hit-rate drop in either direction.
- **Throughput gate, `workers=8` / 300 s, `benchmarks/six_plus/x6_workers.py`, re-run on a
  quiescent machine**: `par6` 1366 → **2835** (+107.5%), `ser6` 1095 → **2310** (+111.0%) —
  both truths roughly doubled, far past "rises on at least one without falling on the other."
  `ser6`'s `reported` flag is `false` at `workers=8` in this run (it was `true` at `workers=1` in
  the same run and at both worker counts in the pre-change T4 baseline); `recommended` is `false`
  at every worker count in both the old and new measurement, so per the decision rule's own
  carve-out this is recorded, not treated as a rejection — the same single-draw RNG sensitivity
  this codebase already has on record for `ser6` specifically (`TOPOLOGY_6PLUS_PLAN.md`'s
  basin-lottery finding, `SEARCH_TIME_PLAN.md` §4.3's own `workers=1` flip for this exact truth).

**The CLI driver** (`_evolve`) was rebuilt on `concurrent.futures.ProcessPoolExecutor` +
`concurrent.futures.wait(..., return_when=FIRST_COMPLETED)` behind a new `_evolve_worker_pool`
(mirroring `_worker_pool`'s own `workers<=1` contract) — a `multiprocessing.Pool` cannot report a
single completion without a `.map()` call waiting for the whole batch, which is exactly the
barrier this removes. The sequential (`workers=1`) branch is a separate, deliberately
dead-simple one-in-one-out loop, not a one-worker special case of the concurrent one, precisely
so the byte-identity gate above has the smallest possible surface to trust. On a `time_limit`
firing, the driver drains whatever is already in flight (at most `item_chunk` = `workers`
individuals) before closing the generator — a strictly smaller overshoot than the old "wait for
up to `population` stragglers."

**The browser was moved to the same protocol, not left on `item_chunk=1`.** `DiscoveryJob`
gained an `evolve_chunk` constructor parameter (default `REFIT_CHUNK`, the same worker-pool-width
concept `refit_chunk` already uses for this job's other per-topology parallel stage) — before
this, the fallback dispatched exactly one offspring at a time regardless of how many Web Workers
the browser had, leaving every worker past the first idle for the whole stage. `next_evolve`/
`submit_evolve`'s existing pull/push shape needed no structural change — it already handed out
and collected a *list*, just always of length one — only its type widened to allow a `None` slot
and `bridge.py`'s `_op_discover_evolve` gained the pass-through for it. Scoped deliberately to
*functional correctness plus using the whole worker pool*, not the CLI driver's finer-grained
per-completion resubmission (`docs/EVOLVE_COMPUTE_SKIP_PLAN.md`'s own scope decision, unchanged
from the plan): the browser dispatches and awaits a whole window together (`pool.map`/
`Promise.all`, mirroring how `screen`/`refit` already batch), refilling only the slots that
returned. Three JS/Python test drivers that pre-dated the sliding window
(`tests/test_web_job.py`'s `Driver.evolve`, `tests/test_discover_growth.py`'s inline loop,
`web/scripts/smoke.mjs`'s `driveWithEvolve`, and `web/src/core/search.ts`'s own production
`evolve()`) all unpacked every slot unconditionally and crashed the instant one came back `None`
— fixed identically in all four: skip a `None` slot, report `None` back for it. Two gate tests
(`test_web_job.py`'s W-EV1, `test_discover_growth.py`'s growth-parity test) that assert an exact
candidate-list match against a CLI reference needed `evolve_chunk=1` added explicitly, for the
same reason the CLI's own `workers=1` and `workers>1` are not expected to agree
candidate-for-candidate: window width changes which offspring see which others' outcomes before
they are themselves proposed, so an exact match needs a matched width, not just a matched
algorithm.

**Full verification, all green**: the complete `pytest` suite (1125 passed, 19 skipped, 0
failed — one pre-existing test that spied on `_next_generation` directly was updated to spy on
`_breeding_pool` instead, since the steady-state path no longer calls `_next_generation` at all,
preserving the test's own invariant rather than deleting it), `mypy --strict` and `ruff check`
clean on every touched file (against the same pre-existing, unrelated `Weighting`-export errors
this codebase already carries), `npm run check` clean, and `npm run smoke` clean end-to-end
including its own "genetic fallback actually ran" check at the browser's new default
`evolve_chunk=8`. `_next_generation` itself is untouched and still real, shipped code — every
other caller (`arms.py`'s remaining arms, and any future non-steady-state use) is unaffected.

### 3.2 Extend early-abandon to evolve's tier-1 search sub-call

**Hypothesis.** Section 1.6 established that evolve's tier-1 global search (`_evolve_one`'s
`fit(..., global_search=True, ...)` call, `discover.py:1879-1891`) always runs the full local
`least_squares` polish after the global stage, with no mechanism to skip it even when the global
stage's own raw cost already lands far above `self.best_cost.get(circuit.complexity)` — exactly
the situation `ABANDON_FACTOR = 100.0` exists to short-circuit in the exhaustive path
(`fit.py:749-753`). If a comparable fraction of evolve's fresh (never-cached) search calls land in
this hopeless regime — plausible given the same bimodal screening-cost landscape
`docs/TOPOLOGY_6PLUS_PLAN.md` §5.7.2 documents for the exhaustive path — skipping the local polish
for those candidates should cut wall-clock without changing which candidate is ultimately
promoted to tier 2, since tier 2 always refits from scratch regardless of which tier-1 path a
topology took (`discover.py:1709-1710`).

**What building this requires, concretely.** `fit()` (`fit.py:572-592`) has no `abandon_above`
parameter and does not expose the global stage's raw cost before running `least_squares`
(`fit.py:648-673`). Two ways to get there, and only one avoids adding cost:

- **(a) Add an `abandon_above` parameter to `fit()` itself**, mirroring `screen()`'s own check
  (`fit.py:778-780`): after `_global_stage` returns `x_start`, evaluate `problem.cost(x_start)`
  and, if it exceeds the threshold, skip the `least_squares` call and build a `FitResult`
  directly from the global-stage point. This adds no extra global-stage evaluation, since
  `problem.cost` on the already-computed `x_start` is cheap relative to a second DE run.
- **(b) Have `_evolve_one`'s search stage call `screen()` first** as a cheap cost check, then
  call `fit()` for the full result only if the screen survives. **Rejected without measurement**:
  this would run `_global_stage` twice per candidate unless seeded and budgeted identically to
  `fit()`'s own global stage, in which case it is strictly more expensive than (a) for the same
  answer — the double-work idea 2e/F already warns against, here recreated at the fit level
  instead of the cache-key level.

So only (a) is a candidate. It also needs its own correctness check before it is trusted:
`docs/SEARCH_TIME_PLAN.md` §3.2 found a structurally similar comment — that a stale threshold
"can never change a result" — to be **false** at least once (a bigger `WORKER_CHUNK` shifted
which of two near-tied CPE/SKINF candidates got a local polish, moving the tier-2 shortlist). An
abandon threshold inside `fit()`'s global path must be checked the same way: does skipping the
local polish on a candidate above the threshold ever change which candidate a generation's
`_cheaper` comparison keeps, in a way that changes the archive `_unique_best` selects tier 2 from?

**Method.** Reuse the 480-seed McNemar discipline on `land_rcl6.json`/`land_series_rcl6.json`
exactly as in 3.1. Additionally report a real measured number for the cost side, not a
projection — per `docs/SEARCH_SPEEDUP_PLAN.md` idea C's own lesson that `differential_evolution`
at a fixed budget frequently never reaches early convergence at all, so an assumed cost model can
be wrong: time a fixed batch of evolve tier-1 search calls (e.g., 200 offspring drawn from a real
`discover(mode="evolve")` run's own proposal stream, replayed against the same spectrum) with and
without the abandon check, and report wall-clock or fit-count reduction directly.

**Decision rule, pre-registered.** Ships only if **both**: (i) frozen-landscape hit rate is not
significantly reduced (same McNemar bar as 3.1), and (ii) a measured, non-projected wall-clock or
per-candidate cost reduction is reported on the timed batch above. If the measured reduction is
negligible — for instance because search-stage calls rarely land far enough above the reference
to trigger the abandon check in evolve's actual population (the same "no cell moved" outcome
`docs/SEARCH_TIME_PLAN.md` §4.1/T6 recorded for the second-screening-seed lever, where a
plausible mechanism turned out to have nothing to repair on the truths tested) — this stays
unshipped and the negative result is recorded exactly that way, not reworded.

**[measured, 2026-09-12] Built, verified correct, and rejected on the speed clause.** `fit()`
gained an `abandon_above: float = math.inf` parameter mirroring `screen()`'s own (the abandon
check sits right after `problem.canonicalize(x_start)`, before `least_squares`; an abandoned
candidate still returns a real `FitResult` with a finite AICc rather than a degenerate one, its
Jacobian filled by a cheap forward finite difference — `n_params + 1` residual evaluations,
verified negligible next to `PUBLISH_LOCAL`'s `max_nfev=20000` — so `_evolve_one`'s existing
`math.isfinite(statistics.aicc)` gate does not silently blackhole an abandoned topology).
`abandon_above=math.inf` reproduces the unmodified `fit()` byte-for-byte (checked directly:
identical `values`, `residuals`, `statistics.aicc`), and the exhaustive path never passes it, so
that half of the change was inert by construction. Wired into `_evolve_one`'s search-stage call
as `ABANDON_FACTOR * reference` when a reference cost is known, mirroring `screen()`'s own
threshold exactly. **Correctness (clause i, reduced scale)**: 3 seeds, `workers=1` (deterministic,
single-process — the only way to A/B via a module-level toggle without a multiprocessing pool
each rebuilding its own copy), comparing `discover(mode="evolve", ...)` with the check active
against `ABANDON_FACTOR` forced to `math.inf` — **`recommended` and the full Pareto front were
byte-identical on all 3 seeds**. This is a much smaller sample than section 3.1's 480-seed
McNemar bar and is reported as exactly that scale, not stretched to stand in for it. **Speed
(clause ii) fails outright**: 99 real search-stage tasks captured from one live `discover
(mode="evolve")` run's own proposal stream (of a 200-task target; the run itself did not produce
more before finishing) and replayed with and without the check, same spectrum, same context —
26/99 (26%) triggered the abandon path, and total wall-clock moved by **3.5%** (10.92 s → 10.54
s). This is the same shape of result section 3.1's sibling document
(`docs/SEARCH_TIME_PLAN.md` §3.5) found for spectrum thinning on the same kind of workload: a
mechanism that measurably fires does not translate into a meaningful wall-clock win, because the
stage it shortens (here, the local trust-region polish) is not the dominant cost at this
problem's `PUBLISH_LOCAL`/DE-budget scale — the global search itself is. **Nothing ships**: both
the `fit()` parameter and its `_evolve_one` wiring were reverted (`git checkout`) rather than
left in the tree unused, per this project's own precedent (`docs/PARAM_OPTIMIZER_PLAN.md`'s
`core/lshade.py` removal) for a change whose own pre-registered bar it did not clear; the full
`tests/test_fit.py` suite (46 tests) was re-run clean after the revert to confirm no residue.

### 3.3 A narrower dispatch-order proxy — explicitly not idea 2b restated

**Why this is not idea 2b.** `docs/SEARCH_SPEEDUP_PLAN.md` idea 2b trained a from-scratch
classifier (a 1-NN over seven structural features: element count, per-code counts, tree depth,
max branch width) to predict whether a candidate falls in the cheaper half of the full-budget cost
distribution, in order to decide **whether to fit it at all**. It reached 70.7% leave-one-out
accuracy against an 80% bar and was rejected — a real but weak signal, not zero, but not strong
enough to gate inclusion. This proposal differs in three ways that matter to its risk profile, not
merely its wording:

1. **It never skips a fit.** Every task in a dispatched generation is still evaluated exactly as
   today; only the *order* changes. A wrong call costs at most some wasted seconds near a
   deadline, never a dropped candidate — 2b's actual failure mode (mispredicting an individual
   candidate's cost class) cannot occur here because no candidate is ever excluded on the proxy's
   say-so.
2. **No trained model and no engineered features.** The proxy is two quantities `_next_generation`
   already computes before dispatch: whether a child came from a single-parent mutation of an
   elite front member or from a crossover between two tournament winners
   (`discover.py:4357-4363`), and whether `_warm_start_for` produced a non-empty inherited-values
   dict for it (`discover.py:1525-1533`, already computed regardless of this proposal). There is
   no accuracy question to fail because nothing is predicted from held-out data — the order is
   read off bookkeeping the loop already does.
3. **It only matters when a wall-clock deadline actually interrupts a batch mid-flight**, which
   today's synchronous per-generation dispatch does not even permit — `discover.py:2887-2892`
   states plainly that a generation, once begun, always finishes. So this proposal's practical
   value is contingent on 3.1 shipping (or at least prototyping) first: only a continuously-fed
   pool has a queue whose order determines what is "in flight" versus "not yet started" when a
   deadline fires. Reordering the single list handed to today's one `executor.map` call has at
   most the minor, already-characterized-as-not-a-real-lever effect `docs/SEARCH_TIME_PLAN.md`
   §3.2 found for `Pool.map`'s own chunksize heuristic. **This should not be attempted
   independently of 3.1.**

**Method — a correlation check before any dispatcher is built.** Before writing a reordering
mechanism, run the cheap diagnostic `docs/SEARCH_SPEEDUP_PLAN.md` idea 2d's own discipline calls
for (count/correlate first, build second): on a batch of offspring sampled from a real
`discover(mode="evolve")` run, does the proxy (mutation-vs-crossover origin, warm-start
non-emptiness) actually correlate with the *measured* wall-clock duration of that candidate's own
tier-1 fit? Report a Spearman rho, the same instrument idea 2a used to warn against reading an
inflated aggregate correlation on a landscape dominated by uninformative cases.

If, and only if, that correlation is non-trivial, proceed to the actual ordering experiment: using
3.1's continuous-dispatch prototype (or, failing that, an isolated harness in the style of
`benchmarks/speedup/idea_2c_async_evolve.py` that fires a synthetic deadline mid-batch rather than
the full `_evolve` loop), measure at a range of deadlines chosen to interrupt roughly the middle of
a generation's dispatch whether the archive collected by the deadline reaches the truth's
equivalence class more often under proxy-ordered dispatch than under today's arbitrary list order,
480 seeds, McNemar, on `land_rcl6.json`/`land_series_rcl6.json` recalibrated so an uninterrupted
run does not already clear the bar.

**Decision rule, pre-registered.** Reject outright, without building the dispatcher, if the
correlation check finds the proxy has no material relationship to actual per-candidate fit
duration (the same finding idea 2d made for residual-peak localization: a plausible-sounding
signal with nothing behind it). If the correlation is real, ship the ordering only if it shows a
significant McNemar improvement in truth-equivalence-class recovery under an interrupted deadline
**and** shows no regression relative to today's order at a normal, uninterrupted budget (a free
reordering must not cost anything when the deadline never bites).

### 3.4 A cheap first count for a rounded-parameter secondary cache

**What this is not.** `_Evaluator.cache` already collapses every fit of the *same* topology
(same `canonical_form()`) to one best-wins entry (section 1.1), and `_warm_start_for` already
skips the polish outright when a child's inherited values are *exactly* equal, float for float, to
the cached candidate's own values (`discover.py:1530-1533`). This proposal is about the gap that
exact-equality check leaves open: a child whose inherited values are not bit-identical to the
cached optimum but converge to essentially the same point once fitted — because the parent that
produced them was itself found via a different warm start, RNG seed, or mutation chain — still
runs the full polish (and possibly the reduced-budget search) today, for an answer the cache
almost certainly already has.

**The cheap counting experiment, specified before any mechanism is proposed** — mirroring
`docs/SEARCH_TIME_PLAN.md` §3.4's own discipline, which counted class multiplicity in an existing
frozen table *before* deciding whether a dedup mechanism was worth building, and which found a
large count (4.4-5.9x) that still did not change the build decision for two independent reasons.
The quantities this count needs — `known.result.params`, `known.result.statistics`'s
per-parameter standard errors, and the `warm` dict `_inherited_values` already produces — are all
already computed by existing code on the path to the exact-equality check at
`discover.py:1530-1533`; the counting instrumentation adds no new expensive computation, in
contrast to idea 2e/F's rejected canonical-form cache, whose key was exactly as expensive as the
thing it replaced.

Concrete tolerance: for every warm start that reaches `_warm_start_for` and fails the exact-equality
check (so today's code proceeds to a polish), compare each inherited value against the cached
candidate's own value for that parameter, scaled by that parameter's own reported standard error
from `known.result.statistics` — e.g., flag a "near-duplicate" whenever every inherited parameter
sits within some small multiple (to be fixed before counting starts, e.g. 0.5) of its own
standard error of the cached value, or, where a standard error is unavailable or non-finite, fall
back to `EQUIVALENCE_RTOL = 1e-6` relative (the same tolerance tier 2's own `_same_response`
already uses for exact-reparameterisation classes). Run this instrumentation, read-only, across a
handful of real `discover(mode="evolve")` runs on existing truths (`par6`/`ser6` from
`benchmarks/six_plus/truths.py`, `mw5`/`mw6` from `benchmarks/speedup/truths.py`) and report: of
all warm starts that are not exact matches, what fraction are near-duplicates by this tolerance.

**The risk this shares with idea 2e/F, stated explicitly and guarded against.** A rounding key
safe enough to avoid false merges (falsely treating two genuinely different optima as the same and
silently keeping the worse one) may itself cost as much to compute as the polish it would skip —
exactly idea 2e/F's finding. Because this count reuses only already-computed values, the counting
step itself should be near-zero cost, but that must be *checked*, not assumed: time the counting
instrumentation's own overhead inside `_warm_start_for` and confirm it does not measurably slow the
runs it is instrumenting before trusting the count.

**Decision rule, pre-registered.** Run the count first, on the runs above, with a pre-registered
bar (for example, non-exact-match near-duplicate rate under 5% closes the item with the count and
nothing is built — the same disposition as most of `docs/SEARCH_SPEEDUP_PLAN.md`'s Phase 1 ideas).
If the rate clears that bar, prototype a tolerance-based cache-hit path (skip the polish, and the
search if applicable, and return the cached candidate's own `FitResult` directly when a warm start
is a near-duplicate) and gate it exactly like 3.1 and 3.2: 480-seed McNemar hit-rate preservation
on the frozen landscape tables, plus a measured (not projected) fit-count or wall-clock reduction
on a real `workers=8` evolve run against the current post-T4 baseline (`par6` 1366, `ser6` 1095).
Note explicitly, before any of this runs, that `docs/SEARCH_TIME_PLAN.md` §3.4 found a *large*
multiplicity count (4.4-5.9x) and still declined to build a mechanism, for two reasons that do not
automatically transfer here: that item's blocking reasons were "no cheap predictive test runnable
before fitting" and "tier 2 refits every equivalence-class member regardless" — the first does not
apply to this proposal if the counting experiment's own tolerance check turns out to be cheap and
predictive (unlike a topology-level symbolic-equivalence test), and the second is about the
*report*, not about tier-1 compute, so it does not block a tier-1-only skip the way it blocks a
tier-2 dedup. Neither reason should be treated as inherited without checking whether it actually
applies to this narrower, parameter-level question.

**[measured, 2026-09-12, a different and cheaper proxy than the count specified above — not the
precise `_warm_start_for` instrumentation this section calls for, run given the shared time
budget].** What actually ran: one `discover(mode="evolve", pool=("R","C"), generations=15,
population=30, max_elements=10, time_limit=90)` call on a 10-element, 5-block Maxwell-Wagner-style
truth, then `result.equivalence_classes()` on the finished archive — the same numeric
`EQUIVALENCE_RTOL`-based response check `SEARCH_TIME_PLAN.md` §3.4 already used on frozen
exhaustive tables, applied here to a live evolve archive instead. Of 21 archived candidates (one
per canonical topology, best-wins, 322 topologies evaluated in 140 s), 12 equivalence classes
formed, 7 of them with more than one member, covering 16 of the 21 candidates (~76%). This
confirms §3.4's own finding — large numeric-response multiplicity — extends from the frozen
exhaustive tables to the evolve fallback's own archive, on one truth and one run; it is **not**
the warm-start-tolerance count this section actually specifies (that needs instrumenting
`_warm_start_for` at `discover.py:1530-1533` directly, comparing inherited values against the
cached optimum's own standard errors before the exact-equality gate) — that measurement was not
attempted this session. Given §3.4's own two independent reasons for not building a dedup
(no cheap predictive test before fitting; the report still needs the full archive for its
equivalence-class grouping regardless of what any cache would have skipped) already extend
cleanly to this reading, this count changes nothing about the item's own disposition: still a
count, not yet a decision to build.

## 4. Work order

1. **Section 3.1 — integrate idea 2c into `_evolve`'s real generation loop.** Cheapest to justify:
   the raw speedup is already measured in isolation (`docs/SEARCH_SPEEDUP_PLAN.md` idea 2c,
   33.6%), and only the integration plus a T4-style gate remain.
2. **Section 3.3's correlation check only** (not the dispatcher) can run in parallel with step 1,
   since it needs only a sample of offspring from an existing evolve run, not the continuous-
   dispatch prototype — but the dispatcher itself, and its own gate, waits on step 1's outcome.
3. **Section 3.2 — extend early-abandon to evolve's tier-1 search call.** Independent of steps 1
   and 3; needs a new `fit()` parameter and its own correctness check before the speed gate, per
   `docs/SEARCH_TIME_PLAN.md` §3.2's precedent that a "cannot change a result" comment was found
   false once already in this codebase.
4. **Section 3.4 — the counting experiment only, first.** Cheapest of all to *start*, because it
   requires no new mechanism, only instrumentation of code that already runs — but it is ordered
   last because, unlike 3.1-3.3, a negative count closes the item immediately with nothing further
   to build, so there is no urgency to sequence it earlier, and its own risk (idea 2e/F's exact
   trap) means the counting instrumentation's overhead must itself be checked before the count is
   trusted.

None of these four should be read as independent of the others' outcomes where noted above (3.3
depends on 3.1's dispatcher; nothing here should be built for its own sake ahead of the count or
correlation check that is supposed to justify it).
