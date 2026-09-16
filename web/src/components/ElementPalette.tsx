// The element palette: every element the loaded core knows. Nothing here is a hard-coded list --
// the catalogue comes from the registry in the running build, so an element added to Python
// appears here without a change.
//
// An element is placed either by dragging it onto a slot or by clicking it and then clicking a
// slot. Both exist on purpose: dragging is what the schematic invites, and clicking is what
// works from a keyboard and on a touchpad.

import type { CatalogueWire } from "../core/types";
import { elementDragData } from "./CircuitCanvas";
import { elementTitle, SymbolPreview } from "./ElementSymbol";

export interface ElementPaletteProps {
  catalogue: CatalogueWire;
  armedCode: string | null;
  onArm: (code: string | null) => void;
}

export function ElementPalette({ catalogue, armedCode, onArm }: ElementPaletteProps) {
  return (
    <section className="palette">
      <h2 className="panel-title">Elements</h2>
      <ul className="palette__list">
        {catalogue.elements.map((element) => {
          const code = element.code;
          const armed = code === armedCode;
          return (
            <li key={code}>
              <button
                type="button"
                className={`palette__item${armed ? " palette__item--armed" : ""}`}
                draggable
                onDragStart={(event) => {
                  elementDragData(event, code);
                  onArm(code);
                }}
                onClick={() => onArm(armed ? null : code)}
                aria-pressed={armed}
                title={elementTitle(element)}
              >
                <SymbolPreview code={code} />
                <span className="palette__code">{code}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="palette__hint">
        {armedCode === null
          ? "Drag an element onto the schematic, or click one here and then click a + on it."
          : `${armedCode} is armed: click a + to place it, or click ${armedCode} again to disarm.`}
      </p>
    </section>
  );
}
