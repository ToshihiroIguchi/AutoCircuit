// The message contract between the main thread and the Pyodide worker.
//
// The worker answers three things: "load yourself", "here are some bytes, put them in your
// filesystem", and "here is a request for the bridge". It makes no decisions -- which is the
// same rule the screening workers follow (docs/WEB_UI_PLAN.md section 2.1), for the same
// reason: anything JavaScript decides is a second implementation nobody tests.

import type { RuntimeWire, VersionsWire } from "../core/types";

/** Protocol version this bundle speaks; the worker refuses a core that answers differently. */
export const BRIDGE_VERSION = 11;

export type WorkerRequest =
  | {
      kind: "init";
      id: number;
      pyodideUrl: string;
      indexUrl: string;
      archiveUrl: string;
      /** The numpy bytecode overlay, applied in stage A; the scipy one in stage B. */
      numpyBytecodeUrl: string;
      scipyBytecodeUrl: string;
    }
  | { kind: "upload"; id: number; name: string; bytes: ArrayBuffer }
  | { kind: "call"; id: number; request: string };

/**
 * Where the load has got to.
 *
 * Two stages, and the names say which: `data` is the moment the page can read, trim, validate
 * and plot -- numpy only -- and `ready` is the moment it can fit and search, which needs scipy
 * (`docs/STARTUP_AND_EDITING_PLAN.md` section 3).
 */
export type LoadStage =
  | "booting"
  | "numpy"
  | "importing"
  | "data"
  | "scipy"
  | "fitting"
  | "ready";

/** The stages that are over once the Data screen is usable, in order. */
export const DATA_STAGES: readonly LoadStage[] = ["booting", "numpy", "importing", "data"];

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
  /** Installing the numpy wheel. */
  packages: number;
  /** Unpacking numpy's bytecode overlay and the package archive into the worker's filesystem. */
  unpack: number;
  /** `import autocircuit.web`, which is the data path and pulls in numpy but not scipy. */
  importing: number;
}

/** What the second stage cost: installing scipy, unpacking its overlay, importing the fitter. */
export interface RuntimeTimings {
  packages: number;
  unpack: number;
  importing: number;
}

export type WorkerResponse =
  | { kind: "status"; stage: LoadStage; detail: string }
  | { kind: "init"; id: number; versions: VersionsWire; timings: LoadTimings }
  // Both of these are broadcasts rather than answers: the second stage is started by the worker
  // when the first one lands, not asked for, so there is no request id to reply to.
  | { kind: "runtime"; runtime: RuntimeWire; timings: RuntimeTimings }
  | { kind: "runtime-failed"; message: string }
  | { kind: "upload"; id: number; path: string }
  | { kind: "call"; id: number; response: string }
  | { kind: "failed"; id: number; message: string };
