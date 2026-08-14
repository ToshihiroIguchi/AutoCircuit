// The shapes `autocircuit.web.bridge` sends back. These are transport records, not view models:
// a spectrum is held in exactly the form Python produced it so it can be handed back unaltered.

import type { WireArray, WireComplexArray, WireFloat } from "./wire";

/** How an edit addresses the circuit: a structural action at one position in the tree. */
export type EditAction = "series" | "parallel" | "replace" | "remove";

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

/** One parameter of one element type, as the registry describes it. */
export interface ElementParamWire {
  name: string;
  unit: string;
  log_scale: boolean;
  hard_lo: WireFloat;
  hard_hi: WireFloat;
}

/** One entry of the element catalogue the palette is built from. */
export interface ElementWire {
  code: string;
  name: string;
  complexity: WireFloat;
  spice_form: string;
  params: ElementParamWire[];
}

/** The whole catalogue: every element the core knows, and the pools it groups them into. */
export interface CatalogueWire {
  elements: ElementWire[];
  pools: Record<string, string[]>;
}

/** A node of the schematic. `path` is how an edit request addresses it -- see `edit` below. */
export type CircuitNodeWire =
  | { kind: "element"; path: number[]; code: string; label: string; name: string }
  | { kind: "series" | "parallel"; path: number[]; children: CircuitNodeWire[] };

/**
 * One fittable parameter of the current circuit.
 *
 * `lower`, `upper` and `start` are present only when the request carried a spectrum: they are
 * the interval the fitter would search and the value it would start from, both derived from the
 * data's own scale. They are not a guess at the device under test, which is why this fitter
 * asks for no initial values.
 */
export interface ParameterWire {
  name: string;
  label: string;
  code: string;
  param: string;
  unit: string;
  log_scale: boolean;
  hard_lo: WireFloat;
  hard_hi: WireFloat;
  lower?: WireFloat;
  upper?: WireFloat;
  start?: WireFloat;
}

/** A parsed circuit: what the canvas draws and what the parameter table lists. */
export interface CircuitWire {
  circuit: string;
  canonical: string;
  n_elements: number;
  n_params: number;
  complexity: WireFloat;
  tree: CircuitNodeWire;
  params: ParameterWire[];
}

/** A model curve for parameters that have not been fitted. */
export interface PreviewWire {
  circuit: string;
  z_model: WireComplexArray;
  values: Record<string, WireFloat>;
  relative_error: WireFloat;
}

/** `Statistics.to_wire()`: the part of a fit that says whether to believe it. */
export interface StatisticsWire {
  n_data: number;
  n_params: number;
  ssr: WireFloat;
  chi2_reduced: WireFloat;
  stderr: WireArray;
  correlation: WireArray;
  aic: WireFloat;
  aicc: WireFloat;
  bic: WireFloat;
  rank: number;
  warnings: string[];
}

/** `FitResult.to_wire()`, lossless: this is the transport record, not a report. */
export interface FitResultWire {
  version: number;
  circuit: string;
  values: WireArray;
  z_model: WireComplexArray;
  residuals: WireArray;
  statistics: StatisticsWire;
  weighting: string;
  success: boolean;
  message: string;
  n_restarts: number;
  restart_spread: Record<string, WireFloat>;
  fixed: Record<string, WireFloat>;
  elapsed_s: WireFloat;
}

/**
 * What the `fit` operation answers with.
 *
 * `residual_real` and `residual_imag` are the weighted residuals the fit minimised, split by
 * Python rather than here: their concatenation order is a detail of the objective function, and
 * a front end that assumed it would mis-plot silently if it ever changed.
 */
export interface FitWire {
  fit: FitResultWire;
  relative_error: WireFloat;
  residual_real: WireArray;
  residual_imag: WireArray;
  /** Non-identifiability and restart-spread warnings, worded as the CLI words them. */
  warnings: string[];
  /** The CLI's own report text, carried verbatim. */
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
