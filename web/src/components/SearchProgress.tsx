// What a running (or just-finished) search looks like while it is still a job, not a result:
// the stage, a bar for whichever tier is active, the counts the bar is drawn from, and the
// per-element-count plan so the user can see the size of what they asked for before it is done.
//
// Named `SearchProgressPanel` rather than `SearchProgress` because that name already belongs to
// the state type this component renders (`src/core/search.ts`); the file keeps the type's name
// since that is what it is a view of.

import { useEffect, useRef, useState } from "react";
import type { SearchProgress, SearchStage } from "../core/search";
import { ParetoTable } from "./ParetoTable";

export interface SearchProgressPanelProps {
  progress: SearchProgress;
  poolSize: number;
}

const STAGE_LABEL: Record<SearchStage, string> = {
  pool: "Starting the worker pool",
  enumerating: "Enumerating the topology space",
  screening: "Screening candidates",
  refitting: "Refitting the shortlist",
  reporting: "Assembling the report",
  done: "Finished",
  cancelled: "Cancelled",
};

function Bar({ done, total }: { done: number; total: number }) {
  const fraction = total > 0 ? Math.min(1, done / total) : 0;
  return (
    <div className="search-progress__bar" role="progressbar" aria-valuenow={done} aria-valuemax={total}>
      <div className="search-progress__bar-fill" style={{ width: `${fraction * 100}%` }} />
    </div>
  );
}

/**
 * A clock that keeps running between the search's own reports.
 *
 * [measured] The screen reports something new every second or so, but the refit does not and
 * cannot: one tier-2 fit is the smallest thing that can finish, and on the capacitor reference
 * the gap between two of them reached 8.6 s. Without a clock of its own the panel simply freezes
 * for that long, which is indistinguishable from a hung page. What ticks here is the elapsed
 * time and nothing else -- the counts and the front still only move when the search actually
 * knows more, because a progress bar that invents motion is worse than one that stops.
 */
function useLiveElapsed(progress: SearchProgress): number {
  const [now, setNow] = useState(() => Date.now());
  const received = useRef(Date.now());
  const shown = useRef(0);
  useEffect(() => {
    received.current = Date.now();
    setNow(Date.now());
  }, [progress]);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, []);
  // Monotone on purpose. The run stamps `elapsedMs` when it emits and React renders that some
  // time later, so a fresh report can be *behind* the clock extrapolated from the previous one
  // -- which showed up in the browser as the elapsed time stepping backwards by a second.
  shown.current = Math.max(shown.current, progress.elapsedMs + (now - received.current));
  return shown.current;
}

export function SearchProgressPanel({ progress, poolSize }: SearchProgressPanelProps) {
  const elapsedMs = useLiveElapsed(progress);

  if (progress.stage === "pool" && progress.plan === null) {
    // Nothing has been enumerated yet -- only the pool boot is worth a bar, and the run's own
    // state does not track that (it is the pool's own onStatus callback that does, upstream).
    return (
      <section className="search-progress">
        <p className="search-progress__stage">{STAGE_LABEL.pool}</p>
        <Bar done={progress.workersReady} total={poolSize} />
        <p className="search-progress__counts">
          {progress.workersReady} / {poolSize} workers ready
        </p>
      </section>
    );
  }

  return (
    <section className="search-progress">
      <p className="search-progress__stage">
        {STAGE_LABEL[progress.stage]} &mdash; {(elapsedMs / 1000).toFixed(1)} s elapsed
      </p>

      {progress.stage === "screening" && (
        <>
          <Bar done={progress.screened} total={progress.toScreen} />
          <p className="search-progress__counts">
            {progress.screened} / {progress.toScreen} screened
            {progress.best !== null && <> &mdash; best so far: <code>{progress.best}</code></>}
          </p>
        </>
      )}

      {(progress.stage === "refitting" || progress.stage === "reporting") && (
        <>
          <Bar done={progress.refitted} total={progress.shortlisted} />
          <p className="search-progress__counts">
            {progress.refitted} / {progress.shortlisted} shortlisted topologies refitted
          </p>
        </>
      )}

      {progress.plan !== null && (
        <table className="search-progress__levels">
          <thead>
            <tr>
              <th>Elements</th>
              <th className="num">Candidates</th>
            </tr>
          </thead>
          <tbody>
            {progress.plan.levels.map((level) => (
              <tr key={level.n_elements}>
                <td>{level.n_elements}</td>
                <td className="num">{level.candidates}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {progress.front.length > 0 && (
        <ParetoTable title="Pareto front so far" rows={progress.front} />
      )}
    </section>
  );
}
