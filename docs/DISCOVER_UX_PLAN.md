# DISCOVER_UX_PLAN.md — four usability fixes on the Discover path

**Status: implemented, all four items (A-D).** Verified by `npm run check` (type-check, the
schematic geometry gate, and the samples-manifest cross-check against `benchmarks/`, all passing)
and `tests/test_cli.py` (24 passed) after the change to item A. There is no quantitative gate here
the way the numbered plans above it have one -- these are usability fixes, not measurements of a
search property -- so "implemented" means the checks each item's own **Verification** section
lists were run and passed, not that a benchmark number moved. This document exists so a
session that gets cleared can pick every item back up without re-deriving it. It was written from
a user review of the Discover workflow (CLI `--workers`, the model-selection criterion, the
Discover screen's Pool control, and the Discover -> Fit hand-off) plus the Data screen's Example
Data panel. Two items that came out of the same review are **not** here:

* Which `criterion` should default — that question needs an experiment before it needs code, and
  has its own document, `docs/CRITERION_SELECTION_PLAN.md`.
* Excluding same-type element placement at genesis time (rather than after, via `simplify()`) —
  rejected. `simplify()` (`circuit.py:293-314`) plus the canonical-form cache already guarantee no
  redundant topology is ever fit twice (`circuit.py:448-456`, `enumerate.py:184-187`,
  `discover.py:1313-1314`, `3603-3606`); filtering earlier would only save the cost of building and
  immediately discarding a `Circuit` object, which was not measured and is expected to be small
  next to a fit. Not worth the added generation-time complexity without a measurement showing
  otherwise.

Each item below is independent and can be implemented and shipped on its own; there is no ordering
dependency between them. Suggested order, lowest risk first: A, B, C, D.

---

## A. CLI `--workers`: stop defaulting to 1 on the desktop path

**Current state.** `src/autocircuit/cli/main.py:666-670`:

```python
p_disc.add_argument(
    "--workers", type=int, default=1,
    help="processes for the screening pass; 1 keeps the run single-process (required "
    "under Pyodide)",
)
```

`core/discover.py`'s library-level default is also `workers: int = 1` (e.g. `discover.py:1666`,
`2147`, `2274`), and `_worker_pool` (`discover.py:2989-2997`) documents why: `workers=1` must
create nothing at all, because that is the Pyodide-safe path where `multiprocessing` does not
exist rather than merely being slow. **That constraint applies to the browser build, which calls
into this same library through Pyodide — it does not apply to the CLI**, which always runs as a
normal desktop Python process. The CLI's own `--workers` default inherited the library's
conservative default without re-examining whether the CLI needs it.

The web frontend already solved the analogous problem for itself:
`web/src/worker/pool.ts:18-23`

```ts
export const MAX_WORKERS = 4;

export function defaultPoolSize(): number {
  const cores = typeof navigator === "undefined" ? MAX_WORKERS : (navigator.hardwareConcurrency ?? MAX_WORKERS);
  return Math.max(1, Math.min(MAX_WORKERS, cores));
}
```

and `web/src/screens/DiscoverScreen.tsx:123` uses `defaultPoolSize()` as the initial
`SearchSettings.workers` value. The CLI is the only front end still hardcoded to 1.

**Change.** In `src/autocircuit/cli/main.py` only:

```python
p_disc.add_argument(
    "--workers", type=int, default=max(1, (os.cpu_count() or 1) - 1),
    help="processes for the screening pass (default: cpu_count - 1 on this machine); "
    "pass 1 to force single-process",
)
```

`import os` at the top of `main.py` if not already imported (it likely is — check before adding).

**Do not change** `core/discover.py`'s function-level defaults (`workers: int = 1` at every call
site listed above). Those are the library API's defaults, used directly by anything that imports
`autocircuit.core.discover` without going through the CLI — including, transitively, the Pyodide
build if it were ever to call `discover()` without going through the JS worker-pool layer. Keeping
the library default at 1 and only changing the CLI's argparse default means:

* a bare `import autocircuit.core.discover; discover(...)` keeps today's safe behaviour,
* `autocircuit discover ...` from a terminal gets a sensible default,
* nothing about `_worker_pool`'s Pyodide-safety contract changes.

`- 1` (not `os.cpu_count()` outright) leaves one core free for the OS and whatever else is running,
matching common CLI convention (e.g. `make -j$(nproc)-1`); this is a judgement call, not a
measurement, and can be revisited if it feels wrong in practice.

**Risks.** Low. Anyone who already passes `--workers` explicitly is unaffected. The help text
changes; update it consistently with the CLI's `discover()` call at `main.py:316` (which passes
`workers=args.workers` unchanged) and the excluded-equivalents re-screen at `main.py:344`.

**Verification.**
1. `autocircuit discover --help` shows a machine-dependent default.
2. `autocircuit discover <spectrum> --workers 1 ...` still runs single-process (spot-check no
   `multiprocessing.Pool` is created — `_worker_pool` already asserts this internally).
3. Existing benchmarks under `benchmarks/` pass their own explicit `--workers`, unaffected by the
   default change — grep `benchmarks/` for any script relying on the *default* value of `--workers`
   rather than passing it explicitly, and fix if found (none expected, but check before shipping).
4. `pytest` — the CLI test suite (`tests/` — search for `--workers` or `main.py` CLI tests) should
   not assume a fixed default of 1; if it does, update it to assert "some positive int" rather than
   a literal 1.

---

## B. Data screen: collapse the Example Data list

**Current state.** `web/src/components/SamplePanel.tsx:41-151`. The component already knows this is
a problem — its own doc comment says so:

```
web/src/components/SamplePanel.tsx:16-19
 * The list grew from five to thirteen when the device cases were added, and thirteen blurbed rows
 * is a wall rather than a menu. The grouping is the manifest's own `group` field, so the page
 * cannot invent a category the data does not carry...
```

There is already one collapsible piece: a single `expanded` boolean (`SamplePanel.tsx:53`) gates
the **command line** under every sample (`SamplePanel.tsx:128-132`), toggled by one button at the
bottom of the whole panel (`SamplePanel.tsx:139-148`, "Show the commands that made these"). The
sample rows themselves — one `<li>` per sample carrying a Load button, label, circuit code,
frequency range/noise, and a blurb paragraph (`SamplePanel.tsx:109-133`) — are always rendered in
full, grouped under `<h3>` headings by `groupsOf()` (`SamplePanel.tsx:21-30`).

**Change.** Make each `<h3>` group (`SamplePanel.tsx:105-137`) independently collapsible, collapsed
by default except the first group. Concretely:

1. Replace the single `expanded` boolean's scope — keep it for the command-line toggle exactly as
   is (that is a different axis: "how much detail per visible row", not "how many rows are
   visible") — and add a second piece of state, `openGroups: Set<string>` (or one `<details>`
   element per group, which needs no state at all and is the simpler option — prefer `<details>`
   unless the existing CSS/animation conventions in this codebase argue against it; check
   `web/src/styles` for any existing `<details>` usage or accordion pattern before choosing).
2. Wrap each group's `<h3>` + `<ul>` (`SamplePanel.tsx:106-136`) in the collapsible container.
   Default: the first group (in manifest order, so whatever `scripts/samples.mjs` lists first —
   check which group that is, likely "Shapes") open, the rest closed.
3. Each closed group's heading should still show a count ("Devices (8)") so the panel reads as a
   menu rather than a wall even collapsed, per the component's own stated problem.
4. Leave `dataReady`/`busy`/`error` handling (`SamplePanel.tsx:96-103`) untouched — those are
   panel-wide, not per-group.

**Risks.** Low, pure presentation. Confirm the Load-button early-click behavior described in
`SamplePanel.tsx:32-40` (buttons are live before the Python runtime is up) still works inside a
collapsed-by-default group — it will, since collapsing does not unmount the `<li>` content under a
native `<details>`, only hides it, but double check if a custom (non-`<details>`) implementation is
used instead, since some patterns unmount hidden content.

**Verification.**
1. `npm run check` (existing type-check + test script).
2. Manual: load the Data screen, confirm one group open by default, others collapsed with a count;
   open/close each group; confirm Load/Queue still fetches correctly from a closed-then-reopened
   group; confirm the existing "Show the commands" toggle still works per-row inside an open group.

---

## C. Discover screen: simplify the Pool control and show element symbols

**Current state.** `web/src/components/SearchPanel.tsx:57-75` — the Pool `<select>` currently lists
`AUTO_POOL`, every named preset from `catalogue.pools` (`"default"`, `"component"`,
`"electrochemical"` — defined once in `src/autocircuit/core/elements.py:486-500` and shared by the
CLI's `--pool` and the browser precisely so both offer the same set), and `CUSTOM_POOL`
(`DiscoverScreen.tsx:204-207`: `[AUTO_POOL, ...Object.keys(catalogue.pools), CUSTOM_POOL]`). When
`CUSTOM_POOL` is chosen, `SearchPanel.tsx:156-192` renders one checkbox per catalogue element,
labelled only by its short code (`element.code`) with the full name in a `title` tooltip
(`SearchPanel.tsx:167`) — no visual symbol.

The Fit screen already solves both halves of this for its own (different) element list, in
`web/src/components/ElementPalette.tsx`:

* preset pools as a row of filter **buttons** rather than a dropdown (`ElementPalette.tsx:33-45`,
  `Object.keys(catalogue.pools)` plus an `"all"` option), and
* a ready-made symbol renderer, `SymbolPreview({ code })` (`web/src/components/ElementSymbol.tsx:121`),
  already imported and used at `ElementPalette.tsx:12,67` next to the element code and full name.

**Change**, in two parts that can ship together or separately:

**C1 — element symbols in the custom-pool checkbox list.** In `SearchPanel.tsx`'s custom-pool
`<li>` (currently `SearchPanel.tsx:166-180`), import `SymbolPreview` from `./ElementSymbol` and
render it before the code, mirroring `ElementPalette.tsx:67-69`:

```tsx
<label title={element.name}>
  <input type="checkbox" ... />
  <SymbolPreview code={element.code} />
  <span className="search-panel__custom-pool-code">{element.code}</span>
</label>
```

Add whatever CSS class `SymbolPreview` needs for correct sizing inside a checkbox row — check
`ElementPalette`'s stylesheet rules for `.palette__item svg` or similar and mirror them under a
`.search-panel__custom-pool-list` selector.

**C2 — collapse the dropdown to Auto / Custom, move presets into the custom panel as quick-fill
buttons.**

1. `DiscoverScreen.tsx:204-207`: change `poolNames` from
   `[AUTO_POOL, ...Object.keys(catalogue.pools), CUSTOM_POOL]` to `[AUTO_POOL, CUSTOM_POOL]`.
   Grep the rest of `web/src` for other consumers of `poolNames` or of `catalogue.pools` used as a
   *dropdown* source (as opposed to `ElementPalette`'s own independent use of the same
   `catalogue.pools`, which is untouched by this change) before removing the wider list, to avoid
   silently breaking something else that reads it.
2. In `SearchPanel.tsx`'s custom-pool block (`SearchPanel.tsx:156-192`), add a button row above the
   checkbox `<ul>`, styled like `ElementPalette.tsx:33-45`'s `.palette__pools`:
   ```tsx
   <div className="search-panel__pool-presets">
     {Object.entries(props.catalogue.pools).map(([name, codes]) => (
       <button
         type="button"
         key={name}
         className="search-panel__pool-preset"
         disabled={locked}
         onClick={() => props.onCustomPool([...codes])}
       >
         {name}
       </button>
     ))}
   </div>
   ```
   Clicking a preset button **replaces** `customPool` with that preset's codes (not merges) — the
   checkboxes remain individually editable afterward, so a preset is a starting point, not a lock.
3. **Do not** change `src/autocircuit/core/elements.py`'s `POOLS` dict or remove `"default"` /
   `"component"` / `"electrochemical"` from the core. The CLI's `--pool component` etc.
   (`main.py:638-642`) must keep working exactly as documented — this change only affects how the
   *browser* offers the same underlying data (dropdown -> quick-fill buttons), leaving the CLI, the
   wire protocol, and `ElementPalette`'s own unrelated pool-filter buttons untouched.

**Why this is consistent with the project's own stated policy.** CLAUDE.md is explicit that the
software must never *require* the user to say what kind of part this is — `pool` is allowed to
exist only as an *optional* narrowing the user asks for (same footing as a skeleton). The named
presets (`"component"`, `"electrochemical"`) are literally that: an assertion about the part, which
is why `SearchPanel.tsx:152-155` already comments that a named pool is exactly this kind of
assertion. Folding them into buttons inside the custom panel — rather than a first-class dropdown
entry sitting next to `auto` — makes that status visually clearer: `auto` is the one true default,
`custom` (optionally seeded from a preset) is the one deliberate narrowing, and there is no third,
ambiguous middle option that looks like a second default.

**Risks.** Medium. The dropdown-to-buttons move touches `DiscoverScreenProps`/`SearchPanelProps`
plumbing (`poolNames` prop). Any saved/serialized `SearchSettings` (check whether settings persist
across sessions, e.g. in `localStorage` or the URL) that stored a named preset as `poolName` would
need a migration path, since `poolName` will no longer legally be `"component"` etc. — check
`DiscoverScreen.tsx`'s `defaultSearchSettings` and any persistence layer before shipping; if one
exists, either keep named `poolName` values working as an alias for `CUSTOM_POOL` + that preset's
codes, or add a one-time migration.

**Verification.**
1. `npm run check`.
2. Manual: Discover screen shows only Auto/Custom in the dropdown; selecting Custom shows preset
   buttons plus symbol+code checkboxes; clicking a preset button fills the checkboxes; running a
   search with a custom pool still calls `discover()` with the right element codes (compare the
   request payload before/after this change on an identical selection).

---

## D. Discover -> Fit: auto-run the fit on arrival

**Current state and why the values do not travel (keep this).**
`web/src/screens/DiscoverScreen.tsx:11-16` and `web/src/App.tsx:690-701` document the decision
already made and correctly kept: the Discover screen's "Fit this circuit" button
(`DiscoverScreen.tsx:273-279`, `onClick={() => onFitCircuit(picked)}`) hands the **topology text
only** to the Fit screen, via `App.tsx`'s `fitCircuit` callback (`App.tsx:702-719`):

```ts
const fitCircuit = useCallback(
  (text: string) => {
    setCircuit(text);
    const searched = search?.spectrumId;
    if (searched !== undefined && spectra.some((s) => s.id === searched)) setSelectedId(searched);
    const report = search?.report;
    if (report !== null && report !== undefined) {
      setFitState((previous) => ({
        ...previous,
        weighting: report.weighting,
        seed: report.seed,
        restarts: report.refit_restarts,
      }));
    }
    setScreen("fit");
  },
  [search?.spectrumId, search?.report, spectra],
);
```

`docs/SCREEN_STATE_PLAN.md` section 3 gives the reason not to carry fitted values: doing so would
install one row of a Pareto front the data cannot fully rank as *the* answer, on a screen whose
whole framing is "you asserted this circuit." `docs/STARTUP_AND_EDITING_PLAN.md` section 1 records
that the weighting/seed/restart settings *should* travel (fixed above, in the code already) so that
re-fitting on the Fit screen reliably reproduces the search's own tier-2 refit rather than landing
somewhere else. **None of this changes.**

The gap is purely: after landing on the Fit screen with the right topology and the right settings,
the user must still notice and click Fit (`FitPanel.tsx:70-74`, `onClick={props.onFit}`, wired to
`FitScreen.tsx:279-286`'s `handleFit`) before seeing a fitted curve. `DiscoverScreen.tsx:12-16`
already plots the picked row inline for exactly this reason — the Discover screen owns showing
"what the search found" precisely because the Fit screen will not show it automatically.

**Change.** Auto-trigger the *same* manual fit action once, right after this specific hand-off —
not on every arrival at the Fit screen, and not in response to ordinary editing.

1. In `FitScreen.tsx`, add an optional prop, e.g. `autoFitToken?: number`. Treat it as a one-shot
   signal: any change to its value (not its truthiness) means "run the fit now."
2. Add a `useEffect` in `FitScreen.tsx`, near `handleFit`'s definition (`FitScreen.tsx:279-311` or
   wherever it ends), with `[props.autoFitToken]` as its only dependency:
   ```ts
   const lastAutoFit = useRef<number | undefined>(undefined);
   useEffect(() => {
     if (props.autoFitToken === undefined) return;
     if (props.autoFitToken === lastAutoFit.current) return;
     lastAutoFit.current = props.autoFitToken;
     if (describe === null || wire === null || spectrumId === null) return;
     void handleFit();
   }, [props.autoFitToken, describe, wire, spectrumId, handleFit]);
   ```
   The `lastAutoFit` ref guards against re-firing if the effect re-runs for an unrelated reason
   (e.g. `describe` becoming non-null slightly after the token changes, because the circuit text
   is still being parsed) — it must fire exactly once per token change, whenever the fit
   preconditions become true, not once per dependency-array change.
3. In `App.tsx`, add a small counter state, e.g. `const [autoFitToken, setAutoFitToken] =
   useState(0)`, and bump it inside `fitCircuit` (`App.tsx:702-719`) alongside `setScreen("fit")`:
   `setAutoFitToken((n) => n + 1)`. Pass `autoFitToken={autoFitToken}` to `<FitScreen>`
   (`App.tsx:791` area).
4. Add one sentence to the doc comment at `App.tsx:690-701` noting that the values still do not
   travel, only a *request to refit* does, and pointing at this document for the reasoning — so a
   future reader does not mistake the auto-trigger for a reversal of the SCREEN_STATE_PLAN decision.

**Risks.** Medium — this is the one item in this document with a real failure mode: firing the
auto-fit more than once, or firing it on an unrelated navigation. Guard conditions:
* The token must only change from the one call site (`fitCircuit`), never from routine circuit
  editing — confirm no other code path calls `setAutoFitToken`.
* Navigating away from Fit and back (e.g. Report -> Fit) must **not** refire the effect — the ref
  guard in step 2 handles this as long as `autoFitToken` itself does not change on that round trip,
  which it will not, since nothing but `fitCircuit` touches it.
* If the user edits the circuit on the Fit screen *before* the auto-fit's async request resolves,
  the in-flight fit should still be allowed to land or be superseded the same way a manually
  triggered fit already handles a same-scenario race (check `handleFit`'s existing handling of a
  stale in-flight request, e.g. via the `fitting` state guard at `FitPanel.tsx:73`, and reuse
  whatever mechanism already exists rather than building a second one).

**Verification.**
1. `npm run check`.
2. Manual: Discover -> pick a Pareto row -> "Fit this circuit" -> Fit screen shows a fitted curve
   without an extra click, with the same statistics a manual Fit click would have produced (compare
   against pre-change manual-click behavior on the same topology/spectrum/settings).
3. Manual: on the Fit screen, edit the circuit by hand (not via Discover hand-off) and confirm no
   fit fires automatically — only the existing preview-curve recompute (`FitScreen.tsx:238-240`-ish)
   should react to hand edits.
4. Manual: Discover -> Fit -> Report -> back to Fit, confirm no second automatic fit fires.
