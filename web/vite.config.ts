import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // Relative, so the built site works from a GitHub Pages sub-path and from a bare directory
  // without being rebuilt for each. The Pyodide runtime is located the same way -- the main
  // thread resolves it against BASE_URL and hands the worker an absolute URL, because a worker
  // module cannot resolve the app's base from its own location once Vite has hashed its name.
  base: "./",
  worker: { format: "es" },
  build: { target: "es2022" },
});
