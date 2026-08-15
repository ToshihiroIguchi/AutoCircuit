// One element, drawn.
//
// Three of these are standard and are drawn as the standard says: IEC 60617 -- which JIS C0617 is
// harmonised with, and which is what EIS packages use -- gives the resistor an empty rectangle,
// the capacitor two parallel plates, the inductor a row of semicircles.
//
// The rest have no standard symbol. A survey of ZView, Gamry, EC-Lab and the EIS literature found
// no agreed drawing for a CPE, and none for the Warburg family either: the notation everyone
// shares is the *code* (W, Ws, Wo, G), not a shape. So this file does not invent one and present
// it as convention. CPE gets the one departure that is widely readable -- a capacitor whose plates
// are curved, saying "a capacitor, but distributed" -- and everything else gets a box with its
// code in it, which is what a tool draws for an element the reader has to be told the name of.
// An element added to the Python registry therefore appears here as a labelled box rather than as
// nothing, which is the behaviour that keeps the palette's promise that the catalogue is dynamic.

import type { ReactNode } from "react";
import type { ElementPlacement } from "../core/schematic";

/** Half the width every symbol draws inside; the cell's leads stop at these edges. */
const HALF = 15;

interface SymbolProps {
  placement: ElementPlacement;
  selected: boolean;
}

/** A boxed element's box, wide enough for its code: 5-character codes exist (SKINF). */
function boxWidth(code: string): number {
  return Math.max(28, code.length * 6 + 10);
}

/** The drawing of one element type, in local coordinates centred on the wire line. */
function symbolPaths(code: string): ReactNode {
  switch (code) {
    case "R":
      return (
        <>
          <line x1={-HALF} y1={0} x2={-12} y2={0} />
          <line x1={12} y1={0} x2={HALF} y2={0} />
          <rect className="cc-sym__fill" x={-12} y={-6.5} width={24} height={13} />
        </>
      );
    case "C":
      return (
        <>
          <line x1={-HALF} y1={0} x2={-3} y2={0} />
          <line x1={3} y1={0} x2={HALF} y2={0} />
          <line x1={-3} y1={-9} x2={-3} y2={9} />
          <line x1={3} y1={-9} x2={3} y2={9} />
        </>
      );
    case "L":
      return (
        <>
          <line x1={-HALF} y1={0} x2={-12} y2={0} />
          <line x1={12} y1={0} x2={HALF} y2={0} />
          <path
            className="cc-sym__line"
            d="M-12,0 a3,3 0 0,1 6,0 a3,3 0 0,1 6,0 a3,3 0 0,1 6,0 a3,3 0 0,1 6,0"
          />
        </>
      );
    case "CPE":
      return (
        <>
          <line x1={-HALF} y1={0} x2={-10} y2={0} />
          <line x1={10} y1={0} x2={HALF} y2={0} />
          <path className="cc-sym__line" d="M-4,-9 Q-10,0 -4,9" />
          <path className="cc-sym__line" d="M4,-9 Q10,0 4,9" />
        </>
      );
    default: {
      const w = boxWidth(code);
      return (
        <>
          <line x1={-HALF} y1={0} x2={-w / 2} y2={0} />
          <line x1={w / 2} y1={0} x2={HALF} y2={0} />
          <rect className="cc-sym__fill" x={-w / 2} y={-9} width={w} height={18} rx={1} />
        </>
      );
    }
  }
}

const DRAWN = new Set(["R", "C", "L", "CPE"]);

/** The symbol itself, centred on (0,0): the code goes inside the box of an element that has one. */
function body(code: string): ReactNode {
  return (
    <>
      {symbolPaths(code)}
      {!DRAWN.has(code) && (
        <text className="cc-sym__code" x={0} y={0} dominantBaseline="central">
          {code}
        </text>
      )}
    </>
  );
}

export function ElementSymbol({ placement, selected }: SymbolProps) {
  return (
    <g
      className={`cc-sym${selected ? " cc-sym--selected" : ""}`}
      transform={`translate(${placement.cx},${placement.cy})`}
    >
      {body(placement.code)}
      <text className="cc-sym__label" x={0} y={-16}>
        {placement.label}
      </text>
    </g>
  );
}

/**
 * The same symbol, standing alone: what the palette offers, drawn as what the canvas will draw.
 *
 * The palette used to list codes while the canvas drew shapes, which left the reader to learn the
 * mapping from the schematic. It is one drawing routine, so the two cannot drift apart.
 */
export function SymbolPreview({ code }: { code: string }) {
  return (
    <svg
      className="cc-sym palette__symbol"
      width={44}
      height={22}
      viewBox="-22 -11 44 22"
      aria-hidden="true"
      focusable="false"
    >
      {body(code)}
    </svg>
  );
}
