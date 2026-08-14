// The schematic, drawn from the tree Python parsed and edited by sending positions back to it.
//
// Every box and every slot here carries a `path`: the list of child indices that addresses it
// from the root, which is exactly what `autocircuit.core.circuit.subtree_at` takes. So an edit
// is "insert an R after this path", never "rebuild the string like this". This file knows how a
// series block and a parallel block look; it does not know what either one means, and it cannot
// produce a circuit the command line would read differently, because it never writes one.

import { Fragment } from "react";
import type { DragEvent } from "react";
import type { CircuitNodeWire } from "../core/types";

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
  return (
    <div className="canvas">
      <span className="canvas__terminal" aria-hidden="true" />
      <Chain node={props.tree} {...props} />
      <span className="canvas__terminal" aria-hidden="true" />
    </div>
  );
}

/**
 * A run of elements in series, with a slot before, between and after each of them.
 *
 * A lone element is drawn as a run of one, so the same slots appear around it. That is not a
 * special case in the model: inserting in series next to a leaf and appending to the block it
 * sits in are the same operation on the Python side, because `series(...)` flattens.
 */
function Chain({ node, ...props }: CircuitCanvasProps & { node: CircuitNodeWire }) {
  const children = node.kind === "series" ? node.children : [node];
  const first = children[0] as CircuitNodeWire;
  return (
    <div className="cc-series">
      <Slot
        {...props}
        path={first.path}
        action="series"
        position="before"
        label={describe(first)}
      />
      {children.map((child) => (
        <Fragment key={child.path.join(".")}>
          <Node node={child} {...props} />
          <Slot
            {...props}
            path={child.path}
            action="series"
            position="after"
            label={describe(child)}
          />
        </Fragment>
      ))}
    </div>
  );
}

function Node({ node, ...props }: CircuitCanvasProps & { node: CircuitNodeWire }) {
  if (node.kind === "element") {
    return <ElementBox node={node} selected={samePath(props.selectedPath, node.path)} {...props} />;
  }
  if (node.kind === "series") {
    // Parsing flattens nested series, so this is unreachable for a real circuit; drawing it as
    // a chain rather than throwing keeps a future tree shape from blanking the screen.
    return <Chain node={node} {...props} />;
  }
  return (
    <div className="cc-parallel">
      <div className="cc-parallel__branches">
        {node.children.map((child) => (
          <div className="cc-branch" key={child.path.join(".")}>
            <Chain node={child} {...props} />
          </div>
        ))}
      </div>
      <Slot
        {...props}
        path={node.path}
        action="parallel"
        position="after"
        label={describe(node)}
        branch
      />
    </div>
  );
}

function describe(node: CircuitNodeWire): string {
  if (node.kind === "element") return node.label;
  return node.kind === "series" ? "this series block" : "this parallel block";
}

function ElementBox({
  node,
  selected,
  busy,
  onSelect,
  onInsert,
  onRemove,
  armedCode,
}: CircuitCanvasProps & { node: CircuitNodeWire & { kind: "element" }; selected: boolean }) {
  return (
    <div className={`cc-element${selected ? " cc-element--selected" : ""}`}>
      <button
        type="button"
        className="cc-element__body"
        onClick={() => onSelect(node.path)}
        title={`${node.name} (${node.code})`}
        aria-pressed={selected}
      >
        {node.label}
      </button>
      <span className="cc-element__tools">
        <button
          type="button"
          className="cc-element__tool"
          disabled={busy || armedCode === null}
          onClick={() => armedCode !== null && onInsert(node.path, "parallel", "after", armedCode)}
          title={
            armedCode === null
              ? "Pick an element in the palette first"
              : `Put ${armedCode} in parallel with ${node.label}`
          }
          aria-label={`Add an element in parallel with ${node.label}`}
        >
          &#8741;
        </button>
        <button
          type="button"
          className="cc-element__tool cc-element__tool--remove"
          disabled={busy}
          onClick={() => onRemove(node.path)}
          title={`Delete ${node.label}`}
          aria-label={`Delete ${node.label}`}
        >
          &times;
        </button>
      </span>
    </div>
  );
}

function Slot({
  path,
  action,
  position,
  label,
  branch = false,
  busy,
  armedCode,
  onInsert,
}: CircuitCanvasProps & {
  path: number[];
  action: "series" | "parallel";
  position: "before" | "after";
  label: string;
  branch?: boolean;
}) {
  function place(code: string): void {
    if (!busy) onInsert(path, action, position, code);
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

  const what = branch ? "as a new branch of" : `${position}`;
  return (
    <button
      type="button"
      className={`cc-slot${branch ? " cc-slot--branch" : ""}`}
      disabled={busy}
      onClick={() => armedCode !== null && place(armedCode)}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      title={
        armedCode === null
          ? "Drag an element here, or pick one in the palette and click"
          : `Insert ${armedCode} ${what} ${label}`
      }
      aria-label={`Insert an element ${what} ${label}`}
    >
      <span aria-hidden="true">+</span>
    </button>
  );
}
