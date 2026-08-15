// Driving and displaying the "what did my skeleton exclude?" pass -- the same shape as
// `SearchProgressPanel` over `search.ts`, because `ExcludedRun` in `../core/excluded.ts` is
// itself the same shape as a search: a job that screens in batches, can be cancelled, and
// resolves with a report whose `summary` sentence already says how much of the space it stands
// for. This panel decides nothing about that; it only renders `progress` and `report` as given.
//
// The pass is expensive on purpose -- it screens a same-size slice of the topology space the
// search itself never looked at -- which is why it is opt-in rather than run automatically with
// every report.

import type { ExcludedReportWire } from "../core/types";
import type { ExcludedProgress, ExcludedStage } from "../core/excluded";

export interface ExcludedPanelProps {
  skeleton: string;
  /** The reported candidate the excluded topologies are screened against. */
  circuit: string;
  running: boolean;
  progress: ExcludedProgress;
  report: ExcludedReportWire | null;
  error: string | null;
  disabled: boolean;
  onStart: () => void;
  onCancel: () => void;
}

const STAGE_LABEL: Record<ExcludedStage, string> = {
  pool: "starting the workers",
  enumerating: "enumerating",
  screening: "screening",
  done: "finished",
  cancelled: "cancelled",
};

function Chips({ circuits }: { circuits: string[] }) {
  return (
    <p className="excluded-panel__chips">
      {circuits.map((circuit) => (
        <code className="excluded-panel__chip" key={circuit}>
          {circuit}
        </code>
      ))}
    </p>
  );
}

export function ExcludedPanel(props: ExcludedPanelProps) {
  const { skeleton, circuit, running, progress, report, error, disabled, onStart, onCancel } =
    props;

  return (
    <section className="excluded-panel">
      <h2 className="panel-title">What the skeleton excluded</h2>

      {error !== null && (
        <p className="excluded-panel__error" role="alert">
          {error}
        </p>
      )}

      {running ? (
        <div className="excluded-panel__running">
          <p className="excluded-panel__stage">
            {STAGE_LABEL[progress.stage]} — {(progress.elapsedMs / 1000).toFixed(1)} s elapsed
          </p>
          <p className="excluded-panel__counts">
            {progress.screened} of {progress.total} checked
          </p>
          {progress.equivalents.length > 0 && (
            <>
              <p className="excluded-panel__found-label">Equivalents found so far:</p>
              <Chips circuits={progress.equivalents} />
            </>
          )}
          <button type="button" className="excluded-panel__cancel" onClick={onCancel}>
            Cancel
          </button>
        </div>
      ) : report !== null ? (
        <div className="excluded-panel__report">
          <p
            className={
              report.partial ? "excluded-panel__summary discover-report__warning" : (
                "excluded-panel__summary"
              )
            }
          >
            {report.summary}
          </p>
          {report.equivalents.length === 0 ? (
            <p className="empty-hint">No excluded topology fit the reported model exactly.</p>
          ) : (
            <Chips circuits={report.equivalents} />
          )}
        </div>
      ) : (
        <div className="excluded-panel__idle">
          <p className="excluded-panel__description">
            This screens the topologies of this size that your skeleton, <code>{skeleton}</code>,
            excluded from the search — the ones never fitted — against <code>{circuit}</code>'s
            own fitted response, and names the ones that reproduce it exactly.
          </p>
          <p className="excluded-panel__cost-warning">
            This costs about as much as the search that produced the report: it screens a
            comparably large set of topologies, just the ones the skeleton left out.
          </p>
          <button
            type="button"
            className="excluded-panel__start"
            disabled={disabled}
            onClick={onStart}
          >
            Check what the skeleton excluded
          </button>
        </div>
      )}
    </section>
  );
}
