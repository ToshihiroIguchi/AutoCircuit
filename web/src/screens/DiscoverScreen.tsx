// The Discover screen: press a button, wait minutes, get a Pareto front -- never a single
// answer. `docs/WEB_UI_PLAN.md` section 1 is why this screen is a job rather than a request: a
// real search takes minutes in the browser, so there is streamed progress and a cancel button
// instead of a spinner.
//
// Every decision behind the search -- which topologies exist, which earn a full-budget refit,
// what the run may claim afterwards -- was made in Python (`autocircuit.core.discover`, driven
// through `autocircuit.web.job`). This screen and `SearchRun` only move batches and draw what
// comes back.

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  CatalogueWire,
  CriterionWire,
  LoadedSpectrum,
  ReportWire,
} from "../core/types";
import { idleProgress, SearchRun, type SearchProgress } from "../core/search";
import { BridgeClient, BridgeError, type SearchOptions } from "../worker/client";
import { defaultPoolSize } from "../worker/pool";
import type { SearchPool } from "../worker/pool";
import { CircuitPreview } from "../components/CircuitPreview";
import { ParetoTable } from "../components/ParetoTable";
import { SearchPanel } from "../components/SearchPanel";
import { SearchProgressPanel } from "../components/SearchProgress";
import { RuntimeNotice } from "../components/RuntimeNotice";

export interface DiscoverScreenProps {
  client: BridgeClient;
  ready: boolean;
  spectrum: LoadedSpectrum | null;
  /** The circuit currently drawn on the Fit screen, or null/empty if there isn't one. */
  skeleton: string | null;
  /**
   * The page's one worker pool, built on first use and kept afterwards.
   *
   * Held by `App` rather than here because the Report screen runs work on it too -- the
   * excluded-equivalents pass is a continuation of this search -- and two pools would mean eight
   * Pyodide workers on a machine where the speed-up already saturates at four.
   */
  acquirePool: (workers: number, onStatus: (ready: number, total: number) => void) => SearchPool;
  /**
   * What to search with, and how to change it.
   *
   * Owned by `App` for the same reason everything else there is: a screen is unmounted when the
   * user visits another tab, so settings kept here would silently return to their defaults
   * between one search and the next. [browser] That is not hypothetical -- it produced an
   * unconstrained four-element run from a form that had said three and a skeleton.
   */
  settings: SearchSettings;
  onSettings: (change: Partial<SearchSettings>) => void;
  /** The model-selection menu the loaded core offers; empty until the worker is ready. */
  criteria: CriterionWire[];
  /** A finished search, for the Report screen. Null while one is running, or after a cancel. */
  onReport: (
    discovery: { report: ReportWire; options: SearchOptions; workers: number } | null,
  ) => void;
  /**
   * Take one of these topologies over to the Fit screen.
   *
   * **The topology, and not the fit.** The discovered parameter values are not carried across
   * as a starting guess, because this fitter has none: pressing Fit there re-runs the same
   * global search from the same data-derived interval and lands in the same place. Carrying
   * numbers over would make a screen that says "these do not seed the fit" look as though they
   * did (docs/METRICS_AND_UX_PLAN.md section 6).
   */
  onFitCircuit: (circuit: string) => void;
}

/** Everything the search panel holds. Every field is an argument `discover` has too, except
 *  `workers`, which sizes the pool rather than the search. */
export interface SearchSettings {
  poolName: string;
  exhaustiveLimit: number;
  useSkeleton: boolean;
  workers: number;
  seed: number;
  weighting: string;
  /**
   * Which model-selection rule ranks the answer -- and the shortlist.
   *
   * A search setting, not a display option: it decides which topologies earn a full-budget
   * refit, so a finished report cannot be re-sorted into what another criterion would have
   * produced. The initial value here is a placeholder until the worker answers with the core's
   * own default (`App` adopts it); hard-coding a different one would be this file quietly
   * disagreeing with the CLI.
   */
  criterion: string;
}

export function defaultSearchSettings(): SearchSettings {
  return {
    poolName: "default",
    exhaustiveLimit: 4,
    useSkeleton: false,
    workers: defaultPoolSize(),
    seed: 0,
    weighting: "modulus",
    criterion: "aic",
  };
}

function errorMessage(error: unknown): string {
  return error instanceof BridgeError || error instanceof Error ? error.message : String(error);
}

export function DiscoverScreen({
  client,
  ready,
  spectrum,
  skeleton,
  acquirePool,
  settings,
  onSettings,
  criteria,
  onReport,
  onFitCircuit,
}: DiscoverScreenProps) {
  const { poolName, exhaustiveLimit, useSkeleton, workers, seed, weighting, criterion } = settings;
  const [catalogue, setCatalogue] = useState<CatalogueWire | null>(null);

  const [progress, setProgress] = useState<SearchProgress>(idleProgress());
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<ReportWire | null>(null);
  const [stoppedEarly, setStoppedEarly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Which front row is drawn above the table. Null until a report arrives, then the recommended
  // one -- the row this report is actually about.
  const [picked, setPicked] = useState<string | null>(null);

  // The pool is not built at page load: four more Pyodide workers, each ~1.5 s and its own copy
  // of numpy and scipy, would tax every visitor who never presses Discover, on top of the ~13 s
  // cold start the page already has (`docs/WEB_UI_PLAN.md` section 2.3). So it comes up on the
  // first Discover press and then stays up for the next one -- rebuilt only if the worker count
  // changes, since that is the one control that changes what the pool itself has to be. `App`
  // owns it, because the Report screen's excluded-equivalents pass runs on the same one.
  const runRef = useRef<SearchRun | null>(null);

  useEffect(() => {
    if (!ready) return;
    client.elements().then(setCatalogue).catch((err: unknown) => setError(errorMessage(err)));
  }, [client, ready]);

  const skeletonAvailable = skeleton !== null && skeleton.trim() !== "";
  useEffect(() => {
    if (!skeletonAvailable && useSkeleton) onSettings({ useSkeleton: false });
  }, [skeletonAvailable, useSkeleton, onSettings]);

  const startSearch = useCallback(async () => {
    if (spectrum === null || running) return;
    setError(null);
    setReport(null);
    // The old report is dropped as the new search starts, not when it finishes: the Report
    // screen must not show one search's classes beside another search's coverage claim.
    onReport(null);
    setStoppedEarly(false);
    setProgress(idleProgress());

    const pool = acquirePool(workers, (up) =>
      setProgress((prev) => ({ ...prev, workersReady: up })),
    );

    const options: SearchOptions = {
      pool: catalogue?.pools[poolName],
      skeleton: useSkeleton ? skeleton : null,
      exhaustiveLimit,
      weighting,
      seed,
      criterion,
    };

    const run = new SearchRun(client, pool, spectrum.current, options, setProgress);
    runRef.current = run;
    setRunning(true);
    try {
      const result = await run.run();
      // Null means cancel landed before the pool -- or the enumeration -- ever produced
      // anything to report, which is a real outcome and not the same as an empty search.
      if (result === null) setStoppedEarly(true);
      else {
        setReport(result);
        setPicked(result.recommended ?? result.pareto[0]?.circuit ?? null);
        onReport({ report: result, options, workers });
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRunning(false);
      runRef.current = null;
    }
  }, [spectrum, running, workers, catalogue, poolName, useSkeleton, skeleton, exhaustiveLimit, weighting, seed, criterion, client, acquirePool, onReport]);

  const cancelSearch = useCallback(() => {
    void runRef.current?.cancel();
  }, []);

  if (spectrum === null) {
    return (
      <>
        <RuntimeNotice ready={ready} />
        <p className="empty-hint">
          Load a spectrum on the Data screen first: a search is a search against data, and the
          candidate topologies are screened and refitted against it.
        </p>
      </>
    );
  }

  return (
    <div className="discover-screen">
      <RuntimeNotice ready={ready} />
      <SearchPanel
        criteria={criteria}
        criterion={criterion}
        onCriterion={(value) => onSettings({ criterion: value })}
        poolNames={catalogue === null ? [poolName] : Object.keys(catalogue.pools)}
        poolName={poolName}
        onPoolName={(value) => onSettings({ poolName: value })}
        exhaustiveLimit={exhaustiveLimit}
        onExhaustiveLimit={(value) => onSettings({ exhaustiveLimit: value })}
        useSkeleton={useSkeleton}
        onUseSkeleton={(value) => onSettings({ useSkeleton: value })}
        skeleton={skeletonAvailable ? skeleton : null}
        workers={workers}
        onWorkers={(value) => onSettings({ workers: value })}
        seed={seed}
        onSeed={(value) => onSettings({ seed: value })}
        weighting={weighting}
        onWeighting={(value) => onSettings({ weighting: value })}
        running={running}
        disabled={!ready || catalogue === null}
        error={error}
        onStart={() => void startSearch()}
        onCancel={cancelSearch}
      />

      {running && <SearchProgressPanel progress={progress} poolSize={workers} />}

      {!running && stoppedEarly && (
        <p className="discover-screen__stopped">
          Cancelled before the search reached anything to report -- no topology had been
          screened or refitted yet.
        </p>
      )}

      {!running && report !== null && (
        <section className="discover-report">
          {/* The CLI's own sentence, verbatim: what a constrained or partial search may claim
              is exactly the part a paraphrase would get subtly wrong. */}
          <p className="discover-report__completeness">{report.completeness}</p>

          {report.refit_progress !== null && (
            <p className="discover-report__warning" role="alert">
              Only {report.refit_progress[0]} of {report.refit_progress[1]} shortlisted
              topologies were fitted; this ranking is partial.
            </p>
          )}

          {/* The picture of whichever row is selected, above the numbers rather than beside
              them: a topology string is what the search *found*, and reading `p(R1,C1-R2)` off
              a table is a translation the reader should not have to do. It is the same renderer
              the Fit screen edits, in read-only mode. */}
          <section className="discover-report__picked">
            <h2 className="panel-title">
              Selected circuit{picked === null ? "" : ": "}
              {picked !== null && <code>{picked}</code>}
            </h2>
            <CircuitPreview client={client} ready={ready} circuit={picked} />
            {picked !== null && (
              <div className="discover-report__handoff">
                <button
                  type="button"
                  className="discover-report__to-fit"
                  onClick={() => onFitCircuit(picked)}
                >
                  Fit this circuit
                </button>
                <span className="discover-report__handoff-note">
                  Takes the topology to the Fit screen, not the fitted values: this fitter uses
                  no starting guess, so refitting there re-runs the same global search and lands
                  in the same place.
                </span>
              </div>
            )}
          </section>

          <ParetoTable
            title="Pareto front (accuracy versus complexity)"
            rows={report.pareto}
            recommended={report.recommended}
            byCriterion={report.by_criterion}
            scoreLabel={report.score_label}
            selected={picked}
            onSelect={setPicked}
          />

          <p className="discover-report__note">
            Different topologies are frequently exact reparameterisations of one another: two
            rows here can describe the same measurable response and no impedance data could
            prefer one over the other. The Report screen groups them into classes, and holds the
            downloads and the structure probe.
          </p>

          <details className="discover-report__full">
            <summary>Full report</summary>
            <pre>{report.summary}</pre>
          </details>
        </section>
      )}
    </div>
  );
}
