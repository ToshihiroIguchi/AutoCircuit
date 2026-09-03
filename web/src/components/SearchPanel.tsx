// The Discover controls and the Discover/Cancel button. Mirrors `FitPanel`'s shape: a row of
// controls, a run button, and the state-dependent text under it -- except a search is a job, not
// an interactive request, so the button toggles into Cancel instead of just showing "busy".

import type { CatalogueWire, CriterionWire } from "../core/types";
import { AUTO_POOL, CUSTOM_POOL } from "../core/types";
import { MAX_WORKERS } from "../worker/pool";
import { SymbolPreview } from "./ElementSymbol";

export interface SearchPanelProps {
  /** The model-selection menu, from the running core's own registry rather than from here. */
  criteria: CriterionWire[];
  criterion: string;
  onCriterion: (value: string) => void;
  poolNames: string[];
  poolName: string;
  onPoolName: (name: string) => void;
  /** The element catalogue the custom pool is built from; null until the worker has answered. */
  catalogue: CatalogueWire | null;
  /** Codes checked for the custom pool, used only while `poolName === CUSTOM_POOL`. */
  customPool: string[];
  onCustomPool: (codes: string[]) => void;
  exhaustiveLimit: number;
  onExhaustiveLimit: (value: number) => void;
  useSkeleton: boolean;
  onUseSkeleton: (value: boolean) => void;
  skeleton: string | null;
  workers: number;
  onWorkers: (value: number) => void;
  seed: number;
  onSeed: (value: number) => void;
  weighting: string;
  onWeighting: (value: string) => void;
  running: boolean;
  disabled: boolean;
  /**
   * Gates the Discover button alone. Distinct from `disabled` -- which locks every control,
   * the custom-pool checkboxes included -- because an empty custom pool must stop a run without
   * also locking the checkboxes a user would need to fix it, which is a deadlock a user cannot
   * get out of.
   */
  startDisabled: boolean;
  error: string | null;
  onStart: () => void;
  onCancel: () => void;
}

const WEIGHTINGS = ["modulus", "proportional", "unit"];

export function SearchPanel(props: SearchPanelProps) {
  const locked = props.disabled || props.running;
  const chosen = props.criteria.find((entry) => entry.name === props.criterion) ?? null;

  return (
    <section className="search-panel">
      <h2 className="panel-title">Discover</h2>

      <div className="search-panel__controls">
        <label>
          Pool
          <select
            value={props.poolName}
            disabled={locked}
            onChange={(event) => props.onPoolName(event.target.value)}
          >
            {props.poolNames.map((name) => (
              <option key={name} value={name}>
                {name === AUTO_POOL
                  ? "auto — the spectrum chooses"
                  : name === CUSTOM_POOL
                    ? "custom — choose elements"
                    : name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Element limit
          <input
            type="number"
            min={1}
            max={10}
            value={props.exhaustiveLimit}
            disabled={locked}
            onChange={(event) => props.onExhaustiveLimit(Number(event.target.value))}
          />
        </label>
        <label>
          Workers
          <input
            type="number"
            min={1}
            max={MAX_WORKERS}
            value={props.workers}
            disabled={locked}
            onChange={(event) => props.onWorkers(Number(event.target.value))}
          />
        </label>
        <label>
          Weighting
          <select
            value={props.weighting}
            disabled={locked}
            onChange={(event) => props.onWeighting(event.target.value)}
          >
            {WEIGHTINGS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label title={chosen?.note ?? ""}>
          Criterion
          <select
            value={props.criterion}
            disabled={locked}
            onChange={(event) => props.onCriterion(event.target.value)}
          >
            {props.criteria.map((entry) => (
              <option key={entry.name} value={entry.name}>
                {entry.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Seed
          <input
            type="number"
            value={props.seed}
            disabled={locked}
            onChange={(event) => props.onSeed(Number(event.target.value))}
          />
        </label>

        {props.running ? (
          <button type="button" className="search-panel__cancel" onClick={props.onCancel}>
            Cancel
          </button>
        ) : (
          <button
            type="button"
            className="search-panel__run"
            disabled={props.startDisabled}
            onClick={props.onStart}
          >
            Discover
          </button>
        )}
      </div>

      {/* The CLI's `--pool` already takes a comma list of arbitrary codes (`main.py`); this is
          that same freedom on the web side, since a named pool is an assertion about the part
          and the person running this search may know something the presets do not group
          together. */}
      {props.poolName === CUSTOM_POOL && (
        <div className="search-panel__custom-pool">
          {props.catalogue === null ? (
            <p className="search-panel__hint">Waiting for the element catalogue…</p>
          ) : (
            <>
              {/* Named presets (`component`, `electrochemical`, ...) are an assertion about the
                  part, same footing as a skeleton -- so they live here as a starting point for
                  the custom pool rather than as a second, ambiguous default beside `auto`. */}
              <div className="search-panel__pool-presets">
                {Object.entries(props.catalogue.pools).map(([name, codes]) => (
                  <button
                    type="button"
                    key={name}
                    className="search-panel__pool-preset"
                    disabled={locked}
                    onClick={() => props.onCustomPool([...codes])}
                  >
                    {name}
                  </button>
                ))}
              </div>
              <ul className="search-panel__custom-pool-list">
                {props.catalogue.elements.map((element) => {
                  const checked = props.customPool.includes(element.code);
                  return (
                    <li key={element.code}>
                      <label title={element.name}>
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={locked}
                          onChange={(event) => {
                            const next = event.target.checked
                              ? [...props.customPool, element.code]
                              : props.customPool.filter((code) => code !== element.code);
                            props.onCustomPool(next);
                          }}
                        />
                        <SymbolPreview code={element.code} />
                        <span className="search-panel__custom-pool-code">{element.code}</span>
                      </label>
                    </li>
                  );
                })}
              </ul>
              {props.customPool.length === 0 && (
                <p className="search-panel__hint">
                  Check at least one element to search with a custom pool.
                </p>
              )}
            </>
          )}
        </div>
      )}

      {/* There is no genetic fallback in the browser (docs/WEB_UI_PLAN.md section 7), so a
          topology above this limit was never a candidate -- not screened, not rejected, simply
          not looked at. That is different from "not found" and the control says so. */}
      <p className="search-panel__hint">
        Exhaustive search only: every topology with up to this many elements from the pool is
        evaluated, and nothing above the limit is searched at all.
      </p>

      {/* The criterion is a search setting rather than a view of the answer, and it has to be
          said out loud: it also ranks the shortlist, so it decides which topologies get a
          full-budget fit at all. Re-sorting a finished report by another criterion would be
          re-sorting a list whose members a different criterion had chosen. */}
      {chosen !== null && (
        <p className="search-panel__hint search-panel__hint--criterion">
          <strong>{chosen.label}:</strong> {chosen.note} It ranks the results and the shortlist —
          so it is part of the search, not a view of it. It does not change the recommendation,
          which is the simplest model that fits as well as any <em>and</em> whose parameters the
          data resolves.
        </p>
      )}

      <label className="search-panel__skeleton">
        <input
          type="checkbox"
          checked={props.useSkeleton}
          disabled={locked || props.skeleton === null}
          onChange={(event) => props.onUseSkeleton(event.target.checked)}
        />
        {props.skeleton === null ? (
          <span>Restrict to a skeleton -- draw a circuit on the Fit screen first.</span>
        ) : (
          <span>
            Restrict to topologies containing <code>{props.skeleton}</code>, the circuit drawn on
            the Fit screen. This is your assertion, not a finding, and the report will say so.
          </span>
        )}
      </label>

      {props.error !== null && (
        <p className="search-panel__error" role="alert">
          {props.error}
        </p>
      )}
    </section>
  );
}
