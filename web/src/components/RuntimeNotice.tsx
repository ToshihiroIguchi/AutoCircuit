// What the screens that are not the Data screen show while the runtime is still coming up.
//
// Every control on them is already disabled during that window, which is correct and, on its own,
// indistinguishable from a program that has broken: an empty element palette and a greyed-out Fit
// button look the same whether Pyodide is still importing numpy or has thrown. The status line in
// the header does say, but it says it in eleven-point grey at the top of the page while the reader
// is looking at the middle of it.

export function RuntimeNotice({ ready }: { ready: boolean }) {
  if (ready) return null;
  return (
    <p className="runtime-notice" role="status">
      The Python runtime is still loading. A first visit takes on the order of ten seconds — nearly
      all of it starting the interpreter and importing the package, not downloading them — and this
      screen comes alive when the line at the top says <strong>Ready</strong>.
    </p>
  );
}
