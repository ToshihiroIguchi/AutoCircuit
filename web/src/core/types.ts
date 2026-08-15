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

// -- The topology search ---------------------------------------------------------------------
//
// A search is the one thing the bridge holds state for, because it is a pair of generators that
// keep the enumeration and the shortlist quota between batches. These records are the batches
// going out and the results coming back; every decision behind them was taken in Python.

/** One screening job: the topology, and the cost above which its polish is not worth running. */
export type ScreenTaskWire = [circuit: string, abandonAbove: number | null];

/** One refit job: the topology, and the full-budget fit settings to run it with. */
export type RefitTaskWire = [circuit: string, restarts: number, seed: number];

/** How many topologies of each size the search is about to look at. */
export interface SearchLevelWire {
  n_elements: number;
  candidates: number;
}

/** What `discover_start` committed to, before anything is fitted. */
export interface SearchPlanWire {
  job: string;
  candidates: number;
  levels: SearchLevelWire[];
  limit: number;
  floor: number;
  pool: string[];
  skeleton: string | null;
  mode: string;
  screen_chunk: number;
  refit_chunk: number;
}

/** A batch of tier-1 work, with how far the screen has got. `tasks` is null when it is done. */
export interface ScreenStepWire {
  tasks: ScreenTaskWire[] | null;
  screened: number;
  total: number;
  /** Best-scoring topology so far, without its score -- a screening cost is not reportable. */
  best: string | null;
}

/** One candidate as a results row: what it is, how well it fits, what it cannot pin down. */
export interface CandidateRowWire {
  circuit: string;
  canonical: string;
  n_elements: number;
  n_params: number;
  complexity: WireFloat;
  aicc: WireFloat;
  chi2_reduced: WireFloat;
  n_unresolved: number;
  /** Parameters whose standard error exceeds their own value. */
  unresolved: string[];
}

/** A batch of tier-2 work, with the Pareto front of everything refitted so far. */
export interface RefitStepWire {
  tasks: RefitTaskWire[] | null;
  refitted: number;
  shortlisted: number;
  front: CandidateRowWire[];
}

/**
 * The finished -- or stopped -- search.
 *
 * `completeness` and `summary` are the CLI's own sentences and are rendered verbatim. What a
 * search is allowed to claim is the part of this report that matters most and the part a
 * paraphrase would quietly get wrong: `complete_up_to` describes the *screen*, and
 * `refit_progress`, when it is not null, says that the ranking below it is partial.
 */
export interface ReportWire {
  /** The search this is the report of; the report screen asks the same worker for more later. */
  job: string;
  /**
   * Every candidate, grouped by the response it produces -- singletons included.
   *
   * The grouping is the structure of the answer and not an annotation on it: two topologies in
   * one class are exact reparameterisations, and no impedance measurement can prefer one. It
   * arrives grouped rather than being reconstructed here from rows that happen to score alike.
   */
  equivalence_classes: string[][];
  /**
   * Asserted elements the fit could not pin down, or null when nothing was asserted.
   *
   * Null and `[]` say different things: null is "no skeleton", `[]` is "the data tested it".
   * [measured] A non-empty list is what a *wrong* skeleton looks like -- it leaves no trace in
   * the residuals or in chi² (`docs/PARTIAL_TOPOLOGY_PLAN.md` §3.2).
   */
  unsupported_assertion: string[] | null;
  /** Per front row, how many distinct places the skeleton sits in it; above one is ambiguous. */
  skeleton_placements: Record<string, number> | null;
  n_evaluated: number;
  complete_up_to: number | null;
  elapsed_s: WireFloat;
  pool: string[];
  mode: string;
  skeleton: string | null;
  refit_progress: [refitted: number, shortlisted: number] | null;
  stopped: boolean;
  completeness: string;
  summary: string;
  candidates: CandidateRowWire[];
  pareto: CandidateRowWire[];
  recommended: string | null;
  unresolved_everywhere: boolean;
}

// -- What a skeleton excluded -----------------------------------------------------------------
//
// A pass of the same shape as the search, over the topologies the skeleton removed from
// consideration: it is screened in batches, it can be stopped, and what it may claim afterwards
// depends on how much of it ran. That last property is the reason it exists at all.

/** What `excluded_start` committed to, before any of it is screened. */
export interface ExcludedStartWire extends ExcludedReportWire {
  /**
   * The spectrum every screen in this pass runs against.
   *
   * The reported candidate's *fitted* response, not the measured data: an exact
   * reparameterisation reaches a noise-free target to machine precision, which the sample's
   * noise would mask. Python chooses it; this side only carries it to the workers.
   */
  target: SpectrumWire;
}

/** A batch of the pass, with how far it has got and what it has found so far. */
export interface ExcludedStepWire {
  tasks: ScreenTaskWire[] | null;
  screened: number;
  total: number;
  equivalents: string[];
}

/** What the pass may claim, finished or stopped -- the difference is inside `summary`. */
export interface ExcludedReportWire {
  job: string;
  /** The search this pass is about. */
  search: string;
  /** The reported candidate whose response the excluded topologies were screened against. */
  circuit: string;
  skeleton: string;
  size: number;
  /** Topologies of that size containing the skeleton: the ones the search evaluated. */
  kept: number;
  /** Topologies of that size that do not, and were therefore never fitted. */
  excluded: number;
  /** How many of those were actually checked. Below `excluded` when the pass was stopped. */
  screened: number;
  partial: boolean;
  equivalents: string[];
  elapsed_s: WireFloat;
  finished: boolean;
  stopped: boolean;
  /** The CLI's sentence, verbatim; it says whether the pass was complete. */
  summary: string;
}

// -- The structure probe, and the files that leave the browser --------------------------------

/** One relaxation read off the distribution. */
export interface DrtPeakWire {
  tau: WireFloat;
  f_peak: WireFloat;
  weight: WireFloat;
  fwhm_decades: WireFloat;
  ideal_fwhm_decades: WireFloat;
  /** Wider than this inversion makes an ideal Debye peak: a distributed process, so try a CPE. */
  broadened: boolean;
}

/**
 * A distribution of relaxation times, as `DRTResult.to_wire()` writes it.
 *
 * Advisory, and never fed back into the search: a DRT peak count read off a regularised
 * inversion of noisy data must not be able to delete the right answer from a search that still
 * calls itself exhaustive (`docs/DISCOVERY_V2_PLAN.md` §3.4). Check `well_described` first --
 * a spectrum the Debye model cannot represent still produces peaks, and they mean nothing.
 */
export interface DrtWire {
  version: number;
  n_relaxations: number;
  well_described: boolean;
  r_inf: WireFloat;
  r_polarisation: WireFloat;
  inductance: WireFloat;
  capacitance: WireFloat;
  lam: WireFloat;
  lam_rule: string;
  max_residual: WireFloat;
  rms_residual: WireFloat;
  tau: WireArray;
  gamma: WireArray;
  peaks: DrtPeakWire[];
  z_fit: WireComplexArray;
  residual_real: WireArray;
  residual_imag: WireArray;
  /** The CLI's own advice lines, carried verbatim. */
  hints: string[];
  summary: string;
}

/** One downloadable file, rendered in Python by the code the command line writes it with. */
export interface ExportArtifactWire {
  filename: string;
  mime: string;
  content: string;
}

/** What build the worker is running; checked at start-up against what this bundle expects. */
export interface VersionsWire {
  bridge: number;
  fit: number;
  spectrum: number;
  validate: number;
  drt: number;
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
