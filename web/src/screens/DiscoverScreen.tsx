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
import type { CatalogueWire, LoadedSpectrum, ReportWire } from "../core/types";
import { idleProgress, SearchRun, type SearchProgress } from "../core/search";
import { BridgeClient, BridgeError, type SearchOptions } from "../worker/client";
import { defaultPoolSize } from "../worker/pool";
import type { SearchPool } from "../worker/pool";
import { ParetoTable } from "../components/ParetoTable";
import { SearchPanel } from "../components/SearchPanel";
import { SearchProgressPanel } from "../components/SearchProgress";

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
  /** A finished search, for the Report screen. Null while one is running, or after a cancel. */
  onReport: (
    discovery: { report: ReportWire; options: SearchOptions; workers: number } | null,
  ) => void;
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
}

export function defaultSearchSettings(): SearchSettings {
  return {
    poolName: "default",
    exhaustiveLimit: 4,
    useSkeleton: false,
    workers: defaultPoolSize(),
    seed: 0,
    weighting: "modulus",
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
  onReport,
}: DiscoverScreenProps) {
  const { poolName, exhaustiveLimit, useSkeleton, workers, seed, weighting } = settings;
  const [catalogue, setCatalogue] = useState<CatalogueWire | null>(null);

  const [progress, setProgress] = useState<SearchProgress>(idleProgress());
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<ReportWire | null>(null);
  const [stoppedEarly, setStoppedEarly] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        onReport({ report: result, options, workers });
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRunning(false);
      runRef.current = null;
    }
  }, [spectrum, running, workers, catalogue, poolName, useSkeleton, skeleton, exhaustiveLimit, weighting, seed, client, acquirePool, onReport]);

  const cancelSearch = useCallback(() => {
    void runRef.current?.cancel();
  }, []);

  if (spectrum === null) {
    return (
      <p className="empty-hint">
        Load a spectrum on the Data screen first: a search is a search against data, and the
        candidate topologies are screened and refitted against it.
      </p>
    );
  }

  return (
    <div className="discover-screen">
      <SearchPanel
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

          <ParetoTable
            title="Pareto front (accuracy versus complexity)"
            rows={report.pareto}
            recommended={report.recommended}
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
