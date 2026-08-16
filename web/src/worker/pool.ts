// A pool of Pyodide workers that fit topologies, and nothing else.
//
// The orchestrator hands out batches (see `src/core/search.ts`); this spreads one batch across
// the workers and returns the answers in the order the batch asked for them. It holds no
// opinion about what to run, which is the same rule the rest of the front end follows: every
// decision in this search was made in `autocircuit.core.discover`.

import { BridgeClient } from "./client";
import type { LoadStage } from "./protocol";

/**
 * Workers to run.
 *
 * [measured] The speed-up saturates at four and eight workers were *slower* than six
 * (`benchmarks/pyodide`), and each costs ~1.5 s of start-up plus its own copy of numpy and
 * scipy, so this is a ceiling rather than a target.
 */
export const MAX_WORKERS = 4;

export function defaultPoolSize(): number {
  const cores = typeof navigator === "undefined" ? MAX_WORKERS : (navigator.hardwareConcurrency ?? MAX_WORKERS);
  return Math.max(1, Math.min(MAX_WORKERS, cores));
}

/** Thrown by anything still in flight when the pool is torn down. */
export class PoolAborted extends Error {
  constructor() {
    super("the search was cancelled");
    this.name = "PoolAborted";
  }
}

export class SearchPool {
  private clients: BridgeClient[] = [];
  private generation = 0;

  constructor(
    private size: number,
    private onStatus: (ready: number, total: number) => void = () => {},
  ) {}

  get workers(): number {
    return this.size;
  }

  /**
   * Bring the pool up, reporting each worker as it becomes usable.
   *
   * Started together rather than one at a time: they are independent, and the browser overlaps
   * four downloads-and-boots far better than it does four in sequence.
   *
   * `full()` and not `ready()`: these workers exist to fit topologies, so a worker whose second
   * load stage is still running is not one this pool may count. Reporting it as up would put a
   * "4 / 4 workers ready" beside a screen that is about to sit still while scipy installs.
   */
  async ready(): Promise<void> {
    if (this.clients.length === this.size) {
      await Promise.all(this.clients.map((client) => client.full()));
      return;
    }
    this.teardown();
    let up = 0;
    this.clients = Array.from({ length: this.size }, () => new BridgeClient(noStatus));
    await Promise.all(
      this.clients.map((client) =>
        client.full().then(() => {
          up += 1;
          this.onStatus(up, this.size);
        }),
      ),
    );
  }

  /**
   * Run one task per entry of `tasks`, at most one per worker at a time.
   *
   * `onDone` fires as each task lands, which is where the progress bar comes from: a batch of
   * 64 screens takes seconds, and waiting for the whole batch to report would leave the UI
   * still for all of it. The returned array is in the batch's order, because the plan matches
   * costs to tasks by position.
   */
  async map<T>(
    tasks: number,
    run: (client: BridgeClient, index: number) => Promise<T>,
    onDone: (completed: number) => void = () => {},
  ): Promise<T[]> {
    if (this.clients.length === 0) throw new PoolAborted();
    const generation = this.generation;
    const results = new Array<T>(tasks);
    let next = 0;
    let completed = 0;
    const worker = async (client: BridgeClient): Promise<void> => {
      while (next < tasks) {
        const index = next;
        next += 1;
        results[index] = await run(client, index);
        if (this.generation !== generation) throw new PoolAborted();
        completed += 1;
        onDone(completed);
      }
    };
    await Promise.all(this.clients.map((client) => worker(client)));
    return results;
  }

  /**
   * Destroy every worker, stopping the fits they are running.
   *
   * Terminating is the only way: Pyodide is single-threaded, so a worker inside a differential
   * evolution never reads the message that would ask it to stop. Anything in flight rejects
   * with `PoolAborted`, and the next `ready()` builds a fresh pool.
   */
  abort(): void {
    this.generation += 1;
    this.teardown();
  }

  private teardown(): void {
    for (const client of this.clients) client.terminate();
    this.clients = [];
  }
}

function noStatus(_stage: LoadStage, _detail: string): void {
  // A pool worker's own loading progress is not shown: four of them reporting at once says
  // nothing the aggregate count does not.
}
