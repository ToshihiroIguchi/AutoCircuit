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
  │ Lin-KK panel            │────>│  autocircuit.web.bridge.handle │
  │                         │<────│    -> autocircuit.io / .core   │
  └─────────────────────────┘     └────────────────────────────────┘
```

Two rules hold this together, both from `docs/WEB_UI_PLAN.md` §4:

- **JavaScript makes no decisions.** `src/worker/` moves bytes and strings. Everything else is
  a call into `autocircuit.web.bridge`, which is a JSON envelope around the functions the CLI
  calls and nothing more.
- **A spectrum is an opaque token.** It is kept in the exact form Python produced and handed
  back unaltered for every operation. `src/core/wire.ts` decodes only for drawing, and there is
  deliberately no encoder — a second implementation of the float format is a way for the
  browser to disagree with the CLI.

A file the user drops is written into the Pyodide filesystem and read from there by
`autocircuit.io.read_many`, so format sniffing, the extension hints and the multi-sweep readers
behave exactly as they do on the command line.

## State

Step 2 of `docs/WEB_UI_PLAN.md` §5: data import, plots and the Lin-KK panel. The circuit
canvas, the discovery job screen and the report are steps 3–5.
