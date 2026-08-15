// Where every wire, symbol and handle of the schematic goes -- as numbers, before anything draws.
//
// The old canvas laid the picture out with flexbox and drew the wires as borders on the boxes it
// happened to produce. That is why they did not meet: a border follows whatever height the box
// ended up with, so a parallel block's rails ran the full height of the block *including* the row
// its "add a branch" affordance sat in, and the series wire arrived at the centre of the whole
// column rather than at the node. A wire is not decoration on a box; it is a segment between two
// points, and both points have to be computed.
//
// So this module computes them. It is deliberately free of React and of the DOM: it takes the
// tree Python parsed and returns coordinates, which makes the properties that were wrong before
// -- every wire axis-aligned, no rail past its outermost branch, one line through every symbol --
// things a test can assert rather than things a screenshot has to be trusted for.
//
// Two passes: `measure` gives every node a box and the height of the wire line inside it, then
// `place` walks the tree again writing segments at absolute coordinates. Measuring first is what
// lets a series run align its children on one line -- the line sits at the deepest port of the
// run, and each child is dropped so its own port lands on it.

import type { CircuitNodeWire } from "./types";

/** Fixed sizes, in CSS pixels. The overlay's buttons are positioned from these too. */
export const GEOMETRY = {
  /** The stub of wire at each end of the whole schematic; the outermost slots sit on it. */
  lead: 26,
  /** The wire between two neighbours in a series run; a slot sits at its middle. */
  gap: 26,
  /** An element cell: this tall, with the wire line this far down from its top. */
  cellH: 40,
  portY: 26,
  /** How much of a cell the symbol itself occupies. Every symbol draws its own leads to fill it. */
  bodyW: 30,
  minCellW: 56,
  /** Label width is estimated, not measured: the label is drawn in a monospaced face. */
  charW: 6.6,
  labelPad: 14,
  /** Vertical space between two branches of a parallel block. */
  branchGap: 16,
  /** The horizontal wire from a rail to the branch it feeds. */
  railLead: 26,
  /** The square hit area of a slot, and of an element's hover tools. */
  slotSize: 22,
  /** How far below a parallel block its "add a branch" button sits. */
  chipDrop: 10,
  chipH: 18,
} as const;

export interface Point {
  x: number;
  y: number;
}

/** One straight segment of wire. Always axis-aligned; the layout never emits a diagonal. */
export interface WireSeg {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

/** One element, with the cell it owns and the point its symbol is centred on. */
export interface ElementPlacement {
  path: number[];
  code: string;
  label: string;
  name: string;
  /** Top-left of the cell, and its size: the select button covers exactly this. */
  x: number;
  y: number;
  w: number;
  h: number;
  /** Centre of the symbol. `cy` is the wire line running through the cell. */
  cx: number;
  cy: number;
}

/** One place an element can be inserted. A handle, never a wire -- see the note in `place`. */
export interface SlotPlacement {
  key: string;
  path: number[];
  action: "series" | "parallel";
  position: "before" | "after";
  /** What the slot is next to, for the tooltip and the accessible name. */
  label: string;
  /** Centre of the hit area. */
  x: number;
  y: number;
}

/** A parallel block: where it sits, and the height its own two terminals are at. */
export interface BlockPlacement {
  path: number[];
  x: number;
  y: number;
  w: number;
  h: number;
  /** The wire line into and out of the block -- level with the middle of its branches. */
  line: number;
}

export interface SchematicLayout {
  width: number;
  height: number;
  wires: WireSeg[];
  /** Where three or more wires meet: the dots that say a crossing is a connection. */
  junctions: Point[];
  elements: ElementPlacement[];
  slots: SlotPlacement[];
  blocks: BlockPlacement[];
}

/** A node's footprint, and how far down inside it the wire line runs. */
interface Size {
  w: number;
  h: number;
  port: number;
}

interface Sink {
  wires: WireSeg[];
  junctions: Point[];
  elements: ElementPlacement[];
  slots: SlotPlacement[];
  blocks: BlockPlacement[];
}

/** A lone element is a series run of one, so the same slots surround it. */
function chainOf(node: CircuitNodeWire): CircuitNodeWire[] {
  return node.kind === "series" ? node.children : [node];
}

export function describeNode(node: CircuitNodeWire): string {
  if (node.kind === "element") return node.label;
  return node.kind === "series" ? "this series block" : "this parallel block";
}

function cellWidth(label: string): number {
  return Math.max(GEOMETRY.minCellW, Math.ceil(label.length * GEOMETRY.charW + GEOMETRY.labelPad));
}

function measure(node: CircuitNodeWire): Size {
  if (node.kind === "element") {
    return { w: cellWidth(node.label), h: GEOMETRY.cellH, port: GEOMETRY.portY };
  }
  if (node.kind === "series") return measureChain(node.children);
  return measureParallel(node.children);
}

function measureChain(children: readonly CircuitNodeWire[]): Size {
  const sizes = children.map(measure);
  if (sizes.length === 0) return { w: GEOMETRY.minCellW, h: GEOMETRY.cellH, port: GEOMETRY.portY };
  const w =
    sizes.reduce((sum, size) => sum + size.w, 0) + GEOMETRY.gap * (sizes.length - 1);
  // One line through the whole run: it sits at the deepest port, and every child hangs from it.
  const port = Math.max(...sizes.map((size) => size.port));
  const below = Math.max(...sizes.map((size) => size.h - size.port));
  return { w, h: port + below, port };
}

function branchLines(children: readonly CircuitNodeWire[]): { sizes: Size[]; lines: number[] } {
  const sizes = children.map(measure);
  const lines: number[] = [];
  let top = 0;
  for (const size of sizes) {
    lines.push(top + size.port);
    top += size.h + GEOMETRY.branchGap;
  }
  return { sizes, lines };
}

function measureParallel(children: readonly CircuitNodeWire[]): Size {
  const { sizes, lines } = branchLines(children);
  const inner = Math.max(...sizes.map((size) => size.w));
  const h =
    sizes.reduce((sum, size) => sum + size.h, 0) + GEOMETRY.branchGap * (sizes.length - 1);
  const first = lines[0] ?? GEOMETRY.portY;
  const last = lines[lines.length - 1] ?? first;
  // The block's own terminals are level with the middle of the stack, so the rails never have to
  // run past the outermost branch to reach them. That overhang was the wire to nowhere.
  return { w: inner + 2 * GEOMETRY.railLead, h, port: (first + last) / 2 };
}

function slotKey(path: number[], action: string, position: string): string {
  return `${path.join(".")}:${action}:${position}`;
}

/** Places one node so that its wire line lands on `lineY`, and returns the box it filled. */
function place(node: CircuitNodeWire, x: number, lineY: number, out: Sink): Size {
  const size = measure(node);
  if (node.kind === "element") {
    const cx = x + size.w / 2;
    out.elements.push({
      path: node.path,
      code: node.code,
      label: node.label,
      name: node.name,
      x,
      y: lineY - size.port,
      w: size.w,
      h: size.h,
      cx,
      cy: lineY,
    });
    // The symbol owns the middle of the cell: the leads stop at its edges rather than being
    // painted through it, which is what lets a capacitor be two plates with a gap between them.
    out.wires.push({ x1: x, y1: lineY, x2: cx - GEOMETRY.bodyW / 2, y2: lineY });
    out.wires.push({ x1: cx + GEOMETRY.bodyW / 2, y1: lineY, x2: x + size.w, y2: lineY });
    return size;
  }
  if (node.kind === "series") {
    placeChain(node.children, x, lineY, out);
    return size;
  }
  placeParallel(node, x, lineY, out);
  return size;
}

/** A series run: children on one line, a wire between each pair, a slot on every wire. */
function placeChain(children: readonly CircuitNodeWire[], x: number, lineY: number, out: Sink): void {
  let cursor = x;
  children.forEach((child, index) => {
    const size = place(child, cursor, lineY, out);
    cursor += size.w;
    if (index < children.length - 1) {
      out.wires.push({ x1: cursor, y1: lineY, x2: cursor + GEOMETRY.gap, y2: lineY });
      out.slots.push({
        key: slotKey(child.path, "series", "after"),
        path: child.path,
        action: "series",
        position: "after",
        label: describeNode(child),
        x: cursor + GEOMETRY.gap / 2,
        y: lineY,
      });
      cursor += GEOMETRY.gap;
    }
  });
}

/**
 * A run with the two slots that bracket it, placed on wire the caller already drew.
 *
 * The caller owns those two stubs -- the schematic's own terminals, or the leads from a pair of
 * rails -- so it is the caller that knows where there is room for a handle.
 */
function placeRun(
  node: CircuitNodeWire,
  x: number,
  lineY: number,
  beforeX: number,
  afterX: number,
  out: Sink,
): void {
  const children = chainOf(node);
  const first = children[0];
  const last = children[children.length - 1];
  placeChain(children, x, lineY, out);
  if (first !== undefined) {
    out.slots.push({
      key: slotKey(first.path, "series", "before"),
      path: first.path,
      action: "series",
      position: "before",
      label: describeNode(first),
      x: beforeX,
      y: lineY,
    });
  }
  if (last !== undefined) {
    out.slots.push({
      key: slotKey(last.path, "series", "after"),
      path: last.path,
      action: "series",
      position: "after",
      label: describeNode(last),
      x: afterX,
      y: lineY,
    });
  }
}

/** A node with children: the wire type is one record for both block kinds, so this is that one. */
type BlockNode = Extract<CircuitNodeWire, { children: CircuitNodeWire[] }>;

function placeParallel(node: BlockNode, x: number, lineY: number, out: Sink): void {
  const size = measure(node);
  const top = lineY - size.port;
  const railL = x;
  const railR = x + size.w;
  const innerX = x + GEOMETRY.railLead;
  const innerW = size.w - 2 * GEOMETRY.railLead;
  out.blocks.push({ path: node.path, x, y: top, w: size.w, h: size.h, line: lineY });

  const lines: number[] = [];
  let cursor = top;
  for (const child of node.children) {
    const branch = measure(child);
    const by = cursor + branch.port;
    const bx = innerX + (innerW - branch.w) / 2;
    lines.push(by);
    // Both leads are horizontal by construction, whatever the branch is made of.
    out.wires.push({ x1: railL, y1: by, x2: bx, y2: by });
    out.wires.push({ x1: bx + branch.w, y1: by, x2: railR, y2: by });
    placeRun(child, bx, by, (railL + bx) / 2, (bx + branch.w + railR) / 2, out);
    cursor += branch.h + GEOMETRY.branchGap;
  }

  const yTop = Math.min(...lines);
  const yBot = Math.max(...lines);
  if (yBot > yTop) {
    out.wires.push({ x1: railL, y1: yTop, x2: railL, y2: yBot });
    out.wires.push({ x1: railR, y1: yTop, x2: railR, y2: yBot });
    for (const railX of [railL, railR]) {
      for (const y of new Set([...lines, lineY])) {
        const horizontals = lines.filter((line) => line === y).length + (y === lineY ? 1 : 0);
        const degree = horizontals + (y > yTop ? 1 : 0) + (y < yBot ? 1 : 0);
        // A dot means "these wires are joined". Drawing one at a corner, where only two wires
        // meet, would say nothing; drawing none at a T would say the wrong thing.
        if (degree >= 3) out.junctions.push({ x: railX, y });
      }
    }
  }

  // The handle for a new branch is a button under the block, not a dangling wire. The old canvas
  // drew it as a dashed line inside the rails, which read as a branch connected to nothing.
  out.slots.push({
    key: slotKey(node.path, "parallel", "after"),
    path: node.path,
    action: "parallel",
    position: "after",
    label: describeNode(node),
    x: x + size.w / 2,
    y: top + size.h + GEOMETRY.chipDrop + GEOMETRY.chipH / 2,
  });
}

/** The whole picture: the tree, plus a terminal stub at each end to hang the outer slots on. */
export function layoutSchematic(tree: CircuitNodeWire): SchematicLayout {
  const out: Sink = { wires: [], junctions: [], elements: [], slots: [], blocks: [] };
  const children = chainOf(tree);
  const size = measureChain(children);
  const lineY = size.port;
  const x = GEOMETRY.lead;
  const width = size.w + 2 * GEOMETRY.lead;

  out.wires.push({ x1: 0, y1: lineY, x2: x, y2: lineY });
  out.wires.push({ x1: x + size.w, y1: lineY, x2: width, y2: lineY });
  placeRun(tree, x, lineY, GEOMETRY.lead / 2, width - GEOMETRY.lead / 2, out);

  let bottom = size.h;
  for (const element of out.elements) bottom = Math.max(bottom, element.y + element.h);
  for (const block of out.blocks) bottom = Math.max(bottom, block.y + block.h);
  for (const slot of out.slots) bottom = Math.max(bottom, slot.y + GEOMETRY.slotSize / 2);
  return { ...out, width, height: bottom };
}
