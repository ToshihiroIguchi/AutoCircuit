# STARTUP_AND_EDITING_PLAN.md — what the page hands over, what it lets you rearrange, and what it makes you wait for

Phase 9. Three questions about the deployed web UI, asked in the order a visitor meets them:

1. Discover hands a circuit to Fit but not its parameters. Is that appropriate?
2. An element already on the canvas cannot be dragged somewhere else. Is that appropriate?
3. Start-up is very slow, and nothing — not even loading an example — works until all of it has
   loaded.

The three answers are different in kind, and saying which kind each one is matters more than the
code:

* **Question 1: the design is right and the sentence it prints is not always true.** The topology
  travelling without the fitted values is a decision this project measured
  (`docs/SCREEN_STATE_PLAN.md` §3.B, §7's gate G2) and it stands. But it rests on *"refitting there
  re-runs the same global search and lands in the same place"*, and that is only true while the Fit
  screen's weighting, restart count and seed are the ones the search refitted under. They travel
  nowhere today, so a search run at `proportional` weighting hands its topology to a screen set to
  `modulus` and promises a number it will not produce. §1 fixes the premise rather than the
  conclusion.
* **Question 2: no, and the reason it is missing is visible in the code.** The canvas already
  accepts a drag *from the palette* and already turns positions into Python-side tree surgery. What
  it lacks is one edit action — `move` — and the two drop handlers that would use it. §2.
* **Question 3: no, and the cost is measured.** 41 MB is fetched and installed before the page will
  read a 6 kB CSV, and **18.3 MB of it is scipy**, which nothing on the Data screen uses. §3 splits
  the load in two so the Data screen comes up on the numpy half, and moves Plotly out of the
  initial bundle.

---

## 0. What was measured, before

**[measured] The cold start, locally, with the network taken out of it.** `npm run build`, then
`vite preview`, then Chromium (Playwright), reading the worker's own stage line:

| run | boot | packages | unpack | import | total since navigation |
|---|---|---|---|---|---|
| 1 (OS file cache cold) | 1.50 s | 3.83 s | 0.52 s | 2.98 s | **9.49 s** |
| 2 (warm) | 0.68 s | 2.18 s | 0.28 s | 1.95 s | **5.27 s** |

Every one of those seconds is CPU: the bytes came off a local disk over localhost. On the deployed
site they are paid *again* as transfer, which is what `docs/WEB_UI_PLAN.md` §2.3 and
`docs/METRICS_AND_UX_PLAN.md` §1.5 are about.

**[measured] What is fetched before the page will do anything, and who needs it:**

| artefact | MB | needed by the Data screen? |
|---|---|---|
| `pyodide.asm.wasm` | 9.60 | yes |
| `python_stdlib.zip` | 7.06 | yes |
| `pyodide.asm.mjs` | 1.25 | yes |
| numpy wheel | 2.92 | yes |
| **scipy wheel** | **14.01** | **no** |
| bytecode overlay, numpy part | 1.39 | yes |
| **bytecode overlay, scipy part** | **4.30** | **no** |
| `autocircuit-src.zip` | 0.43 | yes |
| app bundle `index-*.js` | 1.42 (0.47 gzip) | its Plotly half only once a spectrum is drawn |

So **18.31 MB of the 41 MB — 45% — is scipy**, and it is downloaded, installed and imported before
the page will read a file. The Data screen's work is reading, trimming, plotting and Lin-KK, and
none of it calls scipy.

**[measured] Applying the bytecode overlay before the wheel it belongs to breaks scipy.** Not a
guess: unpacking today's single overlay after `loadPackage(["numpy"])` and only then loading scipy
gives `ImportError: cannot import name 'loggamma' from 'scipy.special' (unknown location)`. This is
why §3 splits the overlay in two rather than keeping one file and unpacking it early.

**[measured] The data path cannot be imported without scipy today, and it is three imports that do
it.** `import autocircuit.io` → `autocircuit/__init__.py` → `core/__init__.py` → `circuit` →
`elements` → `from scipy import special`. Beyond that chain, `core/validate.py` reaches into
`core/fit.py` for `Weighting` and `weight_vectors` — two names that use nothing but numpy — and
`core/stats.py` imports `scipy.special.betainc` at module scope for one function, the F-test.

---

## 1. The hand-off: keep what it carries, fix what it claims

### 1.1 What stays

`onFitCircuit` carries the topology and not the fit. `docs/SCREEN_STATE_PLAN.md` §3.B rejected
carrying the fit on two grounds — a Pareto row is *one of several topologies the data cannot tell
apart*, and installing one as "the fit" on a screen framed *you asserted this circuit* drops the
qualification; and it buys nothing, because gate G2 measured an independent refit reproducing the
search's own numbers to every reported digit (AIC −324.335, χ²(reduced) 0.13180). Neither ground has
weakened. Nothing here re-opens that.

### 1.2 What is wrong

G2 was measured with the search left on its defaults, which happen to be the Fit screen's defaults:
modulus weighting, seed 0, and the job's `final_restarts = 5`. The Discover screen lets the user
change the weighting and the seed. Change either, and:

* the Fit screen refits under settings that did not produce the row it was handed;
* the note under the button — *"refitting there re-runs the same global search and lands in the same
  place"* — becomes a false statement made by the program about itself;
* and the two screens now disagree about a model neither of them says is a different model.

That is the same shape as every failure this project keeps recording: the report still looks
healthy.

### 1.3 The fix

**Carry the fit settings with the topology, and take them from the core rather than from the
browser's copy.** `discover_report` gains three fields — `weighting`, `seed` and `refit_restarts` —
which are what `job.py` actually refitted the reported rows under. `App.fitCircuit` writes them into
`FitState` beside the circuit, and the note says so.

Three fields and not two: `final_restarts` is a Python-side default that no wire carries today, and
a hand-typed `5` in TypeScript would be a fourth copy of a number — the mistake
`docs/SCREEN_STATE_PLAN.md` §8 records having already been made once with `BRIDGE_VERSION`.

Rejected alternative: *let the Fit screen keep its own settings and weaken the note to "may land
somewhere else"*. That trades a false promise for a vague one while leaving the two screens
disagreeing. The promise is worth keeping because it is true whenever the settings match, and making
them match is three fields.

## 2. Moving an element that is already there

### 2.1 Is the omission appropriate? No

The canvas is a topology editor whose every other structural operation exists: insert in series,
insert in parallel, delete, replace. *Move* is the one a user reaches for after drawing the wrong
order, and today it costs a delete and a re-insert — which also loses the element's label, and with
it any value the parameter table held under that name. The affordance is doubly expected because
dragging is already how an element arrives from the palette: a canvas that accepts a drag from the
left-hand list and refuses one from itself reads as broken rather than as restrained.

### 2.2 Where the operation belongs

In Python, with the other tree surgery. `CircuitCanvas`'s header states the rule — *"this file knows
how a series block and a parallel block look; it does not know what either one means"* — and a move
is exactly where a JavaScript implementation would go wrong, because removing the source changes the
path of the target. Doing the arithmetic in the browser is how the two implementations of the
grammar this project refuses to have would get created.

`core/circuit.py` gains `move_subtree(root, source, target, action, position)`, and the bridge's
`edit` op gains the action `move`. The implementation avoids path arithmetic entirely:

1. replace the source subtree with a **marker node**, which leaves every other path valid because a
   leaf is swapped for a leaf;
2. insert the source subtree at the target through the same `series`/`parallel` builders an insert
   uses, so a move and an insert cannot produce different trees;
3. find the marker **by object identity** — the builders preserve untouched children — and delete it
   through `remove_subtree`, so the collapse rules that apply to a delete apply here too.

Two edge cases fall out rather than being special-cased: dropping an element onto itself returns the
circuit unchanged, and moving an element to a new branch of the block it is already in likewise
returns it unchanged.

**The label travels with the element.** `R1` moved between two positions is still `R1`, so the value
the parameter table holds under `R1.R` still belongs to it. A delete-and-reinsert renumbers, which is
the other reason this is not "two operations the user can already do".

### 2.3 The interaction

* **Drag.** An element on the canvas is `draggable`; the payload is its path under a private MIME
  type distinct from the palette's, so a slot can tell "insert a new C" from "move R1 here". Every
  existing drop target accepts both: a slot moves the element to that position in series, and an
  element's own cell moves it into parallel with that element — the same two meanings the targets
  already have for a palette drag.
* **Click.** Dragging is not available from a keyboard, and the palette already has this covered
  with arm-then-click. An element's hover tools gain a **move** button that arms *that element*; the
  next slot clicked receives it. Arming an element and arming a palette code are mutually exclusive,
  because a slot can only do one thing when clicked.

## 3. Start-up

### 3.1 The two halves

Nothing about the Data screen needs scipy, so the load is split at that line:

* **Stage A — the data runtime.** Boot Pyodide, install **numpy**, unpack the package archive and the
  numpy half of the bytecode overlay, import the light bridge. The page can now read files, load
  examples, trim, validate and plot.
* **Stage B — the model runtime.** Install **scipy**, unpack its half of the overlay, import the rest
  of the bridge. Fit, Discover, Report and the element palette come alive.

Stage B starts on its own as soon as stage A finishes, and is not waited for. This is *not* the
prefetch that `docs/METRICS_AND_UX_PLAN.md` §1.5 measured and rejected: nothing is fetched earlier
than it is now, and nothing overlaps the boot. The 18.3 MB is fetched **later**, after the page is
usable, so it competes with a visitor reading their data rather than with the wasm the boot blocks
on. The total does not improve; the wait before the first useful thing does.

### 3.2 What has to change in Python

The staged import is only possible if the data path can be imported without scipy. Four changes,
each small and each independently justifiable:

* **`core/weighting.py`** (new): `Weighting` and `weight_vectors`, moved out of `fit.py`, which
  re-exports them. Pure numpy, and `validate.py` was importing the whole fitter for them.
* **`core/stats.py`**: `from scipy.special import betainc` moves inside the F-test function. The
  module's own comment already noted the import was inherited rather than wanted.
* **`autocircuit/__init__.py` and `core/__init__.py`**: re-export through PEP 562 `__getattr__` so
  that importing a submodule does not pull the whole core in. `from autocircuit import Circuit` and
  `from autocircuit.core import Spectrum` keep working, and mypy keeps seeing the types through
  `TYPE_CHECKING` imports.
* **`web/light.py`** (new): `BRIDGE_VERSION`, the JSON envelope, and the four operations that need
  no scipy — `version`, `read`, `trim`, `validate`. Anything else it looks up in
  `web/bridge.py`, which it imports on first use.

There is **one** `handle`, one envelope and one dispatch, completed lazily. A second entry point for
the browser would be exactly the fork of the science `docs/WEB_UI_PLAN.md` §4 forbids.

`version` answers what stage A can know: the bridge version (so the handshake still guards the
build), the spectrum and validate wire versions, the reader list, and the criteria menu. A new
`runtime` op answers the rest — the fit and DRT wire versions — once scipy is in. `BRIDGE_VERSION`
goes 7 → 8, which also covers §1.3's three report fields.

### 3.3 What has to change in the browser

* **`precompile.mjs`** writes `pyodide-bytecode-numpy.zip` and `pyodide-bytecode-scipy.zip` instead
  of one overlay, because §0 measured that applying scipy's bytecode before its wheel breaks the
  import.
* **The worker** runs the two stages, posting `init` after A and a `runtime` broadcast after B. A
  request for an operation the light bridge does not have waits on stage B inside the worker, so the
  main thread never has to know which side of the line an operation is on.
* **`BridgeClient`** gains `full()` beside `ready()`. `SearchPool` waits on `full()`, because a
  worker that cannot fit yet is not a worker that is ready to be counted.
* **`App`** carries `dataReady` (stage A) and `ready` (stage B). The Data screen is enabled by the
  first; the palette, the Fit screen, the Discover screen and the catalogue fetch by the second.
* **`Plot.tsx`** imports Plotly with a dynamic `import()`, moving ~1.1 MB out of the initial bundle
  and into a chunk fetched when the first plot is drawn. The Data screen has no plot until a
  spectrum is loaded, so this is bytes deferred past the same line as scipy.

### 3.4 "Not even the example loads"

With stage A the example list is live about twice as early. It is still not live *immediately*, so
the second half of the complaint is answered separately: **the Load buttons and the drop zone are
enabled from the first paint**, and a file chosen before the runtime is up is held and read the
moment stage A lands. `BridgeClient.readFile` already awaits `ready()`, so the queue is a promise
that already exists; what is added is that the page says so — a pending row that reads *"waiting for
the Python runtime"* rather than a disabled button that says nothing.

Rejected alternative: *parse the CSV in JavaScript so an example can be shown before Python is up*.
That is a second reader, disagreeing with `autocircuit.io` about delimiter sniffing and column
mapping on exactly the files that are hard to read. `core/samples.ts` already states the rule: a
loaded sample takes the path a dropped file takes.

## 4. Gates

* **E1 — the hand-off promise is kept.** A search run at a *non-default* weighting, handed to the
  Fit screen and refitted there with no other change, reproduces the search's own numbers for that
  row. Measured before the change as well as after, since the "before" is the defect.
* **E2 — a move is a move.** Dragging an element to a new position produces the circuit the same
  edit produces from the keyboard path, keeps the element's label, and leaves the parameter values
  keyed to it intact. Dropping an element on itself is a no-op, not an error. Python tests cover the
  tree operation, including the collapse cases.
* **E3 — the data path does not import scipy.** `npm run smoke` boots Pyodide with **numpy only**
  and answers `version`, `read`, `trim` and `validate` before scipy is loaded; a heavy operation
  attempted at that point fails with a message naming the missing package rather than hanging. Then
  scipy is loaded and the rest of the existing smoke run proceeds unchanged.
* **E4 — the Data screen is usable in about half the time.** The stage-A "ready to read" moment,
  measured in the same browser and the same way as §0, against §0's totals. Both readings are
  reported, rested and loaded, as `docs/WEB_UI_PLAN.md` requires of any cold-start claim.
* **E5 — nothing else moved.** The Python suite, `ruff`, `mypy`, `npm run check`, `npm run build`,
  and the deployed site answering the same version handshake and producing the same front on the
  same sample.

## 5. What was measured, after

All browser readings are Chromium under Playwright against `npm run build` + `vite preview` on the
development machine, which is the same arrangement §0's "before" was taken with. Localhost takes
the network out: what is left is CPU, and the deployed site pays the bytes on top (§7).

### E1 — the hand-off promise is kept. [met, exactly, and the defect it fixes is measured]

Capacitor sample (71 points), pool `default`, element limit 3, **`proportional` weighting**,
**seed 3**, four workers — that is, a search deliberately *not* on the settings the Fit screen used
to default to. Recommended row `C1-L1`.

| | AIC | χ²(reduced) | RMS \|ΔZ\|/\|Z\| | C1.C |
|---|---|---|---|---|
| the search's own refit | **−51.0323** | **0.68841** | **69.240%** | — |
| Fit screen after the hand-off | **−51.0323** | **0.68841** | **69.240%** | 2.88176e−06 F |
| Fit screen as it behaved *before* (modulus, seed 0) | −306.097 | 0.11422 | 47.458% | 1.10852e−06 F |

The third row is the defect, and it is worse than a mismatched score: the same topology on the same
data comes back with a capacitance **2.6× different**, under a button whose note said the refit
"lands in the same place". After the change the Fit panel reads `proportional`, seed 3, 5 restarts
on arrival — the search's own three, off the report — and every reported digit agrees.

Gate G2 of `docs/SCREEN_STATE_PLAN.md` is therefore unchanged and now true of more than the default
settings: carrying the fitted values would still save one refit and change no number on the screen.

### E2 — a move is a move. [met]

In the browser, on `C1-R1-L1`:

* **drag** the L1 cell onto the slot before C1 → `L1-C1-R1`;
* **click** — the ✧ tool on L1, then that same slot → `L1-C1-R1`, identical, and the arm clears;
* **drop onto an element** rather than a slot → `C1-p(R1,L1)`, the parallel connection that target
  already meant for a palette drag;
* a value typed into the parameter table for `L1.L` (1.25e-9) is **still there after the move**,
  because the element keeps its label — which a delete-and-reinsert would not have done.

In Python, 8 tests on `move_subtree` and 3 on the bridge's `move` action, including the two
no-ops that fall out of the marker algorithm rather than being special-cased (source == target;
moving an element into a new branch of the block it is already in) and the collapse case (moving a
branch out of a two-branch parallel block leaves the survivor in series).

### E3 — the data path does not import scipy. [met, and it is checked in two places]

`npm run smoke` now runs the two stages in the order and at the points the worker does:

```
data runtime loaded in 0.8 s
  ok   scipy really is absent
  ok   a file can be read before scipy exists
  ok   and trimmed
  ok   a fitting operation says which package is missing rather than hanging or 404-ing
  ok   and scipy was not dragged in by trying
model runtime loaded in 2.2 s (3.0 s in total)
...
all checks passed
```

`tests/test_web_light.py` asks the same question of the library, in a subprocess with a
`sys.meta_path` finder that refuses `scipy` outright — because by the time a test runs in the main
process, twenty other tests have imported scipy and the question cannot be asked at all.

### E4 — the Data screen is usable in about a third of the time. [met, and better than the plan said]

Same browser, same build arrangement, warm-cache runs:

| | before (§0) | after, run 1 | after, run 2 |
|---|---|---|---|
| **usable for data** | 5.27 s | **1.53 s** | **1.48 s** |
| usable for fitting | 5.27 s | 4.94 s | 5.07 s |
| stage A breakdown | — | boot 0.72 / numpy 0.32 / unpack 0.06 / import 0.17 | boot 0.74 / numpy 0.42 / unpack 0.07 / import 0.18 |
| stage B breakdown | — | scipy 1.60 / unpack 0.18 / import 1.64 | scipy 1.72 / unpack 0.21 / import 1.66 |

**3.4× to the first useful moment, and the whole load is no slower** — 4.94 / 5.07 s against
5.27 s, which is inside this machine's own drift.

What is fetched before the page can read a file went **41.0 MB → 22.1 MB**: the scipy wheel
(14.01) and its bytecode overlay (5.00, up from 4.30 now that the split is taken by stage rather
than by package) are no longer among them, and the app bundle fell from 1.42 MB to 284 kB
(gzip 468 kB → 88 kB) with Plotly moved into a chunk fetched when the first plot is drawn.

And the second half of question 3, which is not a speed measurement at all: clicking **Load** on an
example **45 ms after the first paint** — before Python exists — now works. The click is accepted,
the row reads *"capacitor.csv — Waiting for the Python runtime, then reading — you do not have to
click again"*, and the spectrum appears at **1.29 s**, as soon as stage A lands. Before, the button
was disabled until 5.3 s (warm) or 9.5 s (cold).

### E5 — nothing else moved.

`npm run check` (type check + the schematic geometry suite), `npm run build`, `npm run smoke`,
`ruff check` and `mypy` (31 source files) all pass. The Python suite is **742 passed, 19 skipped in
351 s** — 19 more tests than before this phase, and the 19 skips are the ngspice round-trip, which
does not run on this machine (`docs/HANDOFF.md` §4).

An earlier full run of the same suite reported two failures, and both are worth naming because
neither was a defect in the change: `test_web_bridge.py::test_bridge_version_is_bumped_for_the_new_operations`
is the deliberate tripwire that pins `BRIDGE_VERSION` as a literal so a human has to acknowledge a
bump, and it did exactly that; and `test_discover.py::test_time_limit_stops_the_search` is the
load-sensitive clock assertion `docs/SCREEN_STATE_PLAN.md` §7 already records, which failed while
this machine was also running a browser, a Vite preview and a Pyodide smoke run, and passes on its
own and in the clean run above.

## 6. Corrections

*(What a measurement changed about the plan above. A gate written from an expectation is withdrawn
with the measurement beside it, never reworded into what the build already does.)*

**Splitting the bytecode overlay by package silently emptied half of it.** The plan said one
overlay per wheel, and that is what was built first: everything under `site-packages/scipy` into
one archive, the rest into the other. It produced a **22-byte** scipy overlay. The reason is the
change made two paragraphs earlier in the same session — `precompile.mjs` compiles what
`import autocircuit.web` touched, and that import no longer reaches scipy at all, which is the
whole point of §3.2. Nothing failed; the site would simply have made every visitor compile ~450
scipy modules that used to arrive compiled, and the only visible sign was a file size. The split is
now taken **between two imports** rather than by package name — snapshot `sys.modules` after the
light import, then import the full bridge and take the difference — which also puts each numpy
module in the stage that first needs it. Stage B's load in the smoke run fell from 4.1 s to 2.2 s
once the overlay was real again.

**A stale `public/` would have published the old overlay.** `public/` is not checked in and is not
emptied between builds, and `vite build` copies it wholesale into `dist/`. After the rename, the
5.8 MB `pyodide-bytecode.zip` was still sitting there — fetched by nothing, shipped to everyone.
`precompile.mjs` now deletes it. A build artefact that has been *renamed* is a build artefact that
has to be removed by name; the alternative is that only a clean clone builds what the repository
describes.

**The plan's "about half the time" was an underestimate, and the estimate was made the honest way
round.** §3.1 reasoned from bytes: 18.3 MB of 41 is 45%, so roughly half. The measured local
improvement is 3.4×, because the bytes were never the whole cost on this machine — installing and
importing scipy is CPU, and that is what came out of the critical path. The reading over a real
network is §7's, and it is a different shape again.

## 7. On the published site

<https://toshihiroiguchi.github.io/AutoCircuit/>, after the deploy. Two cold visits, each in a
**fresh browser context** — empty HTTP cache, which is what makes them first visits rather than
reloads — on the development machine's own link:

| | visit 1 | visit 2 |
|---|---|---|
| usable for data | **21.67 s** (boot 14.04, numpy 6.44, unpack 0.07, import 0.21) | **18.01 s** (boot 12.35, numpy 5.03, unpack 0.06, import 0.19) |
| usable for fitting | 68.65 s (scipy 45.04, unpack 0.22, import 1.72) | 36.16 s (scipy 16.30, unpack 0.23, import 1.62) |

**The bytes the page no longer waits for, timed from the same origin in a third fresh context:**
the scipy wheel is 14.01 MB in **21.06 s** and its overlay 5.00 MB in **2.84 s** — about **24 s of
transfer that used to sit in front of the first usable moment and now sits behind it**. (numpy for
comparison: 2.92 MB in 2.18 s, its overlay 0.79 MB in 2.44 s.)

**And the example loads early on the real site, not only on localhost.** Load clicked at **0.40 s**
after navigation — before Python exists at all — and the spectrum appeared at **18.08 s**, which is
70 ms after the data stage landed. The click waited; the visitor did not have to.

Three things this run says that the localhost measurement could not:

* **The second stage's spread is the network's, and it is wide** — 45.04 s against 16.30 s for the
  same 19 MB, minutes apart. This is the same machine and link the rest of this project's cold-start
  numbers come from, which is exactly why they are always reported as a pair.
* **No cross-session comparison is available, and none is claimed.** `README.md` recorded 21 s to a
  usable page for the *previous* build on an earlier day; today's link delivers roughly half the
  throughput that one implies, so the two numbers cannot be subtracted. What can be compared is
  what was measured in one sitting: 22.1 MB before the page works instead of 41.0 MB, and 24 s of
  measured transfer moved out of the way.
* The version handshake passes — the published core answers 8 and the published bundle speaks 8 —
  and drag-to-move works in production: `C1-R1-L1` dragged to `L1-C1-R1` on the live page.
