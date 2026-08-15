// Proves the schematic's geometry, without a browser.
//
// The complaints this answers were all about the picture rather than about the circuit: symbols
// that were all the same rectangle, wires that did not meet the things they connected, and a line
// that ran out of a parallel block to nothing. The first is a matter of what is drawn and is
// checked by eye; the other two are arithmetic, and arithmetic can be asserted.
//
// So this runs src/core/schematic.ts over a handful of trees and checks the properties that were
// false before: every wire is axis-aligned, no wire ends anywhere except on another wire, on a
// symbol or at the outer terminals, a junction dot appears exactly where three or more wires meet
// -- recomputed here from the emitted segments rather than trusted from the layout -- nothing is
// drawn through a symbol, and the whole thing is one connected network. The handle that adds a
// branch is checked to be outside its block, because as a dashed line inside it it was read as a
// branch wired to nothing.
//
//   npm run schematic
//
// The .ts import is Node's own type stripping; schematic.ts is written in erasable syntax.
import { GEOMETRY, layoutSchematic } from "../src/core/schematic.ts";

const failures = [];

function check(name, condition, detail = "") {
  if (condition) {
    console.log(`  ok   ${name}`);
  } else {
    console.log(`  FAIL ${name}${detail ? ` -- ${detail}` : ""}`);
    failures.push(name);
  }
}

// -- the trees, in the shape `autocircuit.web.bridge` sends them ------------------------------

const E = (code, label) => ({ kind: "element", code, label, name: code });
const S = (...children) => ({ kind: "series", children });
const P = (...children) => ({ kind: "parallel", children });

function withPaths(node, path = []) {
  if (node.kind === "element") return { ...node, path };
  return { ...node, path, children: node.children.map((kid, i) => withPaths(kid, [...path, i])) };
}

const CASES = {
  "one element": E("R", "R1"),
  "p(R1,R2)-C1": S(P(E("R", "R1"), E("R", "R2")), E("C", "C1")),
  "R1-p(C1,R2-W1)": S(E("R", "R1"), P(E("C", "C1"), S(E("R", "R2"), E("W", "W1")))),
  "p(R1,C1)-p(R2,C2)": S(P(E("R", "R1"), E("C", "C1")), P(E("R", "R2"), E("C", "C2"))),
  "p(R1,p(C1,L1)-R2,CPE1)": S(
    P(E("R", "R1"), S(P(E("C", "C1"), E("L", "L1")), E("R", "R2")), E("CPE", "CPE1")),
  ),
  "deep series in every branch": S(
    E("L", "L1"),
    P(S(E("R", "R1"), E("C", "C1")), S(E("W", "W1"), E("SKINF", "SKINF1"), E("R", "R2"))),
  ),
};

// -- geometry helpers -------------------------------------------------------------------------

const EPS = 1e-6;
const near = (a, b) => Math.abs(a - b) < EPS;
const samePoint = (p, q) => near(p.x, q.x) && near(p.y, q.y);

function onSegment(wire, p) {
  const withinX = p.x >= Math.min(wire.x1, wire.x2) - EPS && p.x <= Math.max(wire.x1, wire.x2) + EPS;
  const withinY = p.y >= Math.min(wire.y1, wire.y2) - EPS && p.y <= Math.max(wire.y1, wire.y2) + EPS;
  if (!withinX || !withinY) return false;
  // Axis-aligned only, which is asserted separately.
  return near(wire.x1, wire.x2) ? near(p.x, wire.x1) : near(p.y, wire.y1);
}

/** How many wire ends leave a point: an endpoint contributes one arm, a pass-through two. */
function arms(wires, p) {
  let total = 0;
  for (const wire of wires) {
    const ends =
      (samePoint(p, { x: wire.x1, y: wire.y1 }) ? 1 : 0) +
      (samePoint(p, { x: wire.x2, y: wire.y2 }) ? 1 : 0);
    if (ends > 0) total += ends;
    else if (onSegment(wire, p)) total += 2;
  }
  return total;
}

function endpoints(wires) {
  const points = [];
  for (const wire of wires) {
    for (const p of [
      { x: wire.x1, y: wire.y1 },
      { x: wire.x2, y: wire.y2 },
    ]) {
      if (!points.some((q) => samePoint(p, q))) points.push(p);
    }
  }
  return points;
}

/** Where a symbol's own leads stop: an endpoint there is the symbol continuing the circuit. */
function symbolEdge(layout, p) {
  const half = GEOMETRY.bodyW / 2;
  return layout.elements.some(
    (el) => near(p.y, el.cy) && (near(p.x, el.cx - half) || near(p.x, el.cx + half)),
  );
}

function connected(layout) {
  const parent = layout.wires.map((_, i) => i);
  const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])));
  const union = (i, j) => {
    parent[find(i)] = find(j);
  };
  for (let i = 0; i < layout.wires.length; i += 1) {
    for (let j = i + 1; j < layout.wires.length; j += 1) {
      const a = layout.wires[i];
      const b = layout.wires[j];
      const touch = [
        { x: a.x1, y: a.y1 },
        { x: a.x2, y: a.y2 },
      ].some((p) => onSegment(b, p));
      const back = [
        { x: b.x1, y: b.y1 },
        { x: b.x2, y: b.y2 },
      ].some((p) => onSegment(a, p));
      if (touch || back) union(i, j);
    }
  }
  // An element joins the lead on its left to the lead on its right: that is what the symbol is.
  const half = GEOMETRY.bodyW / 2;
  for (const el of layout.elements) {
    const left = layout.wires.findIndex(
      (w) => near(w.y1, el.cy) && near(w.y2, el.cy) && near(Math.max(w.x1, w.x2), el.cx - half),
    );
    const right = layout.wires.findIndex(
      (w) => near(w.y1, el.cy) && near(w.y2, el.cy) && near(Math.min(w.x1, w.x2), el.cx + half),
    );
    if (left >= 0 && right >= 0) union(left, right);
  }
  return new Set(layout.wires.map((_, i) => find(i))).size;
}

// -- the checks -------------------------------------------------------------------------------

for (const [name, spec] of Object.entries(CASES)) {
  console.log(name);
  const layout = layoutSchematic(withPaths(spec));
  const half = GEOMETRY.bodyW / 2;

  check(
    "every wire is axis-aligned",
    layout.wires.every((w) => near(w.x1, w.x2) || near(w.y1, w.y2)),
  );
  check(
    "no wire has zero length",
    layout.wires.every((w) => !(near(w.x1, w.x2) && near(w.y1, w.y2))),
  );

  const dangling = endpoints(layout.wires).filter(
    (p) =>
      arms(layout.wires, p) === 1 &&
      !near(p.x, 0) &&
      !near(p.x, layout.width) &&
      !symbolEdge(layout, p),
  );
  check(
    "no wire ends in mid-air",
    dangling.length === 0,
    dangling.map((p) => `(${p.x},${p.y})`).join(" "),
  );

  const expected = endpoints(layout.wires).filter((p) => arms(layout.wires, p) >= 3);
  check(
    "a junction dot wherever three or more wires meet, and nowhere else",
    expected.length === layout.junctions.length &&
      expected.every((p) => layout.junctions.some((q) => samePoint(p, q))),
    `${layout.junctions.length} drawn, ${expected.length} implied by the wires`,
  );

  check(
    "every element has a lead to each side of its symbol",
    layout.elements.every(
      (el) =>
        layout.wires.some(
          (w) =>
            near(w.y1, el.cy) &&
            near(w.y2, el.cy) &&
            near(Math.min(w.x1, w.x2), el.x) &&
            near(Math.max(w.x1, w.x2), el.cx - half),
        ) &&
        layout.wires.some(
          (w) =>
            near(w.y1, el.cy) &&
            near(w.y2, el.cy) &&
            near(Math.min(w.x1, w.x2), el.cx + half) &&
            near(Math.max(w.x1, w.x2), el.x + el.w),
        ),
    ),
  );

  check(
    "no wire is drawn through a symbol",
    layout.wires.every((w) =>
      layout.elements.every((el) => {
        const box = { x0: el.cx - half, x1: el.cx + half, y0: el.cy - 13, y1: el.cy + 13 };
        const lo = { x: Math.min(w.x1, w.x2), y: Math.min(w.y1, w.y2) };
        const hi = { x: Math.max(w.x1, w.x2), y: Math.max(w.y1, w.y2) };
        return !(lo.x < box.x1 - EPS && hi.x > box.x0 + EPS && lo.y < box.y1 && hi.y > box.y0);
      }),
    ),
  );

  check("the whole network is connected", connected(layout) === 1, `${connected(layout)} pieces`);

  check(
    "no two symbols overlap",
    layout.elements.every((a, i) =>
      layout.elements.every(
        (b, j) =>
          i >= j ||
          a.x + a.w <= b.x + EPS ||
          b.x + b.w <= a.x + EPS ||
          a.y + a.h <= b.y + EPS ||
          b.y + b.h <= a.y + EPS,
      ),
    ),
  );

  const branchSlots = layout.slots.filter((slot) => slot.action === "parallel");
  check(
    "the add-a-branch handle sits outside its block, not between its rails",
    branchSlots.every((slot) => {
      const block = layout.blocks.find((b) => b.path.join(".") === slot.path.join("."));
      return block !== undefined && slot.y > block.y + block.h;
    }),
    `${branchSlots.length} handles, ${layout.blocks.length} blocks`,
  );

  check(
    "every parallel block gets exactly one of them",
    branchSlots.length === layout.blocks.length,
  );

  // The reason the rails never overhang: the block meets the rest of the circuit halfway up its
  // own stack, so there is nothing for a rail to reach past its outermost branch to.
  check(
    "a block's terminals are level with the middle of its branches",
    layout.blocks.every((block) => {
      const rail = layout.wires.find((w) => near(w.x1, block.x) && near(w.x2, block.x));
      return rail !== undefined && near(block.line, (rail.y1 + rail.y2) / 2);
    }),
  );

  check(
    "nothing is drawn outside the reported extent",
    layout.wires.every(
      (w) =>
        Math.min(w.x1, w.x2) >= -EPS &&
        Math.max(w.x1, w.x2) <= layout.width + EPS &&
        Math.min(w.y1, w.y2) >= -EPS &&
        Math.max(w.y1, w.y2) <= layout.height + EPS,
    ),
  );
}

console.log(failures.length === 0 ? "\nall checks passed" : `\n${failures.length} FAILED`);
process.exit(failures.length === 0 ? 0 : 1);
