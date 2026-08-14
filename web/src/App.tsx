// The shell: one Pyodide client, the spectra everything else works on, and which screen is
// showing. The screens themselves are in src/screens/ -- Data (load, validate, trim) and Fit
// (draw a circuit, fit it). They share the loaded spectra because a fit is fitted to the
// spectrum the Data screen has selected, in the window it has been trimmed to.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BridgeClient, BridgeError } from "./worker/client";
import type { LoadStage } from "./worker/protocol";
import type { LoadedSpectrum, SpectrumWire, VersionsWire } from "./core/types";
import { StatusBar } from "./components/StatusBar";
import { DataScreen, type FileError } from "./screens/DataScreen";
import { DiscoverScreen } from "./screens/DiscoverScreen";
import { FitScreen, INITIAL_CIRCUIT } from "./screens/FitScreen";

type Screen = "data" | "fit" | "discover";

const SCREENS: ReadonlyArray<readonly [Screen, string]> = [
  ["data", "Data"],
  ["fit", "Fit"],
  ["discover", "Discover"],
];

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

  const [screen, setScreen] = useState<Screen>("data");
  // Owned here, not by FitScreen, because the Discover screen offers this same circuit as a
  // search skeleton -- a partly drawn circuit is already exactly what `discover(skeleton=...)`
  // takes (see FitScreen's own header comment).
  const [circuit, setCircuit] = useState(INITIAL_CIRCUIT);
  const [spectra, setSpectra] = useState<LoadedSpectrum[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [fileErrors, setFileErrors] = useState<FileError[]>([]);
  const [dragActive, setDragActive] = useState(false);

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

  const selected = useMemo(() => spectra.find((s) => s.id === selectedId) ?? null, [spectra, selectedId]);
  // "" is a real value while the field is mid-edit (FitScreen shows its own parse error for
  // it); Discover only wants a skeleton when there is one, so a blank field means null.
  const skeleton = circuit.trim() === "" ? null : circuit;

  return (
    <div className="app">
      <header className="app-header">
        <h1>AutoCircuit</h1>
        <StatusBar stage={stage} detail={detail} versions={versions} bootError={bootError} />
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
        />
      ) : (
        <DiscoverScreen client={client} ready={ready} spectrum={selected} skeleton={skeleton} />
      )}
    </div>
  );
}
