// The element palette: every element the loaded core knows, grouped by the same named pools the
// CLI offers to `--pool`. Nothing here is a hard-coded list -- the catalogue comes from the
// registry in the running build, so an element added to Python appears here without a change.
//
// An element is placed either by dragging it onto a slot or by clicking it and then clicking a
// slot. Both exist on purpose: dragging is what the schematic invites, and clicking is what
// works from a keyboard and on a touchpad.

import { useState } from "react";
import type { CatalogueWire } from "../core/types";
import { elementDragData } from "./CircuitCanvas";
import { SymbolPreview } from "./ElementSymbol";

export interface ElementPaletteProps {
  catalogue: CatalogueWire;
  armedCode: string | null;
  onArm: (code: string | null) => void;
}

const ALL = "all";

export function ElementPalette({ catalogue, armedCode, onArm }: ElementPaletteProps) {
  const [pool, setPool] = useState("component");
  const codes =
    pool === ALL
      ? catalogue.elements.map((element) => element.code)
      : (catalogue.pools[pool] ?? catalogue.elements.map((element) => element.code));
  const byCode = new Map(catalogue.elements.map((element) => [element.code, element]));

  return (
    <section className="palette">
      <h2 className="panel-title">Elements</h2>
      <div className="palette__pools">
        {[...Object.keys(catalogue.pools), ALL].map((name) => (
          <button
            key={name}
            type="button"
            className={`palette__pool${name === pool ? " palette__pool--active" : ""}`}
            onClick={() => setPool(name)}
            aria-pressed={name === pool}
          >
            {name}
          </button>
        ))}
      </div>
      <ul className="palette__list">
        {codes.map((code) => {
          const element = byCode.get(code);
          if (element === undefined) return null;
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
                title={`${element.name} -- ${element.params
                  .map((p) => `${p.name} [${p.unit}]`)
                  .join(", ")}`}
              >
                <SymbolPreview code={code} />
                <span className="palette__code">{code}</span>
                <span className="palette__name">{element.name}</span>
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
