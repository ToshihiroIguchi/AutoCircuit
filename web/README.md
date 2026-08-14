# AutoCircuit in a browser

The same Python core the CLI runs, in a static site: Vite + React on the front, Pyodide behind
it. There is no server and there will not be one — see `docs/WEB_UI_PLAN.md` §7.

```powershell
cd web
npm install
npm run dev          # http://localhost:5173
npm run build        # -> dist/, deployable as static files
npm run smoke        # the Python path under Pyodide, headless, no browser
```

`npm run dev` and `npm run build` both run `npm run assets` first, so a change to
`src/autocircuit/**` is picked up without a second command.

## What lands in `public/`

Nothing in `public/` is checked in; `scripts/build-assets.mjs` produces all of it.

| file | what it is |
|------|-----------|
| `autocircuit-src.zip` | the Python package, built by `benchmarks/pyodide/make_zip.py` — the same builder the Pyodide benchmark uses, so the site and the benchmark cannot ship different cores |
| `pyodide/` | the Pyodide runtime **and the numpy and scipy wheels** |

The wheels are vendored rather than fetched from a CDN at run time. The npm `pyodide` package
does not carry them, so the script takes them from wherever they already are on disk and falls
back to the CDN once. That is what lets the site work offline and what keeps a development
machine off the network; it is also why `public/` is ~29 MB.

## How the pieces fit

```
  main thread                     bridge worker
  ┌─────────────────────────┐     ┌────────────────────────────────┐
  │ React: table, plots,    │ JSON│ Pyodide                        │
  │ Lin-KK panel, canvas,   │────>│  autocircuit.web.bridge.handle │
  │ parameter table         │<────│    -> autocircuit.io / .core   │
  └─────────────────────────┘     └────────────────────────────────┘
```

Two screens so far, under `src/screens/`. `App.tsx` owns the Pyodide client and the loaded
spectra; a screen is a view over them.

| screen | what it does |
|--------|--------------|
| Data | drop a file, see it plotted, trim its frequency window, read the Lin-KK verdict |
| Fit | draw a circuit, watch it against the data, fit it — with no initial values |

Two rules hold this together, both from `docs/WEB_UI_PLAN.md` §4:

- **JavaScript makes no decisions.** `src/worker/` moves bytes and strings. Everything else is
  a call into `autocircuit.web.bridge`, which is a JSON envelope around the functions the CLI
  calls and nothing more.
- **A spectrum is an opaque token.** It is kept in the exact form Python produced and handed
  back unaltered for every operation. `src/core/wire.ts` decodes only for drawing, and there is
  deliberately no encoder — a second implementation of the float format is a way for the
  browser to disagree with the CLI.
- **A circuit is edited by position, not by string.** `CircuitCanvas` draws the tree Python
  parsed and sends back "this action, at this path"; the `edit` operation performs the surgery
  and answers with the circuit that resulted. The canvas cannot write a circuit string, which is
  what keeps the grammar from having a second implementation here.

A file the user drops is written into the Pyodide filesystem and read from there by
`autocircuit.io.read_many`, so format sniffing, the extension hints and the multi-sweep readers
behave exactly as they do on the command line.

## State

Steps 1–3 of `docs/WEB_UI_PLAN.md` §5: data import, plots and the Lin-KK panel; then the
schematic canvas, the live preview and the manual fit. The discovery job screen and the report
are steps 4 and 5.

`npm run smoke` covers the Python path end to end without a browser. Two things it cannot cover,
which cost a real browser to find: how a panel is *sized* (see `docs/HANDOFF.md` §9 on Plotly
heights), and how long a fit feels — 5 s for three parameters, which is why the Fit button has a
busy state.
