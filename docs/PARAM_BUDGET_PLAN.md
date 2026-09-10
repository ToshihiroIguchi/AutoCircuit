# PARAM_BUDGET_PLAN.md — should the exhaustive search be budgeted by free parameters instead of elements?

**Status: Phases 0-2 done. Phases run in order; each states in advance what result means
"do not ship" and a null result is an acceptable outcome of any phase after Phase 1.**

## 1. Why this needs an experiment before it needs an opinion

The exhaustive stage enumerates and claims completeness on **raw element count**
(`exhaustive_limit`, `complete_up_to`, `GROWTH_REACH`). A `C` costs one free parameter and a
`CPE` costs two, so "every plausible topology with up to 5 elements" is a different amount of
model *freedom* depending on the pool. The question that prompted this document: does that bias
the search toward the parameter-rich element?

**Investigated first, and the premise is half right — but the half that is right is not the half
that was named.**

Selection is already parameter-aware, twice over. Tier 1's `_screening_score`
(`core/discover.py:3032`) and tier 2's `Candidate.score` both feed `circuit.n_params` to the
chosen criterion (default BIC). And `Circuit.complexity` (`core/circuit.py:153`) — the first key
of `recommended` (`discover.py:624`) and the axis `pareto_front` (`discover.py:1766`) dominates
on — is a weighted sum, not a raw element count. **There is no code path in which a CPE wins a
comparison because it is counted as one element instead of two parameters.**

What *is* raw element count, unconditionally, is the **budget, the coverage claim, and the tier-2
refit quota**. Those are measurably distorted, for reasons that have nothing to do with the
originally suspected mechanism. §2 below is what was measured; §3 states the decisions taken; §4
is the enumerator design; §5 is the tier-2 re-key; §6 is what the completeness claim becomes; §7
is the `Circuit.complexity` question; §8 is what a first draft of this plan missed and had to be
added before anything could ship; §9 is the phase order with pre-registered stop rules.

## 2. Measurements

**F1 — the budget is unequal by a factor that is now known.** Enumerated topologies after
`simplify`/`is_plausible` dedup:

| pool | today: elements ≤ 5 | params ≤ 5 | params ≤ 6 | params ≤ 7 |
|---|---|---|---|---|
| `R,C,L` | 449 (params 1–5) | 449 | 2,174 (all 1,725 six-element) | 11,033 |
| `R,C,L,CPE` (default pool) | **2,976 (params 1–10)** | 627 | **3,212** | **17,273** |
| `R,C,L,CPE,W,Wo` | 31,712 | 4,575 | 34,913 | 280,112 |

At element cap 5 on the default pool, **79 % of the enumerated space carries more free
parameters than the entire `R,C,L` cap-5 space allows**. A parameter budget of 6 contains
**every six-element `R,C,L` topology exhaustively** — the reach `docs/TOPOLOGY_6PLUS_PLAN.md`
built the whole growth stage for and still ships off by default (`GROWTH_DEFAULT = 0`). `R,C,L`
at P=7 is 11,033, the same number as `docs/SEARCH_ALGORITHM_SCREENING.md` §4.2's cheap arena —
that arena *is* a parameter level, though it was never named as one.

**F2 — the tier-2 quota and the Pareto front disagree about what "size" means.**
`_quota_by_size` (`discover.py:3072`) and `_refit_order` (`3170`) bucket on
`len(circuit.leaves)`; the score *inside* the bucket is parameter-aware (`_screening_score`
takes `n_params`), and `pareto_front`/`recommended` dominate on `Circuit.complexity`. On today's
default-pool cap-5 space that is **5 buckets guarding a 19-value axis** — `_quota_by_size`'s own
docstring promise ("the Pareto front has candidates at each complexity") is met on 26 % of that
axis. The pathology the docstring records is stated in parameters ("raw residual always improves
with parameters"); the implementation substitutes element count for that.

**F3 — `Circuit.complexity` is `n_params` plus four unmeasured numbers.** Measured over every
`Element` subclass, `complexity − n_params` is `0` everywhere except **`W +0.5`, `CPE +0.5`,
`SKINF +0.5`, `SKINW +1.0`**:

| code | n_params | complexity | surcharge |
|---|---|---|---|
| R, C, L | 1 | 1.0 | 0 |
| W | 1 | 1.5 | **+0.5** |
| Ws, Wo, G | 2 | 2.0 | 0 |
| CPE | 2 | 2.5 | **+0.5** |
| CC | 3 | 3.0 | 0 |
| SKINF | 2 | 2.5 | **+0.5** |
| SKINW | 2 | 3.0 | **+1.0** |
| HN | 4 | 4.0 | 0 |

The `Element.complexity` comment (`core/elements.py:107-109`) says "elements that can absorb a
lot of unexplained behaviour (CPE, HN) are deliberately expensive" — **HN's surcharge is 0**, so
the stated rationale is contradicted by its own table for one of the two elements it names. The
weights date from the first baseline commit (`f88cd07`, confirmed by `git log -S`), carry no
`[measured]` note anywhere in `docs/` — unusual for this repository — and `complexity` is the
first key of `recommended`, the value every report leads with.

**F4 — the payoff, on the `R1-Ws1` spectrum of `docs/POOL_FROM_SPECTRUM_PLAN.md` §5** (1 %
noise, 10 pts/decade), screened candidates and the level actually completed:

| pool | element axis | parameter axis |
|---|---|---|
| `R,C,L,CPE` | 2,887 screened / 5 elements | 15,827 / 7 params |
| `R,C,L,CPE,Wo` | 9,702 / 5 | 4,129 / 6 |
| `R,C,L,CPE,Ws,G` | 2,433 / **4** | 5,678 / 6 |
| `R,C,L,CPE,W,Ws,Wo,G` | 6,465 / **4** | 4,068 / 5 |

`POOL_FROM_SPECTRUM_PLAN.md` §2's rejected repair — "One added code is affordable and keeps the
fifth level; two are not" — is an arithmetic about *element* levels; on the parameter axis all
four pools complete a level. And §5's documented failure, the 3-parameter truth `R1-Ws1` answered
by the 7-parameter stand-in `p(p(R1-CPE1,CPE2)-C1,R2)`, is structurally impossible at a budget of
6: the stand-in is outside the space while the truth is inside it.

**F5 — the cost, stated up front.** A parameter budget is **not** a superset of today's space.
At P=6 on `R,C,L,CPE` it gains all 1,725 six-element `R,C,L` topologies and **loses 1,489** that
today's cap-5 covers (element levels 4 and 5 become partial), and the element-wise completeness
claim that the report would still be able to make drops from 5 to **3**.

**F6 — cost must be counted in fits, not topologies, and doing so reverses the sign.** Using
`docs/SEARCH_ALGORITHM_SCREENING.md`'s measured per-screen cost (1.77 s CPE-bearing, 0.87 s
otherwise) as a proxy:

| space | n topologies | CPE-bearing | cost proxy | buckets (element / param / complexity) |
|---|---|---|---|---|
| today, elements ≤ 5 | 2,976 | **84.9 %** | 1.00× | 5 / 10 / 19 |
| params ≤ 5 | 627 | 28.4 % | **0.15×** | 5 / 5 / 10 |
| params ≤ 6 | 3,212 | **32.3 %** | **0.77×** | 6 / 6 / 13 |
| params ≤ 7 | 17,273 | 36.1 % | 4.24× | 7 / 7 / 15 |

**A parameter budget of 6 is 8 % more topologies than today's element budget of 5, and roughly a
quarter *less* work**, because the mix shifts away from the expensive element (84.9 % → 32.3 %
CPE-bearing). Counting topologies rather than fits gets the sign of this trade-off wrong.

**F7 — every truth in this repository is parameter-lean, so the existing benchmarks cannot
detect the harm this change can do.** Parameters per element, on every reference truth defined
anywhere in this project:

| set | truths | ratio params/elements |
|---|---|---|
| `benchmarks/six_plus/truths.py` (9) | `par5`…`mix7` | **1.00, every one** (R/C/L only) |
| `benchmarks/discovery_v2.py` `REFERENCES` (3) | 5, 4, 4 params on 4 elements each | 1.25, 1.00, 1.00 |
| `LARGE_REFERENCES` (3) | 6/6, 8/6, 9/7 | 1.00, 1.33, 1.29 |

The enumerated space at element cap 5 reaches ratio 2.0 (41 topologies), with bulk mass at
1.2–1.6. **No truth anywhere in this repository is small in elements and large in parameters —
exactly the class a parameter budget deletes.** Scoring only against these fifteen truths would
confirm the change for free: a vacuous pass of the kind `docs/HANDOFF.md` §3 already lists
several of. Two of the three `LARGE_REFERENCES` truths cost 8 and 9 parameters, so no budget
below 8 can recover them — true of today's element cap 5 as well, but stated rather than
discovered mid-round.

**F8 — two constants silently change identity under a re-key, one with a measured hazard
attached.**

* `REFINE_DEFAULT = 30` with `MIN_REFINE_PER_SIZE = 5` (`discover.py:169-181`): the quota is
  `max(5, 30 // buckets)`. At today's 5 buckets that is 6; at 6 buckets exactly 5; at **7
  buckets the floor binds** and `REFINE_DEFAULT` becomes inert — the exact regime its own
  docstring warns about.
* `best_cost` (the early-abandon and warm-accept reference) is keyed on `complexity`
  (`discover.py:1456, 1637, 2578`). Collapsing `complexity` to `n_params` (§7's arm B) drops the
  key count on today's space from 19 to 10, so a stale `abandon_above` threshold is shared across
  more candidates — exactly the mechanism `docs/SEARCH_TIME_PLAN.md` §3.2 measured and rejected a
  shipped optimisation over ("a stale threshold can never change a result" was disproved there).
  Arm B of §7 needs its own fingerprint to rule this out before its numbers are trusted.

**Two premises corrected during design, recorded because they were load-bearing during the
investigation.** (i) An early `params ≤ 7` figure was computed by enumerating to 6 elements and
filtering — 2,174 / 8,414 — rather than truly enumerating to 7 parameters; the true values,
11,033 / 17,273, are what appear in F1 above. (ii) `max_candidates` binds on the
**post-feasibility** count (`discover.py:2882-2893`), not the raw enumerated one, so "31,712
exceeds 20,000 and coverage falls" does not describe what happens; F4 is the real measurement.

## 3. Decisions taken

1. **Replace** the exhaustive budget with a parameter budget. The element cap survives where it
   already has no completeness claim to make: the genetic sampler and (pending Phase 5) growth.
2. **Include** `Circuit.complexity` in this round: measure whether the four surcharges (F3) earn
   themselves, and unify on `n_params` if they do not.
3. **Replace** the user-facing knob: `--max-params` on the CLI, "Parameter limit" in the browser.

## 4. The pruned enumerator

See `core/enumerate.py`. Parameters are additive over the tree exactly as elements are, so
`_compose` (`enumerate.py:158-190`) transfers verbatim with "size" read as "parameter count",
with three edits: the base case fires whenever a code's own `n_params` equals the requested
level (not only at level 1, since a 2-parameter CPE is a leaf of level 2); the survival check
compares parameter counts rather than element counts (equivalent under `simplify`, since every
`_MERGEABLE` code costs exactly one parameter); and partitions are pruned by `pmin =
min(n_params)` over the pool, cutting `itertools.product`'s labelling work rather than filtering
its output. Prototyped and measured on `R,C,L,CPE,W,Wo` at P=6: 34,913 trees in 0.84 s against
362,606 in 7.7 s for enumerate-then-filter.

Two gates, both free (no behavioural claim, provable by construction, checked anyway):
list-identity with the element-axis enumerator on unit-parameter-cost pools, and set-equality
against enumerate-then-filter on mixed-cost pools including `("CPE","Ws")` (the only pool with
`pmin = 2`, exercising the empty-even-level pruning path).

## 5. The tier-2 quota

`_quota_by_size`/`_shortlist`/`_shortlist_candidates`/`_refit_order` re-key on `n_params`, not
`Circuit.complexity` — see F2's mechanism (parameter-driven, not complexity-driven) and F3
(keying on `complexity` would hand its four unmeasured surcharges control over which topologies
reach tier 2 at all, and would multiply the bucket count from 5 to 19 on today's space, roughly
tripling tier 2's wall clock). A provable corollary: inside a fixed-`n_params` bucket every
information criterion is `deviance(cost)` plus a constant, so `criterion` becomes inert as a
tier-1 ranking device — this voids the scoping premise of `docs/CRITERION_SELECTION_PLAN.md` §1
under this key and must be recorded there when it ships, not silently.

## 6. The completeness claim

Lemma (sound and tight): with `m = max(n_params)` over the pool, a parameter budget `P` contains
every *n*-element topology iff `n ≤ P // m`. `complete_up_to` keeps its exact current meaning
(largest element count whose topologies were *all* evaluated) and is derived from
`complete_up_to_params // m` — every existing consumer keeps reading a field that is still true,
merely smaller, and the field is never repurposed. New fields: `max_params`,
`complete_up_to_params`, `base_complete_up_to_params`. New coverage sentence, parameter-budget
path only; the element-budget path is byte-identical to today. `skeleton` and `growth_width > 0`
are refused in combination with `max_params` (`ValueError`) until Phase 8 states which axis each
takes.

## 7. The `Circuit.complexity` surcharges

Arm A is today's table; arm B is `complexity = n_params` for every element. Measured on the
CPE-bearing arenas where the arms can differ (`REFERENCES`, `LARGE_REFERENCES`,
`criterion_selection.py`'s negative controls, and §8's new parameter-dense truths). Ships only if
arm A's `recommended_correct` is strictly better, or arm B's `by_criterion_overfits` is strictly
worse; a tie collapses `complexity` to `n_params` and that is a reportable result, not a failed
one. Arm B must clear F8's `best_cost` fingerprint before its numbers are trusted. Whatever the
outcome, `Circuit.complexity` and `Element.complexity`'s docstrings are corrected to state the
identity and stop naming HN.

## 8. What a first draft of this plan missed

* **E.1 — parameter-dense negative-control truths do not exist anywhere in this repository
  (F7) and must be built before anything is wired**, e.g. `p(R1,CPE1)-p(R2,CPE2)-CPE3` (5
  elements / 8 parameters), `p(R1,CPE1)-C1-p(R2,CPE2)` (5/7), and one exercising `SKINF`. Two
  readings: recovery (how much is lost, stated rather than avoided) and **honesty** — when the
  truth sits outside the budget, does the coverage sentence correctly decline, or does it
  confidently attach a completeness claim to a wrong in-budget recommendation? A budget that
  fails the honesty reading does not ship at any default, regardless of every other gate.
* **E.2 — real measured data was never in the first draft.** `benchmarks/measured/`'s 7 datasets
  and gates R1–R4 are CPE-dense and the closest thing to the actual use case; R3 (split-half
  stability, 1/7 today) is a legible baseline for a change in either direction.
* **E.3 — no ladder over the budget itself.** F6 gives cost, F1 gives reach; neither says which P
  is right. Run P ∈ {5,6,7} against the recovery arenas plus E.1's controls with the rule fixed
  first: the default is the smallest P not beaten by a larger one on any arena.
* **E.4 — a parameter budget can be derived from the spectrum; an element budget never could
  be.** `n_data = 2·n_points` is commensurable with a parameter count (`_screening_score` already
  hard-rejects at `n_data − k − 1 ≤ 0`) and with nothing an element count contains. This is the
  strongest purpose-level argument for the whole change (`CLAUDE.md`'s "a knob the target user
  cannot set correctly is not a feature" / "derived from the spectrum's own shape") and the first
  draft did not mention it. A null result — no data-derived rule beating the best constant from
  E.3 — is acceptable and ships the constant.
* **E.5 — growing by a parameter needs an operator that does not exist.** Upgrading an element in
  place (`C → CPE`) is not the same move as inserting one; `enumerate.py:347`'s `_insertions`
  only inserts. A design item for Phase 5 if growth turns out still to be needed.
* **E.6 — skeleton mode leaves two coverage semantics standing** once the default moves; must be
  resolved explicitly (extend the budget to `grow_up_to`, or state the split in the report) and
  not left implicit.
* **E.7 — `--pool auto`'s widening rule (C1–C5) is calibrated against element-level cost.** F4
  shows that cost mostly disappears under a parameter budget; the widening threshold needs
  re-measuring, not just re-running.
* **E.8 — equivalence-class membership changes with the space**, and `docs/OBJECTIVE_PLAN.md`'s
  measured `interpret` claims were measured on the element-axis space. Gate O1's byte-identity is
  unaffected by construction; the *content* an `interpret` report reads is not.
* **E.9 — the `max_candidates` cutoff needs its own grid over pool × P**, since `R,C,L,CPE,W,Wo`
  at P=7 is 280,112 pre-feasibility and a level will again be dropped whole — the same mechanism
  as today, on a new axis, and it should be charted rather than discovered from a report.
* **E.10 — `n_unresolved` / `unresolved_everywhere` rates** are the cheapest early indicator that
  a budget is buying reach the data cannot support, ahead of E.1's slower confirmation.

## 9. Phases

Each phase names, in advance, what would make it not ship.

0. **Confirm, no code.** This document. *Null rule:* if the parameter axis completes no higher a
   level than the element axis on any of F4's four pools, stop and record the negative.
1. **The enumerator, dark. [done, 2026-09-08]** §4, no caller in `discover.py`.
   `count_params` added to `core/circuit.py`; `_PARAM_LEVELS`, `_pool_min_params`,
   `_survives_params`, `_compose_params`, `_param_level`, `enumerate_topologies_by_params`,
   `enumerate_up_to_params`, `count_topologies_by_params` added to `core/enumerate.py`, all in a
   new section, none called from `discover.py`. Gates, all measured: list-identity with the
   element-axis enumerator on unit-parameter-cost pools (`("R","C","L")`, `("R","C","L","W")`);
   set-equality against enumerate-then-filter on four mixed-cost pools × three budgets, including
   `("CPE","Ws")` (`pmin = 2`, exercising the empty-even-level pruning path); the §6 completeness
   lemma as a property test (`R,C,L,CPE` at P=6: level 3 full at 61/61, level 4 a strict subset at
   318/376); `tests/test_enumerate.py` untouched (`git diff` empty, its 66 tests unaffected) —
   kept structurally guaranteed by putting the new tests in a **separate** file,
   `tests/test_enumerate_params.py` (50 tests, all passing); `ruff check`/`ruff format --check`
   clean on every touched/new file (pre-existing formatting warnings in `circuit.py`/
   `enumerate.py` confirmed unchanged by `git stash` comparison); `mypy --strict` clean on both
   core files. Full-suite regression, beyond the two enumerate-related files: `pytest -q` is
   1103 passed / 19 skipped / 1 failed, and the one failure
   (`test_web_bridge.py::test_bridge_version_is_bumped_for_the_new_operations`, pinned to
   `BRIDGE_VERSION == 15` against today's `16`) reproduces identically with this phase's changes
   stashed out — pre-existing, unrelated to this work, not a Phase 1 regression.
   `benchmarks/ev5_fingerprint.py --mode exhaustive` is **byte-identical** before and after this
   phase's changes (same sha256, confirmed via `git stash`), as expected since nothing `discover`
   calls has changed. No null branch; nothing else observed.
2. **Build E.1's controls and E.2's real-data arm, before wiring. [done, 2026-09-08]**
   Three parameter-dense truths added in `benchmarks/six_plus/param_dense_truths.py`, reusing
   `truths.py`'s `Truth`/`screen`/`tune_until_screened` machinery (extended with a `ranges=`
   argument to `tune`/`tune_until_screened`, since CPE's `Q` and SKINF's `A`/`n` need their own
   tuning bounds rather than the R/C/L-shaped default): `cpe_triple`
   (`p(R1,CPE1)-p(R2,CPE2)-CPE3`, 5 elements / 8 params, ratio 1.6), `cpe_c_mix`
   (`p(R1,CPE1)-C1-p(R2,CPE2)`, 5/7, ratio 1.4), `skinf_cpe`
   (`p(R1,SKINF1)-p(R2,SKINF2)-CPE1`, 5/8, ratio 1.6, the one exercising `SKINF`). All three
   passed the four-part admission screen on the tuner's first seed (weakest leverage 8.79-9.90%
   against 1% noise, 0 unresolved, 2.1-3.2% worst deviation, feasible).
   **A latent bug surfaced and was fixed building these**: `Truth.time_constants()` matched
   capacitor labels with `str.startswith("C")`, which also matches `"CPE1"` and `"CC1"` — invisible
   as long as every truth in `truths.py` was R/C/L only, and a `KeyError` the moment a CPE-bearing
   truth was added. Fixed with an exact `re.fullmatch(r"C\d+", ...)` match; `truths.py --check`
   reproduces its existing 9-truth table identically after the fix (`git diff` on the fix is
   the regex change plus the new `ranges` parameter, nothing else).
   **Recovery baseline on today's element axis** (`benchmarks/six_plus/param_dense_baseline.py`,
   `discover(pool=truth.pool, mode="exhaustive")`, seeds 1-3, `complete_up_to=5` on every run, so
   each truth's own topology is enumerated exactly): `cpe_triple` 1/3, `cpe_c_mix` 2/3, `skinf_cpe`
   1/3 recommended (`reported`/`on_front` track `recommended` on every row but one:
   `skinf_cpe` seed 1 is reported and on the front but not recommended).
   **This is itself a finding, independent of any parameter budget**: even where the topology is
   exhaustively enumerated and there is no budget question at all, recovery of these
   CPE/SKINF-dense five-element truths is seed-dependent and well under 100% — the same
   basin-lottery mechanism `docs/TOPOLOGY_6PLUS_PLAN.md` §2(a) measured for tier-1 screening,
   now seen on the parameter-dense class E.1 exists to build. Phase 3's recovery numbers under a
   parameter budget must be read against *this* baseline, not against an assumed 100%.
   **E.2, real-data baseline**: `benchmarks/measured/measured.py pipeline`/`split-half` re-run
   on the element axis. **Operational finding first**: the first attempt used the script's default
   `--time-limit` (none), and one dataset's `mode="auto"` fallback ran unbounded — killed after
   ~2 h of continuous CPU time with zero output, a real hazard for anything in this repository
   that calls `discover()` on real data without a wall-clock budget. Re-run at `--time-limit 60`
   (seconds per `discover()` call): **R2 1/7 in-band** (`chi2_reduced` in `[0.5, 3]`) — reproduces
   `docs/IMPACT_PLAN.md` §4's documented three-to-six-orders-of-magnitude-too-large pattern under
   `weighting="auto"` rather than contradicting it; **R3 2/7 stable (29%)** against the 80% bar,
   close to `IMPACT_PLAN.md`'s recorded 1/7 (the small difference is plausibly the 60 s bound
   changing which local optimum `mode="auto"`'s fallback lands in, not a code regression — not
   chased further, since both numbers are far below the bar either way). Both readings recorded
   here as the "before" picture Phase 3 re-runs under a parameter budget, with the same
   `--time-limit 60` so the two are comparable.
3. **`discover(max_params=...)`, opt-in, default `None`. [shipped, 2026-09-09: EV5, G1 and
   E.1's honesty reading all measured and passing, the last only after a fix; F4 and E.9 also
   measured 2026-09-09 (both below, within item 4), E.10 deliberately not run (below); E.2
   measured 2026-09-10 — stop rule (e) fires, negative recorded, see below]**
   §6's fields/sentences/refusals, `--max-params`. Gates:
   EV5 byte-identical on the element path (non-negotiable); G1 with and
   without the budget; F4's `R1-Ws1` re-measurement including the *recommendation*, not just the
   level reached; E.1's honesty reading; E.2's R2/R3; E.9's grid; E.10's rates. *Ships off by
   default, negative recorded, if:* (a) `reported` falls on any G1 reference; (b) the `R1-Ws1`
   recommendation at P=6 is no closer to the truth than today's stand-in; (c) F4 re-measures with
   the parameter axis completing a lower level on a widened pool; (d) E.1's honesty rule trips;
   (e) E.2's R3 falls.
   **What shipped**: `Enumeration` gains `axis`/`element_cost` and a derived `element_coverage()`;
   `enumerate_candidates(max_params=...)` switches its level source to
   `enumerate_topologies_by_params`; `_exhaustive` returns a 5-tuple; `DiscoveryResult` gains the
   three §6 fields; the parameter-budget coverage sentence; `--max-params`; and both refusals.
   The lever is off unless asked for, so nothing about a default has moved and none of the
   stop rules above can fire yet.
   **The non-negotiable gate passed, on the second attempt, and the first attempt is the part
   worth keeping.** `ev5_fingerprint.py --mode exhaustive,auto` is byte-identical before and
   after (484,386 bytes, same sha256, all three references). It was *not*, at first: adding
   `max_params`/`complete_up_to_params`/`base_complete_up_to_params` to `to_dict()` changed the
   fingerprint on every reference, because EV5 fingerprints that dict and **an always-null key is
   still a key**. No number had moved; the payload had. The three fields were removed from the
   wire schema again and left as Python attributes only — `completeness()`'s prose carries them
   for a `--json` reader until phase 9 wires the browser that needs them. A gate that can only be
   passed by not writing the obvious line is worth more than one written loosely enough to pass
   either way.
   `tests/test_discover_params.py` (15 tests) covers the lemma on four pools, both coverage
   sentences, the unchanged wire payload, both refusals and the `MAX_PARAM_BUDGET` clamp.
   **G1, with and without the budget [measured, 2026-09-09]**, all three `REFERENCES`, two seeds
   each, `mode="exhaustive"`, element axis at `exhaustive_limit=5` against `max_params=6`:

   | reference | axis | reported | on front | recommended | screened | seconds | `complete_up_to` |
   |---|---|---:|---:|---:|---:|---:|---:|
   | capacitor (C-R-L + skin effect) | elements | 2/2 | 2/2 | 2/2 | 6,598 | 350, 361 | 5 |
   | capacitor (C-R-L + skin effect) | params ≤ 6 | 2/2 | 2/2 | 2/2 | **2,318** | **82, 103** | 3 |
   | Maxwell-Wagner (two blocks) | elements | 2/2 | 2/2 | 2/2 | 2,581 | 77, 81 | 5 |
   | Maxwell-Wagner (two blocks) | params ≤ 6 | 2/2 | 2/2 | 2/2 | 2,220 | 78, 74 | 3 |
   | Randles (with Warburg) | elements | 2/2 | 2/2 | 2/2 | 3,713 | 100, 101 | 5 |
   | Randles (with Warburg) | params ≤ 6 | 2/2 | 2/2 | 2/2 | **4,775** | **113, 118** | 3 |

   **Decision rule (a) does not fire: `reported` falls nowhere.** Recovery is 6/6 on both axes,
   and so is `recommended` — each arm names the truth or the same exact reparameterisation of it
   (the capacitor's `R1-C1-L1-SKINF1` and `SKINF1-R1-C1-L1` are one circuit written from two
   traversals; the two Maxwell-Wagner seeds pick the same pair of class members on both axes).
   These three truths cost 5, 4 and 4 parameters, so each sits *inside* a budget of 6 even where
   the budget's own element-wise claim has dropped from 5 to 3 exactly as F5 said it would. That
   distinction is the whole point of §6 and this is the first run to exercise it: a truth can be
   enumerated in full while the report declines to claim completeness at its element count.
   **F6's cost proxy is confirmed in direction and refined in size, now that it is real fits
   rather than a topology count.** The capacitor reference — the widest pool here, five codes
   with both `CPE` and `SKINF` at two parameters each — is **3.5-4.3x faster** under the budget
   (350 s → 82 s) for identical recovery, which is a larger win than F6's 0.77x proxy predicted.
   Maxwell-Wagner is a wash. Randles goes the *other way*, 15% slower on 29% more topologies,
   and the reason is its pool: `("R", "C", "CPE", "W")` prices `W` at one parameter, so a budget
   of 6 buys more of that pool's space than an element cap of 5 does. The proxy's sign was right
   where the pool is expensive and wrong where it is cheap — worth stating, because it means the
   ladder in phase 4 has to be read per pool and not as one number.
   **E.1's honesty reading tripped its own stop rule (d), unanimously, and the fix is the most
   useful thing this phase produced [measured, 2026-09-09].** The three parameter-dense truths of
   §8's E.1 cost 7-8 parameters, so a budget of 6 puts all three *outside* the space by
   construction — the arm exists for no other purpose. On every row (3 truths × 3 seeds, ~2-5 min
   each) the search behaved correctly and the *report* did not:

   | reading | result |
   |---|---|
   | truth `reported` / `on_front` / `recommended` | **0/9** — correct: it is outside the budget |
   | recommendation's own size | **5 elements, 6 parameters, on every row** |
   | recommendation's `n_unresolved` | **0, on every row** |
   | `complete_up_to` | **3, on every row** |

   So the reader was handed a five-element circuit, recommended, every parameter of it resolved,
   under a coverage sentence whose only completeness claim was about *three* elements — and
   nothing in the report connected those two numbers. Every clause of that sentence was true.
   That is precisely the pre-registered trip condition, and precisely the failure shape
   `docs/HANDOFF.md` §3 is a list of.
   **What the rule's own wording then required was a fix, not an abandonment** ("does not ship at
   any default *until the sentence is fixed*"), and the fix is `DiscoveryResult
   ._with_recommendation_note`: when the recommendation's element count exceeds `complete_up_to`,
   the report now says so and says what it means — "it was evaluated, but its own size was not
   searched exhaustively, so a better topology of that size may simply never have been tried.
   That part of the report is a find, not a completeness claim." The wording deliberately mirrors
   `_with_growth_note`, which has made the same distinction for the growth stage since
   `TOPOLOGY_6PLUS_PLAN.md` §4.7.
   **The gap was never parameter-specific, which is the part worth carrying forward.** On the
   element axis the enumeration cannot produce it — everything enumerated is inside the cap — but
   two other routes can and always could: a `seeds=` circuit larger than the cap, and the genetic
   fallback under `mode="auto"`, whose candidates `complete_up_to` does not bound at all. Neither
   said anything before this. A new axis did not introduce the defect; it made it routine enough
   to be caught. `_with_recommendation_note` therefore applies on both axes rather than being
   scoped to the budget that found it, and `ev5_fingerprint.py` is re-checked byte-identical on
   the element path to show that doing so changed no existing report.
   **Fix verified, 2026-09-09**: `ev5_fingerprint.py --mode exhaustive,auto` is byte-identical
   to the pre-fix baseline on all three references (same 484,386 bytes); a new test in
   `tests/test_discover_params.py` drives the note both ways (fires above `complete_up_to`,
   silent at or below it) on a real parameter-dense spectrum; and the full suite is
   1120 passed / 19 skipped / 0 failed. **With the fix in place, Phase 3's status is: shipped,
   off by default, and every gate run so far — EV5, G1, and E.1's honesty reading — passed. F4's
   `R1-Ws1` recommendation re-measurement is supplementary and E.9's grid is measured (both
   below); E.10's rates were deliberately not run (below); E.2's R2/R3 under the budget is now
   measured and tripped
   the lever's own stop rule (e) — see below.**
   **F4's `R1-Ws1` re-measurement [measured, 2026-09-09] — supplementary, not decisive.** The
   original benchmark script behind F4's documented finding (the 3-parameter truth answered by a
   7-parameter stand-in, `p(p(R1-CPE1,CPE2)-C1,R2)`) could not be located in this repository, so
   this re-runs a reconstruction: `R1-Ws1` (`R1.R=50`, `Ws1.R=500`, `Ws1.tau=0.01`) on pool
   `(R,C,L,CPE,Ws)`, 3 noise seeds, element-cap-5 against `max_params=6`:

   | seed | axis | recommendation | is truth | rel. error | seconds |
   |---:|---|---|---:|---:|---:|
   | 0 | elements | `R1-Ws1` | yes | 1.352% | 1,486 |
   | 0 | params ≤ 6 | `Ws1-R1` | yes | 1.352% | 161 |
   | 1 | elements | `R1-Ws1` | yes | 1.250% | 1,554 |
   | 1 | params ≤ 6 | `Ws1-R1` | yes | 1.250% | 145 |
   | 2 | elements | `R1-Ws1` | yes | 1.343% | 1,565 |
   | 2 | params ≤ 6 | `Ws1-R1` | yes | 1.343% | 159 |

   Both axes recommend the truth (or its traversal-order twin) on every seed, to identical
   relative error, and the parameter budget does it **9.3-10.7x faster** (161/145/159 s against
   1,486/1,554/1,565 s) — `complete_up_to` for the budget arm is only 3 elements against the
   element arm's 5, exactly F1's mechanism: this pool's `m = 2` (CPE and Ws both cost two
   parameters), so a 3-parameter truth like this one is fully enumerated by parameter level long
   before the corresponding element level is affordable.
   **This must not be read as validating or refuting Phase 3's stop rule (b).** The
   reconstruction does not reproduce the original pathology at all — both axes get the *right*
   answer here, where the original finding was that the element-cap-5 answer was *wrong*. The
   likely reason is scope: the original pool apparently included `Wo` and `G` alongside `Ws`
   (§2's F4 table lists results for `R,C,L,CPE,Ws,G` and `R,C,L,CPE,W,Ws,Wo,G`, not the narrower
   five-code pool used here), and a wider pool gives the element-cap-5 search more CPE-stack room
   to out-fit the true Warburg branch — exactly the mechanism `docs/POOL_FROM_SPECTRUM_PLAN.md`
   §1 already measured (a CPE stack reaching the noise floor in place of a genuine diffusion
   element). Reconstructing that wider pool without the original truth values and seed would be
   guessing at a second benchmark rather than re-running the first one, so it was not attempted.
   **What actually discharges stop rule (b)'s concern is E.1's honesty reading** (above): a
   negative control built specifically to sit outside the budget, which did trip a real defect
   and got a fix shipped. This F4 re-run stands as a real, separate, and favourable data point —
   correct recovery, large cost win, on a realistic diffusion-element spectrum — not as the
   closing measurement stop rule (b) asked for.
   **E.2's R2/R3 under the budget [measured, 2026-09-10] — stop rule (e) fires.**
   `benchmarks/measured/measured.py pipeline`/`split-half --max-params 6 --time-limit 60`, the
   same budget G1 and E.1 use and the same `--time-limit 60` the element-axis baseline (above)
   was measured at, so the two are comparable:

   | gate | element axis (baseline) | params ≤ 6 |
   |---|---:|---:|
   | R2 in-band | 1/7 | **1/7 — unchanged** |
   | R3 stable | 2/7 (29%) | **0/7 (0%)** |

   R2 does not move: the same single dataset (`impedancepy-biologic`) is the only one landing in
   `chi2_reduced ∈ [0.5, 3]` on either axis, and every other row fails in the same direction
   (`chi2_reduced` ranging from 3.49 to 1.6e4) under the budget too. **R3 falls, from 2/7 to
   0/7** — literally stop rule (e) as written. Both numbers sit far below the 80% bar and the
   swing is two datasets out of seven, so this is not a large-sample result and is not chased
   further this round; it is recorded as a trip rather than waved past on sample size alone,
   because that is exactly what the rule was written to catch. A plausible mechanism, not
   confirmed further: `--pool auto` on real data reaches for a wider, CPE/W-heavy candidate set
   than any `REFERENCES` truth uses, and G1 already measured that pool shape driving
   `complete_up_to` down to as little as 3 elements under a budget of 6 (above) — so odd/even
   halves of a noisy real spectrum are being compared inside a smaller, differently-shaped
   exhaustive region than the element-cap-5 baseline explores, more of it reached by screening
   than by enumeration, which is the same basin-lottery mechanism `TOPOLOGY_6PLUS_PLAN.md` §2(a)
   and E.1's own controls already measured elsewhere in this plan. **This does not change Phase
   3's shipped status** — the lever is already off by default, and this result is an argument for
   keeping it that way, not a reason to touch the code — but it retires the "not yet a blocker"
   framing E.2 carried above: the stop rule has now fired once, on the gate closest to this
   project's actual use case, and any future move toward promoting `max_params` past an opt-in
   default (item 8 below) has to address this finding rather than cite E.2 as still pending.
4. **E.3's ladder over P, and E.4's data-derived cap.** E.4 may end in a null result.
   **E.3, first leg [measured, 2026-09-09]: the three `REFERENCES` at P ∈ {5, 7}, two seeds each**
   (`--max-params`, `workers=4`; P=6 already measured in Phase 3's G1). Combined with that P=6
   row:

   | reference | P | screened | seconds (2 seeds) | `complete_up_to` (elements) | recovery |
   |---|---:|---:|---|---:|---:|
   | capacitor (SKINF) | 5 | 424 | 33, 38 | 2 | 2/2 |
   | capacitor (SKINF) | 6 | 2,318 | 82, 103 | 3 | 2/2 |
   | capacitor (SKINF) | 7 | 13,130 | 637, 694 | 3 | 2/2 |
   | Maxwell-Wagner | 5 | 438 | 24, 26 | 2 | 2/2 |
   | Maxwell-Wagner | 6 | 2,220 | 74, 78 | 3 | 2/2 |
   | Maxwell-Wagner | 7 | 11,810 | 486, 570 | 3 | 2/2 |
   | Randles (Warburg) | 5 | 822 | 30, 31 | 2 | 2/2 |
   | Randles (Warburg) | 6 | 4,775 | 113, 118 | 3 | 2/2 |
   | Randles (Warburg) | 7 → **6**\* | 4,775 | 142, 150 | 3 | 2/2 |

   \* Asking for `max_params=7` on the Randles pool (`R,C,CPE,W`) produced the *same* screened
   count and `complete_up_to_params` as the P=6 row — `max_candidates` (20,000, the default)
   clamped level 7 before it finished, exactly the mechanism F1/F6's own reasoning already names
   for the element axis, now seen on this axis. This is E.9's grid finding itself for free, and
   is recorded there rather than re-derived: the ceiling is per-pool, not per-budget-number.

   **On this arena, P=5 is never beaten — but this arena cannot show a larger P mattering, and
   that has to be said before the number is used.** Recovery is 6/6 at every P tested, including
   the element axis's own cap-5 run from Phase 3's G1. That is because all three `REFERENCES`
   truths cost 4-5 parameters, so **every one of them was already inside a budget of 5** — this
   ladder tests whether raising P past a truth's own cost buys anything (cost only, per the table:
   5x-16x more screening for identical recovery), not whether P=5 is *enough* in general. F1's
   whole reach argument for P ≥ 6 was about six-element `R,C,L` topologies and eight-parameter
   truths, neither of which any `REFERENCES` truth is. Applying E.3's decision rule literally to
   this arena alone ("smallest P not beaten by a larger P") would say P=5, and that reading would
   be an artefact of an arena too easy to distinguish the candidates — the same trap
   `docs/AUTOEIS_COMPARISON.md` §1.5c already names for small truths sitting inside
   `complete_up_to` on the element axis. The arena that can actually move this number is E.1's
   three controls (7-8 parameters, outside a budget of 6 by construction), next.

   **E.9, the cheap version [measured, 2026-09-09]: a pure enumeration-count grid, no fitting.**
   `count_topologies_by_params` (Phase 1) charted six pools × P ∈ {1..7} against
   `max_candidates = 20,000` (pre-feasibility-filter counts, so this is a conservative bound —
   the real, spectrum-dependent feasibility filter only ever removes candidates, so the true
   clamp point can only be at the same level or later than this table predicts, never earlier):

   | pool | first level where cumulative > 20,000 |
   |---|---|
   | default (`R,C,L,CPE`) | never, through P=7 (17,273 at P=7) |
   | Maxwell-Wagner-style (`R,C,L,CPE`) | same as default |
   | capacitor-style (`R,C,L,CPE,SKINF`) | **P=7** (26,445) |
   | Randles-style (`R,C,CPE,W`) | **P=7** (44,360) |
   | F4's (`R,C,L,CPE,Ws`) | **P=7** (26,445) |
   | wide (`R,C,L,CPE,W,Wo`) | **P=6** (34,913) |

   This reproduces the REFERENCES ladder's own free data point exactly: the Randles-pool request
   for `max_params=7` above landed on `complete_up_to_params=6` because the real (feasibility-
   filtered) count still exceeded 20,000 at level 7, and this table's raw bound already flags
   that pool at P=7. **The ceiling is per-pool, not per-budget-number**, which is the shape E.9
   asked to have charted rather than discovered from a report: P=7 is free on the two narrowest
   pools tested and already unreachable in full on three of the other four, and the widest pool
   here loses P=6 as well as P=7. A P chosen without checking this table risks silently losing
   the very completeness claim it exists to make, on exactly the CPE/SKINF/W-bearing pools this
   whole plan is about.

   **E.10 [not run this round].** `n_unresolved`/`unresolved_everywhere` rates were proposed as a
   cheap early indicator, ahead of E.1's slower confirmation. E.1's own controls already ran and
   gave the stronger, slower confirmation this item exists as a proxy for (Phase 3's honesty
   reading, 9/9 rows at `n_unresolved = 0` on a wrong recommendation), so a separate rate-tracking
   pass adds no information this round. Named here as deliberately not run, not silently dropped.

   **E.3, second leg [measured, 2026-09-09/10]: E.1's three controls at P ∈ {5, 7}** (P=6 already
   measured in Phase 3's honesty reading). This is the arena the REFERENCES ladder itself named
   as the one that could actually move the number, because these three truths straddle real
   budget boundaries instead of sitting inside every P tested:

   | truth | cost | P=5 | P=6 | P=7 |
   |---|---:|---|---|---|
   | `cpe_triple` | 8 params | 0/3 | 0/3 | 0/3 |
   | `cpe_c_mix` | 7 params | 0/3 | 0/3 | **3/3 reported, 2/3 recommended** |
   | `skinf_cpe` | 8 params | 0/3 | 0/3 | 0/3 |

   **This is the cleanest confirmation in the whole plan that the parameter axis behaves exactly
   as designed on both sides of a cost boundary.** `cpe_triple` and `skinf_cpe` (8 parameters)
   stay outside every budget tested, including P=7, and the honesty note fires correctly on
   every one of the 15 relevant rows (3 truths × 3 seeds × {P=5, P=7} minus `cpe_c_mix`'s
   now-recovered cells) — never a silent miss. `cpe_c_mix` (exactly 7 parameters) is invisible to
   the search at P=5 and P=6, and the moment the budget reaches its own cost at P=7 the search
   finds it on **every** seed (`reported` 3/3) and prefers it on two of three (`recommended` 2/3;
   seed 3 finds it but a different candidate wins the front that seed — a real, ordinary ranking
   outcome, not a coverage failure, since `complete_up_to_params = 7` for this run and the truth
   was evaluated). No honesty-note false negative anywhere in 27 rows across both legs.
   **Cost, for the record**: P=5 stayed cheap (27-44 s per row, `benchmarks/six_plus/
   param_dense_budget5.json`); P=7 was expensive on the CPE-pool truths (752-1,250 s) and
   markedly cheaper on the SKINF pool (296-309 s, `param_dense_budget7.json`) — consistent with
   `SEARCH_ALGORITHM_SCREENING.md`'s finding that CPE, not element count, is the dominant cost
   driver, since `skinf_cpe`'s pool carries only one CPE code against `cpe_triple`'s three.
5. **X4 at P=7: does the budget make growth unnecessary?** `--max-params 7` on the `six_plus`
   R,C,L-only truths is exactly "every topology up to 7 elements", inside `max_candidates`.
   `Arm("params7", growth_width=0, screen_restarts=1, max_params=7)` added to `recovery.py`'s
   `ARMS`, scored on `reported`/`on_front`/`recommended` (never pooled) plus the five-element
   `over_grown` negative control. Supersedes growth **iff** it beats `grow` on `reported` for the
   6- and 7-element truths on every shape **and** matches `base` on the control. `ser6`/`ser7`
   expected to stay at 0 — written down before the numbers arrive, and not a regression if so.
   Scope the first pass to `--only par5,par6,ser6,mix6 --seeds 1` before the full grid.
   **[measured, 2026-09-10] — does not supersede growth.** Full grid, all nine `six_plus` truths
   × 3 seeds, `benchmarks/six_plus/x4_params7.json`, against `base`/`grow` from the
   existing `x4_recovery.json`:

   | | `base` | `grow` | `params7` |
   |---|---:|---:|---:|
   | six/seven-element `reported` (18 cells) | 0/18 | 14/18 | **15/18** |
   | six/seven-element `recommended` (18 cells) | 0/18 | 12/18 | 12/18 |
   | five-element control, recommended correctly (9 cells) | 9/9 | 9/9 | 9/9 |
   | five-element control, over-grown | 0/9 | 0/9 | 0/9 |
   | median seconds, six/seven-element | 20 | 46 | **131** |
   | median seconds, control | 13 | 57 | 118 |

   Aggregates look close, and the per-truth breakdown is why the decision rule reads them apart
   rather than pooling:

   | truth | `grow` reported/recommended | `params7` reported/recommended |
   |---|---:|---:|
   | `par6` | 3/3, 3/3 | 3/3, 3/3 — tie |
   | `mix6` | 3/3, 3/3 | 3/3, 3/3 — tie |
   | `par7` | 3/3, 3/3 | 3/3, 3/3 — tie |
   | `mix7` | 3/3, 3/3 | 3/3, 3/3 — tie |
   | `ser6` | **2/3**, 0/3 | **0/3**, 0/3 — `params7` loses |
   | `ser7` | 0/3, 0/3 | **3/3**, 0/3 — `params7` wins on `reported` only |

   **The pre-registered rule fires on the first line that breaks it: `params7` loses to `grow` on
   `ser6`'s `reported`, so it does not beat `grow` on every shape, so it does not supersede
   growth.** The control is a clean tie (9/9 either way, no over-growing), which is the half of
   the rule that *did* hold. `ser7` moves the other way — `params7` finds a truth-equivalent on
   every seed where `grow` finds none — but the final `recommended` column stays 0/3 for both, so
   it changes nothing the report says. Both single-truth swings (`ser6` down, `ser7` up) are most
   likely the tier-1 screening lottery `TOPOLOGY_6PLUS_PLAN.md` §2(a) already measured and
   `SEARCH_TIME_PLAN.md` §4.3 already caught flipping `ser6`'s own `reported` flag between two
   otherwise-identical runs — both arms here run at `screen_restarts=1`, a single seed draw per
   topology, and `ser6`/`ser7` are exactly the shape that grid already named as the one every
   basin-lottery and identifiability measurement in this repository agrees is thinnest. Not
   chased further, because the rule does not need the mechanism resolved to give its verdict:
   full parameter-axis enumeration to seven elements is **more expensive** than growth (2.3-2.8x
   on the six/seven-element cells, ~2x on the control) for a **tied-at-best** recovery rate, so
   item 5's question is answered — no, the budget does not make growth unnecessary, and `grow`
   stays the cheaper, no-worse mechanism for reaching past `complete_up_to` on an `R,C,L`-only
   pool. This does not touch `GROWTH_DEFAULT` (still `0`, for `TOPOLOGY_6PLUS_PLAN.md`'s own
   reasons) or anything about `max_params`'s shipped, off-by-default status.
6. **Re-key the quota (§5). Independent of 1–5; shippable alone.** Gates: G1 no truth lost on any
   seed; Q1 `recovered` not fallen; Q3 `by_criterion_overfits` not risen; the tier-1 inertness
   corollary asserted as a unit test; `REFINE_DEFAULT` re-derived for the new bucket count; EV5
   re-baselined with every changed line read (will differ by design — this is the instrument that
   caught the last shortlist bug while 744 tests passed). *Null rule:* any failure reverts to
   `n_elements`. `recovery.py` (X4) is explicitly not a gate here — its nine truths are `R,C,L`
   only, so the three axes coincide and the check would be vacuous.
   **[shipped, code and cheap gates 2026-09-11; G1/Q1/Q3's full-cost runs still pending.]**
   `Ranked.n_elements` → `Ranked.n_params`; `_shortlist`/`_shortlist_candidates`/`_refit_order`
   re-keyed; `_quota_by_size` kept its name (renaming would have touched a large number of
   historical `docs/` entries that describe what happened at the time, for no behavioural
   reason) but its docstring and every caller's now say parameter count, not element count.
   **The constant, from a free replay, before any code changed**: `benchmarks/screening_round/
   quota_replay.py` (new) replays `_shortlist` over the frozen 21,057-topology
   `land_rclcpe6.json` landscape with no fitting at all, sweeping `MIN_REFINE_PER_SIZE` under
   both keys. The decision rule ("largest floor keeping every arena's refit-count multiplier at
   or under 1.25×, checked against `land_rclcpe6`'s replay and a parameter-count-only structural
   estimate on the three `REFERENCES` pools") landed on **`MIN_REFINE_PER_SIZE = 5 → 3`**: at 5
   the multiplier is 1.66–1.93× across the four arenas checked, at 3 it is 1.03–1.22×, and the
   truth's own 18-member equivalence class survives the shortlist at every setting tried (ranked
   81st of 21,057 by screening cost, regardless of key or floor). `REFINE_DEFAULT`'s docstring
   now states the corollary this forces: at 3, the floor binds on every parameter-count bucket
   count of 10 or more, which is every CPE-bearing pool this project actually searches, so
   `REFINE_DEFAULT` is inert there by construction rather than by the old, narrower "below
   `MIN_REFINE_PER_SIZE * buckets`" statement.
   **The tier-1 inertness corollary, gated as two unit tests** rather than asserted from the
   docstring alone (`tests/test_discover_exhaustive.py`): a positive one showing
   `_shortlist`'s output is byte-identical across all seven `CRITERIA` on a CPE-bearing fixture
   spanning several parameter-count buckets, and a negative one showing the *mechanism* the old
   key was exposed to — two same-element-count, different-parameter-count circuits
   (`p(R1-CPE1,R2)`, four parameters; `CPE1-CPE2-CPE3`, six) whose relative `_screening_score`
   ranking flips between AIC and BIC at a chosen cost pair, which is exactly what a single
   element-count bucket used to expose a criterion choice to and a parameter-count bucket never
   does (each stands in its own bucket). Both pass; `pytest -q` (full suite) is **1122 passed,
   19 skipped, 0 failed**; `ruff check`/`ruff format --check`/`mypy --strict` clean on every
   touched file (the one pre-existing `discover.py` mypy error, an unexported `Weighting`
   re-export, reproduces identically with the change stashed out).
   **EV5** (`--mode exhaustive,auto`, all three `REFERENCES`, run before/after in an isolated
   `git worktree` rather than an in-place `git stash` after the first attempt at that raced a
   concurrently-running background test suite and had to be aborted and recovered): differs, as
   expected, and characterised rather than merely diffed. `recommended` and `complete_up_to` are
   **byte-identical on all six (reference × mode) rows**. The Pareto front is identical on two of
   three references and gains exactly one member on the capacitor reference (`R1-C1-L1`, a
   three-element candidate that the old element-count-4 bucket had been losing to CPE/SKINF
   competitors it now no longer shares a bucket with) — a strict improvement in what the front
   shows, not a regression. Candidate counts shift in the direction F6's cost proxy predicted:
   down on the two references where CPE-stack duplicates previously crowded the shortlist
   (Maxwell-Wagner 39→35, Randles 39→37) and up on the widest pool (capacitor 37→40), with the
   "only-before" sets dominated by CPE-pair topologies (`CPE1-CPE2`, `p(CPE1,CPE2)`, ...) giving
   way to "only-after" sets of more parameter-diverse ones. This mini-arena spot check (4-element
   cap, not the full 5-element G1) is not gate G1 itself — the full-cost `discovery_v2.py gate`
   run and `criterion_selection.py`'s Q1/Q3 slice are still pending, per the staged order of work
   agreed with the user — but it is a favourable, structurally-consistent early read.
7. **§7's surcharge measurement.** Independent. Arm B must clear the `best_cost` fingerprint
   first.
8. **Move the default and the user-facing knob.** Only if 3, 4 and 5 all passed — **item 3 has
   not**: E.2 tripped its stop rule (e) on 2026-09-10 (above), which this item's own condition
   already treats as disqualifying rather than a soft note. Not attempted until that finding is
   addressed, not merely re-read as acceptable. E.6 resolved first. `--exhaustive-limit` kept as
   a deprecated alias. Requires a re-baselined EV5, fresh G1, fresh X4, and a date beside every
   number in `docs/` describing the old space.
9. **Browser**, last. `BRIDGE_VERSION` bump with a changelog line; "Element limit" becomes
   "Parameter limit"; growth controls hidden under a parameter budget rather than computing on
   the wrong axis.

## Blast radius not otherwise covered

`mode="auto"` escalates more often once `complete_up_to` falls under a parameter budget (a real
behaviour change to be read in Phase 3's EV5 diff, not a footnote). The genetic sampler stays on
the element axis — it makes no completeness claim and a parameter-budgeted mutation needs its own
acceptance rule plus E.5's missing upgrade operator. `PARSIMONY_SCALING` is also keyed on
`complexity` but currently 0, so §7 is inert there. `benchmarks/topology_space.py`'s independent
naive enumerator gets the parameter-axis set-equality check noted in its own docstring, beside
gate G2.
