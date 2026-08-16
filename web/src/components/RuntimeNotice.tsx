// What the screens that are not the Data screen show while the fitter is still coming up.
//
// Every control on them is already disabled during that window, which is correct and, on its own,
// indistinguishable from a program that has broken: an empty element palette and a greyed-out Fit
// button look the same whether Pyodide is still importing scipy or has thrown. The status line in
// the header does say, but it says it in eleven-point grey at the top of the page while the reader
// is looking at the middle of it.
//
// It names scipy rather than "the Python runtime" because that is now what is missing: the data
// path is already up by the time anyone can be on this screen at all, and the wait left is the
// 14 MB wheel the fitter needs (`docs/STARTUP_AND_EDITING_PLAN.md` section 3).

export function RuntimeNotice({ ready }: { ready: boolean }) {
  if (ready) return null;
  return (
    <p className="runtime-notice" role="status">
      Fitting needs scipy, which is still loading — it is the largest part of the download, and it
      is fetched after the page comes up so that reading and plotting do not have to wait for it.
      This screen comes alive when the line at the top says <strong>Ready</strong>.
    </p>
  );
}
