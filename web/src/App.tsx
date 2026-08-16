// The shell: one Pyodide client, one worker pool, the spectra everything else works on, and
// which screen is showing. The screens themselves are in src/screens/ -- Data (load, validate,
// trim), Fit (draw a circuit, fit it), Discover (search for one) and Report (read the answer,
// and take it away). They share the loaded spectra because a fit is fitted to the spectrum the
// Data screen has selected, in the window it has been trimmed to.
//
// What lives here rather than in a screen follows one rule, and it is the rule the whole of
// `docs/SCREEN_STATE_PLAN.md` exists to state:
//
//   **A result belongs to the session. A screen owns only what the user is composing.**
//
// A React screen is unmounted the moment the user looks at another tab. So a finished search, a
// finished fit, a structure probe, and the runs producing them are held here; a half-typed
// circuit string, an armed palette button and a parse error are left in the screen, because
// losing a draft on a tab switch is the behaviour a draft should have.
//
// [measured] The rule used to be the weaker "lift what *another* screen needs", which preserved
// every result except on the screen that produced it: one tab switch away and back emptied the
// Discover screen of a search the Report screen was still showing, and left the Fit screen
// saying "Not fitted" while the Report screen offered "Download the fit of R1"
// (docs/SCREEN_STATE_PLAN.md section 2).
//
// The same arrangement also put `running` inside the screen, so returning to a tab mid-search
// found a re-armed Discover button and a second search could be dispatched onto the pool the
// first one was using. That one is read off the old code rather than measured -- what is measured
// is the behaviour now, which is that the button stays disabled and the progress rows carry on.
//
// The pool is here for that reason plus one more -- two screens run work on it, and a second
// pool would be four more Pyodide workers.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BridgeClient, BridgeError, type SearchOptions } from "./worker/client";
import type { LoadStage } from "./worker/protocol";
import type {
  CatalogueWire,
  DrtWire,
  ExcludedReportWire,
  FitWire,
  LoadedSpectrum,
  ReportWire,
  SpectrumWire,
  VersionsWire,
} from "./core/types";
import { ExcludedRun, idleExcluded, type ExcludedProgress } from "./core/excluded";
import { idleProgress, SearchRun, type SearchProgress } from "./core/search";
import { ThemeContext, useTheme } from "./core/theme";
import { SearchPool } from "./worker/pool";
import { StatusBar } from "./components/StatusBar";
import { ThemeToggle } from "./components/ThemeToggle";
import { DataScreen, type FileError } from "./screens/DataScreen";
import {
  DiscoverScreen,
  defaultSearchSettings,
  type SearchSettings,
} from "./screens/DiscoverScreen";
import { FitScreen, INITIAL_CIRCUIT, defaultFitState, type FitState } from "./screens/FitScreen";
import { ReportScreen } from "./screens/ReportScreen";

type Screen = "data" | "fit" | "discover" | "report";

/**
 * The order the work runs in: load, search for a topology, refine the one you picked, take the
 * answer away.
 *
 * Fit came before Discover until the hand-off existed, because the dependency ran that way --
 * the circuit drawn on the Fit screen is what a constrained search asserts as its skeleton. That
 * dependency is still there and still runs backwards; it is just no longer the common path.
 */
const SCREENS: ReadonlyArray<readonly [Screen, string]> = [
  ["data", "Data"],
  ["discover", "Discover"],
  ["fit", "Fit"],
  ["report", "Report"],
];

/**
 * A finished search, and the options it ran with.
 *
 * The options travel with the report because the excluded-equivalents pass on the Report screen
 * is a continuation of *this* search and has to screen with the same weighting and seed. The job
 * id is inside the report itself.
 *
 * Derived from `SearchState` below rather than stored: it is the Report screen's view of a
 * search, and there is only one search.
 */
export interface Discovery {
  report: ReportWire;
  options: SearchOptions;
  /** The pool size that search ran on, so its continuation does not rebuild the pool. */
  workers: number;
}

/**
 * The topology search: the job, where it has got to, and what it found.
 *
 * Held here rather than on the Discover screen for the reason at the top of this file. Two of its
 * fields are provenance rather than results, and they are the reason this is one record instead
 * of several pieces of state:
 *
 *  * `spectrum` is **the data the search ran against**, captured when it started -- not a
 *    reference to whichever spectrum is selected by the time the answer is read. The Discover
 *    screen plots the found model over it, and plotting a model over a window it was not fitted
 *    to would be a picture of something that never happened. Same reasoning as `ManualFit`.
 *  * `options` is what it ran with, which the excluded-equivalents pass has to match.
 */
export interface SearchState {
  /**
   * This run, as distinct from any other.
   *
   * Not the job id, which does not exist until the space has been enumerated -- and the window
   * between pressing Discover and that answer is exactly when a cancel-and-restart happens. A
   * message from a superseded run is dropped by comparing this.
   */
  token: string;
  spectrumId: string;
  /** What the user calls that data, for the caption over the plots. */
  spectrumLabel: string;
  spectrum: SpectrumWire;
  options: SearchOptions;
  workers: number;
  progress: SearchProgress;
  running: boolean;
  report: ReportWire | null;
  /** Which front row is drawn, plotted and offered to the Fit screen. */
  picked: string | null;
  /**
   * The fit behind `picked`, fetched from the worker that still holds it.
   *
   * Not computed here and not re-fitted: it is the tier-2 refit this row was *ranked* on, so the
   * curve on screen is the curve the score describes (docs/SCREEN_STATE_PLAN.md section 4).
   */
  pickedFit: FitWire | null;
  pickedError: string | null;
  picking: boolean;
  /** Cancelled before anything had been screened or refitted, which is a real outcome. */
  stoppedEarly: boolean;
  error: string | null;
}

/**
 * A manual fit, and the data it was fitted to.
 *
 * The *spectrum itself*, not a reference to whichever window is selected later: a netlist header
 * states the frequency band the model is valid over, so exporting a fit against a window it was
 * not fitted to would put a false claim in a file that outlives the session. The id is kept
 * beside it only so the file can be labelled with the name the user knows the data by.
 */
export interface ManualFit {
  fit: FitWire;
  spectrumId: string;
  spectrum: SpectrumWire;
}

/**
 * The excluded-equivalents pass, and the search it belongs to.
 *
 * Held here rather than on the Report screen because a screen is unmounted when the user visits
 * another tab, and this pass takes as long as the search did. Losing minutes of work to a glance
 * at the data would be an odd thing to charge someone for. The `job` is what it belongs to: a
 * pass is about one search, and a new search must not inherit the old one's answer.
 */
export interface ExcludedState {
  job: string;
  report: ExcludedReportWire | null;
  progress: ExcludedProgress;
  running: boolean;
  error: string | null;
}

/** The structure probe, and the frequency window it was run over. Same reasoning. */
export interface DrtState {
  spectrum: SpectrumWire;
  result: DrtWire | null;
  running: boolean;
  error: string | null;
}

function nextId(): string {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function errorMessage(error: unknown): string {
  return error instanceof BridgeError || error instanceof Error ? error.message : String(error);
}

export function App() {
  const [stage, setStage] = useState<LoadStage>("booting");
  const [detail, setDetail] = useState("Starting the Python runtime");
  const [versions, setVersions] = useState<VersionsWire | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);

  const { choice: themeChoice, resolved: theme, setChoice: setTheme } = useTheme();

  const [screen, setScreen] = useState<Screen>("data");
  // Owned here, not by FitScreen, because the Discover screen offers this same circuit as a
  // search skeleton -- a partly drawn circuit is already exactly what `discover(skeleton=...)`
  // takes (see FitScreen's own header comment).
  const [circuit, setCircuit] = useState(INITIAL_CIRCUIT);
  const [spectra, setSpectra] = useState<LoadedSpectrum[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [fileErrors, setFileErrors] = useState<FileError[]>([]);
  const [dragActive, setDragActive] = useState(false);
  // The element catalogue: what the loaded core was built with, so it cannot change while the
  // page is open. Fetched once here rather than by each of the two screens that need it -- the
  // palette on Fit and the pool menu on Discover -- and by the search, which needs the pool.
  const [catalogue, setCatalogue] = useState<CatalogueWire | null>(null);
  // The three long-running jobs of the session, and the manual fit. Every one of them outlives
  // the screen that started it; see the file header.
  const [search, setSearch] = useState<SearchState | null>(null);
  const [fitState, setFitState] = useState<FitState>(defaultFitState);
  const [settings, setSettings] = useState<SearchSettings>(defaultSearchSettings);
  const [excluded, setExcluded] = useState<ExcludedState | null>(null);
  const [drt, setDrt] = useState<DrtState | null>(null);
  const excludedRun = useRef<ExcludedRun | null>(null);
  const searchRun = useRef<SearchRun | null>(null);
  // The fits behind the front rows, keyed `job|circuit`. A refetch would be cheap -- the worker
  // has the fit and does not refit it -- but flicking between rows should not flicker.
  const candidateFits = useRef(new Map<string, FitWire>());

  const clientRef = useRef<BridgeClient | null>(null);
  if (clientRef.current === null) {
    clientRef.current = new BridgeClient((s, d) => {
      setStage(s);
      setDetail(d);
    });
  }
  const client = clientRef.current;
  const ready = versions !== null;

  useEffect(() => {
    client
      .ready()
      .then((answer) => {
        setVersions(answer);
        // The default criterion comes from the loaded core, not from a constant here. The two
        // would otherwise drift apart silently, and the browser disagreeing with the command
        // line about which model won is exactly the class of failure this project keeps
        // finding (docs/HANDOFF.md section 3).
        setSettings((prev) => ({ ...prev, criterion: answer.default_criterion }));
        return client.elements();
      })
      .then(setCatalogue)
      .catch((err: unknown) => setBootError(errorMessage(err)));
  }, [client]);

  // Keeps the selected row valid: picks the first spectrum on the initial load and whenever the
  // selected one is removed, without needing bespoke selection logic in every mutation below.
  useEffect(() => {
    setSelectedId((prev) => {
      if (prev !== null && spectra.some((s) => s.id === prev)) return prev;
      return spectra[0]?.id ?? null;
    });
  }, [spectra]);

  const runValidation = useCallback(
    async (id: string, spectrum: SpectrumWire) => {
      try {
        const validation = await client.validate(spectrum);
        setSpectra((prev) =>
          prev.map((s) =>
            // The `s.current === spectrum` guard drops a stale answer: if the window was
            // trimmed again before this validation returned, its result belongs to a spectrum
            // that is no longer the selected one's current window.
            s.id === id && s.current === spectrum
              ? { ...s, validation, validationError: null, validating: false }
              : s,
          ),
        );
      } catch (err) {
        const message = errorMessage(err);
        setSpectra((prev) =>
          prev.map((s) =>
            s.id === id && s.current === spectrum
              ? { ...s, validation: null, validationError: message, validating: false }
              : s,
          ),
        );
      }
    },
    [client],
  );

  const loadFile = useCallback(
    async (file: File) => {
      try {
        const wires = await client.readFile(file);
        const multiple = wires.length > 1;
        const entries: LoadedSpectrum[] = wires.map((wire, index) => ({
          id: nextId(),
          label: multiple ? `${file.name} #${index + 1}` : file.name,
          original: wire,
          current: wire,
          validation: null,
          validationError: null,
          validating: true,
        }));
        setSpectra((prev) => [...prev, ...entries]);
        for (const entry of entries) void runValidation(entry.id, entry.current);
      } catch (err) {
        setFileErrors((prev) => [...prev, { id: nextId(), name: file.name, message: errorMessage(err) }]);
      }
    },
    [client, runValidation],
  );

  const handleFiles = useCallback(
    (files: File[]) => {
      for (const file of files) void loadFile(file);
    },
    [loadFile],
  );

  const removeSpectrum = useCallback((id: string) => {
    setSpectra((prev) => prev.filter((s) => s.id !== id));
  }, []);

  const dismissFileError = useCallback((id: string) => {
    setFileErrors((prev) => prev.filter((e) => e.id !== id));
  }, []);

  const applyTrim = useCallback(
    async (id: string, fMin: number | null, fMax: number | null): Promise<string | null> => {
      const target = spectra.find((s) => s.id === id);
      if (target === undefined) return "This spectrum is no longer loaded.";
      try {
        const trimmed = await client.trim(target.original, fMin, fMax);
        setSpectra((prev) =>
          prev.map((s) =>
            s.id === id
              ? { ...s, current: trimmed, validation: null, validationError: null, validating: true }
              : s,
          ),
        );
        void runValidation(id, trimmed);
        return null;
      } catch (err) {
        return errorMessage(err);
      }
    },
    [spectra, client, runValidation],
  );

  const resetTrim = useCallback(
    (id: string) => {
      const target = spectra.find((s) => s.id === id);
      if (target === undefined) return;
      setSpectra((prev) =>
        prev.map((s) =>
          s.id === id
            ? { ...s, current: s.original, validation: null, validationError: null, validating: true }
            : s,
        ),
      );
      void runValidation(id, target.original);
    },
    [spectra, runValidation],
  );

  // Window-level drag-and-drop, as required: a file may be dropped anywhere on the page, not
  // just onto the drop-zone element. The enter/leave counter is needed because those events fire
  // for every child element the pointer crosses.
  useEffect(() => {
    let depth = 0;
    function onDragEnter(event: DragEvent): void {
      event.preventDefault();
      depth += 1;
      setDragActive(true);
    }
    function onDragOver(event: DragEvent): void {
      event.preventDefault();
    }
    function onDragLeave(event: DragEvent): void {
      event.preventDefault();
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragActive(false);
    }
    function onDrop(event: DragEvent): void {
      event.preventDefault();
      depth = 0;
      setDragActive(false);
      const files = event.dataTransfer?.files;
      if (!ready || files === undefined || files.length === 0) return;
      // A file dropped from another screen is still a load, so it goes where the loading is
      // reported -- otherwise the reader's verdict on it would land on a page nobody is looking
      // at.
      setScreen("data");
      handleFiles(Array.from(files));
    }
    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [ready, handleFiles]);

  // One pool for the whole page, and it is not built until something asks for it: four more
  // Pyodide workers, each ~1.5 s and its own copy of numpy and scipy, would tax every visitor who
  // never searches (`docs/WEB_UI_PLAN.md` §2.5). Two screens run work on it -- the search, and
  // the excluded-equivalents pass that follows it -- and they must not each keep their own, so it
  // is held here and handed out. The status callback is indirected through a ref because the pool
  // outlives the run that created it.
  const poolRef = useRef<SearchPool | null>(null);
  const poolStatusRef = useRef<(ready: number, total: number) => void>(() => {});
  const acquirePool = useCallback(
    (workers: number, onStatus: (ready: number, total: number) => void): SearchPool => {
      poolStatusRef.current = onStatus;
      if (poolRef.current === null || poolRef.current.workers !== workers) {
        poolRef.current?.abort();
        poolRef.current = new SearchPool(workers, (ready, total) =>
          poolStatusRef.current(ready, total),
        );
      }
      return poolRef.current;
    },
    [],
  );

  // Stable, because the Discover screen keeps it in an effect's dependencies.
  const changeSettings = useCallback((change: Partial<SearchSettings>) => {
    setSettings((prev) => ({ ...prev, ...change }));
  }, []);

  // -- The topology search -----------------------------------------------------------------
  //
  // Run from here rather than from the Discover screen, so that a tab switch mid-search neither
  // loses the progress nor re-arms the Discover button. Every write goes through `setSearch`,
  // which belongs to this component and is therefore still alive when a batch lands while the
  // user is reading something else.

  const startSearch = useCallback(
    async (spectrum: LoadedSpectrum, skeleton: string | null) => {
      const options: SearchOptions = {
        pool: catalogue?.pools[settings.poolName],
        skeleton: settings.useSkeleton ? skeleton : null,
        exhaustiveLimit: settings.exhaustiveLimit,
        weighting: settings.weighting,
        seed: settings.seed,
        criterion: settings.criterion,
      };
      const { workers } = settings;
      const token = nextId();
      // The whole record is replaced as the search starts, not when it finishes: the Report
      // screen must not show one search's classes beside another search's coverage claim, and
      // the plots must not show the previous search's model over the new search's data.
      setSearch({
        token,
        spectrumId: spectrum.id,
        spectrumLabel: spectrum.label,
        spectrum: spectrum.current,
        options,
        workers,
        progress: idleProgress(),
        running: true,
        report: null,
        picked: null,
        pickedFit: null,
        pickedError: null,
        picking: false,
        stoppedEarly: false,
        error: null,
      });
      // Only ever updates the run it was made for: a search started right after a cancel must
      // not have its record overwritten by the cancelled one's last message.
      const update = (change: Partial<SearchState>) =>
        setSearch((prev) => (prev === null || prev.token !== token ? prev : { ...prev, ...change }));

      const pool = acquirePool(workers, (up) =>
        update({ progress: { ...idleProgress(), workersReady: up } }),
      );
      const run = new SearchRun(client, pool, spectrum.current, options, (progress) =>
        update({ progress }),
      );
      searchRun.current = run;
      try {
        const result = await run.run();
        // Null means cancel landed before the pool -- or the enumeration -- ever produced
        // anything to report, which is a real outcome and not the same as an empty search.
        if (result === null) update({ stoppedEarly: true });
        else update({ report: result, picked: result.recommended ?? result.pareto[0]?.circuit ?? null });
      } catch (err) {
        update({ error: errorMessage(err) });
      } finally {
        update({ running: false });
        // Guarded for the same reason `update` is: a superseded run finishing must not clear the
        // handle its successor is being cancelled through.
        if (searchRun.current === run) searchRun.current = null;
      }
    },
    [client, catalogue, settings, acquirePool],
  );

  const cancelSearch = useCallback(() => {
    void searchRun.current?.cancel();
  }, []);

  /** Draw and plot one row of the front. The fit comes from the worker that still holds it. */
  const pickCandidate = useCallback(
    async (circuitText: string) => {
      const job = search?.report?.job;
      if (job === undefined) return;
      const key = `${job}|${circuitText}`;
      const cached = candidateFits.current.get(key);
      const update = (change: Partial<SearchState>) =>
        setSearch((prev) => (prev === null || prev.report?.job !== job ? prev : { ...prev, ...change }));
      if (cached !== undefined) {
        update({ picked: circuitText, pickedFit: cached, pickedError: null, picking: false });
        return;
      }
      update({ picked: circuitText, pickedFit: null, pickedError: null, picking: true });
      try {
        const answer = await client.discoverCandidate(job, circuitText);
        candidateFits.current.set(key, answer);
        // Guarded on the row as well as the job: a fast click through three rows must land on
        // the one the user stopped at, whatever order the answers come back in.
        setSearch((prev) =>
          prev === null || prev.report?.job !== job || prev.picked !== circuitText
            ? prev
            : { ...prev, pickedFit: answer, pickedError: null, picking: false },
        );
      } catch (err) {
        setSearch((prev) =>
          prev === null || prev.report?.job !== job || prev.picked !== circuitText
            ? prev
            : { ...prev, pickedError: errorMessage(err), picking: false },
        );
      }
    },
    [client, search?.report?.job],
  );

  // The recommended row is what the report is about, so it is what gets drawn -- but only once
  // the search has finished, and the fetch is the same one a click makes.
  const picked = search?.picked ?? null;
  const pickedFit = search?.pickedFit ?? null;
  const picking = search?.picking ?? false;
  const pickedError = search?.pickedError ?? null;
  useEffect(() => {
    if (picked !== null && pickedFit === null && !picking && pickedError === null) {
      void pickCandidate(picked);
    }
  }, [picked, pickedFit, picking, pickedError, pickCandidate]);

  // What the Report screen reads. Both are views of state held above rather than copies of it:
  // there is one search and one manual fit in a session, and two records of either is two things
  // that can disagree.
  const discovery = useMemo<Discovery | null>(
    () =>
      search === null || search.report === null
        ? null
        : { report: search.report, options: search.options, workers: search.workers },
    [search],
  );
  const manualFit = useMemo<ManualFit | null>(
    () =>
      fitState.fit === null
        ? null
        : {
            fit: fitState.fit.result,
            spectrumId: fitState.fit.spectrumId,
            spectrum: fitState.fit.spectrum,
          },
    [fitState.fit],
  );

  // The two pieces of work the Report screen starts. They live here for the same reason the pool
  // does: the screen that starts them is unmounted the moment the user looks at another tab, and
  // both of these cost real time.
  const runExcluded = useCallback(async () => {
    if (discovery === null) return;
    const job = discovery.report.job;
    const update = (change: Partial<ExcludedState>) =>
      setExcluded((prev) =>
        prev === null || prev.job !== job ? prev : { ...prev, ...change },
      );
    setExcluded({
      job,
      report: null,
      progress: idleExcluded(),
      running: true,
      error: null,
    });
    const pool = acquirePool(discovery.workers, (ready) =>
      update({ progress: { ...idleExcluded(), workersReady: ready } }),
    );
    const run = new ExcludedRun(
      client,
      pool,
      job,
      discovery.report.recommended,
      discovery.options,
      (progress) => update({ progress }),
    );
    excludedRun.current = run;
    try {
      update({ report: await run.run() });
    } catch (err) {
      update({ error: errorMessage(err) });
    } finally {
      update({ running: false });
      excludedRun.current = null;
    }
  }, [client, discovery, acquirePool]);

  const cancelExcluded = useCallback(() => {
    void excludedRun.current?.cancel();
  }, []);

  const runDrt = useCallback(
    async (spectrum: SpectrumWire) => {
      setDrt({ spectrum, result: null, running: true, error: null });
      const update = (change: Partial<DrtState>) =>
        setDrt((prev) =>
          prev === null || prev.spectrum !== spectrum ? prev : { ...prev, ...change },
        );
      try {
        update({ result: await client.drt(spectrum) });
      } catch (err) {
        update({ error: errorMessage(err) });
      } finally {
        update({ running: false });
      }
    },
    [client],
  );

  /**
   * The Discover screen's hand-off: take a topology to the Fit screen and go there.
   *
   * The topology and the data selection, and nothing else. Why the fitted values do not travel is
   * `DiscoverScreenProps.onFitCircuit` and `docs/SCREEN_STATE_PLAN.md` section 3; why the *data*
   * does is the other half of the same argument. A search ran against one spectrum, and handing
   * its topology to a Fit screen pointed at a different one would fit a model to data the search
   * never saw while the button that did it said "Fit this circuit".
   */
  const fitCircuit = useCallback(
    (text: string) => {
      setCircuit(text);
      const searched = search?.spectrumId;
      if (searched !== undefined && spectra.some((s) => s.id === searched)) setSelectedId(searched);
      setScreen("fit");
    },
    [search?.spectrumId, spectra],
  );

  const selected = useMemo(() => spectra.find((s) => s.id === selectedId) ?? null, [spectra, selectedId]);
  // "" is a real value while the field is mid-edit (FitScreen shows its own parse error for
  // it); Discover only wants a skeleton when there is one, so a blank field means null.
  const skeleton = circuit.trim() === "" ? null : circuit;

  return (
    <div className="app">
      <header className="app-header">
        <h1>AutoCircuit</h1>
        <StatusBar stage={stage} detail={detail} versions={versions} bootError={bootError} />
        <ThemeToggle choice={themeChoice} onChoice={setTheme} />
      </header>

      <nav className="app-tabs">
        {SCREENS.map(([name, title]) => (
          <button
            key={name}
            type="button"
            className={`app-tab${screen === name ? " app-tab--active" : ""}`}
            onClick={() => setScreen(name)}
            aria-current={screen === name ? "page" : undefined}
          >
            {title}
          </button>
        ))}
      </nav>

      {/* Only the plots read this, and they read it as a value rather than as CSS -- Plotly draws
          into a canvas, which no stylesheet reaches. It wraps the screens rather than the page
          because nothing above here has a colour that is not already a custom property. */}
      <ThemeContext.Provider value={theme}>
        {screen === "data" ? (
          <DataScreen
            ready={ready}
            dragActive={dragActive}
            formats={versions?.formats ?? []}
            spectra={spectra}
            selected={selected}
            selectedId={selectedId}
            fileErrors={fileErrors}
            onFiles={handleFiles}
            onSelect={setSelectedId}
            onRemove={removeSpectrum}
            onDismissError={dismissFileError}
            onApplyTrim={applyTrim}
            onResetTrim={resetTrim}
          />
        ) : screen === "fit" ? (
          <FitScreen
            client={client}
            ready={ready}
            catalogue={catalogue}
            spectrum={selected}
            circuit={circuit}
            onCircuit={setCircuit}
            state={fitState}
            onState={setFitState}
          />
        ) : screen === "discover" ? (
          <DiscoverScreen
            client={client}
            ready={ready}
            catalogue={catalogue}
            spectrum={selected}
            skeleton={skeleton}
            search={search}
            settings={settings}
            onSettings={changeSettings}
            criteria={versions?.criteria ?? []}
            onStart={(spectrumToSearch) => void startSearch(spectrumToSearch, skeleton)}
            onCancel={cancelSearch}
            onPick={(row) => void pickCandidate(row)}
            onFitCircuit={fitCircuit}
          />
        ) : (
          <ReportScreen
            client={client}
            ready={ready}
            spectra={spectra}
            spectrum={selected}
            discovery={discovery}
            manualFit={manualFit}
            excluded={excluded}
            drt={drt}
            onRunExcluded={() => void runExcluded()}
            onCancelExcluded={cancelExcluded}
            onRunDrt={(wire) => void runDrt(wire)}
          />
        )}
      </ThemeContext.Provider>
    </div>
  );
}
