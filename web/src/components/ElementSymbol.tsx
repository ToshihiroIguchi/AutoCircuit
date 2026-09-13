// One element, drawn.
//
// Three of these are standard and are drawn as the standard says: IEC 60617 -- which JIS C0617 is
// harmonised with, and which is what EIS packages use -- gives the resistor an empty rectangle,
// the capacitor two parallel plates, the inductor a row of semicircles.
//
// The rest have no standard symbol. A survey of ZView, Gamry, EC-Lab and the EIS literature found
// no agreed drawing for a CPE, and none for the Warburg family either: the notation everyone
// shares is the *code* (W, Ws, Wo, G), not a shape. So this file does not invent one and present
// it as convention. CPE used to depart from that rule with a glyph of its own -- two plates both
// bowing outward -- and that departure collided with IEC 60617 rather than merely extending it:
// the standard already assigns a curved plate to the polarized/electrolytic capacitor (one
// straight plate, one curved), so the old glyph's outward-bowed right-hand plate read as that
// symbol, mirrored -- a misreading in-domain for a tool whose users measure real electrolytic
// capacitors. CPE is therefore drawn with `C`'s own straight-plate shape (the true and only
// honest claim: "capacitor-like") plus its code beneath the wire, exactly the "a tool draws a
// box with its code in it" treatment given to every other non-IEC element, just without the box.
// Every element added to the Python registry appears here as a labelled box rather than as
// nothing, which is the behaviour that keeps the palette's promise that the catalogue is dynamic.

import type { ReactNode } from "react";
import type { ElementPlacement } from "../core/schematic";
import type { ElementWire } from "../core/types";

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
      // Same shape as `C`: two straight plates. See the file header for why -- CPE no longer
      // gets a glyph of its own, only its code drawn beneath the wire (see `body`).
      return symbolPaths("C");
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

//: R, C and L carry no code text -- their IEC 60617 shapes are self-identifying. Everything
//: else needs its code written somewhere: a boxed element gets it centred inside the box;
//: CPE, drawn as a plain capacitor, gets it beneath the wire instead, at the same offset the
//: designator label above uses in the other direction (see `ElementSymbol`'s `y={-16}`).
const SELF_IDENTIFYING = new Set(["R", "C", "L"]);

/** The symbol itself, centred on (0,0): the code goes inside the box of an element that has one,
 * or beneath the wire for a shaped-but-unlabelled element (CPE). */
function body(code: string): ReactNode {
  const shaped = code === "CPE";
  return (
    <>
      {symbolPaths(code)}
      {!SELF_IDENTIFYING.has(code) && (
        <text
          className="cc-sym__code"
          x={0}
          y={shaped ? 16 : 0}
          dominantBaseline={shaped ? undefined : "central"}
        >
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
/** The tooltip text for an element: just its full name, same as SearchPanel's checkbox label. */
export function elementTitle(element: ElementWire): string {
  return element.name;
}

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
