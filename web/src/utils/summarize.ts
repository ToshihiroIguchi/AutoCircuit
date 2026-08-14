// Decodes just enough of a SpectrumWire to fill the spectra table -- point count, frequency
// range, |Z| range. This is display-only: nothing here is sent back across the bridge, so it is
// fine to summarize with plain numbers instead of the wire's float sentinels.

import type { SpectrumWire } from "../core/types";
import { decodeArray, decodeComplexArray } from "../core/wire";

export interface SpectrumSummary {
  points: number;
  fMin: number;
  fMax: number;
  zMagMin: number;
  zMagMax: number;
}

export function summarizeSpectrum(spectrum: SpectrumWire): SpectrumSummary {
  const f = decodeArray(spectrum.f);
  const { re, im } = decodeComplexArray(spectrum.z);

  let fMin = Number.POSITIVE_INFINITY;
  let fMax = Number.NEGATIVE_INFINITY;
  let zMagMin = Number.POSITIVE_INFINITY;
  let zMagMax = Number.NEGATIVE_INFINITY;

  for (let i = 0; i < f.length; i += 1) {
    const fv = f[i] as number;
    if (fv < fMin) fMin = fv;
    if (fv > fMax) fMax = fv;
    const magnitude = Math.hypot(re[i] as number, im[i] as number);
    if (magnitude < zMagMin) zMagMin = magnitude;
    if (magnitude > zMagMax) zMagMax = magnitude;
  }

  return { points: f.length, fMin, fMax, zMagMin, zMagMax };
}
