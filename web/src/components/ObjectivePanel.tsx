// What the reader came for, applied to a search that has already finished.
//
// `CLAUDE.md`'s Objectives section: there are two reasons to bring a spectrum here and they want
// different reports out of the *same* analysis. Four things about this panel are decisions
// rather than layout:
//
//  * **The objective is asked of the report, never of the search.** The switch below re-fetches
//    `discover_objective`; it cannot re-run, re-rank or re-recommend anything, because
//    `discoverStart` takes no objective and `core/discover.py` cannot receive one. That is gate
//    O1's structural half (`docs/OBJECTIVE_PLAN.md`), and it is why switching is instant.
//  * **The sentences arrive rendered.** `summary` is composed in Python and shown verbatim,
//    exactly as `completeness` is, because the part that says what may *not* be claimed is the
//    part a second implementation in TypeScript would get subtly wrong. The tables beside it are
//    the same numbers in a form that can be scanned, not a paraphrase of the prose.
//  * **Under `model` the equivalence class is a non-problem, and saying so is still work.** The
//    members have the same terminal Z over the measured band, so they export and simulate
//    identically -- and they are free to differ outside it, which is why the band is shown as
//    part of the deliverable rather than as a footnote to it.
//  * **Under `interpret` the class is the question.** Every quantity carries what the whole
//    class said: `spread` where they agree, and a plain warning where they do not. A reading
//    shown without that is a form-dependent number presented as a measurement.
//
// It is re-fetched rather than stored: the answer is arithmetic over fits the worker already
// holds, so re-deriving it costs nothing and cannot go stale against the search it describes
// (`docs/SCREEN_STATE_PLAN.md` -- a screen owns only what is being typed).

import { useEffect, useState } from "react";

import type { InterpretationWire, ModelReportWire, Objective, ObjectiveAnswer } from "../core/types";
import { decodeFloat } from "../core/wire";
import type { BridgeClient } from "../worker/client";

export interface ObjectivePanelProps {
  client: BridgeClient;
  /** The finished search this reads. Null while none has finished. */
  job: string | null;
  /** The circuit to report; null means the search's own recommendation. */
  circuit: string | null;
  ready: boolean;
}

const CHOICES: Array<{ objective: Objective; label: string; hint: string }> = [
  {
    objective: "model",
    label: "A circuit to simulate with",
    hint: "The deliverable is the circuit and the band it reproduces the measurement over.",
  },
  {
    objective: "interpret",
    label: "What is inside the part",
    hint: "The deliverable is the processes the spectrum can distinguish, and its claim is conditional.",
  },
];

function formatValue(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const magnitude = Math.abs(value);
  if (magnitude !== 0 && (magnitude < 1e-3 || magnitude >= 1e5)) return value.toExponential(4);
  return value.toPrecision(6).replace(/\.?0+$/, "");
}

function percent(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return `${(value * 100).toPrecision(3)}%`;
}

function ModelBody({ model }: { model: ModelReportWire }) {
  const fMin = decodeFloat(model.band.f_min);
  const fMax = decodeFloat(model.band.f_max);
  return (
    <>
      <p className="interpretation__intro">
        <code>{model.circuit}</code> reproduces the measurement over{" "}
        <strong>
          {formatValue(fMin)} Hz – {formatValue(fMax)} Hz
        </strong>
        , which is the band that was measured. Outside it this model is extrapolation and nothing
        here has tested it. Inside it: RMS |dZ|/|Z| {percent(decodeFloat(model.relative_error))},
        worst point {percent(decodeFloat(model.worst_relative_error))}, reduced chi²{" "}
        {formatValue(decodeFloat(model.chi2_reduced))}.
      </p>

      <table className="interpretation__table">
        <thead>
          <tr>
            <th>Readout</th>
            <th className="num">Value</th>
            <th>Unit</th>
            <th>Read at</th>
          </tr>
        </thead>
        <tbody>
          {model.readouts.map((q) => (
            <tr key={q.name}>
              <td>
                <code>{q.name}</code>
              </td>
              <td className="num">{formatValue(decodeFloat(q.value))}</td>
              <td>{q.unit === "-" ? "" : q.unit}</td>
              <td>{q.note ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {model.readouts.length === 0 && (
        <p className="empty-hint">
          Nothing the measured band determines: this part is neither capacitive nor inductive
          anywhere in it, and every terminal readout is gated on the response it describes.
        </p>
      )}

      <table className="interpretation__table">
        <thead>
          <tr>
            <th>Frequency</th>
            <th className="num">ESR = Re Z of this model</th>
          </tr>
        </thead>
        <tbody>
          {model.esr_curve.map((point) => (
            <tr key={String(point.f_hz)}>
              <td>{formatValue(decodeFloat(point.f_hz))} Hz</td>
              <td className="num">{formatValue(decodeFloat(point.esr_ohm))} Ω</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* What the equivalence class means here, and what an unresolved parameter means here.
          Both are composed in Python: they are statements about what may be claimed. */}
      {model.notes.map((note) => (
        <p className="interpretation__intro" key={note.slice(0, 40)}>
          {note}
        </p>
      ))}
    </>
  );
}

function InterpretBody({ reading }: { reading: InterpretationWire }) {
  const members = reading.class_members ?? [];
  const counts = reading.class_relaxation_counts ?? [];
  const disagreesOnCount = new Set(counts).size > 1;
  const spreadOf = new Map((reading.class_spread ?? []).map((row) => [row.name, row] as const));

  return (
    <>
      <p className="interpretation__intro">
        Read from the impedance alone, so every quantity here is geometry-free: a capacitance and
        not a permittivity, a time constant and not a diffusion coefficient.
      </p>
      <p className="interpretation__intro">
        {members.length > 1
          ? `Which of them are properties of the measurement and which only of the circuit form
             is checked against the ${members.length - 1} other topolog${
               members.length === 2 ? "y" : "ies"
             } this search could not tell apart from it.`
          : "Which of them are properties of the measurement and which only of this circuit form" +
            " is a distinction nothing here could check: no other topology this search found" +
            " reproduces the same response, so there is no second form to disagree with it."}
      </p>

      {disagreesOnCount && (
        <p className="discover-report__warning" role="alert">
          These topologies do not agree on how many relaxations this part shows —{" "}
          {members.map((name, i) => `${name} says ${counts[i]}`).join(", ")}. That count is a
          property of the form that was reported, not of the measurement, and choosing between the
          forms takes physical knowledge of the sample rather than more fitting.
        </p>
      )}

      <table className="interpretation__table">
        <thead>
          <tr>
            <th>Quantity</th>
            <th className="num">Value</th>
            <th>Unit</th>
            <th>Holds for</th>
          </tr>
        </thead>
        <tbody>
          {reading.quantities.map((q) => {
            const spread = spreadOf.get(q.name);
            const partial = spread !== undefined && spread.reported_by < members.length;
            return (
              <tr key={q.name} className={q.invariant ? "" : "interpretation__form"}>
                <td>
                  <code>{q.name}</code>
                </td>
                <td className="num">{formatValue(decodeFloat(q.value))}</td>
                <td>{q.unit}</td>
                <td>
                  {/* A class of one agrees with itself, which is not evidence. Only a real
                      comparison earns the figure. */}
                  {partial
                    ? `only ${spread?.reported_by} of ${members.length} forms report it`
                    : !q.invariant
                      ? "this circuit form only"
                      : members.length > 1 && spread !== undefined
                        ? `the measurement (all ${members.length} agree to ${(
                            decodeFloat(spread.spread) * 100
                          ).toPrecision(2)}%)`
                        : "the measurement (unchecked: only one form found)"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}

export function ObjectivePanel({ client, job, circuit, ready }: ObjectivePanelProps) {
  const [objective, setObjective] = useState<Objective>("model");
  const [answer, setAnswer] = useState<ObjectiveAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || job === null) {
      setAnswer(null);
      return;
    }
    let cancelled = false;
    setError(null);
    setAnswer(null);
    client
      .discoverObjective(job, objective, circuit)
      .then((result) => {
        if (!cancelled) setAnswer(result);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [client, job, circuit, objective, ready]);

  if (job === null) return null;

  const chosen = CHOICES.find((choice) => choice.objective === objective);
  const body = answer?.objective ?? null;

  return (
    <section className="interpretation">
      <h2 className="panel-title">What did you come here for?</h2>
      <div className="theme-toggle" role="group" aria-label="Objective">
        {CHOICES.map((choice) => (
          <button
            key={choice.objective}
            type="button"
            className={
              choice.objective === objective
                ? "theme-toggle__button theme-toggle__button--active"
                : "theme-toggle__button"
            }
            aria-pressed={choice.objective === objective}
            onClick={() => setObjective(choice.objective)}
          >
            {choice.label}
          </button>
        ))}
      </div>
      <p className="interpretation__intro">
        {chosen?.hint} It changes this report and nothing else: the circuit above and every value
        in it are the same whichever you pick.
      </p>

      {error !== null && (
        <p className="discover-report__warning" role="alert">
          The report could not be computed: {error}
        </p>
      )}

      {answer === null && error === null && <p className="empty-hint">Reading…</p>}

      {body !== null && answer !== null && (
        <>
          {body.unavailable !== undefined && <p className="empty-hint">{body.unavailable}</p>}
          {body.model !== undefined && <ModelBody model={body.model} />}
          {body.interpretation !== undefined && (
            <InterpretBody reading={body.interpretation} />
          )}
          {body.notes.map((note) => (
            <p className="interpretation__intro" key={note.slice(0, 40)}>
              {note}
            </p>
          ))}
          <details className="discover-report__full">
            <summary>The report in full, as the command line prints it</summary>
            <pre>{answer.summary}</pre>
          </details>
        </>
      )}
    </section>
  );
}
