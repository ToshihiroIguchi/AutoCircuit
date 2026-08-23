// What the reported circuit says is inside the part -- and what its equivalence class forbids
// it from saying.
//
// `CLAUDE.md`'s purpose point 2: the circuit is a means, and the target is the internal
// structure. Two things about how this is shown are decisions rather than layout:
//
//  * **The sentences arrive rendered.** `summary` is composed in Python and printed verbatim,
//    exactly as `completeness` is, because the part that says what may *not* be claimed is the
//    part a second implementation in TypeScript would get subtly wrong. The table beside it is
//    the same numbers in a form that can be scanned, not a paraphrase of the prose.
//  * **The class is not a footnote.** Under discovery the recommendation is one of several
//    topologies the data cannot tell apart, so every quantity carries what the whole class said:
//    `spread` for the ones they agree on, and a plain warning where they do not. A reading shown
//    without that is a form-dependent number presented as a measurement.
//
// It is re-fetched rather than stored: the answer is arithmetic over fits the worker already
// holds, so re-deriving it costs nothing and cannot go stale against the search it describes
// (`docs/SCREEN_STATE_PLAN.md` -- a screen owns only what is being typed).

import { useEffect, useState } from "react";

import type { InterpretationAnswer } from "../core/types";
import type { BridgeClient } from "../worker/client";

export interface InterpretationPanelProps {
  client: BridgeClient;
  /** The finished search this reads. Null while none has finished. */
  job: string | null;
  /** The circuit to read; null means the search's own recommendation. */
  circuit: string | null;
  ready: boolean;
}

function formatValue(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const magnitude = Math.abs(value);
  if (magnitude !== 0 && (magnitude < 1e-3 || magnitude >= 1e5)) return value.toExponential(4);
  return value.toPrecision(6).replace(/\.?0+$/, "");
}

export function InterpretationPanel({ client, job, circuit, ready }: InterpretationPanelProps) {
  const [answer, setAnswer] = useState<InterpretationAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || job === null) {
      setAnswer(null);
      return;
    }
    let cancelled = false;
    setError(null);
    client
      .discoverInterpret(job, circuit)
      .then((result) => {
        if (!cancelled) setAnswer(result);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [client, job, circuit, ready]);

  if (job === null) return null;

  const reading = answer?.interpretation ?? null;
  const members = reading?.class_members ?? [];
  const counts = reading?.class_relaxation_counts ?? [];
  const disagreesOnCount = new Set(counts).size > 1;
  const spreadOf = new Map(
    (reading?.class_spread ?? []).map((row) => [row.name, row] as const),
  );

  return (
    <section className="interpretation">
      <h2 className="panel-title">What this says is inside the part</h2>
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

      {error !== null && (
        <p className="discover-report__warning" role="alert">
          The interpretation could not be computed: {error}
        </p>
      )}

      {answer === null && error === null && <p className="empty-hint">Reading…</p>}

      {reading !== null && answer !== null && (
        <>
          {disagreesOnCount && (
            <p className="discover-report__warning" role="alert">
              These topologies do not agree on how many relaxations this part shows —{" "}
              {members.map((name, i) => `${name} says ${counts[i]}`).join(", ")}. That count is a
              property of the form that was reported, not of the measurement, and choosing between
              the forms takes physical knowledge of the sample rather than more fitting.
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
                const partial =
                  spread !== undefined && spread.reported_by < members.length;
                return (
                  <tr key={q.name} className={q.invariant ? "" : "interpretation__form"}>
                    <td>
                      <code>{q.name}</code>
                    </td>
                    <td className="num">{formatValue(q.value as number)}</td>
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
                                (spread.spread as number) * 100
                              ).toPrecision(2)}%)`
                            : "the measurement (unchecked: only one form found)"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <details className="discover-report__full">
            <summary>The reading in full, as the command line prints it</summary>
            <pre>{answer.summary}</pre>
          </details>
        </>
      )}
    </section>
  );
}
