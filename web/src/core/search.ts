// Driving the topology search from the main thread.
//
// The shape of this file is the whole architecture of the search in the browser: the
// orchestrator worker holds `autocircuit.web.job`, which yields batches of work, and this
// spreads each batch across a pool of workers and hands the answers back. It decides nothing.
// Which topologies exist, which of them earn a full-budget refit, what each screen's
// early-abandon threshold is, and what the run may claim afterwards are all decided in
// `autocircuit.core.discover` -- the same functions the command line drives
// (`docs/WEB_UI_PLAN.md` section 2.1).
//
// Two things here are not merely plumbing:
//
//  * **Progress comes from within a batch.** The plan hands out 64 screens at a time, which is
//    seconds of work; the pool reports each finished task, so the bar moves without the batch
//    size having to shrink. Shrinking it would change the search -- an abandon threshold one
//    batch stale is the one thing a driver's batching touches.
//  * **Cancelling terminates workers.** Pyodide is single-threaded, so a worker inside a
//    differential evolution never reads a "stop" message. The pool is destroyed and rebuilt,
//    and the report then says what coverage was actually reached rather than what was asked
//    for.

import type {
  CandidateRowWire,
  EvolveOutcomeWire,
  EvolveTaskWire,
  ReportWire,
  SearchLevelWire,
  SearchPlanWire,
  SpectrumWire,
} from "./types";
import type { BridgeClient, SearchOptions } from "../worker/client";
import { PoolAborted, SearchPool } from "../worker/pool";

export type SearchStage =
  | "pool"
  | "enumerating"
  | "screening"
  | "refitting"
  | "evolving"
  | "reporting"
  | "done"
  | "cancelled";

/** Everything the job screen draws while a search is running. */
export interface SearchProgress {
  stage: SearchStage;
  plan: SearchPlanWire | null;
  /** Workers up, of the pool size asked for; only meaningful during `pool`. */
  workersReady: number;
  screened: number;
  toScreen: number;
  /** Best-scoring topology so far. Deliberately without its score: a screen is not reportable. */
  best: string | null;
  refitted: number;
  shortlisted: number;
  /** The Pareto front of everything refitted so far, straight from the plan. */
  front: CandidateRowWire[];
  /**
   * True once the search is on its second pass, over a pool the spectrum asked to widen.
   *
   * `screened` and `toScreen` both restart there, because it is a second, larger space. A bar
   * that went backwards without saying why would read as a bug rather than as the search
   * finding out that the data needs an element the default pool does not have.
   */
  widened: boolean;
  /** The pool being searched right now, which is not the one the plan started with if widened. */
  pool: string[];
  /** Per-size counts for the space being screened now; empty until the first batch lands. */
  levels: SearchLevelWire[];
  elapsedMs: number;
}

const IDLE: SearchProgress = {
  stage: "pool",
  plan: null,
  workersReady: 0,
  screened: 0,
  toScreen: 0,
  best: null,
  refitted: 0,
  shortlisted: 0,
  front: [],
  widened: false,
  pool: [],
  levels: [],
  elapsedMs: 0,
};

/** How often progress is pushed at the UI while a batch is in flight. */
const PROGRESS_INTERVAL_MS = 100;

/** A guard against a hang, not a statement about the search: it does at most two passes. */
const MAX_PASSES = 4;

export function idleProgress(): SearchProgress {
  return { ...IDLE };
}

/**
 * One run of the search, from enumeration to report.
 *
 * Construct, `run()`, and `cancel()` if the user asks. A cancelled run still resolves with a
 * report -- of what it reached -- because that is a result, not a failure.
 */
export class SearchRun {
  private state: SearchProgress = idleProgress();
  private started = Date.now();
  private lastEmit = 0;
  private job: string | null = null;
  private cancelled = false;

  constructor(
    private client: BridgeClient,
    private pool: SearchPool,
    private spectrum: SpectrumWire,
    private options: SearchOptions,
    private onProgress: (progress: SearchProgress) => void,
  ) {}

  /**
   * Run the search. Null means it was stopped before there was anything to report -- while the
   * pool was still starting, or before the space had been enumerated.
   */
  async run(): Promise<ReportWire | null> {
    this.started = Date.now();
    this.emit({ stage: "pool", workersReady: 0 }, true);
    await this.pool.ready();
    if (this.cancelled) return null;

    this.emit({ stage: "enumerating" }, true);
    const plan = await this.client.discoverStart(this.spectrum, this.options);
    const job = (this.job = plan.job);
    this.emit({ stage: "screening", plan, toScreen: plan.candidates }, true);

    try {
      // Up to a few passes, and which it is comes from the search rather than from a count
      // kept here: under a derived pool the completed tier-2 fit is the evidence `choose_pool`
      // reads, so tier 2 running out is not necessarily the end -- and the same completed fit
      // is what `_is_underfitted` reads for the genetic fallback, the search's other escalation
      // past plain exhaustive search. `MAX_PASSES` is a guard against a bug on either side
      // turning into a hang, not a statement about the search.
      for (let pass = 0; pass < MAX_PASSES; pass += 1) {
        await this.screen(job);
        if (this.cancelled) break;
        const step = await this.refit(job);
        if (this.cancelled) break;
        if (step.evolve) {
          // Tier 1 of the fallback, then loop back: `screen` no-ops (nothing left to screen)
          // and `refit` now answers from the fallback's own shortlist instead, the same way it
          // already does after a pool widening -- one tier-2 driving loop, not two.
          await this.evolve(job);
          if (this.cancelled) break;
          this.emit({ stage: "screening" }, true);
          continue;
        }
        if (!step.more) break;
        this.emit({ stage: "screening" }, true);
      }
    } catch (error) {
      // A pool torn down under a running batch is how cancelling works, not a failure.
      if (!(error instanceof PoolAborted) && !this.cancelled) throw error;
    }
    return this.report(job);
  }

  /**
   * Ask the search to stop, and make it stop.
   *
   * Both halves are needed: the Python side stops handing out batches, and the workers already
   * fitting are terminated, because nothing else interrupts them.
   */
  async cancel(): Promise<void> {
    if (this.cancelled) return;
    this.cancelled = true;
    const job = this.job;
    this.pool.abort();
    if (job !== null) {
      try {
        await this.client.discoverCancel(job);
      } catch {
        // The report is still the source of truth about what was reached; if the orchestrator
        // cannot be told, it will be asked instead.
      }
    }
    this.emit({ stage: "cancelled" }, true);
  }

  private async screen(job: string): Promise<void> {
    let costs: Array<number | null> | null = null;
    for (;;) {
      const step = await this.client.discoverScreen(job, costs);
      this.emit(
        {
          screened: step.screened,
          toScreen: step.total,
          best: step.best,
          widened: step.widened,
          pool: step.pool,
          levels: step.levels ?? [],
        },
        true,
      );
      const tasks = step.tasks;
      if (tasks === null || this.cancelled) return;
      const base = step.screened;
      costs = await this.pool.map(
        tasks.length,
        (client, index) => {
          const [circuit, abandonAbove] = tasks[index] as [string, number | null];
          return client.screenTask(this.spectrum, circuit, abandonAbove, this.options);
        },
        (completed) => this.emit({ screened: base + completed }),
      );
      if (this.cancelled) return;
    }
  }

  /**
   * Runs tier 2 to its end.
   *
   * `more` is true when the search has another pass to do after it; `evolve` says which kind --
   * true means the next thing to drive is the genetic fallback's own tier 1 (`evolve` below),
   * false means it is a pool widening (loop back to `screen`).
   */
  private async refit(job: string): Promise<{ more: boolean; evolve: boolean }> {
    let results: Array<Awaited<ReturnType<BridgeClient["refitTask"]>>> | null = null;
    this.emit({ stage: "refitting" }, true);
    for (;;) {
      const step = await this.client.discoverRefit(job, results);
      this.emit(
        { refitted: step.refitted, shortlisted: step.shortlisted, front: step.front },
        true,
      );
      const tasks = step.tasks;
      if (tasks === null) {
        return { more: step.more && !this.cancelled, evolve: step.evolve && !this.cancelled };
      }
      if (this.cancelled) return { more: false, evolve: false };
      const base = step.refitted;
      results = await this.pool.map(
        tasks.length,
        (client, index) =>
          client.refitTask(this.spectrum, tasks[index] as [string, number, number], this.options),
        (completed) => this.emit({ refitted: base + completed }),
      );
      if (this.cancelled) return { more: false, evolve: false };
    }
  }

  /**
   * Runs the genetic fallback's own tier 1 to its end, one offspring per round trip through
   * the worker pool -- the same shape `screen` fans a batch across, calling `evolveTask`
   * instead of `screenTask`. Its own tier 2 is not driven here: once tier 1 finishes, the next
   * `refit` call answers from the fallback's own shortlist instead.
   */
  private async evolve(job: string): Promise<void> {
    let outcomes: EvolveOutcomeWire[] | null = null;
    this.emit({ stage: "evolving" }, true);
    for (;;) {
      const step = await this.client.discoverEvolve(job, outcomes);
      const tasks = step.tasks;
      if (tasks === null || this.cancelled) return;
      outcomes = await this.pool.map(tasks.length, (client, index) =>
        client.evolveTask(this.spectrum, tasks[index] as EvolveTaskWire, this.options),
      );
      if (this.cancelled) return;
    }
  }

  private async report(job: string): Promise<ReportWire> {
    this.emit({ stage: "reporting" }, true);
    const report = await this.client.discoverReport(job);
    this.emit({ stage: this.cancelled ? "cancelled" : "done", front: report.pareto }, true);
    return report;
  }

  private emit(change: Partial<SearchProgress>, force = false): void {
    this.state = { ...this.state, ...change, elapsedMs: Date.now() - this.started };
    const now = Date.now();
    if (!force && now - this.lastEmit < PROGRESS_INTERVAL_MS) return;
    this.lastEmit = now;
    this.onProgress(this.state);
  }
}
