// The full-auto report's headline structure: candidates grouped into classes that produce the
// same measurable response, never flattened into a ranked list with a winner. `DiscoveryResult`
// reports a Pareto front plus equivalence classes for exactly this reason (see the "Full auto"
// section of the project's CLAUDE.md) -- different topologies are frequently exact
// reparameterisations of one another, and picking one over the rest of its class is not
// something an impedance measurement can do. `ParetoTable` renders the accuracy-vs-complexity
// trade-off; this renders the equivalence structure underneath it. Order is the search's own and
// is never re-sorted here -- the search already put the best class first.

import type { CandidateRowWire } from "../core/types";
import { decodeFloat } from "../core/wire";
import { formatNumber } from "../utils/format";

export interface EquivalenceClassesProps {
  /** Groups of circuit strings, best AICc first, singletons included. Rendered in this order. */
  classes: string[][];
  /** Every evaluated candidate; members are looked up here by `circuit`. */
  rows: CandidateRowWire[];
  recommended: string | null;
}

export function EquivalenceClasses({ classes, rows, recommended }: EquivalenceClassesProps) {
  const byCircuit = new Map<string, CandidateRowWire>();
  for (const row of rows) byCircuit.set(row.circuit, row);
  const ambiguous = classes.filter((members) => members.length > 1).length;

  return (
    <section className="equivalence-classes">
      <h2 className="panel-title">Equivalence classes</h2>

      {classes.length === 0 ? (
        <p className="empty-hint">Nothing has been fitted yet.</p>
      ) : (
        <>
          <p className="equivalence-classes__intro">
            Members of a class produce the same measurable response: no impedance measurement can
            prefer one over the others. Choosing between them takes physical knowledge of the
            sample, not more fitting.
          </p>
          {/* The headline of this panel is how many classes hold more than one topology, and a
              column of "Class n -- 1 topology" headings hides it. Saying "none" is the point of
              the count: an unambiguous report is a result, not an absence of one. */}
          <p className="equivalence-classes__count">
            {classes.length} class{classes.length === 1 ? "" : "es"},{" "}
            {ambiguous === 0
              ? "none of them holding topologies the data cannot tell apart"
              : `${ambiguous} of them holding topologies the data cannot tell apart`}
            .
          </p>

          {classes.map((members, index) => {
            const heading =
              members.length === 1
                ? `Class ${index + 1} — 1 topology`
                : `Class ${index + 1} — ${members.length} topologies the data cannot tell apart`;

            return (
              <div className="equivalence-classes__class" key={index}>
                <h3 className="equivalence-classes__heading">{heading}</h3>
                <ul className="equivalence-classes__members">
                  {members.map((circuit) => {
                    const row = byCircuit.get(circuit) ?? null;
                    return (
                      <li className="equivalence-classes__member" key={circuit}>
                        <code>{circuit}</code>
                        {circuit === recommended && (
                          <span className="equivalence-classes__badge">
                            simplest that fits as well as any
                          </span>
                        )}
                        {row !== null && (
                          <span className="equivalence-classes__detail">
                            AICc {formatNumber(decodeFloat(row.aicc), 6)}, chi²{" "}
                            {formatNumber(decodeFloat(row.chi2_reduced), 5)}, {row.n_params}{" "}
                            params
                            {row.unresolved.length > 0 && (
                              <> — unresolved: {row.unresolved.join(", ")}</>
                            )}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </>
      )}
    </section>
  );
}
