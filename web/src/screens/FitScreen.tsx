// The Fit screen: draw a circuit, watch it against the data, press Fit.
//
// The whole point of this screen is what it does *not* ask for. There is no place to type a
// starting guess, because the fitter does not need one: the interval it searches comes from the
// measured frequency range and impedance magnitude, and the value it starts from is the centre
// of that interval. A number typed in the parameter table moves the preview curve; it does not
// seed the fit. `ParameterTable` says so in as many words, because the arrangement implies
// otherwise to anyone who has used software that does need a guess.
//
// The canvas is also, already, a skeleton editor: a partly drawn circuit is exactly what
// `discover(skeleton=...)` takes. Step 4 adds the button; nothing here has to change for it.
//
// What this screen keeps and what `App` keeps is the rule in `docs/SCREEN_STATE_PLAN.md`: the fit,
// the values it produced, the holds and bounds it honoured and the settings it ran with are
// *results* and live in `App`, because a tab switch unmounts this component. What stays here is
// what the user is composing -- the armed palette button, the selected element, the parse error --
// and whatever a single round trip recomputes from the circuit string.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  CatalogueWire,
  CircuitNodeWire,
  CircuitWire,
  FitWire,
  LoadedSpectrum,
  PreviewWire,
  SpectrumWire,
} from "../core/types";
import { decodeArray, decodeComplexArray, decodeFloat } from "../core/wire";
import { BridgeClient, BridgeError } from "../worker/client";
import { CircuitCanvas } from "../components/CircuitCanvas";
import { ElementPalette } from "../components/ElementPalette";
import { FitPanel } from "../components/FitPanel";
import { ParameterTable } from "../components/ParameterTable";
import { PlotsPanel, type ModelOverlay } from "../components/PlotsPanel";
import { RuntimeNotice } from "../components/RuntimeNotice";

/** The simplest circuit there is. Anything else would be a guess about the device. */
export const INITIAL_CIRCUIT = "R1";

/**
 * Everything about a manual fit that must outlive a glance at another tab.
 *
 * Held by `App`. The async fit writes through `App`'s setter rather than this screen's, which is
 * what lets a fit that lands while the user is elsewhere still arrive.
 */
export interface FitState {
  /** What the user typed, or what the last fit produced, by parameter name. */
  values: Record<string, number>;
  /** Parameters the fitter must not move. */
  held: string[];
  bounds: Record<string, [number, number]>;
  /**
   * The finished fit, and enough about it to know when it stops being about what is on screen.
   *
   * `signature` is the circuit-and-values this fit describes: editing either retires it, so
   * fitted numbers never sit beside a model they no longer belong to. The spectrum travels as
   * itself and not as a reference, because an export is a claim about *which data was fitted* --
   * a netlist header states the frequency window the model is valid over.
   */
  fit: {
    result: FitWire;
    signature: string;
    spectrumId: string;
    spectrum: SpectrumWire;
  } | null;
  fitting: boolean;
  error: string | null;
  /** What a fit runs with. Provenance too: the panel must never show a fit under other settings. */
  weighting: string;
  restarts: number;
  seed: number;
}

export function defaultFitState(): FitState {
  return {
    values: {},
    held: [],
    bounds: {},
    fit: null,
    fitting: false,
    error: null,
    weighting: "modulus",
    restarts: 5,
    seed: 0,
  };
}

export interface FitScreenProps {
  client: BridgeClient;
  ready: boolean;
  /** The element catalogue, fetched once by `App`; null until the worker has answered. */
  catalogue: CatalogueWire | null;
  spectrum: LoadedSpectrum | null;
  /** Lifted into `App` so the Discover screen can offer this circuit as a search skeleton. */
  circuit: string;
  onCircuit: (value: string) => void;
  /** The session's fit state, and the setter that owns it. */
  state: FitState;
  onState: (update: (previous: FitState) => FitState) => void;
}

function errorMessage(error: unknown): string {
  return error instanceof BridgeError || error instanceof Error ? error.message : String(error);
}

/** Find an element by its label; labels are unique within a circuit, which is what makes the
 *  canvas and the parameter table able to point at the same thing. */
function pathOfLabel(node: CircuitNodeWire, label: string): number[] | null {
  if (node.kind === "element") return node.label === label ? node.path : null;
  for (const child of node.children) {
    const found = pathOfLabel(child, label);
    if (found !== null) return found;
  }
  return null;
}

function labelAtPath(node: CircuitNodeWire, path: number[]): string | null {
  if (node.kind === "element") return path.length === 0 ? node.label : null;
  const [index, ...rest] = path;
  const child = node.children[index as number];
  return child === undefined ? null : labelAtPath(child, rest);
}

export function FitScreen({
  client,
  ready,
  catalogue,
  spectrum,
  circuit: circuitText,
  onCircuit: setCircuitText,
  state,
  onState,
}: FitScreenProps) {
  const wire = spectrum?.current ?? null;
  const { values, held, bounds, fitting, weighting, restarts, seed } = state;

  const [describe, setDescribe] = useState<CircuitWire | null>(null);
  const [circuitError, setCircuitError] = useState<string | null>(null);
  const [armedCode, setArmedCode] = useState<string | null>(null);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewWire | null>(null);
  const [editing, setEditing] = useState(false);

  /** One change to the session's fit state. */
  const update = useCallback(
    (change: Partial<FitState>) => onState((previous) => ({ ...previous, ...change })),
    [onState],
  );
  const setError = useCallback((message: string | null) => update({ error: message }), [update]);

  // What the last `circuit` request asked about. Comparing against this rather than against the
  // answer is what keeps an equivalent-but-differently-spelled string ("C1 - R1") from being
  // re-requested forever once Python answers with its own formatting.
  const asked = useRef<{ text: string; wire: SpectrumWire | null } | null>(null);
  const previewTicket = useRef(0);

  /** Store a parsed circuit and drop any hold or bound that its parameters no longer have. */
  const adopt = useCallback(
    (result: CircuitWire) => {
      const names = new Set(result.params.map((param) => param.name));
      setDescribe(result);
      setCircuitError(null);
      onState((previous) => {
        const heldKept = previous.held.filter((name) => names.has(name));
        const boundEntries = Object.entries(previous.bounds).filter(([name]) => names.has(name));
        if (
          heldKept.length === previous.held.length &&
          boundEntries.length === Object.keys(previous.bounds).length
        ) {
          return previous;
        }
        return { ...previous, held: heldKept, bounds: Object.fromEntries(boundEntries) };
      });
    },
    [onState],
  );

  // Parse whatever is in the text field. A syntax error leaves the last good circuit on the
  // canvas: the user is usually mid-edit, and blanking the screen at every intermediate
  // keystroke would be worse than showing the message under the field.
  useEffect(() => {
    if (!ready) return undefined;
    const text = circuitText.trim();
    if (text === "") {
      setCircuitError("Enter a circuit, for example R1-p(R2,C1).");
      return undefined;
    }
    if (asked.current !== null && asked.current.text === text && asked.current.wire === wire) {
      return undefined;
    }
    const timer = setTimeout(() => {
      asked.current = { text, wire };
      client
        .circuit(text, wire === null ? {} : { spectrum: wire })
        .then(adopt)
        .catch((err: unknown) => setCircuitError(errorMessage(err)));
    }, 250);
    return () => clearTimeout(timer);
  }, [client, ready, circuitText, wire, adopt]);

  const params = describe?.params ?? [];

  /** Every parameter's current value: what the user typed, or what the fitter would start from. */
  const effective = useMemo(() => {
    const out: Record<string, number> = {};
    for (const param of params) {
      const start = param.start === undefined ? 0 : decodeFloat(param.start);
      out[param.name] = values[param.name] ?? start;
    }
    return out;
  }, [params, values]);

  const signature = `${describe?.circuit ?? ""}|${JSON.stringify(effective)}`;
  const currentFit = state.fit !== null && state.fit.signature === signature ? state.fit.result : null;

  // Retire a fit the moment it stops describing what is on screen -- an edit to the circuit or to
  // any value. Done as a write rather than as a filter on read, because the Report screen's
  // exports come off the same record: it must not be possible to download a fit this screen is
  // no longer showing (docs/SCREEN_STATE_PLAN.md section 2 measured that pair the other way
  // round).
  //
  // Guarded on `describe`, which is null for one round trip after a mount or a circuit change.
  // Without the guard, walking to the Report screen and back would retire a fit that nothing
  // about the model had invalidated -- there would simply be no parsed circuit yet to compare to.
  useEffect(() => {
    if (describe === null) return;
    onState((previous) =>
      previous.fit === null || previous.fit.signature === signature
        ? previous
        : { ...previous, fit: null },
    );
  }, [describe, signature, onState]);

  // The preview curve. It is recomputed for every change to the circuit or to a value, which is
  // cheap: one impedance evaluation, no fitting.
  useEffect(() => {
    if (!ready || describe === null || wire === null) {
      setPreview(null);
      return;
    }
    const ticket = previewTicket.current + 1;
    previewTicket.current = ticket;
    client
      .preview(describe.circuit, effective, { spectrum: wire })
      .then((result) => {
        if (previewTicket.current === ticket) setPreview(result);
      })
      .catch((err: unknown) => {
        if (previewTicket.current === ticket) setError(errorMessage(err));
      });
  }, [client, ready, describe, effective, wire, setError]);

  const applyEdit = useCallback(
    async (request: Parameters<BridgeClient["edit"]>[0]) => {
      setEditing(true);
      setError(null);
      try {
        const result = await client.edit(request, wire === null ? {} : { spectrum: wire });
        asked.current = { text: result.circuit, wire };
        setCircuitText(result.circuit);
        adopt(result);
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setEditing(false);
      }
    },
    [client, wire, adopt, setError],
  );

  // Every write below goes through `onState`, which belongs to `App`: a fit that lands while the
  // user is reading another tab therefore arrives, instead of being dropped into a component that
  // no longer exists.
  const spectrumId = spectrum?.id ?? null;
  const handleFit = useCallback(async () => {
    if (describe === null || wire === null || spectrumId === null) return;
    update({ fitting: true, error: null });
    try {
      const fixed: Record<string, number> = {};
      for (const name of held) if (name in effective) fixed[name] = effective[name] as number;
      const result = await client.fitCircuit(
        describe.circuit,
        { weighting, restarts, seed },
        { spectrum: wire, fixed, bounds },
      );
      // Adopt the fitted values, and remember the state this fit describes so that the next
      // edit to the circuit or to a value retires it instead of leaving stale numbers beside a
      // model they no longer belong to.
      const fitted = decodeArray(result.fit.values);
      const next: Record<string, number> = { ...values };
      const shown: Record<string, number> = {};
      params.forEach((param, index) => {
        next[param.name] = fitted[index] as number;
        shown[param.name] = fitted[index] as number;
      });
      update({
        values: next,
        fit: {
          result,
          signature: `${describe.circuit}|${JSON.stringify(shown)}`,
          spectrumId,
          // The window as it was when the fit ran. A later trim of the same spectrum must not
          // silently re-label this fit as having been made against the new one.
          spectrum: wire,
        },
      });
    } catch (err) {
      update({ error: errorMessage(err) });
    } finally {
      update({ fitting: false });
    }
  }, [client, describe, wire, spectrumId, held, effective, values, params, weighting, restarts, seed, bounds, update]);

  const model: ModelOverlay | null = useMemo(() => {
    if (currentFit !== null) {
      const { re, im } = decodeComplexArray(currentFit.fit.z_model);
      return {
        label: "Fit",
        re,
        im,
        residualReal: decodeArray(currentFit.residual_real),
        residualImag: decodeArray(currentFit.residual_imag),
        residualTitle: `Fit residuals (${currentFit.fit.weighting} weighting)`,
        residualUnit: "weighted",
        residualPlaceholder: "",
      };
    }
    if (preview !== null && describe !== null && preview.circuit === describe.circuit) {
      const { re, im } = decodeComplexArray(preview.z_model);
      return {
        label: "Preview",
        re,
        im,
        residualReal: null,
        residualImag: null,
        residualTitle: "Residuals",
        residualUnit: "%",
        residualPlaceholder: "Press Fit to see the residuals of a fitted model.",
      };
    }
    return null;
  }, [currentFit, preview, describe]);

  const selectedPath =
    describe === null || selectedLabel === null ? null : pathOfLabel(describe.tree, selectedLabel);

  if (spectrum === null) {
    return (
      <>
        <RuntimeNotice ready={ready} />
        <p className="empty-hint">
          Load a spectrum on the Data screen first: a circuit is fitted to data, and the search
          bounds are derived from the data too.
        </p>
      </>
    );
  }

  return (
    <div className="fit-screen">
      <RuntimeNotice ready={ready} />
      <div className="fit-screen__build">
        {catalogue !== null && (
          <ElementPalette catalogue={catalogue} armedCode={armedCode} onArm={setArmedCode} />
        )}

        <section className="circuit-panel">
          <h2 className="panel-title">Circuit</h2>
          {describe === null ? (
            <p className="empty-hint">Parsing…</p>
          ) : (
            <CircuitCanvas
              tree={describe.tree}
              selectedPath={selectedPath}
              armedCode={armedCode}
              busy={editing || fitting}
              onSelect={(path) => setSelectedLabel(labelAtPath(describe.tree, path))}
              onInsert={(path, action, position, code) =>
                void applyEdit({ circuit: describe.circuit, path, action, position, code })
              }
              onRemove={(path) =>
                void applyEdit({ circuit: describe.circuit, path, action: "remove" })
              }
            />
          )}

          <label className="circuit-panel__field">
            <span>Circuit</span>
            <input
              type="text"
              value={circuitText}
              spellCheck={false}
              onChange={(event) => setCircuitText(event.target.value)}
              aria-label="Circuit description"
            />
          </label>
          {circuitError !== null && (
            <pre className="circuit-panel__error" role="alert">
              {circuitError}
            </pre>
          )}
          {describe !== null && selectedLabel !== null && catalogue !== null && (
            <div className="circuit-panel__selected">
              <span>{selectedLabel} is a</span>
              <select
                value={params.find((p) => p.label === selectedLabel)?.code ?? ""}
                disabled={editing || fitting}
                aria-label={`Element type of ${selectedLabel}`}
                onChange={(event) => {
                  const path = pathOfLabel(describe.tree, selectedLabel);
                  if (path !== null) {
                    void applyEdit({
                      circuit: describe.circuit,
                      path,
                      action: "replace",
                      code: event.target.value,
                    });
                    setSelectedLabel(null);
                  }
                }}
              >
                {catalogue.elements.map((element) => (
                  <option key={element.code} value={element.code}>
                    {element.code} — {element.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          {describe !== null && (
            <p className="circuit-panel__meta">
              {describe.n_elements} element{describe.n_elements === 1 ? "" : "s"},{" "}
              {describe.n_params} parameter{describe.n_params === 1 ? "" : "s"}
            </p>
          )}
        </section>
      </div>

      <FitPanel
        fit={currentFit}
        preview={preview}
        weighting={weighting}
        restarts={restarts}
        seed={seed}
        fitting={fitting}
        disabled={!ready || describe === null || editing}
        error={state.error}
        onWeighting={(value) => update({ weighting: value })}
        onRestarts={(value) => update({ restarts: value })}
        onSeed={(value) => update({ seed: value })}
        onFit={() => void handleFit()}
      />

      {describe !== null && (
        <ParameterTable
          params={params}
          values={effective}
          fixed={Object.fromEntries(
            held.filter((name) => name in effective).map((name) => [name, effective[name] as number]),
          )}
          bounds={bounds}
          fit={currentFit}
          selectedLabel={selectedLabel}
          disabled={fitting}
          onValue={(name, value) =>
            onState((previous) => ({ ...previous, values: { ...previous.values, [name]: value } }))
          }
          onFix={(name, hold) => {
            // Ticking Fix captures the value as it stands, so the hold means a number rather
            // than a reference to whatever the box shows later.
            onState((previous) =>
              hold
                ? {
                    ...previous,
                    values: { ...previous.values, [name]: effective[name] as number },
                    held: previous.held.includes(name) ? previous.held : [...previous.held, name],
                  }
                : { ...previous, held: previous.held.filter((entry) => entry !== name) },
            );
          }}
          onBound={(name, index, value) =>
            onState((previous) => {
              const param = params.find((entry) => entry.name === name);
              const fallback: [number, number] = [
                param?.lower === undefined ? 0 : decodeFloat(param.lower),
                param?.upper === undefined ? 0 : decodeFloat(param.upper),
              ];
              const next: Record<string, [number, number]> = { ...previous.bounds };
              if (value === null) {
                delete next[name];
                return { ...previous, bounds: next };
              }
              const pair: [number, number] = [...(previous.bounds[name] ?? fallback)];
              pair[index] = value;
              next[name] = pair;
              return { ...previous, bounds: next };
            })
          }
          onSelectLabel={setSelectedLabel}
        />
      )}

      <PlotsPanel key={`fit-plots-${spectrum.id}`} spectrum={spectrum.current} model={model} />
    </div>
  );
}
