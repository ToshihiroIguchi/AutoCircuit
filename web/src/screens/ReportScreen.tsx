// The Report screen: what the search is entitled to claim, and the files that carry it away.
//
// The Discover screen is where a search is *run*; this is where its answer is read. Three of the
// four things here exist because of a rule in CLAUDE.md rather than because of a UI idea, and
// they are the reason this screen is not just a download button:
//
//  * **Equivalence classes are shown as classes.** Different topologies are routinely exact
//    reparameterisations of one another, so a ranked list with a winner would be a claim the data
//    cannot support. The grouping arrives from Python already made.
//  * **A skeleton narrows what the report may claim, and saying so is not optional.** So a
//    constrained search gets a panel naming what the data could not test (the measured signature
//    of a wrong skeleton), where the assertion sits ambiguously, and -- on request -- which
//    equivalent forms the assertion removed from consideration entirely.
//  * **The structure probe stands beside the search, never inside it.** A DRT peak count read off
//    a regularised inversion of noisy data must not be able to remove a topology from a search
//    that still calls itself exhaustive (`docs/DISCOVERY_V2_PLAN.md` §3.4).
//
// The downloads are rendered in Python, by the same functions that write `--json`, `--csv` and
// `--spice`. A file outlives the session it came from, so it is not a browser's idea of the same
// report.

import type { LoadedSpectrum, SpectrumWire } from "../core/types";
import { idleExcluded } from "../core/excluded";
import type { BridgeClient } from "../worker/client";
import type { Discovery, DrtState, ExcludedState, ManualFit } from "../App";
import { DrtPanel } from "../components/DrtPanel";
import { EquivalenceClasses } from "../components/EquivalenceClasses";
import { ExcludedPanel } from "../components/ExcludedPanel";
import { ExportPanel, type ExportItem } from "../components/ExportPanel";
import { InterpretationPanel } from "../components/InterpretationPanel";
import { ParetoTable } from "../components/ParetoTable";
import { SkeletonFindings } from "../components/SkeletonFindings";
import { RuntimeNotice } from "../components/RuntimeNotice";

export interface ReportScreenProps {
  client: BridgeClient;
  ready: boolean;
  /** Every loaded spectrum, so a fit can be exported against the one it was fitted to. */
  spectra: LoadedSpectrum[];
  /** The selected spectrum, which is what the structure probe describes. */
  spectrum: LoadedSpectrum | null;
  discovery: Discovery | null;
  manualFit: ManualFit | null;
  /** The two long-running jobs this screen starts; `App` owns them so a tab switch cannot end
   *  them, and each says which search or spectrum it belongs to. */
  excluded: ExcludedState | null;
  drt: DrtState | null;
  onRunExcluded: () => void;
  onCancelExcluded: () => void;
  onRunDrt: (spectrum: SpectrumWire) => void;
}

export function ReportScreen({
  client,
  ready,
  spectra,
  spectrum,
  discovery,
  manualFit,
  excluded,
  drt,
  onRunExcluded,
  onCancelExcluded,
  onRunDrt,
}: ReportScreenProps) {
  const report = discovery?.report ?? null;
  const drtSource = spectrum?.current ?? null;

  // A pass belongs to the search it was run on, and a probe to the window it was run over. One
  // that belongs to something else is not shown at all: a stale answer sitting beside fresh data
  // is the failure this whole project is arranged against, and it is cheaper to drop the answer
  // than to caption it.
  const pass = excluded !== null && excluded.job === report?.job ? excluded : null;
  const probe = drt !== null && drt.spectrum === drtSource ? drt : null;
  const fitSpectrum =
    manualFit === null ? null : (spectra.find((s) => s.id === manualFit.spectrumId) ?? null);

  const discoveryExports: ExportItem[] =
    report === null
      ? []
      : [
          {
            key: "json",
            label: "JSON report",
            hint: "Everything below, coverage sentence included — the file `discover --json` writes.",
            run: () =>
              client.exportDiscovery(report.job, "json", {
                // Only when a pass has actually finished: an absent key and an empty result mean
                // different things wherever a skeleton is involved.
                excluded: pass?.report?.job,
              }),
          },
          {
            key: "csv",
            label: "Candidate table (CSV)",
            hint: "One row per topology, with the ones it cannot be told apart from — `discover --csv`.",
            run: () => client.exportDiscovery(report.job, "csv"),
          },
          {
            key: "netlist",
            label: "SPICE subcircuit",
            hint: `A .subckt for ${report.recommended ?? "the recommended candidate"}, ladders synthesised for fractional elements — \`discover --spice\`.`,
            run: () => client.exportDiscovery(report.job, "netlist"),
          },
        ];

  // The name the user knows the data by, for the file's header. The fit itself travels with the
  // spectrum it was made against, so an export stays possible -- and stays truthful -- after that
  // spectrum has been trimmed again or unloaded.
  const fitLabel = fitSpectrum?.label ?? "data no longer loaded";
  const fitExports: ExportItem[] =
    manualFit === null
      ? []
      : [
          {
            key: "fit-json",
            label: "JSON report",
            hint: "Parameters, standard errors and statistics — the file `fit --json` writes.",
            run: () =>
              client.exportFit(manualFit.fit.fit, manualFit.spectrum, "json", {
                source: fitLabel,
              }),
          },
          {
            key: "fit-netlist",
            label: "SPICE subcircuit",
            hint: "A .subckt of the fitted values, valid over the fitted frequency window.",
            run: () =>
              client.exportFit(manualFit.fit.fit, manualFit.spectrum, "netlist", {
                source: fitLabel,
              }),
          },
        ];

  if (report === null && manualFit === null && spectrum === null) {
    return (
      <>
        <RuntimeNotice ready={ready} />
        <p className="empty-hint">
          Nothing to report yet. Load a spectrum on the Data screen, then fit a circuit you already
          know on the Fit screen or search for one on the Discover screen.
        </p>
      </>
    );
  }

  return (
    <div className="report-screen">
      <RuntimeNotice ready={ready} />
      {report === null ? (
        <p className="empty-hint">
          No search has finished in this session. The Discover screen runs one; its coverage
          statement, its equivalence classes and its exports appear here.
        </p>
      ) : (
        <section className="report-screen__discovery">
          {/* The CLI's own sentence, verbatim: what a constrained or partial search may claim is
              exactly the part a paraphrase would get subtly wrong. */}
          <p className="discover-report__completeness">{report.completeness}</p>

          {report.refit_progress !== null && (
            <p className="discover-report__warning" role="alert">
              Only {report.refit_progress[0]} of {report.refit_progress[1]} shortlisted topologies
              were fitted; the ranking and the classes below are partial, and a topology missing
              from them is missing for that reason rather than on the evidence.
            </p>
          )}

          {report.unresolved_everywhere && (
            <p className="discover-report__warning" role="alert">
              Every candidate that fits this data leaves parameters the data cannot resolve —
              their standard errors exceed their own values. That is a finding about the
              measurement rather than about the search: a wider frequency window or more points
              would fix it, a longer search would not.
            </p>
          )}

          <EquivalenceClasses
            classes={report.equivalence_classes}
            rows={report.candidates}
            recommended={report.recommended}
            scoreLabel={report.score_label}
          />

          <ParetoTable
            title="Pareto front (accuracy versus complexity)"
            rows={report.pareto}
            recommended={report.recommended}
            byCriterion={report.by_criterion}
            scoreLabel={report.score_label}
          />

          {/* `unsupported_assertion` is null when nothing was fitted, and an empty list when the
              fit resolved every asserted element. The panel says the second of those in as many
              words, so it must not be handed the first: "the data tested your assertion" is a
              finding, and there is no finding when there was no fit. */}
          {report.skeleton !== null && report.unsupported_assertion !== null && (
            <SkeletonFindings
              skeleton={report.skeleton}
              unsupported={report.unsupported_assertion}
              placements={report.skeleton_placements ?? {}}
            />
          )}

          {report.skeleton !== null && report.unsupported_assertion === null && (
            <p className="report-screen__skeleton-only">
              The search was restricted to topologies containing <code>{report.skeleton}</code>,
              which you asserted. Nothing was fitted under it, so the data has said nothing about
              that assertion either way.
            </p>
          )}

          {report.skeleton !== null && report.recommended !== null && (
            <ExcludedPanel
              skeleton={report.skeleton}
              circuit={report.recommended}
              running={pass?.running ?? false}
              progress={pass?.progress ?? idleExcluded()}
              report={pass?.report ?? null}
              error={pass?.error ?? null}
              disabled={!ready || (pass?.running ?? false)}
              onStart={onRunExcluded}
              onCancel={onCancelExcluded}
            />
          )}

          {/* Purpose point 2: the circuit is the means and the inside of the part is the end.
              It sits above the downloads and below the classes on purpose -- it is a reading of
              the recommendation, and the classes are what limit what the reading may say. */}
          <InterpretationPanel
            client={client}
            job={report.job}
            circuit={null}
            ready={ready}
          />

          <ExportPanel
            title="Download this search"
            description="Written in Python by the same functions the command line writes them with, so a file saved here is the file the CLI would have produced."
            items={discoveryExports}
            disabled={!ready}
          />

          <details className="discover-report__full">
            <summary>Full report</summary>
            <pre>{report.summary}</pre>
          </details>
        </section>
      )}

      {fitExports.length > 0 && manualFit !== null && (
        <ExportPanel
          title={`Download the fit of ${manualFit.fit.fit.circuit}`}
          description={`Fitted on the Fit screen against ${fitLabel}.`}
          items={fitExports}
          disabled={!ready}
        />
      )}

      {drtSource !== null && (
        <DrtPanel
          drt={probe?.result ?? null}
          running={probe?.running ?? false}
          error={probe?.error ?? null}
          disabled={!ready || (probe?.running ?? false)}
          onRun={() => onRunDrt(drtSource)}
        />
      )}
    </div>
  );
}
