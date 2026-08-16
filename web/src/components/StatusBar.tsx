// The four load stages the bridge client reports, then a discreet build line once ready. A cold
// start was measured at ~13 s in a browser -- Pyodide's own boot and the package import, not the
// download (`docs/WEB_UI_PLAN.md` section 2.3) -- so for a quarter of a minute this is the only
// thing on screen, and it must say what is happening rather than just spin.
//
// It also runs a clock, for the reason the search panel runs one: the stages move when a stage
// really finishes, and nothing here advances on a timer. A bar that fills itself would be a claim
// about progress this page cannot make, and would look exactly the same if the worker had died.

import { useEffect, useRef, useState } from "react";
import type { LoadStage } from "../worker/protocol";
import type { VersionsWire } from "../core/types";

const STAGE_LABELS: Record<LoadStage, string> = {
  booting: "Starting the Python runtime",
  packages: "Loading numpy and scipy",
  importing: "Loading AutoCircuit",
  ready: "Ready",
};

export interface StatusBarProps {
  stage: LoadStage;
  detail: string;
  versions: VersionsWire | null;
  bootError: string | null;
}

/** Seconds since the page started loading, ticking while `running` and frozen afterwards. */
function useElapsed(running: boolean): number {
  const started = useRef(performance.now());
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(
      () => setElapsed((performance.now() - started.current) / 1000),
      250,
    );
    return () => window.clearInterval(timer);
  }, [running]);
  return elapsed;
}

export function StatusBar({ stage, detail, versions, bootError }: StatusBarProps) {
  const elapsed = useElapsed(versions === null && bootError === null);

  if (bootError !== null) {
    return (
      <div className="status-bar status-bar--error" role="alert">
        Failed to start the Python runtime: {bootError}
      </div>
    );
  }

  if (versions === null) {
    const stages: LoadStage[] = ["booting", "packages", "importing", "ready"];
    return (
      <div className="status-bar status-bar--loading" role="status" aria-live="polite">
        <span className="status-bar__spinner" aria-hidden="true" />
        <span className="status-bar__detail">{detail || STAGE_LABELS[stage]}</span>
        <ol className="status-bar__steps">
          {stages.map((s) => (
            <li
              key={s}
              className={
                s === stage
                  ? "status-bar__step status-bar__step--current"
                  : stages.indexOf(s) < stages.indexOf(stage)
                    ? "status-bar__step status-bar__step--done"
                    : "status-bar__step"
              }
            >
              {STAGE_LABELS[s]}
            </li>
          ))}
        </ol>
        <span className="status-bar__elapsed">{elapsed.toFixed(1)} s</span>
      </div>
    );
  }

  // Nothing once it is ready. The four wire-format versions and the reader list used to live
  // here; they were a developer's diagnostic and a Data-screen answer respectively, shown on
  // every screen to everyone forever (docs/METRICS_AND_UX_PLAN.md section 3). The versions are
  // now a console line from `worker/client.ts` -- and the guard that actually protects anyone
  // from a stale build was never this text but `bridge.worker.ts`'s version check, which
  // refuses to run and says both numbers. The reader list moved to the drop zone, which is
  // where "what can I drop here?" is asked.
  return null;
}
