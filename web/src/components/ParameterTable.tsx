// One row per fittable parameter: the value the model is being drawn with, the interval the
// fitter will search, and -- once there is a fit -- the standard error and the restart spread.
//
// Two of these columns carry a claim that has to stay straight. A typed *value* moves the
// preview only: pressing Fit runs the same global search the CLI runs, from the same
// data-derived bounds, and does not start from what is in the box. Ticking *Fix* is the one
// thing that makes a number binding, and it removes that parameter from the fit rather than
// nudging it. The hint under the table says so, because a table of editable numbers next to a
// Fit button implies the opposite.

import { useState } from "react";
import type { FitWire, ParameterWire } from "../core/types";
import { decodeArray, decodeFloat } from "../core/wire";
import { formatNumber } from "../utils/format";

export interface ParameterTableProps {
  params: ParameterWire[];
  /** The value each parameter is currently drawn with, explicit or the fitter's start. */
  values: Record<string, number>;
  /** Parameters held at their value, by name. */
  fixed: Record<string, number>;
  /** Search-interval overrides, by name; absent means the data-derived interval. */
  bounds: Record<string, [number, number]>;
  /** The current fit, if the one on screen still describes what is on screen. */
  fit: FitWire | null;
  selectedLabel: string | null;
  disabled: boolean;
  onValue: (name: string, value: number) => void;
  onFix: (name: string, held: boolean) => void;
  onBound: (name: string, index: 0 | 1, value: number | null) => void;
  onSelectLabel: (label: string) => void;
}

/**
 * Six significant digits, and an exponent where a decimal expansion would be unreadable.
 *
 * JavaScript only switches to exponential notation below 1e-7, which prints a 3.3 uF capacitance
 * as 0.0000033 -- a string nobody can check at a glance against a datasheet. The threshold here
 * is the point where the leading zeros start to outnumber the digits.
 */
function asText(value: number): string {
  if (!Number.isFinite(value)) return String(value);
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude < 1e-3 || magnitude >= 1e6) {
    return value.toExponential(5).replace(/\.?0+e/, "e");
  }
  return String(Number(value.toPrecision(6)));
}

export function ParameterTable(props: ParameterTableProps) {
  const stderr = props.fit === null ? null : decodeArray(props.fit.fit.statistics.stderr);
  const spread = props.fit?.fit.restart_spread ?? {};

  return (
    <section className="params">
      <h2 className="panel-title">Parameters</h2>
      <table className="params__table">
        <thead>
          <tr>
            <th>Parameter</th>
            <th className="num">Value</th>
            <th>Unit</th>
            <th className="num">Std. error</th>
            <th className="num">Rel.</th>
            <th>Fix</th>
            <th className="num">Search from</th>
            <th className="num">to</th>
          </tr>
        </thead>
        <tbody>
          {props.params.map((param, index) => {
            const value = props.values[param.name] ?? 0;
            const held = param.name in props.fixed;
            const error = stderr === null ? null : (stderr[index] as number);
            const override = props.bounds[param.name];
            const derivedLo = param.lower === undefined ? null : decodeFloat(param.lower);
            const derivedHi = param.upper === undefined ? null : decodeFloat(param.upper);
            return (
              <tr
                key={param.name}
                className={param.label === props.selectedLabel ? "params__row--selected" : undefined}
                onClick={() => props.onSelectLabel(param.label)}
              >
                <td>
                  <span className="params__label">{param.label}</span>
                  <span className="params__param">.{param.param}</span>
                </td>
                <td className="num">
                  <NumberInput
                    value={value}
                    disabled={props.disabled}
                    ariaLabel={`Value of ${param.name}`}
                    onCommit={(next) => next !== null && props.onValue(param.name, next)}
                  />
                </td>
                <td className="params__unit">{param.unit}</td>
                <td className="num">
                  {error === null ? "" : held ? "held" : formatNumber(error, 3)}
                </td>
                <td className="num">
                  {error === null || held || value === 0 || !Number.isFinite(error)
                    ? ""
                    : `${((error / Math.abs(value)) * 100).toFixed(1)}%`}
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={held}
                    disabled={props.disabled}
                    aria-label={`Hold ${param.name} at its value`}
                    onChange={(event) => props.onFix(param.name, event.target.checked)}
                  />
                </td>
                <td className="num">
                  <NumberInput
                    value={override?.[0] ?? derivedLo}
                    disabled={props.disabled || held}
                    ariaLabel={`Lower search bound for ${param.name}`}
                    muted={override === undefined}
                    onCommit={(next) => props.onBound(param.name, 0, next)}
                  />
                </td>
                <td className="num">
                  <NumberInput
                    value={override?.[1] ?? derivedHi}
                    disabled={props.disabled || held}
                    ariaLabel={`Upper search bound for ${param.name}`}
                    muted={override === undefined}
                    onCommit={(next) => props.onBound(param.name, 1, next)}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {Object.keys(spread).length > 0 && (
        <p className="params__note">
          Restart spread:{" "}
          {Object.entries(spread)
            .map(([name, value]) => `${name} ${(decodeFloat(value) * 100).toFixed(1)}%`)
            .join(", ")}
        </p>
      )}
      <p className="params__note">
        A value moves the preview curve only. Fit searches the interval on the right from
        scratch, so it needs no starting guess and will not use one. Tick Fix to hold a
        parameter you already know.
      </p>
    </section>
  );
}

/**
 * A numeric cell that commits on blur or Enter rather than on every keystroke.
 *
 * Committing per keystroke would send a preview request for every intermediate string a number
 * passes through while it is typed ("1", "1e", "1e-"), most of which are not numbers.
 */
function NumberInput({
  value,
  onCommit,
  disabled,
  ariaLabel,
  muted = false,
}: {
  value: number | null;
  onCommit: (value: number | null) => void;
  disabled: boolean;
  ariaLabel: string;
  muted?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? (value === null ? "" : asText(value));

  function commit(): void {
    if (draft === null) return;
    const text = draft.trim();
    setDraft(null);
    // Emptying the box is a real instruction -- it clears an override rather than meaning
    // "leave it as it was" -- so it commits `null` instead of being dropped as unparseable.
    if (text === "") onCommit(null);
    else if (Number.isFinite(Number(text)) && Number(text) !== value) onCommit(Number(text));
  }

  return (
    <input
      type="text"
      inputMode="decimal"
      className={`params__input${muted ? " params__input--muted" : ""}`}
      value={shown}
      disabled={disabled}
      aria-label={ariaLabel}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commit();
        } else if (event.key === "Escape") {
          setDraft(null);
        }
      }}
    />
  );
}
