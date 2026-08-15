# The schematic — how the circuit is drawn

The Fit screen's circuit panel, phase 6 step 3. The science behind it did not change; the picture
did. This is kept for the same reason the other plans are: the wrong version of it looked
reasonable, and the reasons it was wrong are not obvious from the code that replaced it.

## 1. What was wrong

From a screenshot of the Fit screen showing `p(R1,R2)-C1`, in that order of severity:

1. **Every element was the same rectangle with its designator inside.** Nothing in the picture
   said which box was a resistor and which was a capacitor. A schematic whose symbols carry no
   type is a block diagram with electrical pretensions — the reader has to fall back on the
   circuit string underneath it, at which point the drawing has earned nothing.
2. **Wires did not meet what they connected.** The rails of a parallel block were the *borders*
   of the flexbox column that held it, so they ran the full height of that column, and the series
   wire arrived at the column's centre rather than at a node. Stub, rail and lead each ended
   wherever its own box happened to end.
3. **A line ran out of the block to nothing.** The dashed segment under the last branch was the
   "add a branch here" affordance. Drawn inside the rails, at the width of a branch, it read as a
   third branch wired to nothing — the picture asserted a connection that the circuit did not
   have.
4. Underneath all three: **the wires were decoration on boxes.** A border follows whatever height
   its box ended up with. Nothing in that layout ever computed where a wire should start or stop,
   so nothing in it could be checked.

## 2. The options, and the one taken

| | approach | what it fixes | what it leaves |
|---|---|---|---|
| A | Patch the CSS: rails from the first branch to the last, junction dots as pseudo-elements, affordance out of the rails | 2 and 3, for the shapes that were tested | 1 untouched; geometry still implicit, so the next nesting depth breaks it again and nothing catches that |
| B | Keep the flexbox layout, put an SVG symbol inside each box | 1 | 2, 3 and 4 exactly as they were |
| C | **Compute the layout, draw it in SVG, overlay the handles as HTML buttons** | all four | costs a layout module and its gate |
| D | Render the schematic in Python and ship the SVG over the bridge | all four | puts a drawing concern inside a package that must stay GUI-free, and makes every edit a round trip through the worker before the picture can move |

**C.** A and B are each half of it, and A's half is the one that decays: the fault in 2 and 3 was
not that the numbers were wrong but that there were no numbers, so a fix expressed as more CSS is
a fix that cannot be asserted. C turns the picture into `layoutSchematic(tree) -> coordinates`, a
pure function of the parsed tree, which is what lets §5's gate exist at all. D was rejected on the
project's own rule — no GUI code in `autocircuit.core` — and would have made a hover redraw wait
on Pyodide.

## 3. What is drawn, and what is not claimed

`src/components/ElementSymbol.tsx`.

* **R, C, L are standard and are drawn as the standard has them**: IEC 60617 — which JIS C0617 is
  harmonised with, and which is what the EIS packages use — gives the resistor an empty rectangle,
  the capacitor two parallel plates, the inductor a row of semicircles.
* **The rest have no standard symbol, and the code does not pretend otherwise.** A survey of
  ZView, Gamry Echem Analyst, EC-Lab and the EIS literature found no agreed drawing for a CPE and
  none for the Warburg family: what practitioners share is the *code* (CPE, W, Ws, Wo, G), not a
  shape. So CPE gets the one departure that is widely readable — a capacitor whose plates are
  curved, "a capacitor, but distributed" — and every other element is drawn as a box carrying its
  own code, which is what a tool draws for something the reader has to be told the name of.
* That fallback is also why the palette's promise still holds. The catalogue comes from the
  registry in the running build, so an element added to Python appears in the palette without a
  change here; it now appears on the canvas too, as a labelled box, rather than as a symbol this
  file would have had to invent.
* **Fitted values are not drawn on the schematic.** The parameter table beneath it already carries
  every value with its unit, its standard error and its search interval, and a value repeated onto
  a symbol is a second place for it to go stale.

## 4. The layout

`src/core/schematic.ts`, free of React and of the DOM.

* **Two passes.** `measure` gives every node a box and the height of the wire line inside it;
  `place` walks the tree again emitting segments at absolute coordinates. Measuring first is what
  lets a series run put all of its children on one line: the line sits at the deepest port in the
  run, and each child is dropped so that its own port lands on it. No wire is ever diagonal
  because no wire is ever fitted to a box after the fact.
* **A parallel block meets the circuit halfway up its own stack.** Its terminals are level with
  the midpoint between its first and last branch, so its rails span exactly the branches and have
  nothing to reach past them for. That is the whole of fault 3's other half.
* **Junction dots are computed, not decorative**: a dot where three or more wires meet, and only
  there. Two wires meeting is a corner and gets none.
* **A handle is never a conductor.** Insertion points, the delete and parallel tools, and the
  "add a branch" button are HTML buttons positioned over the drawing, in a layer that the SVG
  cannot be confused with: real buttons, focusable and labelled, and drawn as buttons. The branch
  button sits *below* its block, outside the rails.

## 5. Gates

**S1 — the geometry, [measured].** `npm run schematic` runs the layout over six trees, from a lone
element to a parallel block with a nested parallel block inside one of its branches, and asserts
twelve properties of each: every wire axis-aligned and non-degenerate; no wire ending anywhere
except on another wire, on a symbol or at the outer terminals; a junction dot exactly where three
or more wires meet, *recomputed from the emitted segments* rather than trusted from the layout;
every element reached by a lead on each side; nothing drawn through a symbol; the network
connected; no two symbols overlapping; every block's terminals level with the middle of its
branches; one add-a-branch handle per block and each outside its block; nothing outside the
reported extent. 72 checks, all passing.

A gate that passes on the first run is a gate that has not been shown to fail, so five mutants
were built from the faults it exists to catch: rails spanning the whole block again (caught — four
wires ending in mid-air, and two junction dots missing); the branch handle back inside the rails
(caught); a branch lead off by three pixels (caught — the axis-alignment and mid-air checks both
fire); the dot rule weakened to four wires (caught); a block entered off-centre (caught, by the
check added after the first four had already been caught and this one had not).

**S2 — the four edits still work, [measured].** In a browser against the dev server: inserting in
series from a slot took `R1` to `R1-C1`; the parallel tool on an element took it to
`R1-p(C1,C2)`; the add-a-branch button took it to `R1-p(C1,C2,C3)`; delete took it back to
`R1-p(C1,C2)`. Each read back from the circuit field, which is written by Python's parse of the
edit rather than by the canvas.

**S3 — both themes, [measured].** Screenshots in dark and light of
`R1-p(C1,R2-W1)-p(L1,SKINF1,CPE1)`, which exercises every drawn symbol, both boxed elements, a
series run inside a branch, and a three-branch block: symbols, wires, dots, labels and the
selected-element state all read correctly in both.

**S4 — it cannot be published broken.** `npm run check` is now `tsc --noEmit && npm run schematic`,
and `npm run build` runs `npm run check`, so the Pages workflow's existing build step gates the
deployment on the geometry as well as on the types.

## 6. Out of scope

* Values on the canvas (§3).
* A schematic on the Discover and Report screens; they list circuits by the thousand and a string
  is the right density there.
* Dragging an element to *move* it. Placement is by insertion, as it was before; a move is
  a remove and an insert, and the tree addresses make that the user's two clicks rather than a
  drag with an ambiguous drop target.
