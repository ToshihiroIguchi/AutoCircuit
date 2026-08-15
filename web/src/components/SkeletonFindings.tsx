// What a skeleton-constrained report has to say about the skeleton itself, as opposed to about
// the candidates it produced: whether the data actually resolved every element the user
// asserted, and whether the skeleton sits inside a front row in more than one place. Both are
// measured facts about the fit, not guesses -- see `docs/PARTIAL_TOPOLOGY_PLAN.md` section 3.2,
// where a wrong skeleton was found to leave no trace in the residuals or in chi2 and to surface
// only as an asserted element the fit had to switch off. This panel is also the one place that
// has to be able to say "nothing to report": if it can only ever warn, a clean skeleton looks
// exactly like one nobody checked.

export interface SkeletonFindingsProps {
  skeleton: string;
  /** Asserted elements the fit could not pin down. Empty means the data tested them. */
  unsupported: string[];
  /** Per front row, how many distinct places the skeleton sits in it. */
  placements: Record<string, number>;
}

export function SkeletonFindings({ skeleton, unsupported, placements }: SkeletonFindingsProps) {
  const ambiguous = Object.entries(placements).filter(([, count]) => count > 1);

  const warningText =
    `The data does not test part of your skeleton: ${unsupported.join(", ")} came back with a ` +
    "standard error larger than its own value, under every way the skeleton fits this circuit. " +
    "The fit is what it is with that element switched off, so the data neither supports nor " +
    "refutes that part of your assertion — which is also what a wrong skeleton looks like.";

  return (
    <section className="skeleton-findings">
      <h2 className="panel-title">Skeleton</h2>

      <p className="skeleton-findings__skeleton">
        The search was restricted to topologies containing <code>{skeleton}</code>, which you
        asserted — it was not discovered by the search.
      </p>

      {unsupported.length > 0 ? (
        <p className="skeleton-findings__warning discover-report__warning" role="alert">
          {warningText}
        </p>
      ) : (
        <p className="skeleton-findings__resolved">
          The data tested every element of your assertion: none of the skeleton's own elements
          came back unsupported.
        </p>
      )}

      {ambiguous.length > 0 && (
        <div className="skeleton-findings__placements">
          <p className="skeleton-findings__placements-intro">
            The skeleton fits into these front-row candidates in more than one place, so the fit
            cannot say which elements are the ones you asserted:
          </p>
          <ul className="skeleton-findings__placements-list">
            {ambiguous.map(([circuit, count]) => (
              <li key={circuit}>
                <code>{circuit}</code> — {count} ways
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
