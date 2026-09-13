// Serves a built site directory at a fixed byte rate, for docs/SEARCH_TIME_PLAN.md §8's
// stdlib-bytecode wire-cost measurement. The trade under test is bandwidth against CPU, so
// bandwidth must be the controlled independent variable, not removed -- a bare localhost
// server (unthrottled) answers a different question than "is this worth it over a real link".
//
// Usage: node scripts/serve-throttled.mjs <dir> <port> <MBps|unlimited>
import { createReadStream, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, resolve } from "node:path";

const [, , dirArg, portArg, rateArg] = process.argv;
if (!dirArg || !portArg || !rateArg) {
  console.error("usage: node scripts/serve-throttled.mjs <dir> <port> <MBps|unlimited>");
  process.exit(1);
}
const ROOT = resolve(dirArg);
const PORT = Number(portArg);
const bytesPerSec = rateArg === "unlimited" ? Infinity : Number(rateArg) * 1e6;

const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".wasm": "application/wasm",
  ".zip": "application/zip",
  ".whl": "application/zip",
  ".map": "application/json",
};

// Chunk-then-delay: each chunk is written immediately and the stream is paused for exactly the
// time that chunk's bytes should have taken at the target rate, so the *average* rate over the
// whole response converges on `bytesPerSec` regardless of file size. A small `highWaterMark`
// keeps this accurate at the slowest rungs (a default 64 KiB chunk at 0.5 MB/s is already a
// 128 ms step, coarse enough to matter for a small file).
const HIGH_WATER_MARK = 8 * 1024;

function serveFile(file, res) {
  const st = statSync(file);
  res.setHeader("Content-Type", MIME[extname(file)] || "application/octet-stream");
  res.setHeader("Content-Length", st.size);
  res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
  const stream = createReadStream(file, { highWaterMark: HIGH_WATER_MARK });
  if (!isFinite(bytesPerSec)) {
    stream.pipe(res);
    return;
  }
  stream.on("data", (chunk) => {
    stream.pause();
    res.write(chunk);
    const delayMs = (chunk.length / bytesPerSec) * 1000;
    setTimeout(() => stream.resume(), delayMs);
  });
  stream.on("end", () => res.end());
  stream.on("error", () => res.end());
}

const server = createServer((req, res) => {
  let path = decodeURIComponent((req.url || "/").split("?")[0]);
  if (path === "/") path = "/index.html";
  const file = join(ROOT, path);
  if (!file.startsWith(ROOT)) {
    res.statusCode = 403;
    res.end("forbidden");
    return;
  }
  try {
    if (statSync(file).isDirectory()) throw new Error("directory");
    serveFile(file, res);
  } catch {
    res.statusCode = 404;
    res.end("not found");
  }
});

server.listen(PORT, () => {
  console.log(`serving ${ROOT} at ${rateArg === "unlimited" ? "unlimited" : rateArg + " MB/s"} on http://localhost:${PORT}/`);
});
