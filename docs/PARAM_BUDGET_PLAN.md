# PARAM_BUDGET_PLAN.md — should the exhaustive search be budgeted by free parameters instead of elements?

**Status: Phase 0 and Phase 1 done. Phases run in order; each states in advance what result means
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
2. **Build E.1's controls and E.2's real-data arm**, before wiring, and baseline both on today's
   element axis.
3. **`discover(max_params=...)`, opt-in, default `None`.** §6's fields/sentences/refusals,
   `--max-params`. Gates: EV5 byte-identical on the element path (non-negotiable); G1 with and
   without the budget; F4's `R1-Ws1` re-measurement including the *recommendation*, not just the
   level reached; E.1's honesty reading; E.2's R2/R3; E.9's grid; E.10's rates. *Ships off by
   default, negative recorded, if:* (a) `reported` falls on any G1 reference; (b) the `R1-Ws1`
   recommendation at P=6 is no closer to the truth than today's stand-in; (c) F4 re-measures with
   the parameter axis completing a lower level on a widened pool; (d) E.1's honesty rule trips;
   (e) E.2's R3 falls.
4. **E.3's ladder over P, and E.4's data-derived cap.** E.4 may end in a null result.
5. **X4 at P=7: does the budget make growth unnecessary?** `--max-params 7` on the `six_plus`
   R,C,L-only truths is exactly "every topology up to 7 elements", inside `max_candidates`.
   `Arm("params7", growth_width=0, screen_restarts=1, max_params=7)` added to `recovery.py`'s
   `ARMS`, scored on `reported`/`on_front`/`recommended` (never pooled) plus the five-element
   `over_grown` negative control. Supersedes growth **iff** it beats `grow` on `reported` for the
   6- and 7-element truths on every shape **and** matches `base` on the control. `ser6`/`ser7`
   expected to stay at 0 — written down before the numbers arrive, and not a regression if so.
   Scope the first pass to `--only par5,par6,ser6,mix6 --seeds 1` before the full grid.
6. **Re-key the quota (§5). Independent of 1–5; shippable alone.** Gates: G1 no truth lost on any
   seed; Q1 `recovered` not fallen; Q3 `by_criterion_overfits` not risen; the tier-1 inertness
   corollary asserted as a unit test; `REFINE_DEFAULT` re-derived for the new bucket count; EV5
   re-baselined with every changed line read (will differ by design — this is the instrument that
   caught the last shortlist bug while 744 tests passed). *Null rule:* any failure reverts to
   `n_elements`. `recovery.py` (X4) is explicitly not a gate here — its nine truths are `R,C,L`
   only, so the three axes coincide and the check would be vacuous.
7. **§7's surcharge measurement.** Independent. Arm B must clear the `best_cost` fingerprint
   first.
8. **Move the default and the user-facing knob.** Only if 3, 4 and 5 all passed. E.6 resolved
   first. `--exhaustive-limit` kept as a deprecated alias. Requires a re-baselined EV5, fresh G1,
   fresh X4, and a date beside every number in `docs/` describing the old space.
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
