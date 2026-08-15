// The shell: one Pyodide client, one worker pool, the spectra everything else works on, and
// which screen is showing. The screens themselves are in src/screens/ -- Data (load, validate,
// trim), Fit (draw a circuit, fit it), Discover (search for one) and Report (read the answer,
// and take it away). They share the loaded spectra because a fit is fitted to the spectrum the
// Data screen has selected, in the window it has been trimmed to.
//
// What lives here rather than in a screen is anything that must outlive a tab switch. A screen
// is unmounted the moment the user looks at another one, so state left inside it is state the
// user loses by glancing away: the drawn circuit, the finished search, the manual fit, and the
// two long-running jobs the Report screen starts. The pool is here for the same reason plus one
// more -- two screens run work on it, and a second pool would be four more Pyodide workers.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BridgeClient, BridgeError, type SearchOptions } from "./worker/client";
import type { LoadStage } from "./worker/protocol";
import type {
  DrtWire,
  ExcludedReportWire,
  FitWire,
  LoadedSpectrum,
  ReportWire,
  SpectrumWire,
  VersionsWire,
} from "./core/types";
import { ExcludedRun, idleExcluded, type ExcludedProgress } from "./core/excluded";
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
import { FitScreen, INITIAL_CIRCUIT } from "./screens/FitScreen";
import { ReportScreen } from "./screens/ReportScreen";

type Screen = "data" | "fit" | "discover" | "report";

const SCREENS: ReadonlyArray<readonly [Screen, string]> = [
  ["data", "Data"],
  ["fit", "Fit"],
  ["discover", "Discover"],
  ["report", "Report"],
];

/**
 * A finished search, and the options it ran with.
 *
 * The options travel with the report because the excluded-equivalents pass on the Report screen
 * is a continuation of *this* search and has to screen with the same weighting and seed. The job
 * id is inside the report itself.
 */
export interface Discovery {
  report: ReportWire;
  options: SearchOptions;
  /** The pool size that search ran on, so its continuation does not rebuild the pool. */
  workers: number;
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
  // Both live here because two screens need them: the Discover screen produces a report and the
  // Report screen reads it, and the Fit screen produces a fit that the Report screen exports.
  const [discovery, setDiscovery] = useState<Discovery | null>(null);
  const [manualFit, setManualFit] = useState<ManualFit | null>(null);
  const [search, setSearch] = useState<SearchSettings>(defaultSearchSettings);
  const [excluded, setExcluded] = useState<ExcludedState | null>(null);
  const [drt, setDrt] = useState<DrtState | null>(null);
  const excludedRun = useRef<ExcludedRun | null>(null);

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
    client.ready().then(setVersions).catch((err: unknown) => setBootError(errorMessage(err)));
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
  const changeSearch = useCallback((change: Partial<SearchSettings>) => {
    setSearch((prev) => ({ ...prev, ...change }));
  }, []);

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
            spectrum={selected}
            circuit={circuit}
            onCircuit={setCircuit}
            onFit={setManualFit}
          />
        ) : screen === "discover" ? (
          <DiscoverScreen
            client={client}
            ready={ready}
            spectrum={selected}
            skeleton={skeleton}
            acquirePool={acquirePool}
            settings={search}
            onSettings={changeSearch}
            onReport={setDiscovery}
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
