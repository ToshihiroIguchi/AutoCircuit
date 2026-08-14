// The pass / fail / checking / not-applicable badge, shared by the spectra table and (in larger
// form) the KK panel's verdict line. Color never carries the meaning alone -- each state also
// gets a symbol and a text label, since two of the four badge colors fall short of 3:1 contrast
// on a light surface by the palette's own numbers.

import type { LoadedSpectrum } from "../core/types";

export type KKBadgeState = "pass" | "fail" | "checking" | "na";

export function kkBadgeState(spectrum: LoadedSpectrum): KKBadgeState {
  if (spectrum.validating) return "checking";
  if (spectrum.validationError !== null) return "na";
  if (spectrum.validation !== null) return spectrum.validation.passed ? "pass" : "fail";
  return "checking";
}

const LABELS: Record<KKBadgeState, string> = {
  pass: "PASS",
  fail: "FAIL",
  checking: "checking",
  na: "N/A",
};

const SYMBOLS: Record<KKBadgeState, string> = {
  pass: "✓",
  fail: "✕",
  checking: "…",
  na: "?",
};

export interface KKBadgeProps {
  state: KKBadgeState;
  title?: string;
  large?: boolean;
}

export function KKBadge({ state, title, large }: KKBadgeProps) {
  const classes = ["kk-badge", `kk-badge--${state}`, large ? "kk-badge--large" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <span className={classes} title={title}>
      <span className="kk-badge__symbol" aria-hidden="true">
        {SYMBOLS[state]}
      </span>
      {LABELS[state]}
    </span>
  );
}
