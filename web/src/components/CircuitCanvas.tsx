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

import { useMemo } from "react";
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
  /** True while an edit is in flight; the canvas stops accepting new ones. */
  busy: boolean;
  onSelect: (path: number[]) => void;
  onInsert: (
    path: number[],
    action: "series" | "parallel",
    position: "before" | "after",
    code: string,
  ) => void;
  onRemove: (path: number[]) => void;
}

/** The drag payload. A private type keeps a stray text drag from being read as an element. */
const DRAG_TYPE = "application/x-autocircuit-element";

export function elementDragData(event: DragEvent, code: string): void {
  event.dataTransfer.setData(DRAG_TYPE, code);
  event.dataTransfer.effectAllowed = "copy";
}

function droppedCode(event: DragEvent): string | null {
  const code = event.dataTransfer.getData(DRAG_TYPE);
  return code === "" ? null : code;
}

function samePath(a: number[] | null, b: number[]): boolean {
  return a !== null && a.length === b.length && a.every((value, index) => value === b[index]);
}

export function CircuitCanvas(props: CircuitCanvasProps) {
  const layout = useMemo(() => layoutSchematic(props.tree), [props.tree]);
  const { armedCode, busy, onSelect, onRemove } = props;

  return (
    <div className="canvas">
      <div
        className={`cc${armedCode === null ? "" : " cc--armed"}`}
        style={{ width: layout.width, height: layout.height }}
      >
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
          return (
            <div
              key={element.path.join(".")}
              className={`cc-el${selected ? " cc-el--selected" : ""}`}
              style={{ left: element.x, top: element.y, width: element.w, height: element.h }}
            >
              <button
                type="button"
                className="cc-el__pick"
                onClick={() => onSelect(element.path)}
                title={`${element.name} (${element.code})`}
                aria-pressed={selected}
                aria-label={`Select ${element.label}, ${element.name}`}
              />
              <span className="cc-el__tools">
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
            </div>
          );
        })}

        {layout.slots.map((slot) => (
          <Slot key={slot.key} slot={slot} {...props} />
        ))}
      </div>
    </div>
  );
}

function Slot({
  slot,
  busy,
  armedCode,
  onInsert,
}: CircuitCanvasProps & { slot: SlotPlacement }) {
  const branch = slot.action === "parallel";

  function place(code: string): void {
    if (!busy) onInsert(slot.path, slot.action, slot.position, code);
  }

  function handleDrop(event: DragEvent): void {
    event.preventDefault();
    const code = droppedCode(event);
    if (code !== null) place(code);
  }

  function handleDragOver(event: DragEvent): void {
    // Only claim the drop when the drag really carries an element, so a file dragged onto the
    // page still reaches the window-level handler that loads it.
    if (event.dataTransfer.types.includes(DRAG_TYPE)) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    }
  }

  const width = branch ? 34 : GEOMETRY.slotSize;
  const height = branch ? GEOMETRY.chipH : GEOMETRY.slotSize;
  const what = branch ? "as a new branch of" : slot.position;
  return (
    <button
      type="button"
      className={`cc-slot${branch ? " cc-slot--branch" : ""}`}
      style={{ left: slot.x - width / 2, top: slot.y - height / 2, width, height }}
      disabled={busy}
      onClick={() => armedCode !== null && place(armedCode)}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      title={
        armedCode === null
          ? "Drag an element here, or pick one in the palette and click"
          : `Insert ${armedCode} ${what} ${slot.label}`
      }
      aria-label={`Insert an element ${what} ${slot.label}`}
    >
      <span aria-hidden="true">+</span>
    </button>
  );
}
