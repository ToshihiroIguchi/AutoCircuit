# CRITERION_SELECTION_PLAN.md — is AIC the right default `criterion`?

**Status: plan only. No benchmark script exists yet; nothing in this document has been measured.**
It exists so a session that gets cleared can pick this back up without re-deriving the scoping
argument, which is the part of this plan that actually took the investigation — the experiment
itself is comparatively mechanical once the scoping is right.

## 1. Why this needs an experiment before it needs an opinion

The current default is `"aic"` (`src/autocircuit/core/stats.py:39`):

```python
type Criterion = Literal["aic", "aicc", "bic", "caic", "hqc", "waic", "ftest"]
CRITERIA: tuple[Criterion, ...] = ("aic", "aicc", "bic", "caic", "hqc", "waic", "ftest")
DEFAULT_CRITERION: Criterion = "aic"
```

with per-criterion notes at `stats.py:53-65`, e.g. BIC's is: *"penalty log(n) per parameter, so it
prefers simpler models than AIC on any real spectrum."* AICc was the default until 2026-08-16
(`stats.py:39`'s own comment); `docs/METRICS_AND_UX_PLAN.md` section 2.6 records that switch and
its reasoning (AICc's small-sample correction grows from 0.29 to 1.36 across the parameter counts
this project actually searches, which was judged not worth the cross-count distortion). **No
document anywhere states why AIC rather than BIC** — the switch away from AICc was measured; the
choice of AIC over BIC (or CAIC, or HQC) was not.

That gap is real, but it is narrower than it looks, because of a design decision already made and
already documented at the point that would otherwise matter most. `DiscoveryResult.recommended`
(`discover.py:562-585`) — the single value every report actually leads with — is **built to ignore
`criterion` entirely**:

```python
@property
def recommended(self) -> Candidate | None:
    """...
    **This does not follow :attr:`criterion`, on purpose.** Choosing BIC instead of AIC
    changes which model a penalty term prefers; it does not make "the extra parameter has a
    standard error larger than its own value" a different kind of mistake. What the chosen
    criterion picks is :attr:`by_criterion`, and :meth:`summary` prints both lines whenever
    they disagree.
    """
    ...
    well_fitting = self._well_fitting()          # chi2 <= PARSIMONY_CHI2_FACTOR (= 2.0) * best chi2
    viable = [c for c in well_fitting if c.n_unresolved == 0] or well_fitting
    if not viable:
        return self.best
    return min(viable, key=lambda c: (c.complexity, c.aicc))   # always AICc as the tie-break
```

So **"should AIC be the default" is not, in this codebase, the same question as "does the report's
headline answer change."** By design it mostly does not. The question this plan actually needs to
answer is narrower and needs to be stated precisely before any code is run, per this project's own
convention (`benchmarks/six_plus/trigger.py`'s docstring is the model to follow — a decision rule
written down before the labelled set is scored).

## 2. What `criterion` actually touches

Three places, all upstream of `recommended`, none of them `recommended` itself:

**(a) Tier-1 -> tier-2 shortlist promotion**, i.e. which topologies get a full-budget refit at all
and therefore can ever appear in `report.pareto` (and therefore can ever be `recommended`).
`_quota_by_size` (`discover.py:2653-2673`) ranks candidates **within each element-count** by
`_screening_score` (`discover.py:2613-2627`), which is `criterion`-dependent:

```python
def _screening_score(cost, n_params, n_data, criterion=DEFAULT_CRITERION):
    ...
    name = criterion if criterion in ("aic", "aicc", "bic", "caic", "hqc") else SCREENING_FALLBACK
    value = information_criteria(cost, n_data, n_params)[name]
    return value if math.isfinite(value) else math.inf
```

The reason this can matter, and is not just a relabelling of the same order: **element count and
parameter count are not the same axis once CPE is in the pool.** Two topologies with the same
number of elements can have different `n_params` (an `R` contributes 1 parameter, a `CPE`
contributes 2), so a criterion's penalty term `f(n_params)` can rank two same-size topologies
differently depending on which penalty function `f` is. AIC's `2k`, BIC's `k*log(n)`, CAIC's
`k*(log(n)+1)` and HQC's `2k*log(log(n))` do not have to agree on the winner within one element-count
class. The near-tie rule around this quota (`REFINE_COST_FACTOR`, same section) works off raw cost,
not the criterion, so it does not erase this effect.

**(b) `by_criterion`** (`discover.py:531-559`) — the value the report shows as "what the chosen
criterion picks", printed alongside `recommended` in `summary()` whenever the two disagree
(`discover.py:576` and the printing logic around `914-916`). This is a real, user-visible number
independent of `recommended`, and a criterion that disagrees with `recommended` often produces a
more confusing report (two circuits offered as "the answer" side by side) even though the
*recommended* one never moves.

**(c) `WAIC` and `ftest` cannot be scored at tier 1 at all**, and this is a hard constraint the
experiment must respect rather than probe around:

```python
#: What the screen ranks by when the chosen criterion cannot be computed from a cost alone.
#: WAIC needs the leverage, which needs the Jacobian, which is the expensive half of a full fit
#: and is exactly what tier 1 does not do; ``ftest`` needs two models rather than one. Both fall
#: back here. That is a decision about *who gets refitted*, not about who wins -- every number
#: that reaches the user comes from tier 2, where the chosen criterion applies in full.
SCREENING_FALLBACK: Criterion = "aic"
```

(`discover.py:2604-2610`). So under `criterion="waic"` or `criterion="ftest"`, the *shortlist* is
always AIC-ranked regardless of the experiment's outcome for (a) — only the *final* pick among
whatever reached tier 2 changes. This means effect (a) can only ever be measured by sweeping
`{aic, aicc, bic, caic, hqc}`; `waic` and `ftest` are relevant only to effect (b), evaluated on
whatever the AIC-ranked shortlist already promoted.

## 3. The three questions, stated precisely

* **Q1 (recovery through the shortlist).** Holding everything else fixed, does the criterion used
  to rank tier-1 -> tier-2 promotion change whether the true topology's equivalence class survives
  to `report.pareto` at all? This is the one place a "wrong" criterion could cost real recovery
  rather than just relabel a report.
* **Q2 (recommended stability — a sanity check on the design claim, not just a question about
  criteria).** Does `report.recommended` in fact stay the same truth-equivalence verdict across
  criteria, as `discover.py:573-577`'s docstring claims it is built to? If Q1 shows the shortlist
  changes with the criterion, Q2 is not guaranteed to hold just because `recommended`'s own formula
  is criterion-blind — a truth that fails to reach `pareto` under criterion X is invisible to
  `recommended` under X regardless of the formula. Measuring Q2 directly, rather than trusting the
  docstring's argument by construction, is the point.
* **Q3 (report clarity / overfitting risk in `by_criterion`).** How often does `by_criterion`
  disagree with `recommended`, per criterion, and — specifically on data that only needs a small
  model — how often does `by_criterion` pick something larger than the truth (an overfit answer
  shown next to the correctly parsimonious one)?

## 4. Method: reuse this project's own labelled sets, do not build a new one

This project already has exactly the kind of labelled, decision-rule-scored infrastructure this
question needs, built for a structurally identical problem (`benchmarks/six_plus/trigger.py`,
scoring four growth-decision candidates on recovery rate and false-positive rate over a
pre-registered truth set). Reuse it rather than inventing a fourth truth set:

* **`benchmarks/discovery_v2.py`'s `REFERENCES`** — the small/medium truths (up to 5-6 elements)
  already used for the exhaustive-stage gates. Exact recovery is expected here regardless of
  criterion (this project's own baseline), so these rows mainly serve as a **negative control for
  Q1**: any criterion that fails to recover a truth this project has always recovered is
  disqualified immediately, independent of what happens on the harder rows.
* **`benchmarks/discovery_v2.py`'s `LARGE_REFERENCES`** (`discovery_v2.py:225` onward, 3 truths at
  6-7 elements, deliberately kept apart from `REFERENCES` per that list's own comment at
  `discovery_v2.py:222-224`) — where recovery is known to be hard and criterion-sensitivity, if it
  exists, is most likely to show up.
* **`benchmarks/six_plus/truths.py`'s nine pre-registered truths** (`BY_ID`) — three shapes
  (`par`, `mix`, `ser`) crossed with three sizes (5, 6, 7 elements), where the five-element rows
  are the project's standard negative control (5 elements is already correct; nothing should want
  to grow past it) and the 6/7-element rows are where growth is correct. This set already comes
  with the project's admission screen (per-parameter leverage, no unresolved parameter at the
  truth's own fit, value-matched deviation under 50%, survives the structural pre-filter — see
  `truths.py:31-48`), so it needs no new vetting.
* **The same (noise, points-per-decade) grid `identifiability.py` (X2) and `trigger.py` (X3)
  already use** — 4 noise levels x 3 ppd = 12 cells per truth. Reusing the identical grid means
  this experiment's numbers are directly comparable to the already-published X2/X3 figures in
  `docs/TOPOLOGY_6PLUS_PLAN.md` section 5.12, rather than sitting in isolation.

Sweep `criterion` over all seven values in `CRITERIA` (`stats.py:36`). Flag `waic` as the expensive
one — computing it needs a full fit (Jacobian) even where it is only used to pick among an
already-promoted tier-2 shortlist, so its *marginal* cost over the other six is small, but it
cannot help with Q1 at all (section 2c) and can be skipped from the tier-1 sweep without losing
anything.

## 5. Metrics, per (truth, noise, ppd, criterion, seed) cell

* `recovered`: a truth-equivalent topology is present in `report.pareto` — the same predicate
  `docs/TOPOLOGY_6PLUS_PLAN.md` and `docs/AUTOEIS_COMPARISON.md` already use ("truth-equivalent
  anywhere in the candidate list").
* `recommended_correct`: a truth-equivalent topology is `report.recommended` specifically.
* `by_criterion_disagrees`: `report.by_criterion` is not the same candidate (by canonical form) as
  `report.recommended`.
* `by_criterion_overfits`: on the five-element negative-control rows only (`par5`/`ser5`/`mix5` at
  the 5->6 boundary, plus `REFERENCES` rows below the exhaustive limit), `by_criterion`'s element
  count exceeds the truth's own.

Record the raw `report.summary()` text per cell as well, for spot-checking disagreements by eye
before trusting the aggregate numbers — this project's own history (`SEARCH_TIME_PLAN.md` section
3.2, the sub-tree re-screen flag) is a standing reminder that an aggregate pass rate can look clean
while individual rows are not what they seem.

## 6. Decision rule — write this down now, not after seeing results

**AIC stops being the shipped `DEFAULT_CRITERION` only if some other criterion in `{aicc, bic,
caic, hqc}` achieves a strictly higher pooled `recovered` rate than AIC across every truth/noise/ppd
cell in section 4, AND does not raise the `by_criterion_overfits` rate on the negative-control rows
by more than 5 percentage points relative to AIC's own rate.**

If more than one criterion clears that bar, the tie-break is the lowest `by_criterion_disagrees`
rate (a report that agrees with itself more often is a clearer report, all else equal).

If Q2 shows `recommended_correct` is in fact criterion-invariant (as the docstring at
`discover.py:573-577` claims by construction) *and* Q1 shows `recovered` is also criterion-invariant
(i.e. the shortlist promotion effect in section 2a turns out not to matter in practice, at least on
this labelled set), then **no criterion clears the bar by definition, `by_criterion_disagrees` and
`by_criterion_overfits` become the only remaining decision axes**, and this plan's fallback rule
applies: pick whichever criterion minimizes `by_criterion_overfits` on the negative controls, with
`by_criterion_disagrees` as the tie-break, and if AIC is not clearly worse than the winner on either
axis, **AIC stays default and the result is recorded as a measured null**, in the same style
`docs/EVOLVE_SEARCH_PLAN.md` section 3.5 records that neither adaptive-parsimony knob it tested
moved a default. A null result here is not a failed experiment; a criterion choice with no
measurable behavioural consequence is itself the finding, and it is the more likely outcome given
section 1's analysis of what `recommended` was built to ignore.

`ftest` is scored on Q3 only (`by_criterion` for `ftest` is a different kind of object — a
sequential nested test along the Pareto front, `discover.py:534-559` — not a comparable score for
Q1's shortlist-ranking question, and section 2c already establishes its tier-1 ranking is always
the AIC fallback regardless).

## 7. Implementation: the benchmark script

New file, `benchmarks/criterion_selection.py`, following the shape of
`benchmarks/six_plus/trigger.py` (import `BY_ID`/`Truth` from `benchmarks/six_plus/truths.py`,
`REFERENCES`/`LARGE_REFERENCES` from `benchmarks/discovery_v2.py`; reuse `discover()` at production
`exhaustive_limit` — 5 for the `*5`/`*6` boundary rows and the `REFERENCES` set, 6 only for the
`*7` truths, mirroring `trigger.py`'s own "one level cheaper" cost note at its docstring lines
55-61).

CLI surface, matching this project's existing benchmark-script conventions:

```
python benchmarks/criterion_selection.py --dry-run
python benchmarks/criterion_selection.py --out benchmarks/criterion_selection.json `
    --only par5,par6 --criteria aic,bic --seeds 3 --workers 8
python benchmarks/criterion_selection.py --out benchmarks/criterion_selection.json `
    --criteria aic,aicc,bic,caic,hqc,ftest --seeds 10 --workers 8
python benchmarks/criterion_selection.py --summarize benchmarks/criterion_selection.json
```

(`waic` omitted from the default `--criteria` list per section 4's cost note; pass it explicitly to
include it, understanding it only contributes to Q3.)

Output: one JSON row per `(truth_id, noise, ppd, criterion, seed)` with the four booleans from
section 5 plus `report.summary()` text; `--summarize` prints, per criterion, the pooled `recovered`
rate, `recommended_correct` rate, `by_criterion_disagrees` rate, and `by_criterion_overfits` rate
(on negative-control rows), as a table — mirroring `trigger.py --summarize`'s existing shape so the
two are easy to read side by side.

**Cost.** This is the X2/X3 grid multiplied by up to 6 criteria (5 for Q1, all but `waic` for Q3,
`ftest` for Q3 only) — a full run is expensive. Pilot first, exactly as `trigger.py`'s own usage
note prescribes: `--only par5,par6 --criteria aic,bic --seeds 3` before committing machine time to
the full sweep. Consider whether Q1's shortlist-promotion question can be answered on a strict
subset of truths (e.g. only the six/seven-element ones, where a promotion effect is most likely to
bite, plus the `REFERENCES`/`*5` negative controls) before running Q3's cheaper `by_criterion`
comparison on the full set — the two questions do not need the same sample size to be conclusive,
and section 6's decision rule only needs Q1 to be conclusive on whichever truths actually show
criterion-sensitivity.

## 8. Contingent implementation (only if section 6's rule picks a criterion other than AIC)

1. `src/autocircuit/core/stats.py:39` — change `DEFAULT_CRITERION`.
2. `src/autocircuit/cli/main.py` — update the `--criterion` argument's default and help text.
3. `docs/METRICS_AND_UX_PLAN.md` section 2.6 — add the new measurement in the same style as the
   AICc->AIC switch it already records (what was measured, what the numbers were, what stayed the
   same for `recommended`).
4. Search `tests/` for anything asserting `DEFAULT_CRITERION == "aic"` or relying on it implicitly
   (e.g. a report snapshot fingerprinted at the AIC default) and update.
5. Update this plan's own `Status` line, and add a pointer sentence to this document's outcome in
   `CLAUDE.md`'s numbered "Start here" list (it currently points here as "plan only, not run").

If section 6 concludes with a null result (AIC stays default), skip 1-2 and do 3-5 only, recording
the null result rather than silently leaving no trace that the question was ever asked and answered.
