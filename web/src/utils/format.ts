// Small formatting helpers for the Data screen. Nothing here talks to the bridge; it only turns
// already-decoded numbers into the compact, monospace-friendly strings the instrument-style UI
// wants.

const SI_PREFIXES: ReadonlyArray<readonly [number, string]> = [
  [1e9, "G"],
  [1e6, "M"],
  [1e3, "k"],
  [1, ""],
  [1e-3, "m"],
  [1e-6, "µ"],
  [1e-9, "n"],
  [1e-12, "p"],
];

/** Format a finite number with an SI prefix, e.g. `formatSi(12345, "Hz") -> "12.3 kHz"`. */
export function formatSi(value: number, unit: string, digits = 3): string {
  if (!Number.isFinite(value)) return `${value} ${unit}`;
  if (value === 0) return `0 ${unit}`;
  const abs = Math.abs(value);
  for (const [scale, prefix] of SI_PREFIXES) {
    if (abs >= scale) return `${(value / scale).toPrecision(digits)} ${prefix}${unit}`;
  }
  const last = SI_PREFIXES[SI_PREFIXES.length - 1] as readonly [number, string];
  return `${(value / last[0]).toPrecision(digits)} ${last[1]}${unit}`;
}

/** Format a range of two SI-scaled values sharing a unit, e.g. `"1.0 Hz .. 100 kHz"`. */
export function formatSiRange(min: number, max: number, unit: string, digits = 3): string {
  return `${formatSi(min, unit, digits)} .. ${formatSi(max, unit, digits)}`;
}

/** Format a fraction (0.01 = 1%) as a percentage string. */
export function formatPercent(fraction: number, digits = 2): string {
  if (!Number.isFinite(fraction)) return `${fraction}`;
  return `${(fraction * 100).toFixed(digits)}%`;
}

/** Format a plain finite/non-finite number with a fixed number of significant digits. */
export function formatNumber(value: number, digits = 4): string {
  if (!Number.isFinite(value)) return `${value}`;
  return value.toPrecision(digits);
}
