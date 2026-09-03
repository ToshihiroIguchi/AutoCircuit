// The Discover screen: press a button, wait minutes, get a Pareto front -- never a single
// answer. `docs/WEB_UI_PLAN.md` section 1 is why this screen is a job rather than a request: a
// real search takes minutes in the browser, so there is streamed progress and a cancel button
// instead of a spinner.
//
// Every decision behind the search -- which topologies exist, which earn a full-budget refit,
// what the run may claim afterwards -- was made in Python (`autocircuit.core.discover`, driven
// through `autocircuit.web.job`). This screen draws what comes back; `App` runs the search and
// holds it, because a search is a result of the session and not of a tab
// (`docs/SCREEN_STATE_PLAN.md`).
//
// It plots the selected row for a reason that is the other half of one decision. The fitted
// values do *not* travel to the Fit screen (see `onFitCircuit`), which is right -- and it leaves
// this screen owing the user a full view of what the search found, rather than a table and a
// schematic. The fit it draws is the tier-2 refit the row was *ranked* on, fetched from the
// worker that still holds it: nothing is re-fitted to make this picture.

import { useEffect, useMemo } from "react";
import type {
  CatalogueWire,
  CriterionWire,
  LoadedSpectrum,
} from "../core/types";
import { AUTO_POOL, CUSTOM_POOL } from "../core/types";
import { decodeArray, decodeComplexArray } from "../core/wire";
import type { SearchState } from "../App";
import { BridgeClient } from "../worker/client";
import { defaultPoolSize } from "../worker/pool";
import { CircuitPreview } from "../components/CircuitPreview";
import { ParetoTable } from "../components/ParetoTable";
import { PlotsPanel, type ModelOverlay } from "../components/PlotsPanel";
import { SearchPanel } from "../components/SearchPanel";
import { SearchProgressPanel } from "../components/SearchProgress";
import { RuntimeNotice } from "../components/RuntimeNotice";

export interface DiscoverScreenProps {
  client: BridgeClient;
  ready: boolean;
  /** The element catalogue, fetched once by `App`; null until the worker has answered. */
  catalogue: CatalogueWire | null;
  /** The spectrum a *new* search would run against. The finished one carries its own. */
  spectrum: LoadedSpectrum | null;
  /** The circuit currently drawn on the Fit screen, or null/empty if there isn't one. */
  skeleton: string | null;
  /**
   * The session's search: the job, its progress, and what it found. Null until one is started.
   *
   * Held by `App` rather than here. [measured] While it lived in this component, one click to
   * another tab and back emptied the screen of a search the Report screen was still showing --
   * and re-armed the Discover button while the search was still running, so a second search
   * could be started onto the pool the first one was using (`docs/SCREEN_STATE_PLAN.md` §2).
   */
  search: SearchState | null;
  /**
   * What to search with, and how to change it.
   *
   * Owned by `App` for the same reason: settings kept here would silently return to their
   * defaults between one search and the next. [browser] That is not hypothetical -- it produced
   * an unconstrained four-element run from a form that had said three and a skeleton.
   */
  settings: SearchSettings;
  onSettings: (change: Partial<SearchSettings>) => void;
  /** The model-selection menu the loaded core offers; empty until the worker is ready. */
  criteria: CriterionWire[];
  onStart: (spectrum: LoadedSpectrum) => void;
  onCancel: () => void;
  /** Draw, plot and offer one row of the front. */
  onPick: (circuit: string) => void;
  /**
   * Take one of these topologies over to the Fit screen.
   *
   * **The topology, and not the fit.** The discovered parameter values are not carried across
   * as a starting guess, because this fitter has none: pressing Fit there re-runs the same
   * global search from the same data-derived interval and lands in the same place. Carrying
   * numbers over would make a screen that says "these do not seed the fit" look as though they
   * did (docs/METRICS_AND_UX_PLAN.md section 6), and it would install one row of a front the
   * data cannot rank into a screen whose whole framing is *you asserted this circuit*
   * (docs/SCREEN_STATE_PLAN.md section 3).
   *
   * Two things do travel with it, and both are what makes the sentence above true rather than
   * exceptions to it: the **data selection**, so the refit is against the spectrum the search
   * ran on, and the **weighting, seed and restart count** the search refitted under, so "lands
   * in the same place" is not a claim about a differently-configured fit
   * (docs/STARTUP_AND_EDITING_PLAN.md section 1). `App` does both.
   */
  onFitCircuit: (circuit: string) => void;
}

/** Everything the search panel holds. Every field is an argument `discover` has too, except
 *  `workers`, which sizes the pool rather than the search. */
export interface SearchSettings {
  poolName: string;
  /** Codes checked in the panel, used only while `poolName === CUSTOM_POOL`. */
  customPool: string[];
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
    // "auto" is not one of the catalogue's pools and deliberately so: it means *no* pool, which
    // is what makes the spectrum choose one (`CLAUDE.md`, and docs/POOL_FROM_SPECTRUM_PLAN.md).
    // It is the default here for the same reason `--pool auto` is the default on the command
    // line -- "what kind of part is this?" is the expert judgement this project exists to
    // remove, and a non-expert's wrong answer to it silently narrows the search.
    poolName: AUTO_POOL,
    customPool: [],
    exhaustiveLimit: 4,
    useSkeleton: false,
    workers: defaultPoolSize(),
    seed: 0,
    weighting: "modulus",
    criterion: "bic",
  };
}

/**
 * The selected row's fit, as the plots want it.
 *
 * The residuals arrive already split into real and imaginary parts by Python, because their
 * concatenation order is a detail of the objective function; and they are the *weighted*
 * residuals the refit minimised, so they are labelled as such rather than as percentages.
 */
function useOverlay(search: SearchState | null): ModelOverlay | null {
  const fit = search?.pickedFit ?? null;
  return useMemo(() => {
    if (fit === null) return null;
    const { re, im } = decodeComplexArray(fit.fit.z_model);
    return {
      label: "Search fit",
      re,
      im,
      residualReal: decodeArray(fit.residual_real),
      residualImag: decodeArray(fit.residual_imag),
      residualTitle: `Refit residuals (${fit.fit.weighting} weighting)`,
      residualUnit: "weighted",
      residualPlaceholder: "",
    };
  }, [fit]);
}

export function DiscoverScreen({
  client,
  ready,
  catalogue,
  spectrum,
  skeleton,
  search,
  settings,
  onSettings,
  criteria,
  onStart,
  onCancel,
  onPick,
  onFitCircuit,
}: DiscoverScreenProps) {
  const { poolName, customPool, exhaustiveLimit, useSkeleton, workers, seed, weighting, criterion } =
    settings;
  const overlay = useOverlay(search);

  const running = search?.running ?? false;
  const report = search?.report ?? null;
  const picked = search?.picked ?? null;

  // A skeleton that has gone away un-ticks the box, so a run cannot assert a circuit that is no
  // longer drawn.
  const skeletonAvailable = skeleton !== null && skeleton.trim() !== "";
  useEffect(() => {
    if (!skeletonAvailable && useSkeleton) onSettings({ useSkeleton: false });
  }, [skeletonAvailable, useSkeleton, onSettings]);

  if (spectrum === null && search === null) {
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
        poolNames={catalogue === null ? [poolName] : [AUTO_POOL, CUSTOM_POOL]}
        poolName={poolName}
        onPoolName={(value) => onSettings({ poolName: value })}
        catalogue={catalogue}
        customPool={customPool}
        onCustomPool={(codes) => onSettings({ customPool: codes })}
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
        disabled={!ready || catalogue === null || spectrum === null}
        startDisabled={
          !ready ||
          catalogue === null ||
          spectrum === null ||
          (poolName === CUSTOM_POOL && customPool.length === 0)
        }
        error={search?.error ?? null}
        onStart={() => spectrum !== null && onStart(spectrum)}
        onCancel={onCancel}
      />

      {running && search !== null && (
        <SearchProgressPanel progress={search.progress} poolSize={search.workers} />
      )}

      {!running && (search?.stoppedEarly ?? false) && (
        <p className="discover-screen__stopped">
          Cancelled before the search reached anything to report -- no topology had been
          screened or refitted yet.
        </p>
      )}

      {!running && report !== null && search !== null && (
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
                  in the same place. It takes the settings this search refitted under —{" "}
                  {report.weighting} weighting, seed {report.seed}, {report.refit_restarts}{" "}
                  restarts — because that promise is only true while they match. Go there to{" "}
                  <em>change</em> the circuit — the search's own fit of it is plotted below.
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
            onSelect={onPick}
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

      {/* The selected row, drawn over the data the search ran against -- which is captured when
          the search starts and is not necessarily what is selected on the Data screen now, so it
          is named rather than assumed. Nothing here is re-fitted: this is the tier-2 refit the
          row was ranked on. */}
      {/* `picked` is null only when the run was stopped before it refitted anything, and there is
          then no fit to draw -- not an empty panel where one should be. */}
      {!running && report !== null && search !== null && picked !== null && (
        <section className="discover-plots">
          {overlay !== null && (
            <p className="discover-plots__source">
              <code>{picked}</code> as the search fitted it, against {search.spectrumLabel} in the
              frequency window the search ran over — not necessarily the spectrum selected on the
              Data screen now, and not re-fitted here.
            </p>
          )}
          {search.pickedError !== null && (
            <p className="discover-plots__error" role="alert">
              {search.pickedError}
            </p>
          )}
          {overlay === null && search.picking && (
            <p className="empty-hint">Fetching the fit behind this row…</p>
          )}
          {overlay !== null && (
            <>
              {search.pickedFit !== null && search.pickedFit.warnings.length > 0 && (
                <ul className="discover-plots__warnings">
                  {search.pickedFit.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              )}
              <PlotsPanel
                key={`discover-plots-${search.token}`}
                spectrum={search.spectrum}
                model={overlay}
              />
            </>
          )}
        </section>
      )}
    </div>
  );
}
