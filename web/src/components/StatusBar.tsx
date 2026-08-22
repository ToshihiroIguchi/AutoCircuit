// The load stages the bridge client reports, and the only thing on the page that says the page is
// not ready yet.
//
// It tells a two-stage story, because the load is two stages: the page becomes able to read data
// before it becomes able to fit it (`docs/STARTUP_AND_EDITING_PLAN.md` section 3). The line says
// which of those has happened, and the second half stays visible -- quietly -- after the first,
// because a visitor who has just been told "you can load data now" is owed the reason the Fit tab
// is still greyed out.
//
// **It is loud for the first stage, and that is a correction rather than a style.** This used to
// render as eleven-point grey text in the page header, beside the title and next to the theme
// toggle, while the whole application underneath it was already painted: tabs, drop zone, and five
// blue Load buttons, none of which could do anything yet. [measured] From GitHub Pages with an
// empty cache the first stage takes 22.3 s and the second finishes at 28.5 s -- 19.4 s of that is
// the wasm and stdlib download alone -- while a reload with a warm cache is 0.78 s and 2.30 s. So
// the honest description of the old arrangement is half a minute of a finished-looking page whose
// only disclaimer was a caption. It now sits in the content column, above the screen, at the size
// of something that is meant to be read.
//
// Three rules it keeps:
//
//  * **No progress bar.** The stages move when a stage really finishes and nothing here advances
//    on a timer. A bar that filled itself would be a claim about progress this page cannot make,
//    and would look exactly the same if the worker had died. The clock is the honest version of
//    the same reassurance.
//  * **An expected duration, because that is the actual question.** "Is it stuck?" is answerable
//    from the measurement above and unanswerable from a spinner, so the measurement is printed.
//  * **The end is announced.** The bar used to vanish, which made the transition from "not ready"
//    to "ready" the disappearance of the only thing that had been saying so. It now says Ready and
//    then removes itself.

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

/** How long the finished line stays before removing itself. */
const READY_LINGER_MS = 4000;

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

/**
 * True for a few seconds after `ready` first goes true, so the finish can be seen happening.
 *
 * Someone who was not watching at that moment gets nothing, which is the right amount: by then the
 * page is working and has no news.
 */
function useJustFinished(ready: boolean): boolean {
  const [showing, setShowing] = useState(false);
  const announced = useRef(false);
  useEffect(() => {
    if (!ready || announced.current) return;
    announced.current = true;
    setShowing(true);
    const timer = window.setTimeout(() => setShowing(false), READY_LINGER_MS);
    return () => window.clearTimeout(timer);
  }, [ready]);
  return showing;
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
  const justFinished = useJustFinished(ready);

  if (bootError !== null) {
    return (
      <div className="status-bar status-bar--error" role="alert">
        <p className="status-bar__headline">
          <strong>Failed to start the Python runtime.</strong> {bootError}
        </p>
      </div>
    );
  }

  if (runtimeError !== null) {
    return (
      <div className="status-bar status-bar--error" role="alert">
        <p className="status-bar__headline">
          <strong>The fitter did not load.</strong> Reading, plotting and the Kramers-Kronig check
          still work; fitting and search do not. {runtimeError}
        </p>
      </div>
    );
  }

  if (!dataReady) {
    return (
      <div className="status-bar status-bar--first" role="status" aria-live="polite">
        <p className="status-bar__headline">
          <span className="status-bar__spinner" aria-hidden="true" />
          <strong>Loading AutoCircuit — the page is not ready yet.</strong>
          <span className="status-bar__elapsed">{elapsed.toFixed(1)} s</span>
        </p>
        <Steps stages={DATA_STAGES} stage={stage} />
        <p className="status-bar__detail">{detail || STAGE_LABELS[stage]}</p>
        <p className="status-bar__note">
          A first visit downloads the Python runtime and its libraries — about 40 MB, and 20–30 s
          on a normal connection. Later visits load from the browser cache and take a couple of
          seconds. Nothing below is live until this line says so, but you can pick files now: they
          are read the moment the reader is up.
        </p>
      </div>
    );
  }

  if (!ready) {
    // Quieter than the first half: the page is usable now, and this is about a tab that is not.
    return (
      <div className="status-bar status-bar--second" role="status" aria-live="polite">
        <p className="status-bar__headline">
          <span className="status-bar__spinner" aria-hidden="true" />
          <strong>Data is ready.</strong> Fitting and search need scipy, still loading — the Fit,
          Discover and Report tabs come alive when this line says Ready.
          <span className="status-bar__elapsed">{elapsed.toFixed(1)} s</span>
        </p>
        <Steps stages={FITTING_STAGES} stage={stage} />
      </div>
    );
  }

  if (justFinished) {
    return (
      <div className="status-bar status-bar--done" role="status" aria-live="polite">
        <p className="status-bar__headline">
          <strong>Ready.</strong> Everything on this page is live.
          <span className="status-bar__elapsed">{elapsed.toFixed(1)} s</span>
        </p>
      </div>
    );
  }

  // Nothing once the finish has been announced. The four wire-format versions and the reader list
  // used to live here; they were a developer's diagnostic and a Data-screen answer respectively,
  // shown on every screen to everyone forever (docs/METRICS_AND_UX_PLAN.md section 3). The
  // versions are now a console line from `worker/client.ts` -- and the guard that actually
  // protects anyone from a stale build was never this text but `bridge.worker.ts`'s version
  // check, which refuses to run and says both numbers. The reader list moved to the drop zone,
  // which is where "what can I drop here?" is asked.
  return null;
}
