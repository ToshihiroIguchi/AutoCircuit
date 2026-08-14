// The message contract between the main thread and the Pyodide worker.
//
// The worker answers three things: "load yourself", "here are some bytes, put them in your
// filesystem", and "here is a request for the bridge". It makes no decisions -- which is the
// same rule the screening workers follow (docs/WEB_UI_PLAN.md section 2.1), for the same
// reason: anything JavaScript decides is a second implementation nobody tests.

import type { VersionsWire } from "../core/types";

/** Protocol version this bundle speaks; the worker refuses a core that answers differently. */
export const BRIDGE_VERSION = 2;

export type WorkerRequest =
  | { kind: "init"; id: number; pyodideUrl: string; indexUrl: string; archiveUrl: string }
  | { kind: "upload"; id: number; name: string; bytes: ArrayBuffer }
  | { kind: "call"; id: number; request: string };

export type LoadStage = "booting" | "packages" | "importing" | "ready";

export type WorkerResponse =
  | { kind: "status"; stage: LoadStage; detail: string }
  | { kind: "init"; id: number; versions: VersionsWire }
  | { kind: "upload"; id: number; path: string }
  | { kind: "call"; id: number; response: string }
  | { kind: "failed"; id: number; message: string };
