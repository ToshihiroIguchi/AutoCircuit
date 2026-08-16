// The load stages the bridge client reports. A cold start is seconds long, so for that whole
// time this is the only thing on screen, and it must say what is happening rather than just spin.
//
// It now tells a two-stage story, because the load is two stages: the page becomes able to read
// data before it becomes able to fit it (`docs/STARTUP_AND_EDITING_PLAN.md` section 3). The line
// says which of those has happened, and the second half stays visible -- quietly -- after the
// first, because a visitor who has just been told "you can load data now" is owed the reason the
// Fit tab is still greyed out.
//
// It also runs a clock, for the reason the search panel runs one: the stages move when a stage
// really finishes, and nothing here advances on a timer. A bar that fills itself would be a claim
// about progress this page cannot make, and would look exactly the same if the worker had died.

import { useEffect, useRef, useState } from "react";
import { DATA_STAGES, type LoadStage } from "../worker/protocol";

const STAGE_LABELS: Record<LoadStage, string> = {
  booting: "Starting the Python runtime",
  numpy: "Loading numpy",
  importing: "Loading AutoCircuit",
  data: "Ready to read data",
  scipy: "Loading scipy",
  fitting: "Loading the fitter",
  ready: "Ready",
};

/** The stages of the second half, in order. */
const FITTING_STAGES: readonly LoadStage[] = ["scipy", "fitting", "ready"];

export interface StatusBarProps {
  stage: LoadStage;
  detail: string;
  /** The page can read, trim, validate and plot. */
  dataReady: boolean;
  /** It can fit and search too. */
  ready: boolean;
  bootError: string | null;
  /** scipy or the fitter failed, which leaves the Data screen working; both are said. */
  runtimeError: string | null;
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

function Steps({ stages, stage }: { stages: readonly LoadStage[]; stage: LoadStage }) {
  const reached = stages.indexOf(stage);
  return (
    <ol className="status-bar__steps">
      {stages.map((s, index) => (
        <li
          key={s}
          className={
            s === stage
              ? "status-bar__step status-bar__step--current"
              : reached >= 0 && index < reached
                ? "status-bar__step status-bar__step--done"
                : "status-bar__step"
          }
        >
          {STAGE_LABELS[s]}
        </li>
      ))}
    </ol>
  );
}

export function StatusBar({
  stage,
  detail,
  dataReady,
  ready,
  bootError,
  runtimeError,
}: StatusBarProps) {
  const elapsed = useElapsed(!ready && bootError === null && runtimeError === null);

  if (bootError !== null) {
    return (
      <div className="status-bar status-bar--error" role="alert">
        Failed to start the Python runtime: {bootError}
      </div>
    );
  }

  if (runtimeError !== null) {
    return (
      <div className="status-bar status-bar--error" role="alert">
        Data loading works, but the fitter did not load: {runtimeError}
      </div>
    );
  }

  if (!dataReady) {
    return (
      <div className="status-bar status-bar--loading" role="status" aria-live="polite">
        <span className="status-bar__spinner" aria-hidden="true" />
        <span className="status-bar__detail">{detail || STAGE_LABELS[stage]}</span>
        <Steps stages={DATA_STAGES} stage={stage} />
        <span className="status-bar__elapsed">{elapsed.toFixed(1)} s</span>
      </div>
    );
  }

  if (!ready) {
    // Quieter than the first half: the page is usable now, and this is about a tab that is not.
    return (
      <div className="status-bar status-bar--second" role="status" aria-live="polite">
        <span className="status-bar__spinner" aria-hidden="true" />
        <span className="status-bar__detail">
          Data is ready. Fitting and search need scipy, still loading.
        </span>
        <Steps stages={FITTING_STAGES} stage={stage} />
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
