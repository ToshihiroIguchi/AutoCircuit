# Model-selection criteria, and seven UI questions

**Status: items 2-7 implemented, gates M1-M3 measured; item 1 was measured and then reverted.**
What each gate returned is recorded beside it below and summarised in `docs/HANDOFF.md` §17. The
parts worth reading are the two that came back different from how they were planned: **§1.5, where
both versions of the cold-start fix were built and neither survived its own measurement**, and
§2.3, where WAIC needed a stated approximation and a cross-check rather than a refusal or a
plausible number.

Written 2026-08-16, after `docs/WEB_UI_PLAN.md` and `docs/SCHEMATIC_PLAN.md`. Seven items were
raised at once; three of them are one-line changes, one is already built, and one is a change to
what every report in this project ranks by. They are planned together because they land in the
same files, and separated here because they are not the same size.

| # | Item | Size |
|---|------|------|
| 1 | Cold start is slow — why, and what actually helps | measure first, then one change |
| 2 | AIC / AICc / BIC / WAIC / CAIC / HQC / F-test, selectable, default **AIC** | the large one |
| 3 | The `bridge v4 · fit v1 · …` line in the header | delete most of it, move one part |
| 4 | Tab order: Data, **Discover**, **Fit**, Report | one array |
| 5 | Discover: draw the selected Pareto-front row | new panel, existing renderer |
| 6 | Discover → Fit hand-off | one button, one callback |
| 7 | Drag an element from the palette onto the circuit | **already implemented** — verify |

---

## 1. Why the start is slow

### 1.1 What is actually being downloaded

`web/dist` is 41 MB. It is not evenly spread:

| artefact | bytes | when it is fetched |
|----------|------:|--------------------|
| `pyodide/scipy-…whl` | 14.0 MB | **after** the interpreter has booted |
| `pyodide/pyodide.asm.wasm` | 9.6 MB | during boot |
| `pyodide/python_stdlib.zip` | 7.1 MB | during boot |
| `pyodide-bytecode.zip` | 5.8 MB | started early (already) |
| `pyodide/numpy-…whl` | 2.9 MB | **after** the interpreter has booted |
| `pyodide/pyodide.asm.mjs` | 1.25 MB | during boot |
| `autocircuit-src.zip` | 0.41 MB | started early (already) |
| `favicon.ico` + `favicon.png` | 0.15 MB | with the page |

### 1.2 The three causes, in order

1. **17 MB of wheels are not asked for until the interpreter exists.**
   `web/src/worker/bridge.worker.ts` awaits `loadPyodide()` — which itself fetches the 9.6 MB
   wasm and the 7.1 MB stdlib — and only then calls `loadPackage(["numpy", "scipy"])`. So 41% of
   the bytes sit behind a barrier they do not depend on. The two archives that step 7 added are
   already started before the boot for exactly this reason; the wheels were not, because
   `loadPackage` fetches them itself.
2. **Nothing is asked for until React has mounted.** The chain is HTML → module bundle → React →
   `BridgeClient` → dynamic `import()` of `pyodide.mjs` → boot → wheels. The document itself
   requests none of the 41 MB, so the connection is idle for as long as the bundle takes.
3. **The work after the transfer is real and already optimised.** [measured, §14 of
   `docs/HANDOFF.md`] boot 0.34 s, packages 0.20 s, unpack, import 0.92 s under Node with the
   bytecode in place — against 1.36 / 3.20 s without it. Step 7 already took ~2× out of this
   half. What is left here is not where the seconds are.

### 1.3 What this plan does about it — superseded by §1.5, which measured it

**Preload the four large artefacts from `index.html`**, so the transfer starts at document parse
instead of after the boot. `<link rel="preload" as="fetch" crossorigin>` for the two wheels, and
`as="fetch"` for the bytecode overlay and the source archive; the wasm and the stdlib are left to
Pyodide, which asks for them first thing anyway.

The wheel file names carry version numbers, so the tags cannot be written by hand — the same
build step that vendors the wheels (`web/scripts/build-assets.mjs`) writes them into `index.html`
through a Vite `transformIndexHtml` hook, from the manifest it already has.

**Gate M1.** In a real browser, on a fresh origin: the number of network requests for each wheel
is exactly one (a preload that does not match the later request would download 17 MB twice, which
is the failure mode this must be checked for), and time-to-ready is measured before and after,
in pairs, on the same machine state — §4 of `docs/HANDOFF.md` says this machine drifts 2×.

### 1.4 What was considered and not done, with the reason

- **Defer scipy.** It is 14 MB of the 17, and the Data screen does not need it: reading, trimming
  and Lin-KK are numpy. But `core/elements.py` imports `scipy.special` at module scope (SKINW's
  Bessel ratio) and `core/fit.py` imports `scipy.optimize`, so `from autocircuit.web import
  handle` pulls scipy in before any operation runs. Deferring it means lazy imports in three core
  modules and a bridge that can answer some operations and not others — a state the front end
  would have to model. It is the largest remaining lever and it is written down here rather than
  taken, because it trades the "one handle, no decisions" property that made the browser agree
  with the CLI digit for digit.
- **A service worker.** Still refused, for the reason §6 of `docs/HANDOFF.md` gives: it would put
  a cache between every visitor and a site that republishes on every push.
- **Shrinking the favicon** (92 KB `.ico` + 59 KB `.png`). Real, and 0.4% of the problem.

### 1.5 [measured] Both versions of §1.3 were built, and neither is in the build

**Nothing about the cold start was changed in the end**, and the two experiments that establish
why are worth more than the change would have been.

**A document's preload cache does not serve a Web Worker's fetch.** The wheels are fetched by
`loadPackage` *inside* `bridge.worker.ts`, so the `<link rel="preload" as="fetch">` §1.3 proposed
did not satisfy that fetch at all: Chrome downloaded all 17 MB a second time and logged
"preloaded … but not used" for both. That is not a tuning failure — no attribute makes a
document preload reachable from a worker.

**Moving the same idea into the worker works, and makes the total worse.** The second version
read a build-written manifest of the wheel names, started both fetches before `loadPyodide`, and
patched `self.fetch` so `loadPackage` was answered from them. Each wheel was then requested
exactly once, and the stage it targeted collapsed. Measured from the deployed site with a fresh
Edge profile each time:

| | boot | packages | total to a ready worker |
|---|---|---|---|
| before | 4.46 / 6.24 s | **7.84 / 4.39 s** | **15.24 / 13.52 s** |
| with the worker prefetch | 17.60 / 12.09 / 9.98 / 26.20 s | **1.67 / 1.80 / 2.75 / 1.66 s** | **22.27 / 16.56 / 15.75 / 30.60 s** |

The packages stage fell by 3–4×. Every reading of the *total* was at or above the worst reading
without it. The cold start over this link is **bandwidth-bound**, so the wheels do not overlap
the boot — they compete with it, and the wasm the boot blocks on arrives later. The time moved
from one stage to another and a little was lost on the way.

So it was reverted, and the reasoning is left in `bridge.worker.ts` and `index.html` where
someone would otherwise have the same idea again. **Reordering transfers cannot help a
bandwidth-bound load; only sending fewer bytes before the page is usable can** — which is what
§1.4's deferred scipy is, and why it is the only remaining lever worth the disruption.

One methodological note, because it is what nearly went wrong here: the stage breakdown said
this change was a large win, and it was the *total* that said otherwise. Do not accept a
per-stage improvement as a cold-start improvement.

---

## 2. Model-selection criteria

### 2.1 What is there now

One number ranks everything: `Statistics.aicc`. It is the sort key for `DiscoveryResult
.candidates`, one of the two axes of `pareto_front`, the shortlist ranking inside `_shortlist`
(as `_screening_aicc`), the column in the CLI's front table and in the browser's, and the
`Lowest AICc` line of the report. `aic` and `bic` are computed and reported in `fit --json`, and
nothing reads them.

### 2.2 The seven, and what each one is

All of them are written on the same scale the file already uses:

```
deviance = n · log(SSR / n)          # −2·logL, less the constant n·log(2π) + n
```

| name | value | note |
|------|-------|------|
| AIC | `deviance + 2k` | **the new default** |
| AICc | `AIC + 2k(k+1)/(n−k−1)` | the old default; the small-sample correction |
| BIC | `deviance + k·log n` | |
| CAIC | `deviance + k·(log n + 1)` | Bozdogan's consistent AIC |
| HQC | `deviance + 2k·log(log n)` | Hannan–Quinn |
| WAIC | `−2·lppd + 2·p_waic`, same constant removed | see §2.3 |
| F-test | *not a score* | see §2.4 |

`n` is the number of real residuals (twice the point count) and `k` the number of free
parameters, exactly as `Statistics` already defines them.

### 2.3 WAIC needs a posterior, and this is a least-squares fitter

WAIC is defined over a posterior distribution; nothing here samples one. Two honest ways out:
refuse the criterion, or state the approximation. This takes the second, analytically:

* the posterior is the **Laplace approximation** at the fitted point, which is the covariance
  this module already computes — in the log search space, for the reason §3 of
  `docs/HANDOFF.md` gives;
* the residual is **linearised** through the same Jacobian the covariance comes from.

Under those two, every integral WAIC needs is Gaussian and closes in one line each. With
`σ² = SSR/n` and the leverage `hᵢ` (the diagonal of the hat matrix, read off the same SVD
`_covariance` already runs):

```
lppd    = Σᵢ [ −½·log(2πσ²) − ½·log(1+hᵢ) − aᵢ²/(2σ²(1+hᵢ)) ]
p_waic  = Σᵢ [ hᵢ²/2 + aᵢ²·hᵢ/σ² ]
```

and `waic = −2·lppd + 2·p_waic − n·log(2π) − n`, which puts it on the scale of the rest.

**What that buys, and what it costs.** It reduces to `deviance + 2·rank` in the well-behaved
limit — WAIC's effective parameter count in place of AIC's nominal one — so on a
rank-deficient circuit it differs from AIC by exactly the amount the data fails to resolve.
`p_waic` is reported beside it, because that difference is the only reason to ask for it. What it
is not is a WAIC computed by sampling: it cannot see posterior non-Gaussianity, which for a
fifteen-decade log-parameterised fit is not nothing. The docstring says so, and so does the UI.

### 2.4 The F-test is not a score, and cannot be made into one

The other six give one number per model, and the search ranks by it. An F-test gives a number
per *pair*: the extra sum of squares divided by the extra parameters, over the complex model's
variance, against `F(k₂−k₁, n−k₂)`. So choosing it means something different from choosing BIC,
and pretending otherwise would be the quiet reinterpretation this project keeps refusing:

* the ranking and the Pareto axis stay **AIC**, and the report says so on the line where the
  choice is reported;
* the *selection* becomes a sequential test along the Pareto front, simplest first: step up to
  the next row only when it buys a significant reduction at α = 0.05.

**It also assumes nesting, and Pareto-front rows are generally not nested.** `R1-p(R2,C1)` and
`C1-R1-L1` are not one inside the other. The test is still the standard tool for "did those extra
parameters earn their place", and it is offered as one, with the assumption named in the report
line itself rather than in a footnote — the same rule §3.1 of `docs/PARTIAL_TOPOLOGY_PLAN.md`
applies to the coverage sentence. Rows where `k₂ ≤ k₁` or `SSR₂ ≥ SSR₁` are skipped rather than
given a meaningless p-value.

The p-value comes from `scipy.special.betainc`, not `scipy.stats`: `special` is already imported
by `core/elements.py`, and `scipy.stats` is a heavy import on a page whose start-up is item 1.

### 2.5 What the criterion does and does not change

**Changes:** the candidate sort order, the `pareto_front` dominance axis, the shortlist ranking
in `_shortlist`, the front table's column heading and values, and the `Lowest …` line.

**Does not change:** `DiscoveryResult.recommended`. That is the parsimony rule, and it is a rule
about *identifiability*, not about a criterion — [measured, §3 of `docs/HANDOFF.md`] minimum-AICc
selected a 9-parameter circuit with two parameters whose standard errors exceeded their own
values. Choosing BIC does not make that a different kind of mistake. The report keeps both lines:
what the criterion picks, and what is worth reporting.

**Screening cannot compute all seven.** `_screening_aicc` works from a cost and a parameter
count, with no Jacobian — so AIC, AICc, BIC, CAIC and HQC are exact there and WAIC is not
available at all. Under `waic` and `ftest` the screen ranks by AIC, and the docstring says which
stage that is true of. The screen decides who gets refitted, not who wins.

### 2.6 The default moves from AICc to AIC

Asked for, and it is a real change to published numbers: `AICc − AIC = 2k(k+1)/(n−k−1)`, which on
a 71-point spectrum is 0.29 at k = 4 and 1.36 at k = 9. It is monotone in k, so the order within
one parameter count is untouched and only comparisons across counts can move — slightly towards
the larger model. Every measured front in `docs/` was taken under AICc and stays labelled as
such; new measurements say which criterion they are under.

### 2.7 Where it is plumbed

| layer | change |
|-------|--------|
| `core/stats.py` | `Criterion`, `CRITERIA`, `criterion_value()`, `f_test()`; `Statistics` gains `caic`, `hqc`, `waic`, `p_waic` |
| `core/fit.py` | `WIRE_VERSION` 1 → 2; `to_dict` and `summary` report all six |
| `core/discover.py` | `discover(criterion=…)`, `Candidate.score()`, `pareto_front(…, criterion)`, `_screening_score`, `DiscoveryResult.criterion`, `.by_criterion`, report lines, `to_dict`/`to_csv` |
| `cli/main.py` | `--criterion` on `fit` and `discover` |
| `web/job.py`, `web/bridge.py` | `criterion` in the search options; row payloads carry `score`; `BRIDGE_VERSION` 4 → 5 |
| `web/src/…` | one `criterion` in `App`, a `<select>` on the search panel and the fit panel, the front table's heading |

**Gate M2. [measured] Passes.** All seven run end to end from the CLI and through the bridge;
`tests/test_criteria.py` is 20 tests over the algebra, the ordering properties, the wire round
trip and the end-to-end search. The Monte-Carlo cross-check, 100,000 draws from the same Laplace
posterior on a fitted `R1-p(R2,C1)`: **waic −1098.551 against −1098.538, p_waic 2.660 against
2.666**. CLI against browser on the Randles sample through `R1-p(C1,R2-W1)`: AIC −1311.19,
AICc −1310.89, BIC −1299.36, CAIC −1295.36, HQC −1306.38, WAIC −1311, effective parameters
4.02 of 4 — every reported digit equal, which is gate W1 again on numbers it had not been
measured on.

---

## 3. The header's build line

It reads `bridge v4 · fit v1 · spectrum v1 · validate v1 formats: generic_csv, keysight,
touchstone, zview`. Two different things are on it and they deserve opposite treatment.

**The four version numbers go.** They are a *developer's* diagnostic, and the diagnosis they
support is already automatic and louder: `bridge.worker.ts` compares `BRIDGE_VERSION` against
what Python answers and refuses to run on a mismatch, with a sentence naming both numbers. The
other three are wire-format versions checked inside `from_wire`, which raises. So the line is not
what protects anyone from a stale build — it is a number a user cannot act on, in the most
valuable strip of the page, on every screen, forever. It moves into the `title` of the header,
where it can still be read when someone is asked for it.

**The format list stays, and moves.** "Which files can I drop here?" is a real user question and
that list is its answer — but it is answered in the header, on the Report screen, hours after the
question was asked. It belongs on the drop zone, which is where the question is asked. Note it is
not a hard-coded list: it comes from the reader registry in the running build.

## 4. Tab order

`Data, Fit, Discover, Report` → `Data, Discover, Fit, Report`. The work runs in that order once
item 6 exists: load, search for a topology, refine the one you picked, take the answer away. It
is one array in `App.tsx` (`SCREENS`) plus the render branch; no state moves, and the Fit screen
is still where a skeleton is drawn for a constrained search, which is the one dependency running
the other way. That dependency is why the two were originally in the other order, and item 6 is
what makes the forward direction the common one.

## 5. Drawing the selected front row

`ParetoTable` becomes selectable — one row at a time, the recommended one selected on arrival —
and the Discover screen draws that row above the table with the same `CircuitCanvas` the Fit
screen uses, in a read-only mode (no slots, no delete buttons, no palette). The renderer is
`web/src/core/schematic.ts` and it takes the parsed tree, so the screen asks the bridge's
`circuit` operation for the tree of the selected row — no JavaScript parses a circuit string,
which is the rule `CircuitCanvas`'s header comment states.

`CircuitCanvas` therefore gains a `readOnly` prop rather than a second component: two renderers
would be two chances for the published picture to disagree with the editable one, and
`npm run schematic` only checks the geometry once.

## 6. Discover → Fit

A button on the selected row: *Fit this circuit*. It sets `App`'s `circuit` — which the Fit
screen already reads and the Discover screen already offers as a skeleton — and switches tabs.

**It hands over the topology, not the fit.** The discovered parameter values are not carried
across as a starting guess, because this fitter has none and the Fit screen says so in as many
words. Refitting on the Fit screen re-runs the same global search from the same data-derived
interval and lands in the same place; carrying values over would make the screen look like it
seeds from them. What it does carry is a note under the field naming the circuit's origin, so a
user who then presses Fit knows what they are refitting.

## 7. Dragging an element onto the circuit — already there

`ElementPalette` sets `draggable` and `elementDragData`; `CircuitCanvas`'s slots implement
`onDragOver`/`onDrop` behind a private MIME type, so a file dragged onto the page still reaches
the window-level loader. Clicking to arm and then clicking a slot exists beside it, on purpose —
drag is what the schematic invites, click is what works from a keyboard.

So the answer to "is this hard?" is that it was done in step 3 and is not discoverable enough.
Two things this plan adds, both about the affordance rather than the mechanism:

- the drop targets **light up while a drag is in progress**. Today a slot looks the same whether
  or not it will accept what is under the pointer, so a user has to guess that the small `+` is a
  target;
- an element may also be dropped **onto an existing element**, placing it in parallel — the
  operation the `∥` button already offers, which is the one a drag naturally aims at.

**Gate M3. [measured] Passes.** In Chrome, from `p(R1,C1)-R2`: a CPE dragged onto the end slot
gives `p(R1,C1)-R2-CPE1`, and an L dragged onto the `R2` symbol gives `p(R1,C1)-p(R2,L1)-CPE1` —
the circuits the click path produces. The drag highlight (`cc--dragging`) is on during both.

---

## 8. Order of work

1. §2 in Python, with its tests (the only item that can be wrong numerically).
2. §2 through the bridge and into the UI.
3. §3, §4, §6 — small, and they touch `App.tsx` together.
4. §5, §7 — both are `CircuitCanvas`.
5. §1, measured in pairs, last, so the browser run that measures it is the one that also
   checks everything above.
