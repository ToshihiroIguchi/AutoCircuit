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
import { defaultPoolSize, SearchPool } from "../worker/pool";
import { ParetoTable } from "../components/ParetoTable";
import { SearchPanel } from "../components/SearchPanel";
import { SearchProgressPanel } from "../components/SearchProgress";

export interface DiscoverScreenProps {
  client: BridgeClient;
  ready: boolean;
  spectrum: LoadedSpectrum | null;
  /** The circuit currently drawn on the Fit screen, or null/empty if there isn't one. */
  skeleton: string | null;
}

function errorMessage(error: unknown): string {
  return error instanceof BridgeError || error instanceof Error ? error.message : String(error);
}

export function DiscoverScreen({ client, ready, spectrum, skeleton }: DiscoverScreenProps) {
  const [catalogue, setCatalogue] = useState<CatalogueWire | null>(null);
  const [poolName, setPoolName] = useState("default");
  const [exhaustiveLimit, setExhaustiveLimit] = useState(4);
  const [useSkeleton, setUseSkeleton] = useState(false);
  const [workers, setWorkers] = useState(defaultPoolSize());
  const [seed, setSeed] = useState(0);
  const [weighting, setWeighting] = useState("modulus");

  const [progress, setProgress] = useState<SearchProgress>(idleProgress());
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<ReportWire | null>(null);
  const [stoppedEarly, setStoppedEarly] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The pool is not built at page load: four more Pyodide workers, each ~1.5 s and its own copy
  // of numpy and scipy, would tax every visitor who never presses Discover, on top of the ~13 s
  // cold start the page already has (`docs/WEB_UI_PLAN.md` section 2.3). So it comes up on the
  // first Discover press and then stays up for the next one -- rebuilt only if the worker count
  // changes, since that is the one control that changes what the pool itself has to be.
  const poolRef = useRef<SearchPool | null>(null);
  const runRef = useRef<SearchRun | null>(null);

  useEffect(() => {
    if (!ready) return;
    client.elements().then(setCatalogue).catch((err: unknown) => setError(errorMessage(err)));
  }, [client, ready]);

  const skeletonAvailable = skeleton !== null && skeleton.trim() !== "";
  useEffect(() => {
    if (!skeletonAvailable && useSkeleton) setUseSkeleton(false);
  }, [skeletonAvailable, useSkeleton]);

  const startSearch = useCallback(async () => {
    if (spectrum === null || running) return;
    setError(null);
    setReport(null);
    setStoppedEarly(false);
    setProgress(idleProgress());

    if (poolRef.current === null || poolRef.current.workers !== workers) {
      poolRef.current?.abort();
      poolRef.current = new SearchPool(workers, (up) =>
        setProgress((prev) => ({ ...prev, workersReady: up })),
      );
    }

    const options: SearchOptions = {
      pool: catalogue?.pools[poolName],
      skeleton: useSkeleton ? skeleton : null,
      exhaustiveLimit,
      weighting,
      seed,
    };

    const run = new SearchRun(client, poolRef.current, spectrum.current, options, setProgress);
    runRef.current = run;
    setRunning(true);
    try {
      const result = await run.run();
      // Null means cancel landed before the pool -- or the enumeration -- ever produced
      // anything to report, which is a real outcome and not the same as an empty search.
      if (result === null) setStoppedEarly(true);
      else setReport(result);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRunning(false);
      runRef.current = null;
    }
  }, [spectrum, running, workers, catalogue, poolName, useSkeleton, skeleton, exhaustiveLimit, weighting, seed, client]);

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
        onPoolName={setPoolName}
        exhaustiveLimit={exhaustiveLimit}
        onExhaustiveLimit={setExhaustiveLimit}
        useSkeleton={useSkeleton}
        onUseSkeleton={setUseSkeleton}
        skeleton={skeletonAvailable ? skeleton : null}
        workers={workers}
        onWorkers={setWorkers}
        seed={seed}
        onSeed={setSeed}
        weighting={weighting}
        onWeighting={setWeighting}
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
            prefer one over the other.
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
