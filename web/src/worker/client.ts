// The main thread's handle on the Pyodide worker: one promise per request, and typed wrappers
// for the bridge operations. Nothing here interprets a payload -- a spectrum goes out exactly
// as it came in.

import type { SpectrumWire, ValidationWire, VersionsWire } from "../core/types";
import type { LoadStage, WorkerRequest, WorkerResponse } from "./protocol";

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

type Pending = { resolve: (value: WorkerResponse) => void; reject: (reason: Error) => void };

export class BridgeClient {
  private worker: Worker;
  private pending = new Map<number, Pending>();
  private nextId = 1;
  private readyPromise: Promise<VersionsWire> | null = null;

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
      }).then((message) => (message as { versions: VersionsWire }).versions);
    }
    return this.readyPromise;
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
