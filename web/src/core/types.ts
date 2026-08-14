// The shapes `autocircuit.web.bridge` sends back. These are transport records, not view models:
// a spectrum is held in exactly the form Python produced it so it can be handed back unaltered.

import type { WireArray, WireComplexArray, WireFloat } from "./wire";

/** One measured or simulated spectrum, as `Spectrum.to_wire()` writes it. */
export interface SpectrumWire {
  version: number;
  f: WireArray;
  z: WireComplexArray;
  metadata: Record<string, unknown>;
}

/** A Lin-KK verdict, as `KKResult.to_wire()` writes it. */
export interface ValidationWire {
  version: number;
  n_elements: number;
  mu: WireFloat;
  tau: WireArray;
  resistances: WireArray;
  r_ohm: WireFloat;
  inductance: WireFloat;
  capacitance: WireFloat;
  z_fit: WireComplexArray;
  residual_real: WireArray;
  residual_imag: WireArray;
  max_residual: WireFloat;
  rms_residual: WireFloat;
  runs_z: WireFloat;
  systematic: boolean;
  passed: boolean;
  residual_limit: WireFloat;
  /** The CLI's verdict text, carried verbatim so the UI never paraphrases the science. */
  summary: string;
}

/** What build the worker is running; checked at start-up against what this bundle expects. */
export interface VersionsWire {
  bridge: number;
  fit: number;
  spectrum: number;
  validate: number;
  formats: string[];
}

/** A spectrum the user has loaded, with the bookkeeping the UI adds around it. */
export interface LoadedSpectrum {
  /** Stable across trims, so a spectrum keeps its identity in the table when its window moves. */
  id: string;
  /** The file it came from, as the user named it. */
  label: string;
  /** As read, before any trimming. Kept so the window can be widened again. */
  original: SpectrumWire;
  /** What every other screen sees: `original` restricted to the current frequency window. */
  current: SpectrumWire;
  validation: ValidationWire | null;
  validationError: string | null;
  validating: boolean;
}
