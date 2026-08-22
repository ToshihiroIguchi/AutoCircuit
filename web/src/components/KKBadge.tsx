// The badge, shared by the spectra table and (in larger form) the KK panel's verdict line.
// Color never carries the meaning alone -- each state also gets a symbol and a text label, since
// several of the badge colors fall short of 3:1 contrast on a light surface by the palette's own
// numbers.
//
// `na` and `inconclusive` are both "no verdict" to a reader and are deliberately separate here:
// `na` means the check could not run, and the panel renders `validationError` for it, whereas
// `inconclusive` means the check ran and could not be applied, and the panel shows its full
// statistics. Folding them together would put an empty error box under a spectrum that has
// numbers to show.

import type { LoadedSpectrum } from "../core/types";

export type KKBadgeState = "pass" | "fail" | "inconclusive" | "checking" | "na";

export function kkBadgeState(spectrum: LoadedSpectrum): KKBadgeState {
  if (spectrum.validating) return "checking";
  if (spectrum.validationError !== null) return "na";
  // `verdict` is taken as given rather than rebuilt from `passed` and the residual: asking the
  // residual question before the pass question would report healthy noisy data as untested.
  if (spectrum.validation !== null) return spectrum.validation.verdict;
  return "checking";
}

const LABELS: Record<KKBadgeState, string> = {
  pass: "PASS",
  fail: "FAIL",
  inconclusive: "NO VERDICT",
  checking: "checking",
  na: "N/A",
};

const SYMBOLS: Record<KKBadgeState, string> = {
  pass: "✓",
  fail: "✕",
  inconclusive: "–",
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
