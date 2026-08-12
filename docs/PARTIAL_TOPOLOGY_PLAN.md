# Partial Topology — Skeleton-Constrained Discovery

Status: **step 1 (enumeration) is implemented and measured**; steps 2–5 are a draft for
approval. Written 2026-08-12.
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

### 3.2 A wrong skeleton must be visible — and how visible is not yet measured

**This is the gate the mode has to pass before it ships, and it has not been run.** The
experiment: fit the capacitor reference (truth `C-R-L-SKINF`) under a skeleton that is wrong
for it, such as the Randles-flavoured `R1-p(R2,C1)`, and record what the report says. The
questions are all empirical, and guessing at them is how the traps above got built:

- does the best constrained fit leave residuals the runs test can see as structure?
- does the parsimony recommendation come with unresolved parameters, or does it look clean?
- is `chi2_reduced` far enough from the unconstrained best to be worth reporting as a warning?

If the answer is "the constrained report is indistinguishable from a good one", the mode needs
an explicit escape valve — the cheapest being to screen a small unconstrained sample alongside
and report when something outside the skeleton fits materially better. That is a real design
decision and it should be made on the measurement, not before it.

### 3.3 The skeleton chooses among forms the data cannot distinguish

`R1-p(R2,C1)` and `p(R1,C1-R2)` fit any single semicircle identically, to 1.2e-15. A skeleton
that asserts a series resistance keeps the first and excludes the second. That is legitimate —
a physical electrode really does have an electrolyte resistance in series — but it is a choice
the user made, and the report must not let it read as something the data supported.

So: the report states which members of each reported equivalence class the skeleton excluded.
This is cheap to compute, because the unconstrained equivalents are exactly the topologies of
the same size that fit identically, and the search already groups by fitted response.

### 3.4 Which element is "yours" can be genuinely ambiguous

Dedup is by canonical form, so each topology is fitted once, but a skeleton can map into the
same topology in more than one way. From skeleton `R1`, both "insert C in parallel, then R in
series with the C" and "insert C in series, then R in parallel with the pair" reach the
canonical form `p(R,[C-R])` — with the user's resistor in a structurally different place each
time, and different fitted values.

The honest output is not to pick one. It is to report the placement count, and when it exceeds
one, to say that the data cannot attribute the assertion to a particular element. Fitting is
unaffected; this is purely a labelling question, and pretending it has a unique answer would be
the same error as reporting one member of an equivalence class as "the answer".

## 4. Design

### 4.1 API

```python
discover(spectrum, *, skeleton="C1-R1-L1", pool=("R", "C", "L", "CPE"), exhaustive_limit=6)
```

- `skeleton: str | None = None`. `None` is today's behaviour, unchanged and bit-identical.
- **`pool` governs the added elements only.** The skeleton may use codes outside it: it is an
  assertion, not a search result. (Implemented this way already.)
- `exhaustive_limit` stays a **total** element count, consistent with everything else in the
  system — but a 4-element skeleton with the default limit of 5 leaves the search exactly one
  free element, which is not what a user asking for "the default search" means. Proposal, and
  the one decision here worth confirming before it is built: **when a skeleton is given, the
  default `exhaustive_limit` becomes `len(skeleton) + 2`**, and the CLI prints the arithmetic
  ("skeleton has 4 elements; evaluating totals 4 to 6, i.e. up to 2 added"). A limit below the
  skeleton's size is an error rather than an empty result.
- Everything else composes unchanged: the feasibility filter, `max_candidates` clamping, the
  two-tier screen, `workers`, `on_progress`, and the `screen_plan()` generator the browser
  drives.

CLI: `autocircuit discover data.csv --skeleton "C1-R1-L1" --pool component`.

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
| 2 | `discover(skeleton=...)`, `DiscoveryResult.skeleton`, completeness wording, CLI flag | M | |
| 3 | Report: excluded equivalents (§3.3), placement multiplicity (§3.4) | M | |
| 4 | Gate P2 — the wrong-skeleton experiment (§3.2), and whatever it forces | M | |
| 5 | Docs: this file, `IMPLEMENTATION_PLAN.md` §6, `HANDOFF.md`, README | S | |

Step 4 is not last because it is least important; it is last because it needs steps 2–3 to run
at all. It is the step most likely to send steps 2–3 back for changes.

## 6. Acceptance gates

- **P1** — with the *true* skeleton, the truth or an exact equivalent is recovered on all three
  reference spectra, 10/10 seeds, and the run is faster than the unconstrained one by
  approximately the ratio in §1. Recovery is the gate; the speed-up is a recorded observation,
  not a target to tune towards (`DISCOVERY_V2_PLAN.md` G1 records what happens when a time
  target is chased).
- **P2** — with a *wrong* skeleton, the report does not read as a successful search. What
  "does not read as" means is defined by the §3.2 measurement, and this gate is written
  properly once that measurement exists. It must not be weakened into "the residuals are
  larger", which is true and useless.
- **P3** — the constrained enumeration equals the unconstrained enumeration filtered by
  `contains_skeleton`, as sets, on the reference cases. **[measured] passes** —
  `tests/test_skeleton.py`.
- **P4** — `skeleton=None` changes nothing: the existing suite stays green and unconstrained
  discovery output is unchanged for a fixed seed.

## 7. Risks

- **A wrong skeleton is silent.** The central one; §3.2 exists to measure it and P2 to gate it.
- **The feature makes the completeness claim easy to misread.** A user who sees "every
  plausible topology was evaluated" and skims past "that contains `C1-R1-L1`" has been misled by
  a true sentence. Mitigated by putting the skeleton in the same line rather than in a footnote,
  which is the same call `complete_up_to` already got.
- **Placement ambiguity looks like a bug.** A report that declines to say which resistor is the
  user's ESR will read as an omission unless it says *why*. Wording matters here.
- **Skeleton growth at large `n`.** The frontier is materialised level by level, so a weak
  skeleton on a wide pool at n = 6 is ~10⁵ trees in memory. `max_candidates` clamping already
  covers the fitting cost, but not the enumeration memory; if it bites, the frontier becomes a
  streamed level like `_compose` already is.

## 8. Out of scope

- **Fixing parameter *values* in the skeleton**, e.g. "the ESL is 5 nH, find the rest".
  `fit(fixed=...)` already does this for a complete circuit and the two features compose
  obviously, but combining them raises its own question — whether a fixed value should
  constrain the tier-1 screen — and it is severable.
- Skeletons expressed as anything other than a circuit: "at least two relaxations", "something
  capacitive at low frequency". `exhaustive_min` and the pool already cover the crude version,
  and DRT covers the diagnostic version.
- Automatically *suggesting* a skeleton from the data. That is what discovery already is.
