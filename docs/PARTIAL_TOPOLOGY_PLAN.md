# Partial Topology — Skeleton-Constrained Discovery

Status: **steps 1–2 are implemented and measured** (enumeration, and the search wired to it),
**step 3 is two thirds done** (§3.4 and §3.5; §3.3 is open and its cost estimate has been
corrected), and **step 4's experiment has been run** — gates P1, P3 and P4 pass, and P2 is
written from the measurement rather than from a guess (§3.2). Written 2026-08-12, measured
2026-08-13.
Prerequisite reading: `docs/DISCOVERY_V2_PLAN.md` (especially the corrections in §3.2, §3.4 and
§5.1 — this design repeats their shape), `docs/HANDOFF.md` §3, and `CLAUDE.md`'s three modes.

## 1. Why

The user usually knows part of the answer before the search starts. A film capacitor has an ESR
and an ESL in series with it; an electrochemical cell has an electrolyte resistance in series
with everything. Making the search rediscover that is not a robustness feature, it is wasted
budget — and worse, it produces reports that offer the user topologies they already know are
wrong.

This is not a new axis. It is the middle of one that already exists:

| mode | structure | parameters |
|------|-----------|------------|
| `fit` | entirely fixed by the user | searched |
| **partial (this document)** | **partly fixed by the user** | **searched** |
| `discover` | free within the pool | searched |

`discover()`'s docstring already calls restricting the pool "the main way to inject physical
knowledge". A skeleton is the same idea with a sharper instrument, and it is a much stronger
one. Candidates at five elements from the component pool `R/C/L/CPE/SKINF`:

| skeleton | n = 3 | n = 4 | n = 5 | n = 6 | reduction at n = 5 |
|----------|------:|------:|------:|------:|-------------------:|
| *none (full space)* | 146 | 1,163 | 10,214 | — | 1.0× |
| `R1` | 69 | 667 | 6,711 | 69,481 | 1.5× |
| `R1-L1` | 15 | 206 | 2,631 | 32,528 | 3.9× |
| `C1-R1-L1` | 1 | 31 | 601 | 9,857 | **17×** |
| `C1-R1-L1-SKINF1` | 0 | 1 | 71 | 2,145 | 144× |

[measured, `tests/test_skeleton.py` and the counts above] Against 1.15–1.75× for the structural
feasibility filter and ~2.3–2.5× for the browser's worker pool, **a three-element skeleton is
the single largest lever in the system**. It also brings six elements into range — 9,857
candidates for `C1-R1-L1`, against a full-space level the search cannot afford at all — which
is the first time discovery can look above five elements while still claiming completeness.

Note the shape of that table: a weak skeleton is a weak constraint (`R1` alone buys 1.5×), and
the reduction is roughly geometric in how much structure the user is willing to assert. That is
the right incentive. It also means the feature cannot be sold as "speed"; it is sold as
*asserting what you know*, and the speed follows.

### 1.1 How large a skeleton, and how many added elements

The obvious next question — "I have a ten-element model of my device, add up to five more" —
has a hard answer, so it is worth stating before anyone designs around the wrong one.

[measured] A ten-element block-structured skeleton
(`R1-L1-p(R2,C1)-p(R3,C2)-p(R4,C3)-p(R5,CPE1)`) against the component pool, with the tier-1
screen timed on this machine at 135 ms per thirteen-element candidate (four-element candidates
cost 30 ms):

| added | total | candidates | tier-1, 1 core | tier-1, 8 workers |
|------:|------:|-----------:|---------------:|------------------:|
| +1 | 11 | 167 | 23 s | seconds |
| **+2** | **12** | **11,418** | **~23 min** | **~3–5 min** |
| +3 | 13 | 521,438 | ~20 h | ~3 h |
| +4 | 14 | ~2·10⁷ (extrapolated) | days | ~4 days |
| +5 | 15 | ~8·10⁸ (extrapolated) | years | months |

Each level costs 40–70× the one before it. **Adding one or two elements to a large skeleton is
practical; adding five is not, by roughly six orders of magnitude.** That is the good news it
looks like: "what is my ten-element model missing?" is nearly always a one- or two-element
question, so the affordable range and the interesting range coincide.

[measured] **The skeleton's *shape* matters more than its size.** The same ten elements as one
flat series node (`R1-C1-L1-CPE1-...`) gives 2,148,316 candidates at +2 against the block
model's 11,418 — **188×** worse — because a flat node with c children has 2^c ways to group a
proper subset of them. Real device models are chains of blocks, so this usually falls the right
way, but a user who writes their skeleton as one long series chain pays for it.

Enumeration memory is the binding constraint before compute is: +3 materialises 780k trees in
33 s, and +4 would hold ~2·10⁷ of them.

## 2. What "contains the skeleton" means — decided and implemented

**Containment is deletion-and-collapse, not subtree matching.** A candidate contains the
skeleton when deleting some of its elements, and collapsing what that empties, leaves the
skeleton behind. `core/enumerate.contains_skeleton()` is that predicate, written out as the
definition of the space independently of how it is generated.

The obvious alternative — "the skeleton appears as a subtree" — is simply wrong here, and not
marginally. `series()` and `parallel()` flatten nested nodes of the same type, so the skeleton
`R1-C1` is nowhere to be found as a subtree of `R1-C1-p(R2,L1)`: that tree is a single
three-child series node. A subtree test would reject the most obvious candidate the user
expects.

`core/enumerate.grow_from_skeleton()` generates the space by insertion closure, and the two
were cross-checked as sets against `enumerate_topologies()` filtered by the predicate — the
same method gate G2 uses on the unconstrained enumerator. That cross-check earned its place
immediately:

**[measured] Attaching an element at an existing position is not enough.** A sub-group of a
flattened node's children is not an addressable position, so putting a capacitor across only
the `C1-L1` half of the skeleton `R1-C1-L1` — canonical form `[C-p(C,[L-R])]` — cannot be built
by any attachment to any position. Attachment alone found **7 of the 16** four-element
topologies containing that skeleton, and **58 of 139** at five elements. That is a silent hole
in precisely the completeness guarantee this mode exists to provide, and it looked like a
complete implementation. `_insertions()` therefore also groups proper subsets of a node's
children and attaches beside the group; `tests/test_skeleton.py` names the case so it cannot be
optimised away again.

**Intermediate trees are not pruned**, only the final level is. A partially grown tree that
`simplify` would collapse, or that `is_plausible_node` would reject, can still be on the only
path to a valid larger candidate. Pruning them is an optimisation that can only lose
topologies, and it would not even be a large one.

## 3. What the constraint costs, and what the report owes the user

This is the part that needs the care, because the failure mode is familiar. **In all three of
this project's measured traps, the report still looked healthy while the answer was gone:** the
screening budget that drops the truth while its exact equivalents stay at ranks 1–3
(`HANDOFF.md` §3), the DRT peak count that would delete the right answer from a search still
calling itself exhaustive (`DISCOVERY_V2_PLAN.md` §3.4), and the tier-2 shortlist that refitted
only five-element circuits (§5.1). A skeleton is the same shape: assert something false and the
search returns a confident Pareto front, equivalence classes and all, over a space that never
contained the answer.

Four obligations follow. None is optional, and none is expensive.

### 3.1 The completeness statement must name the skeleton

`DiscoveryResult.completeness()` currently reads *"every plausible topology with up to N
elements from this pool was evaluated"*. Under a skeleton that sentence is false. It becomes
*"every plausible topology with up to N elements that contains `C1-R1-L1` was evaluated"* —
still a completeness claim, and a more useful one inside its space, but a different one.

`DiscoveryResult` therefore gains `skeleton: str | None`, and `completeness()` branches on it.
The `complete_up_to` arithmetic itself is unaffected: sizes below the skeleton's own element
count contain nothing that contains the skeleton, so the level-by-level accounting still starts
at 1 and `exhaustive_min` keeps its existing meaning.

**Implemented.** Two details the draft had not spelled out, both decided the same way:
`summary()` prints the skeleton on its own line above the coverage sentence, marked *asserted
by you, not discovered*; and the `--json` report carries the whole `coverage` sentence beside
`complete_up_to`, because a machine reader given only the integer would reconstruct exactly the
unconstrained claim this section exists to prevent.

### 3.2 A wrong skeleton must be visible — measured, and not where anyone expected

The experiment is `benchmarks/discovery_v2.py wrong-skeleton`: each reference under a skeleton
its truth does not contain, 10 seeds, the three questions asked as numbers. The answers, in
full, are in `benchmarks/README.md`. They are worth stating here because two of the three
overturn what this section originally assumed.

**[measured] The residuals say nothing. 0/30.** Not "less than hoped" — nothing at all: the
runs test sees noise in every seed, and `chi2_reduced` equals what the *truth itself* achieves
on the same data to two figures, on every reference. The escape valve proposed above — screen
a small unconstrained sample and report when something outside the skeleton fits materially
better — is therefore dead on the evidence, and it would have looked reasonable forever if it
had been built instead of measured. Nothing outside fits better because the constrained best
already fits as well as the generating circuit.

**[measured] Two of the three "wrong" skeletons were not falsifiable at all, and finding that
out is the result.** `p(R1,CPE1)` is a strict *generalisation* of `p(R1,C1)`: a CPE with n = 1
is a capacitor. So the Maxwell-Wagner and Randles skeletons contain the truth's *behaviour*
while `contains_skeleton` correctly reports that they do not contain its *topology*. Both come
back as the skeleton itself, every parameter resolved, and the fitted exponent sitting at
n ≈ 1 — which is the finding, and it is already in the report as a parameter value. **Wrong at
the level of element codes is not the same as wrong at the level of what the data can
express**, and no report can be asked to refute an assertion the data cannot refute.

**[measured] Where the skeleton *is* falsifiable, the report does say something — and the
signal is not the fit quality.** Asserting `R1-p(R2,C1)` against the capacitor truth returns
`R1-p(R2,C1-L1-SKINF1)`, which becomes the truth exactly when R2 goes to an open. The fit
neutralises the asserted parallel branch, and the element it had to neutralise is precisely
the one that will not resolve: 9/10 seeds carry an unresolved parameter and
`unresolved_everywhere` is true on the same 9. So:

> **A wrong skeleton that the data can refute announces itself as an asserted element the fit
> had to switch off, not as a worse fit.**

That is what P2 should be written on, and what §3.4's warning was already half-detecting by
accident. What it forces is small and specific: the report should say *which* of the user's
asserted elements the fit had to neutralise, rather than reporting an unresolved parameter
somewhere in the circuit and leaving them to notice it is one of theirs. Placement ambiguity
(§3.5) is part of the same computation — if every placement of the skeleton has a neutralised
element, the assertion is doing no work anywhere.

### 3.3 The skeleton chooses among forms the data cannot distinguish

`R1-p(R2,C1)` and `p(R1,C1-R2)` fit any single semicircle identically, to 1.2e-15. A skeleton
that asserts a series resistance keeps the first and excludes the second. That is legitimate —
a physical electrode really does have an electrolyte resistance in series — but it is a choice
the user made, and the report must not let it read as something the data supported.

So: the report states which members of each reported equivalence class the skeleton excluded.

**[corrected] "This is cheap to compute" was wrong, and it was wrong in the same way twice.**
The first draft argued that the unconstrained equivalents are the same-size topologies that
fit identically, and that the search already groups by fitted response. It does — *among the
candidates it fitted*. The excluded ones are by definition the candidates it did not fit, so
their equivalence is exactly the thing not known, and establishing it means screening the
same-size topologies outside the skeleton: at five elements on the component pool that is
10,214 − 601 ≈ 9,600 fits, which is the work the skeleton was asserted to avoid.

Three honest options, in ascending cost, to be settled by measurement rather than by argument:

1. **Report the size of the excluded space.** `grow_up_to` and `enumerate_topologies` already
   produce both counts, so "your skeleton excluded 9,613 of the 10,214 five-element
   topologies" costs one enumeration pass and no fitting. It states the price of the assertion
   without naming what was bought.
2. **Screen the excluded topologies against the reported model's own response**, not against
   the data. An exact reparameterisation returns a cost around 1e-30 against a noise-free
   target, so one tier-1 screen per excluded topology of that size identifies the excluded
   equivalents exactly. This is the real §3.3, at roughly the cost of the unconstrained screen
   at one size — minutes, not the whole search, and plausibly an opt-in flag rather than a
   default.
3. **Precompute the exact-equivalence partition of the enumerated space offline.** Exact
   equivalence is algebraic and data-independent, so it could be a table computed once per
   (pool, size) rather than per run. That is a benchmark-sized job and its own decision.

Option 1 is free and belongs in the report either way. Which of 2 or 3 to build — if either —
should wait for gate P2, since what a wrong skeleton actually looks like decides how much
weight this section has to carry.

### 3.4 Past a certain size the data is the limit, not the search

A thirteen-element candidate carries 14–15 parameters against the 142 real residuals of a
71-point spectrum. This project has already measured what happens well below that: on that same
capacitor spectrum, minimum-AICc selected a **nine**-parameter circuit two of whose parameters
had standard errors larger than their own values (`HANDOFF.md` §3), which is why
`DiscoveryResult.recommended` applies parsimony instead of taking the AICc winner.

So a search that grows a ten-element skeleton by three or four does not fail by returning
nothing. It fails by returning a wall of candidates that all fit essentially perfectly and none
of which are identifiable — every one with a large `n_unresolved`, the parsimony rule rejecting
all of them, and a Pareto front carrying no information. **No amount of enumeration speed fixes
that**, because the missing constraint is measurement, not compute. If large skeletons turn out
to matter, the answer is more data (wider frequency window, multiple bias points), not a bigger
search.

This is worth saying in the report too: when the shortlist's candidates are uniformly
unresolved, that is a finding about the experiment, and it should be stated as one.

**Implemented** as `DiscoveryResult.unresolved_everywhere`, printed above the recommendation.
It is deliberately not a skeleton-only warning — the condition is a property of the data and
the front, and an unconstrained search can reach it too — but a skeleton is the systematic way
to arrive there. [measured] A flat resistive spectrum searched under the skeleton `R1-C1-L1`
returns `chi2_reduced` of 4e-4 with two of its three parameters carrying standard errors
larger than their own values: a report that printed only the fit quality would be inviting
exactly the wrong conclusion. That is also a preview of what §3.2 has to measure properly.

### 3.5 Which element is "yours" can be genuinely ambiguous

Dedup is by canonical form, so each topology is fitted once, but a skeleton can map into the
same topology in more than one way. From skeleton `R1`, both "insert C in parallel, then R in
series with the C" and "insert C in series, then R in parallel with the pair" reach the
canonical form `p(R,[C-R])` — with the user's resistor in a structurally different place each
time, and different fitted values.

The honest output is not to pick one. It is to report the placement count, and when it exceeds
one, to say that the data cannot attribute the assertion to a particular element. Fitting is
unaffected; this is purely a labelling question, and pretending it has a unique answer would be
the same error as reporting one member of an equivalence class as "the answer".

**Implemented** as `enumerate.count_skeleton_placements()`, surfaced through
`DiscoveryResult.placements_of()` and a summary section. Two placements count as one when an
automorphism of the topology carries one to the other, which falls out of marking the
skeleton's leaves and taking the canonical form of the marked tree — counting raw leaf subsets
instead would invent an ambiguity for every symmetric circuit. The example above is not
exotic: asserting `R1` against the recovered `R1-p(R2,C1)` gives two placements, so a user who
asserts "there is a series ESR" is told that the fit cannot say which of the two resistors is
theirs.

## 4. Design

### 4.1 API

```python
discover(spectrum, *, skeleton="C1-R1-L1", pool=("R", "C", "L", "CPE"), exhaustive_limit=6)
```

- `skeleton: str | None = None`. `None` is today's behaviour, unchanged and bit-identical.
- **`pool` governs the added elements only.** The skeleton may use codes outside it: it is an
  assertion, not a search result. (Implemented this way already.)
- `exhaustive_limit` stays a **total** element count, consistent with everything else in the
  system, and a limit below the skeleton's own size is an error rather than an empty result.
  The CLI prints the arithmetic ("skeleton has 10 elements; evaluating totals 10 to 12, i.e. up
  to 2 added"), because a total is not what the user was thinking in.
- **The default limit is whatever `max_candidates` allows, not a fixed number of added
  elements.** [measured — corrects this document's first draft] The first draft proposed
  defaulting to `len(skeleton) + 2`, which is right for a ten-element skeleton and wrong for a
  three-element one: §1.1 measures +2 as the affordable ceiling at k = 10 (11,418 candidates),
  while at k = 3 the same budget reaches +3 comfortably (9,857). A fixed offset ignores the
  thing that actually varies. `discover()` already clamps `exhaustive_limit` down when a level
  would push the count past `max_candidates` (default 20,000) and already reports the result
  honestly through `complete_up_to` — so the default is simply a generous limit, and the
  existing machinery lands on +2 for k = 10 and +3 for k = 3 with no new rule and no new way to
  be wrong.
- Everything else composes unchanged: the feasibility filter, the two-tier screen, `workers`,
  `on_progress`, and the `screen_plan()` generator the browser drives.

One implementation note that falls out of §1.1: levels must be grown **incrementally**. Calling
`grow_from_skeleton(skeleton, pool, n)` once per size recomputes the whole insertion closure
each time, and the clamping check has to run *before* the next frontier is materialised — at
k = 10 the +4 frontier is ~2·10⁷ trees, so a `max_candidates` test applied after building it
would run out of memory to enforce a limit that was already exceeded. `grow_up_to()` therefore
keeps the frontier between levels and stops on the frontier size, not only on the kept count.

CLI: `autocircuit discover data.csv --skeleton "C1-R1-L1" --pool component`.

**Implemented, with three points the draft above left open.**

- **The clamp aborts a level while it is being built, not after.** Stopping *on* the frontier
  size, as written above, still means the offending level is the one that gets built — the
  check only bites on the level after it, and the argument that the next level is always larger
  is empirical, not a theorem. `grow_up_to(max_frontier=...)` instead abandons a level the
  moment it passes the bound and ends the iteration there, so peak memory is bounded by the
  bound itself and the levels already yielded are whole. `discover()` passes `max_candidates`.
- **The default reach is `len(skeleton) + 5`** (`discover.SKELETON_REACH`), with
  `exhaustive_limit=None` meaning "reach, then let the clamps decide". Five added elements is
  past the affordable range at every skeleton size in §1.1 — deliberately, since the point is
  that the clamp, not the constant, chooses where a given skeleton stops.
- **A skeleton and the genetic search do not compose, so they are not allowed to.**
  `mode="evolve"` with a skeleton raises, and `mode="auto"` runs the exhaustive stage alone
  rather than falling back. `mutate()` deletes and retypes elements, so an evolved population
  is not confined to circuits containing the skeleton; filtering its offspring instead would
  reject nearly all of them, and letting it run unfiltered would produce a report whose
  candidates came from two different spaces while `completeness()` could only name one. That is
  §3.1's failure in a new place. For the same reason `max_elements`, which caps the genetic
  search only, no longer clamps the enumeration limit when a skeleton is given — otherwise its
  default of 7 would silently cut a ten-element skeleton off below its own size.

### 4.2 Where this leaves the web UI

The circuit canvas of `docs/WEB_UI_PLAN.md` §3 step 3 is already a skeleton editor — "draw part
of a circuit and press Discover" is the same interaction as "draw all of it and press Fit". That
is the reason this document is being settled before phase 6 rather than after it: building the
canvas once, knowing it serves both, is cheaper than building it twice. Nothing in the web plan
has to change; step 3 gains a second button.

## 5. Work order

| step | contents | size | status |
|------|----------|------|--------|
| 1 | `contains_skeleton`, `grow_from_skeleton`, cross-check tests | M | **done** — `tests/test_skeleton.py`, 89 tests; see §2 |
| 2 | `grow_up_to()`, `discover(skeleton=...)`, `DiscoveryResult.skeleton`, completeness wording, CLI flag | M | **done** — see the notes in §3.1 and §4.1 |
| 3 | Report: excluded equivalents (§3.3), unresolved-across-the-board (§3.4), placement multiplicity (§3.5) | M | §3.4 and §3.5 **done**; §3.3 open — its cost estimate was wrong, see the correction there |
| 4 | Gate P2 — the wrong-skeleton experiment (§3.2), and whatever it forces | M | experiment **done and recorded**; what it forces (naming the neutralised element) is not built |
| 5 | Docs: this file, `IMPLEMENTATION_PLAN.md` §6, `HANDOFF.md`, README | S | |

Step 4 is not last because it is least important; it is last because it needs steps 2–3 to run
at all. It is the step most likely to send steps 2–3 back for changes.

## 6. Acceptance gates

- **P1** — with the *true* skeleton, the truth or an exact equivalent is recovered on all three
  reference spectra, 10/10 seeds, and the run is faster than the unconstrained one by
  approximately the ratio in §1. Recovery is the gate; the speed-up is a recorded observation,
  not a target to tune towards (`DISCOVERY_V2_PLAN.md` G1 records what happens when a time
  target is chased). **[measured] passes 30/30**, at 2.7–15.4× fewer candidates and 1.7–6×
  faster. One unlooked-for result: on the capacitor reference the truth is the *recommendation*
  10/10 with the skeleton against 9/10 without it — asserting the ESR puts it where the
  parsimony rule can no longer drop it at 1% noise. A skeleton is not only a way to search
  less.
- **P2** — with a *wrong* skeleton, the report does not read as a successful search. Now that
  §3.2 has been measured, the gate can be written, and the measurement rules out the two
  obvious wordings before it does. Not "the residuals are larger" — they are not, 0/30, and
  that phrasing was warned against here before anyone knew how completely true the warning
  was. Not "something unconstrained fits better" either — nothing does. The gate is:

  1. **A falsifiable wrong skeleton must show up as an asserted element the fit had to
     neutralise**, named as the user's own, on the reference where the assertion is genuinely
     refutable. [measured] The raw signal is already there 9/10 seeds; naming it is §3.2's
     forced change.
  2. **An unfalsifiable wrong skeleton must not be treated as a failure.** A CPE asserted where
     the sample has an ideal capacitance fits identically and returns n ≈ 1; the report's job
     there is to state the coverage constraint and the fitted exponent, both of which it does.
     A gate that demanded a warning here would be demanding a false one.
  3. **No run may present the skeleton as confirmed by the data.** This is the one that holds
     in all three cases, and `completeness()` is what carries it.
- **P3** — the constrained enumeration equals the unconstrained enumeration filtered by
  `contains_skeleton`, as sets, on the reference cases. **[measured] passes** —
  `tests/test_skeleton.py`.
- **P4** — `skeleton=None` changes nothing: the existing suite stays green and unconstrained
  discovery output is unchanged for a fixed seed.

## 7. Risks

- **A wrong skeleton is silent.** The central one. [measured] It is *completely* silent in
  everything the report currently emphasises — residuals, chi², coverage — and the one place it
  does surface is a parameter that will not resolve. §3.2 records the measurement and P2 is
  written on it.
- **The feature makes the completeness claim easy to misread.** A user who sees "every
  plausible topology was evaluated" and skims past "that contains `C1-R1-L1`" has been misled by
  a true sentence. Mitigated by putting the skeleton in the same line rather than in a footnote,
  which is the same call `complete_up_to` already got.
- **Placement ambiguity looks like a bug.** A report that declines to say which resistor is the
  user's ESR will read as an omission unless it says *why*. Wording matters here.
- **Skeleton growth runs out of memory before it runs out of time.** [measured] The frontier is
  materialised level by level: 780k trees at +3 from a ten-element skeleton, ~2·10⁷ at +4.
  `max_candidates` clamping covers the fitting cost but not the enumeration memory, which is
  why §4.1 has `grow_up_to()` stop on the frontier size as well. A user who writes their
  skeleton as one flat series chain hits this 188× sooner than one who writes it as blocks.
- **The mode invites a question it cannot answer.** "I have ten elements, add five" is a
  perfectly reasonable thing to ask and the answer is no, twice over: ~10⁹ candidates (§1.1)
  and, well before that, a model with more parameters than the data can resolve (§3.4). The CLI
  should say which of the two limits it is hitting rather than simply grinding.

## 8. Out of scope

- **Fixing parameter *values* in the skeleton**, e.g. "the ESL is 5 nH, find the rest".
  `fit(fixed=...)` already does this for a complete circuit and the two features compose
  obviously, but combining them raises its own question — whether a fixed value should
  constrain the tier-1 screen — and it is severable.
- Skeletons expressed as anything other than a circuit: "at least two relaxations", "something
  capacitive at low frequency". `exhaustive_min` and the pool already cover the crude version,
  and DRT covers the diagnostic version.
- Automatically *suggesting* a skeleton from the data. That is what discovery already is.
