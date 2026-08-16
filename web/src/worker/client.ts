// The main thread's handle on the Pyodide worker: one promise per request, and typed wrappers
// for the bridge operations. Nothing here interprets a payload -- a spectrum goes out exactly
// as it came in.

import type {
  CatalogueWire,
  CircuitWire,
  DrtWire,
  EditAction,
  ExcludedReportWire,
  ExcludedStartWire,
  ExcludedStepWire,
  ExportArtifactWire,
  FitResultWire,
  FitWire,
  PreviewWire,
  RefitStepWire,
  RefitTaskWire,
  ReportWire,
  ScreenStepWire,
  SearchPlanWire,
  SpectrumWire,
  ValidationWire,
  VersionsWire,
} from "../core/types";
import type { LoadStage, LoadTimings, WorkerRequest, WorkerResponse } from "./protocol";

/** A failure the Python side reported, as opposed to one the transport invented. */
export class BridgeError extends Error {
  constructor(
    message: string,
    readonly type: string,
  ) {
    super(message);
    this.name = "BridgeError";
  }
}

/**
 * What the parameters of a circuit are being judged against.
 *
 * The spectrum is what turns a topology into a search space: every bound and every starting
 * value below is derived from the measured frequency range and impedance magnitude. `fixed` and
 * `bounds` are the user's overrides, and they are sent with *every* call rather than stored,
 * because the bridge holds no state (see `autocircuit/web/bridge.py`).
 */
export interface CircuitContext {
  spectrum?: SpectrumWire;
  fixed?: Record<string, number>;
  bounds?: Record<string, [number, number]>;
}

/** One structural edit: an action at a position, and the element it adds where one is added. */
export interface EditRequest {
  circuit: string;
  path: number[];
  action: EditAction;
  code?: string;
  position?: "before" | "after";
}

/**
 * The knobs the topology search exposes. Every one of them is an argument `discover` has too.
 *
 * There is no screening-budget knob, and that is deliberate: reducing it for the browser is the
 * one economy measured to lose the truth while leaving the report looking healthy
 * (`docs/WEB_UI_PLAN.md` section 1). `exhaustiveLimit` is the honest lever -- it costs coverage,
 * which `complete_up_to` then reports.
 */
export interface SearchOptions {
  pool?: string[];
  skeleton?: string | null;
  exhaustiveLimit?: number;
  weighting?: string;
  seed?: number;
  restarts?: number;
  /**
   * Which model-selection rule ranks the candidates and draws the front.
   *
   * It travels with the search rather than being applied to the answer, because it also ranks
   * the tier-1 shortlist -- which topologies get a full-budget refit at all. Re-sorting a
   * finished report by another criterion would therefore be re-sorting a list whose members a
   * different criterion had chosen.
   */
  criterion?: string;
}

/** The knobs the DRT exposes. `undefined` for a series term means "decide from the data". */
export interface DrtOptions {
  pointsPerDecade?: number;
  seriesInductance?: boolean;
  seriesCapacitance?: boolean;
  regularisation?: number;
}

/** Which file to write. The same three the command line writes. */
export type ExportKind = "json" | "csv" | "netlist";

/** What goes into one. Every field has a command-line counterpart. */
export interface ExportOptions {
  /** Which candidate a discovery netlist is of; the recommended one by default. */
  circuit?: string;
  /** An excluded-equivalents pass to fold into the JSON report, when one has been run. */
  excluded?: string;
  top?: number;
  /** SPICE subcircuit name (`--subckt`). */
  name?: string;
  /** Ladder-synthesis accuracy target for fractional elements (`--spice-error`). */
  errorTarget?: number;
  /** What the data is called *to the user*; the worker's own path would mean nothing to them. */
  source?: string;
}

/** The knobs `fit` exposes. Every one of them is an argument the CLI has too. */
export interface FitOptions {
  weighting?: string;
  restarts?: number;
  seed?: number;
  time_limit?: number | null;
}

/** Drop the absent members so an omitted override is absent on the wire, not `undefined`. */
function wireContext(context: CircuitContext): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (context.spectrum !== undefined) out.spectrum = context.spectrum;
  if (context.fixed !== undefined) out.fixed = context.fixed;
  if (context.bounds !== undefined) out.bounds = context.bounds;
  return out;
}

type Pending = { resolve: (value: WorkerResponse) => void; reject: (reason: Error) => void };

/** How many clients this page has built, so a console line says which one it is about. */
let clientsBuilt = 0;

const seconds = (ms: number): string => `${(ms / 1000).toFixed(2)} s`;

/**
 * Put the load breakdown where anyone can read it.
 *
 * The cold start is a gate (W3) whose answer differs by machine and by browser, so a figure
 * measured here is worth more than any number this project could hard-code: it is the visitor's
 * own. One line per worker, at load only.
 */
function report(
  index: number,
  timings: LoadTimings & { total: number },
  versions: VersionsWire,
): void {
  const stages = [
    `boot ${seconds(timings.boot)}`,
    `packages ${seconds(timings.packages)}`,
    `unpack ${seconds(timings.unpack)}`,
    `import ${seconds(timings.importing)}`,
  ].join(", ");
  const whole = index === 0 ? ` — ${seconds(timings.total)} since navigation` : "";
  console.info(`AutoCircuit worker ${index} ready: ${stages}${whole}`);
  // The build numbers used to sit in the page header. They are a developer's diagnostic and
  // the diagnosis they support is already automatic and louder -- `bridge.worker.ts` refuses to
  // run against a core answering a different bridge version -- so they belong here, where
  // someone who has been *asked* for them can find them, rather than in the most valuable strip
  // of the page on every screen forever (docs/METRICS_AND_UX_PLAN.md section 3).
  if (index === 0) {
    console.info(
      `AutoCircuit build: bridge v${versions.bridge}, fit v${versions.fit}, ` +
        `spectrum v${versions.spectrum}, validate v${versions.validate}, drt v${versions.drt}`,
    );
  }
}

export class BridgeClient {
  private worker: Worker;
  private pending = new Map<number, Pending>();
  private nextId = 1;
  private readyPromise: Promise<VersionsWire> | null = null;
  /** What the load cost, once it has finished; null while it is still going on. */
  private loadTimings: (LoadTimings & { total: number }) | null = null;
  // The element catalogue is the one answer that cannot change while the page is open: it is
  // the registry the loaded core was built with.
  private cataloguePromise: Promise<CatalogueWire> | null = null;
  /** 0 for the page's own client; 1.. for the pool members built on the first search. */
  private readonly index = clientsBuilt++;

  constructor(private onStatus: (stage: LoadStage, detail: string) => void = () => {}) {
    this.worker = new Worker(new URL("./bridge.worker.ts", import.meta.url), { type: "module" });
    this.worker.onmessage = (event: MessageEvent<WorkerResponse>) => this.receive(event.data);
    this.worker.onerror = (event) => {
      const error = new Error(event.message || "the worker failed to start");
      for (const [, entry] of this.pending) entry.reject(error);
      this.pending.clear();
    };
  }

  /** Boot Pyodide and load the core. Safe to call repeatedly; the work happens once. */
  ready(): Promise<VersionsWire> {
    if (this.readyPromise === null) {
      // The Pyodide distribution and the source archive are served beside the app, so they are
      // located from its base URL rather than from the worker's own -- once Vite has hashed the
      // worker into assets/ its location says nothing about where public/ ended up.
      const base = new URL(import.meta.env.BASE_URL, self.location.href);
      this.readyPromise = this.send({
        kind: "init",
        id: 0,
        pyodideUrl: new URL("pyodide/pyodide.mjs", base).href,
        indexUrl: new URL("pyodide/", base).href,
        archiveUrl: new URL("autocircuit-src.zip", base).href,
        bytecodeUrl: new URL("pyodide-bytecode.zip", base).href,
      }).then((message) => {
        const { versions, timings } = message as { versions: VersionsWire; timings: LoadTimings };
        // `performance.now()` on this thread is measured from the navigation, so it is the whole
        // cold start and not just the worker's share of it -- which is what gate W3 asks about.
        this.loadTimings = { ...timings, total: performance.now() };
        report(this.index, this.loadTimings, versions);
        return versions;
      });
    }
    return this.readyPromise;
  }

  /** What this client's load cost, or null while it is still loading. */
  timings(): (LoadTimings & { total: number }) | null {
    return this.loadTimings;
  }

  /** Read one dropped file, returning every sweep it holds. */
  async readFile(file: File): Promise<SpectrumWire[]> {
    await this.ready();
    const bytes = await file.arrayBuffer();
    const uploaded = await this.send({ kind: "upload", id: 0, name: file.name, bytes }, [bytes]);
    const { path } = uploaded as { path: string };
    try {
      const result = await this.call<{ spectra: SpectrumWire[] }>({ op: "read", path });
      return result.spectra;
    } catch (error) {
      // A reader's diagnostic names the file it failed on, which on the command line is the path
      // the user typed and here is the scratch path the worker invented. The message is written
      // for the person reading it, so it gets their name back rather than being rewritten.
      if (error instanceof BridgeError) {
        throw new BridgeError(error.message.split(path).join(file.name), error.type);
      }
      throw error;
    }
  }

  /** Restrict a spectrum to a frequency window; either end may be left open. */
  async trim(
    spectrum: SpectrumWire,
    fMin: number | null,
    fMax: number | null,
  ): Promise<SpectrumWire> {
    const result = await this.call<{ spectrum: SpectrumWire }>({
      op: "trim",
      spectrum,
      f_min: fMin,
      f_max: fMax,
    });
    return result.spectrum;
  }

  /** The Lin-KK verdict on a spectrum. */
  async validate(spectrum: SpectrumWire): Promise<ValidationWire> {
    const result = await this.call<{ validation: ValidationWire }>({ op: "validate", spectrum });
    return result.validation;
  }

  /** Every element the core knows, and the named pools it groups them into. */
  async elements(): Promise<CatalogueWire> {
    if (this.cataloguePromise === null) {
      this.cataloguePromise = this.call<CatalogueWire>({ op: "elements" });
    }
    return this.cataloguePromise;
  }

  /** Parse a circuit string into the tree the canvas draws and the parameters it lists. */
  async circuit(circuit: string, context: CircuitContext = {}): Promise<CircuitWire> {
    return this.call<CircuitWire>({ op: "circuit", circuit, ...wireContext(context) });
  }

  /**
   * Apply one structural edit and get the circuit that results.
   *
   * The tree surgery happens in Python. This method carries a position and an action; it does
   * not know what a parallel block is, which is what keeps the browser from building a topology
   * the command line would read differently.
   */
  async edit(request: EditRequest, context: CircuitContext = {}): Promise<CircuitWire> {
    return this.call<CircuitWire>({ op: "edit", ...request, ...wireContext(context) });
  }

  /** The model curve for parameters that have not been fitted; missing ones take the fitter's
   *  own starting value. */
  async preview(
    circuit: string,
    values: Record<string, number>,
    context: CircuitContext = {},
  ): Promise<PreviewWire> {
    return this.call<PreviewWire>({ op: "preview", circuit, values, ...wireContext(context) });
  }

  /** Fit a known topology. No initial values are asked for, because none are needed. */
  async fitCircuit(circuit: string, options: FitOptions, context: CircuitContext = {}): Promise<FitWire> {
    return this.call<FitWire>({ op: "fit", circuit, ...options, ...wireContext(context) });
  }

  // -- The topology search ------------------------------------------------------------------
  //
  // Two roles, both served by this same class. The orchestrator answers `discover*`: it holds
  // the search and hands out batches. A pool worker answers `screenTask`/`refitTask`: one
  // topology in, one number or one fit out, and no state at all. Which role a client is in is
  // decided by whoever calls it, which is why a pool member is an ordinary BridgeClient.

  /** One tier-1 screen. `abandonAbove` of null is infinity: nothing to beat yet. */
  async screenTask(
    spectrum: SpectrumWire,
    circuit: string,
    abandonAbove: number | null,
    options: SearchOptions = {},
  ): Promise<number | null> {
    const result = await this.call<{ cost: number | null }>({
      op: "screen_task",
      spectrum,
      circuit,
      abandon_above: abandonAbove,
      weighting: options.weighting,
      seed: options.seed,
    });
    return result.cost;
  }

  /** One tier-2 refit, whole. Null means the topology could not be fitted, which is an answer. */
  async refitTask(
    spectrum: SpectrumWire,
    task: RefitTaskWire,
    options: SearchOptions = {},
  ): Promise<FitResultWire | null> {
    const [circuit, restarts, seed] = task;
    const result = await this.call<{ fit: FitResultWire | null }>({
      op: "refit_task",
      spectrum,
      circuit,
      restarts,
      seed,
      weighting: options.weighting,
    });
    return result.fit;
  }

  /** Enumerate the space and open both plans. Nothing is fitted yet. */
  async discoverStart(spectrum: SpectrumWire, options: SearchOptions): Promise<SearchPlanWire> {
    return this.call<SearchPlanWire>({
      op: "discover_start",
      spectrum,
      pool: options.pool,
      skeleton: options.skeleton,
      exhaustive_limit: options.exhaustiveLimit,
      weighting: options.weighting,
      seed: options.seed,
      restarts: options.restarts,
      criterion: options.criterion,
    });
  }

  /** Hand back the last batch's costs, take the next batch. */
  async discoverScreen(job: string, costs: Array<number | null> | null): Promise<ScreenStepWire> {
    return this.call<ScreenStepWire>({ op: "discover_screen", job, costs });
  }

  /** Hand back the last batch's fits, take the next batch and the front so far. */
  async discoverRefit(
    job: string,
    results: Array<FitResultWire | null> | null,
  ): Promise<RefitStepWire> {
    return this.call<RefitStepWire>({ op: "discover_refit", job, results });
  }

  /** The report, whether the search finished or was stopped. */
  async discoverReport(job: string): Promise<ReportWire> {
    return this.call<ReportWire>({ op: "discover_report", job });
  }

  /**
   * The fit behind one row of a finished search: the curve it drew and the residuals it minimised.
   *
   * Nothing is fitted by this call. Every reported row came from a tier-2 refit whose whole
   * `FitResult` the orchestrator still holds, so this is a hand-over rather than a computation --
   * which is what makes plotting a front row cost nothing (docs/SCREEN_STATE_PLAN.md §4). Omit
   * the circuit to ask for the recommended row.
   */
  async discoverCandidate(job: string, circuit?: string | null): Promise<FitWire> {
    return this.call<FitWire>({ op: "discover_candidate", job, circuit: circuit ?? null });
  }

  /** Stop handing out work. The report stays readable afterwards, and says it was stopped. */
  async discoverCancel(job: string): Promise<{ job: string; screened: number; refitted: number }> {
    return this.call({ op: "discover_cancel", job });
  }

  // -- What the skeleton excluded -------------------------------------------------------------
  //
  // The same two roles again. The pool workers answer `screenTask`, unchanged and unaware that
  // this is a different question -- what makes it a different question is the *target* the
  // orchestrator hands back here, which is the reported model's own fitted response.

  /** Enumerate what the skeleton excluded. Nothing is screened yet; the counts come first. */
  async excludedStart(job: string, circuit?: string | null): Promise<ExcludedStartWire> {
    return this.call<ExcludedStartWire>({ op: "excluded_start", job, circuit: circuit ?? null });
  }

  /** Hand back the last batch's costs, take the next batch. */
  async excludedScreen(job: string, costs: Array<number | null> | null): Promise<ExcludedStepWire> {
    return this.call<ExcludedStepWire>({ op: "excluded_screen", job, costs });
  }

  /** What the pass may claim, whether it finished or was stopped. */
  async excludedReport(job: string): Promise<ExcludedReportWire> {
    return this.call<ExcludedReportWire>({ op: "excluded_report", job });
  }

  /** Stop handing out work; the partial report stays readable and says it is partial. */
  async excludedCancel(job: string): Promise<{ job: string; screened: number; total: number }> {
    return this.call({ op: "excluded_cancel", job });
  }

  // -- Beside the search, and out of the browser -----------------------------------------------

  /** The distribution of relaxation times: advice printed beside a search, never fed into one. */
  async drt(spectrum: SpectrumWire, options: DrtOptions = {}): Promise<DrtWire> {
    const result = await this.call<{ drt: DrtWire }>({
      op: "drt",
      spectrum,
      points_per_decade: options.pointsPerDecade,
      series_inductance: options.seriesInductance,
      series_capacitance: options.seriesCapacitance,
      regularisation: options.regularisation,
    });
    return result.drt;
  }

  /**
   * One downloadable file describing a search this worker still holds.
   *
   * The text is written in Python by the same functions the command line writes it with, so a
   * file saved here is the file `--json`, `--csv` or `--spice` would have produced.
   */
  async exportDiscovery(
    job: string,
    kind: ExportKind,
    options: ExportOptions = {},
  ): Promise<ExportArtifactWire> {
    return this.call<ExportArtifactWire>({
      op: "export",
      kind,
      job,
      circuit: options.circuit,
      excluded: options.excluded,
      top: options.top,
      name: options.name,
      error_target: options.errorTarget,
    });
  }

  /** The same, for a fit the user drew themselves: the whole fit travels back to be rendered. */
  async exportFit(
    fit: FitResultWire,
    spectrum: SpectrumWire,
    kind: ExportKind,
    options: ExportOptions = {},
  ): Promise<ExportArtifactWire> {
    return this.call<ExportArtifactWire>({
      op: "export",
      kind,
      fit,
      spectrum,
      source: options.source,
      name: options.name,
      error_target: options.errorTarget,
    });
  }

  /**
   * Destroy the worker, whatever it is doing.
   *
   * The only way to stop a fit that is already running: Pyodide is single-threaded and a
   * differential evolution inside it does not check for messages. So a cancelled search
   * terminates its pool and builds a new one, at about 1.5 s and one copy of numpy and scipy
   * per worker. That is the price of a cancel button that actually cancels.
   */
  terminate(): void {
    this.worker.terminate();
    const stopped = new Error("the worker was terminated");
    for (const [, entry] of this.pending) entry.reject(stopped);
    this.pending.clear();
  }

  private async call<T>(request: object): Promise<T> {
    await this.ready();
    const message = await this.send({ kind: "call", id: 0, request: JSON.stringify(request) });
    const answer = JSON.parse((message as { response: string }).response);
    if (!answer.ok) throw new BridgeError(answer.error.message, answer.error.type);
    return answer.result as T;
  }

  private send(message: WorkerRequest, transfer: Transferable[] = []): Promise<WorkerResponse> {
    const id = this.nextId;
    this.nextId += 1;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ ...message, id }, transfer);
    });
  }

  private receive(message: WorkerResponse): void {
    if (message.kind === "status") {
      this.onStatus(message.stage, message.detail);
      return;
    }
    const entry = this.pending.get(message.id);
    if (entry === undefined) return;
    this.pending.delete(message.id);
    if (message.kind === "failed") entry.reject(new Error(message.message));
    else entry.resolve(message);
  }
}
