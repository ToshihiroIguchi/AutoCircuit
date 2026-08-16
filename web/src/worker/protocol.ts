// The message contract between the main thread and the Pyodide worker.
//
// The worker answers three things: "load yourself", "here are some bytes, put them in your
// filesystem", and "here is a request for the bridge". It makes no decisions -- which is the
// same rule the screening workers follow (docs/WEB_UI_PLAN.md section 2.1), for the same
// reason: anything JavaScript decides is a second implementation nobody tests.

import type { VersionsWire } from "../core/types";

/** Protocol version this bundle speaks; the worker refuses a core that answers differently. */
export const BRIDGE_VERSION = 6;

export type WorkerRequest =
  | {
      kind: "init";
      id: number;
      pyodideUrl: string;
      indexUrl: string;
      archiveUrl: string;
      bytecodeUrl: string;
    }
  | { kind: "upload"; id: number; name: string; bytes: ArrayBuffer }
  | { kind: "call"; id: number; request: string };

export type LoadStage = "booting" | "packages" | "importing" | "ready";

/**
 * What each load stage cost, in milliseconds, measured inside the worker.
 *
 * Reported rather than kept private because the cold start is a gate (W3) and because a number
 * a visitor can read off their own machine is the only kind this project can collect: the
 * stages are 3-5x slower in a browser than under Node (`docs/WEB_UI_PLAN.md` section 2.3), so
 * one machine's breakdown settles nothing on its own.
 */
export interface LoadTimings {
  /** Starting the interpreter: fetching the wasm, instantiating it, importing the stdlib. */
  boot: number;
  /** Installing the numpy and scipy wheels. */
  packages: number;
  /** Unpacking the bytecode overlay and the package archive into the worker's filesystem. */
  unpack: number;
  /** `import autocircuit.web`, which pulls numpy and scipy in with it. */
  importing: number;
}

export type WorkerResponse =
  | { kind: "status"; stage: LoadStage; detail: string }
  | { kind: "init"; id: number; versions: VersionsWire; timings: LoadTimings }
  | { kind: "upload"; id: number; path: string }
  | { kind: "call"; id: number; response: string }
  | { kind: "failed"; id: number; message: string };
