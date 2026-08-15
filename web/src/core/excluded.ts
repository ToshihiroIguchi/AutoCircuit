// Driving the "what did my skeleton exclude?" pass from the main thread.
//
// The same shape as `search.ts`, deliberately: the orchestrator holds a generator that yields
// batches of screening work, this fans them across the same pool, and it decides nothing. Which
// topologies the skeleton excluded, what response they are judged against, how exact "exact" is,
// and what a stopped pass may then claim are all `autocircuit.core.discover.excluded_plan`'s
// (`docs/WEB_UI_PLAN.md` §2.6).
//
// Two things are worth knowing before changing anything here.
//
//  * **The screens do not run against the measured data.** They run against `target`, the
//    reported model's own fitted response, which the orchestrator hands back when the pass
//    opens. An exact reparameterisation reaches a noise-free target to machine precision; the
//    sample's noise would hide exactly the equivalence this pass exists to find.
//  * **A pass that is stopped has to claim less, and it says so itself.** The report carries
//    `screened` against `excluded`, and its `summary` sentence changes accordingly, so nothing
//    here needs to decide how to word a partial answer.

import type { ExcludedReportWire, SpectrumWire } from "./types";
import type { BridgeClient, SearchOptions } from "../worker/client";
import { PoolAborted, SearchPool } from "../worker/pool";

export type ExcludedStage = "pool" | "enumerating" | "screening" | "done" | "cancelled";

/** Everything the panel draws while the pass is running. */
export interface ExcludedProgress {
  stage: ExcludedStage;
  workersReady: number;
  screened: number;
  /** Topologies the skeleton excluded: the size of the whole pass. */
  total: number;
  /** Excluded topologies found so far to fit the reported model exactly. */
  equivalents: string[];
  elapsedMs: number;
}

const IDLE: ExcludedProgress = {
  stage: "pool",
  workersReady: 0,
  screened: 0,
  total: 0,
  equivalents: [],
  elapsedMs: 0,
};

/** How often progress is pushed at the UI while a batch is in flight. */
const PROGRESS_INTERVAL_MS = 100;

export function idleExcluded(): ExcludedProgress {
  return { ...IDLE };
}

/**
 * One run of the excluded-equivalents pass.
 *
 * Construct, `run()`, and `cancel()` if the user asks. A cancelled pass still resolves with a
 * report -- of what it checked -- because that is a result, and the sentence in it says how much
 * of the space it stands for.
 */
export class ExcludedRun {
  private state: ExcludedProgress = idleExcluded();
  private started = Date.now();
  private lastEmit = 0;
  private job: string | null = null;
  private target: SpectrumWire | null = null;
  private cancelled = false;

  constructor(
    private client: BridgeClient,
    private pool: SearchPool,
    /** The finished search this pass is about. It stays alive in the orchestrator. */
    private search: string,
    /** Which reported candidate to screen against; null means the recommended one. */
    private circuit: string | null,
    private options: SearchOptions,
    private onProgress: (progress: ExcludedProgress) => void,
  ) {}

  /** Run the pass. Null means it was stopped before there was anything to report. */
  async run(): Promise<ExcludedReportWire | null> {
    this.started = Date.now();
    this.emit({ stage: "pool", workersReady: 0 }, true);
    await this.pool.ready();
    if (this.cancelled) return null;

    this.emit({ stage: "enumerating" }, true);
    const start = await this.client.excludedStart(this.search, this.circuit);
    this.job = start.job;
    this.target = start.target;
    this.emit({ stage: "screening", total: start.excluded, screened: 0 }, true);

    try {
      await this.screen(start.job);
    } catch (error) {
      // A pool torn down under a running batch is how cancelling works, not a failure.
      if (!(error instanceof PoolAborted) && !this.cancelled) throw error;
    }
    const report = await this.client.excludedReport(start.job);
    this.emit(
      {
        stage: this.cancelled ? "cancelled" : "done",
        screened: report.screened,
        total: report.excluded,
        equivalents: report.equivalents,
      },
      true,
    );
    return report;
  }

  /**
   * Ask the pass to stop, and make it stop.
   *
   * Both halves again: Python stops handing out batches, and the workers already screening are
   * terminated, because a Pyodide worker inside a differential evolution reads no messages.
   */
  async cancel(): Promise<void> {
    if (this.cancelled) return;
    this.cancelled = true;
    const job = this.job;
    this.pool.abort();
    if (job !== null) {
      try {
        await this.client.excludedCancel(job);
      } catch {
        // The report is still the source of truth about what was checked.
      }
    }
    this.emit({ stage: "cancelled" }, true);
  }

  private async screen(job: string): Promise<void> {
    const target = this.target;
    if (target === null) return;
    let costs: Array<number | null> | null = null;
    for (;;) {
      const step = await this.client.excludedScreen(job, costs);
      this.emit(
        { screened: step.screened, total: step.total, equivalents: step.equivalents },
        true,
      );
      const tasks = step.tasks;
      if (tasks === null || this.cancelled) return;
      const base = step.screened;
      costs = await this.pool.map(
        tasks.length,
        (client, index) => {
          const [circuit, abandonAbove] = tasks[index] as [string, number | null];
          return client.screenTask(target, circuit, abandonAbove, this.options);
        },
        (completed) => this.emit({ screened: base + completed }),
      );
      if (this.cancelled) return;
    }
  }

  private emit(change: Partial<ExcludedProgress>, force = false): void {
    this.state = { ...this.state, ...change, elapsedMs: Date.now() - this.started };
    const now = Date.now();
    if (!force && now - this.lastEmit < PROGRESS_INTERVAL_MS) return;
    this.lastEmit = now;
    this.onProgress(this.state);
  }
}
