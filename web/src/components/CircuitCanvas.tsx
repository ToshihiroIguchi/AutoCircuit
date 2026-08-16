// The schematic, drawn from the tree Python parsed and edited by sending positions back to it.
//
// Every symbol and every handle here carries a `path`: the list of child indices that addresses it
// from the root, which is exactly what `autocircuit.core.circuit.subtree_at` takes. So an edit
// is "insert an R after this path", never "rebuild the string like this". This file knows how a
// series block and a parallel block look; it does not know what either one means, and it cannot
// produce a circuit the command line would read differently, because it never writes one.
//
// It is drawn in two layers over the same coordinates, and the split is the point:
//
//   * an SVG that paints the circuit -- wires, junction dots, symbols -- and takes no clicks;
//   * absolutely positioned HTML buttons for everything that can be done to it.
//
// Keeping them apart is what stops the picture from lying. The previous canvas drew its "add a
// branch here" affordance as a dashed line inside a parallel block's rails, where it read as a
// third branch wired to nothing; here an affordance is a button, a wire is a wire, and no handle
// is ever drawn as a conductor. It also keeps the handles as real <button>s -- focusable,
// labelled, drop targets -- rather than SVG shapes wearing ARIA roles.

import { useEffect, useMemo, useState } from "react";
import type { DragEvent } from "react";
import type { CircuitNodeWire } from "../core/types";
import type { SlotPlacement } from "../core/schematic";
import { GEOMETRY, layoutSchematic } from "../core/schematic";
import { ElementSymbol } from "./ElementSymbol";

export interface CircuitCanvasProps {
  tree: CircuitNodeWire;
  /** The element whose parameters the table is highlighting, if any. */
  selectedPath: number[] | null;
  /** The element code the palette has armed, placed by clicking a slot. */
  armedCode: string | null;
  /**
   * An element of *this* circuit that has been armed to move, placed by clicking a slot.
   *
   * The click half of drag-to-move, and the same arrangement the palette has for the same
   * reason: dragging is what the schematic invites and is unavailable from a keyboard. Mutually
   * exclusive with `armedCode`, because a slot can only do one thing when it is clicked.
   */
  armedMove: number[] | null;
  onArmMove: (path: number[] | null) => void;
  /** True while an edit is in flight; the canvas stops accepting new ones. */
  busy: boolean;
  /**
   * Draw the circuit and nothing else: no slots, no delete buttons, no drop targets.
   *
   * A prop rather than a second component. Two renderers would be two chances for the picture
   * shown beside a search result to disagree with the editable one, and `npm run schematic`
   * checks the geometry once (`docs/SCHEMATIC_PLAN.md`).
   */
  readOnly?: boolean;
  onSelect: (path: number[]) => void;
  onInsert: (
    path: number[],
    action: "series" | "parallel",
    position: "before" | "after",
    code: string,
  ) => void;
  /**
   * Move an element that is already in the circuit to another position in it.
   *
   * `from` and `to` both address the tree *as it is now*: what the target's path becomes once
   * the source has been torn out is worked out in Python, by `move_subtree`, for the reason at
   * the top of this file (docs/STARTUP_AND_EDITING_PLAN.md section 2.2).
   */
  onMove: (
    from: number[],
    to: number[],
    connect: "series" | "parallel",
    position: "before" | "after",
  ) => void;
  onRemove: (path: number[]) => void;
}

/**
 * The two drag payloads. Private types keep a stray text drag from being read as an element, and
 * keep the two kinds apart: a slot has to know whether it is being handed a *new* element from
 * the palette or an existing one from the canvas, and the answer decides which edit it makes.
 * `getData` is unreadable during `dragover`, so the distinction has to be in the type and not in
 * the payload.
 */
const DRAG_TYPE = "application/x-autocircuit-element";
const MOVE_TYPE = "application/x-autocircuit-move";

export function elementDragData(event: DragEvent, code: string): void {
  event.dataTransfer.setData(DRAG_TYPE, code);
  event.dataTransfer.effectAllowed = "copy";
}

function moveDragData(event: DragEvent, path: number[]): void {
  // JSON rather than a joined string, so that the root's empty path is `[]` and not `""` -- which
  // would be indistinguishable from "this drag carries no path at all".
  event.dataTransfer.setData(MOVE_TYPE, JSON.stringify(path));
  event.dataTransfer.effectAllowed = "move";
}

function droppedCode(event: DragEvent): string | null {
  const code = event.dataTransfer.getData(DRAG_TYPE);
  return code === "" ? null : code;
}

/** The source path of a move drag, or null when the drag is not one. */
function droppedPath(event: DragEvent): number[] | null {
  const raw = event.dataTransfer.getData(MOVE_TYPE);
  if (raw === "") return null;
  const parsed: unknown = JSON.parse(raw);
  return Array.isArray(parsed) && parsed.every((n) => typeof n === "number") ? parsed : null;
}

/** Claim a drop only when the drag really carries an element, so a file drop still loads. */
function allowElementDrop(event: DragEvent): void {
  const types = event.dataTransfer.types;
  if (types.includes(DRAG_TYPE)) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  } else if (types.includes(MOVE_TYPE)) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }
}

function samePath(a: number[] | null, b: number[]): boolean {
  return a !== null && a.length === b.length && a.every((value, index) => value === b[index]);
}

export function CircuitCanvas(props: CircuitCanvasProps) {
  const layout = useMemo(() => layoutSchematic(props.tree), [props.tree]);
  const { armedCode, armedMove, onArmMove, busy, onSelect, onRemove, readOnly = false } = props;
  // True from the moment an element leaves the palette -- or leaves its own place on the canvas --
  // until the drag ends, so every target can show itself. Without it a slot looks the same
  // whether or not it will accept what is under the pointer, and the small `+` has to be guessed
  // at -- which is why dragging read as missing when it had been there since step 3
  // (`docs/METRICS_AND_UX_PLAN.md` section 7).
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (readOnly) return undefined;
    // `dragenter` on the window, not `dragstart` here: the drag starts in the palette, which is
    // not a child of this element, and `dragstart` does not reach it.
    function onEnter(event: globalThis.DragEvent): void {
      const types = event.dataTransfer?.types;
      if (types?.includes(DRAG_TYPE) === true || types?.includes(MOVE_TYPE) === true) {
        setDragging(true);
      }
    }
    function onEnd(): void {
      setDragging(false);
    }
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragend", onEnd);
    window.addEventListener("drop", onEnd);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragend", onEnd);
      window.removeEventListener("drop", onEnd);
    };
  }, [readOnly]);

  const classes = [
    "cc",
    (armedCode !== null || armedMove !== null) && !readOnly ? "cc--armed" : "",
    dragging ? "cc--dragging" : "",
    readOnly ? "cc--read-only" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="canvas">
      <div className={classes} style={{ width: layout.width, height: layout.height }}>
        <svg
          className="cc__paint"
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          aria-hidden="true"
          focusable="false"
        >
          <g className="cc__wires">
            {layout.wires.map((wire, index) => (
              <line
                key={`w${index}`}
                x1={wire.x1}
                y1={wire.y1}
                x2={wire.x2}
                y2={wire.y2}
                shapeRendering="crispEdges"
              />
            ))}
          </g>
          {layout.junctions.map((dot, index) => (
            <circle key={`j${index}`} className="cc__junction" cx={dot.x} cy={dot.y} r={2.5} />
          ))}
          {layout.elements.map((element) => (
            <ElementSymbol
              key={element.path.join(".")}
              placement={element}
              selected={samePath(props.selectedPath, element.path)}
            />
          ))}
        </svg>

        {layout.elements.map((element) => {
          const selected = samePath(props.selectedPath, element.path);
          const moving = samePath(armedMove, element.path);
          // Dropping onto a symbol puts the dropped element in *parallel* with it -- the
          // operation the || button already offers, and the one a drag aimed at a symbol is
          // aiming at. Series insertion keeps its own targets, between the symbols, where a
          // drag aimed at a gap in the wire lands. A drag that carries a path rather than a code
          // means the same thing about an element already here, so it makes the same connection
          // and moves rather than adds.
          function receive(event: DragEvent): void {
            event.preventDefault();
            if (busy) return;
            const code = droppedCode(event);
            if (code !== null) {
              props.onInsert(element.path, "parallel", "after", code);
              return;
            }
            const from = droppedPath(event);
            if (from !== null) props.onMove(from, element.path, "parallel", "after");
          }
          return (
            <div
              key={element.path.join(".")}
              className={`cc-el${selected ? " cc-el--selected" : ""}${
                moving ? " cc-el--moving" : ""
              }`}
              style={{ left: element.x, top: element.y, width: element.w, height: element.h }}
              draggable={!readOnly && !busy}
              onDragStart={(event) => moveDragData(event, element.path)}
              onDragOver={readOnly ? undefined : allowElementDrop}
              onDrop={readOnly ? undefined : receive}
            >
              <button
                type="button"
                className="cc-el__pick"
                onClick={() => onSelect(element.path)}
                title={
                  readOnly
                    ? `${element.name} (${element.code})`
                    : `${element.name} (${element.code}) — drag it to move it, or drop an ` +
                      `element here to put it in parallel`
                }
                aria-pressed={selected}
                aria-label={`Select ${element.label}, ${element.name}`}
              />
              {readOnly ? null : (
              <span className="cc-el__tools">
                <button
                  type="button"
                  className={`cc-el__tool${moving ? " cc-el__tool--armed" : ""}`}
                  disabled={busy}
                  onClick={() => onArmMove(moving ? null : element.path)}
                  title={
                    moving
                      ? `${element.label} is armed to move: click a + to put it there, or click ` +
                        `this again to leave it where it is`
                      : `Move ${element.label}: click a + to say where. Dragging it does the same.`
                  }
                  aria-pressed={moving}
                  aria-label={`Move ${element.label}`}
                >
                  &#10021;
                </button>
                <button
                  type="button"
                  className="cc-el__tool"
                  disabled={busy || armedCode === null}
                  onClick={() =>
                    armedCode !== null && props.onInsert(element.path, "parallel", "after", armedCode)
                  }
                  title={
                    armedCode === null
                      ? "Pick an element in the palette first"
                      : `Put ${armedCode} in parallel with ${element.label}`
                  }
                  aria-label={`Add an element in parallel with ${element.label}`}
                >
                  &#8741;
                </button>
                <button
                  type="button"
                  className="cc-el__tool cc-el__tool--remove"
                  disabled={busy}
                  onClick={() => onRemove(element.path)}
                  title={`Delete ${element.label}`}
                  aria-label={`Delete ${element.label}`}
                >
                  &times;
                </button>
              </span>
              )}
            </div>
          );
        })}

        {readOnly
          ? null
          : layout.slots.map((slot) => <Slot key={slot.key} slot={slot} {...props} />)}
      </div>
    </div>
  );
}

function Slot({
  slot,
  busy,
  armedCode,
  armedMove,
  onArmMove,
  onInsert,
  onMove,
}: CircuitCanvasProps & { slot: SlotPlacement }) {
  const branch = slot.action === "parallel";

  function place(code: string): void {
    if (!busy) onInsert(slot.path, slot.action, slot.position, code);
  }

  /** The same position, for an element that is already in the circuit. */
  function relocate(from: number[]): void {
    if (busy) return;
    onMove(from, slot.path, slot.action, slot.position);
    onArmMove(null);
  }

  function handleDrop(event: DragEvent): void {
    event.preventDefault();
    const code = droppedCode(event);
    if (code !== null) {
      place(code);
      return;
    }
    const from = droppedPath(event);
    if (from !== null) relocate(from);
  }

  const width = branch ? 34 : GEOMETRY.slotSize;
  const height = branch ? GEOMETRY.chipH : GEOMETRY.slotSize;
  const what = branch ? "as a new branch of" : slot.position;
  // A slot does one thing when clicked, so the two arms cannot both be live; the canvas keeps
  // them exclusive and the move wins here only because it is the one that is null by default.
  const title =
    armedMove !== null
      ? `Move the armed element ${what} ${slot.label}`
      : armedCode === null
        ? "Drag an element here, or pick one in the palette and click"
        : `Insert ${armedCode} ${what} ${slot.label}`;
  return (
    <button
      type="button"
      className={`cc-slot${branch ? " cc-slot--branch" : ""}`}
      style={{ left: slot.x - width / 2, top: slot.y - height / 2, width, height }}
      disabled={busy}
      onClick={() => {
        if (armedMove !== null) relocate(armedMove);
        else if (armedCode !== null) place(armedCode);
      }}
      onDragOver={allowElementDrop}
      onDrop={handleDrop}
      title={title}
      aria-label={`Insert or move an element ${what} ${slot.label}`}
    >
      <span aria-hidden="true">+</span>
    </button>
  );
}
