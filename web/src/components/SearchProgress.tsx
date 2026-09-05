// What a running (or just-finished) search looks like while it is still a job, not a result:
// the stage, a bar per tier, the counts the bars are drawn from, and the per-element-count plan
// so the user can see the size of what they asked for before it is done.
//
// Named `SearchProgressPanel` rather than `SearchProgress` because that name already belongs to
// the state type this component renders (`src/core/search.ts`); the file keeps the type's name
// since that is what it is a view of.
//
// **Every tier has its own bar, and all of them stay on screen.** [measured] One bar that changed
// what it was counting reported a regression twice per run: it filled to ~97% screening 66
// candidates, then restarted at 0/31 for the refit, having earlier restarted once already after
// the worker pool came up (`docs/SCREEN_STATE_PLAN.md` §2). The bars are not merged into one
// instead, because the honest denominator for a merged bar does not exist: the shortlist size is
// unknown until screening ends, and a tier-2 refit costs three orders of magnitude more than a
// tier-1 screen, so any single percentage would be a fabricated weighting. Three counters that
// each only rise say the same thing without inventing anything.

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
  // Reached only when the best exhaustive fit still looks underfit and there is element
  // budget left -- the same escalation `discover(mode="auto")` makes on the command line.
  evolving: "Falling back to a genetic search",
  reporting: "Assembling the report",
  done: "Finished",
  cancelled: "Cancelled",
};

/** How far through the run each tier is. Order is the order they happen in. */
const ORDER: SearchStage[] = [
  "pool",
  "enumerating",
  "screening",
  "refitting",
  "evolving",
  "reporting",
  "done",
];

/** Where a stage stands, which decides how its row is drawn and what it may claim. */
type RowState = "waiting" | "running" | "finished";

function stateOf(current: SearchStage, row: SearchStage): RowState {
  // A cancelled run never advances past what it reached, so no row is marked finished on the
  // strength of the run having moved on -- it did not move on, it stopped.
  if (current === "cancelled") return "waiting";
  const at = ORDER.indexOf(current);
  const mine = ORDER.indexOf(row);
  if (at > mine) return "finished";
  return at === mine ? "running" : "waiting";
}

function Row({
  step,
  label,
  state,
  done,
  total,
  unit,
  note,
}: {
  /** "Preparation", or "Stage 1 of 2". */
  step: string;
  label: string;
  state: RowState;
  done: number;
  /** Zero means not yet known, which is drawn as such rather than as a full or an empty bar. */
  total: number;
  unit: string;
  note?: React.ReactNode;
}) {
  const known = total > 0;
  // A finished stage is shown full. That is not rounding up: the tier ran to the end of its own
  // list, and `stateOf` refuses to call anything finished on a cancelled run.
  const shown = state === "finished" && known ? total : done;
  const fraction = known ? Math.min(1, shown / total) : 0;
  return (
    <div className={`search-progress__row search-progress__row--${state}`}>
      <p className="search-progress__row-head">
        <span className="search-progress__step">{step}</span>
        <span className="search-progress__label">{label}</span>
      </p>
      <div
        className="search-progress__bar"
        role="progressbar"
        aria-label={label}
        aria-valuenow={shown}
        aria-valuemax={known ? total : undefined}
      >
        <div className="search-progress__bar-fill" style={{ width: `${fraction * 100}%` }} />
      </div>
      <p className="search-progress__counts">
        {known ? (
          <>
            {shown} / {total} {unit}
          </>
        ) : state === "waiting" ? (
          <>not started — the count is known once the previous stage ends</>
        ) : (
          <>{unit}</>
        )}
        {note}
      </p>
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
  // `enumerating` and `reporting` have no counter of their own -- they are one call each -- so
  // they are named in the heading and fold into the neighbouring rows below.
  const screening = stateOf(progress.stage, "screening");
  const refitting = stateOf(progress.stage, "refitting");
  // The plan's breakdown until the first batch of a pass lands, and the pass's own after that:
  // a widening replaces the enumeration, and the old breakdown would describe a space nobody is
  // screening any more.
  const levels = progress.levels.length > 0 ? progress.levels : (progress.plan?.levels ?? []);

  return (
    <section className="search-progress">
      <p className="search-progress__stage">
        {STAGE_LABEL[progress.stage]} &mdash; {(elapsedMs / 1000).toFixed(1)} s elapsed
      </p>

      <Row
        step="Preparation"
        label="Worker pool"
        state={stateOf(progress.stage, "pool")}
        done={progress.workersReady}
        total={poolSize}
        unit="workers ready"
      />
      {progress.widened && (
        <p className="search-progress__widened">
          The default pool&rsquo;s own completed fit still left a systematic residual, so the
          search widened its pool to <code>{progress.pool.join(", ")}</code> and is screening the
          larger space. The counts below start again with it, and the report will say which
          element counts the wider pool could still cover.
        </p>
      )}

      <Row
        step="Stage 1 of 2"
        label="Screening candidates"
        state={screening}
        done={progress.screened}
        total={progress.toScreen}
        unit="screened"
        note={
          progress.best !== null && (
            <>
              {" "}
              &mdash; best so far: <code>{progress.best}</code>
            </>
          )
        }
      />
      <Row
        step="Stage 2 of 2"
        label="Refitting the shortlist"
        state={refitting}
        done={progress.refitted}
        total={progress.shortlisted}
        unit="shortlisted topologies refitted"
      />

      {levels.length > 0 && (
        <table className="search-progress__levels">
          <thead>
            <tr>
              <th>Elements</th>
              <th className="num">Candidates</th>
            </tr>
          </thead>
          <tbody>
            {levels.map((level) => (
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
