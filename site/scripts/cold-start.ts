import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const COLD_START_BUDGET_MS = 3_000;
const RUNS = 5;
const HOST = "127.0.0.1";
const SETTLE_MS = 25;

const SITE = fileURLToPath(new URL("../", import.meta.url));

function freePort(): Promise<number> {
  return new Promise((accept, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, HOST, () => {
      const address = server.address();
      const port = typeof address === "object" && address !== null ? address.port : 0;
      server.close((error) => (error ? reject(error) : accept(port)));
    });
  });
}

async function previewReady(origin: string, deadline: number): Promise<void> {
  while (performance.now() < deadline) {
    try {
      if ((await fetch(origin)).ok) return;
    } catch {
      // The preview server refuses connections until its listener is ready.
    }
    await new Promise((accept) => setTimeout(accept, SETTLE_MS));
  }
  throw new Error("Preview server did not start");
}

function entryAsset(html: string): string {
  const match = /<script[^>]+src="([^"]+assets\/[^"]+\.js)"/.exec(html);
  if (match?.[1] === undefined) throw new Error("Missing bundled entry asset");
  return match[1].startsWith("/") ? match[1] : `/${match[1]}`;
}

function settle(child: ReturnType<typeof spawn>): Promise<void> {
  if (child.exitCode !== null) return Promise.resolve();
  return new Promise((accept) => {
    child.once("exit", () => accept());
    child.kill("SIGTERM");
  });
}

/** Time the fixture build from a cold preview listener to its first data payload. */
async function measure(): Promise<number> {
  const port = await freePort();
  const origin = `http://${HOST}:${port}`;
  const started = performance.now();
  const child = spawn(
    process.execPath,
    [
      "node_modules/vite/bin/vite.js",
      "preview",
      "--host",
      HOST,
      "--port",
      String(port),
      "--strictPort",
    ],
    { cwd: SITE, stdio: "ignore" },
  );
  try {
    await previewReady(origin, started + COLD_START_BUDGET_MS);
    const html = await (await fetch(`${origin}/`)).text();
    await Promise.all([
      fetch(`${origin}${entryAsset(html)}`).then((response) => response.text()),
      fetch(`${origin}/data/latest.json`).then((response) => response.text()),
    ]);
    return performance.now() - started;
  } finally {
    await settle(child);
  }
}

function median(samples: readonly number[]): number {
  const sorted = [...samples].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2
    : (sorted[middle] ?? 0);
}

async function main(): Promise<void> {
  const samples: number[] = [];
  for (let run = 1; run <= RUNS; run++) {
    const elapsed = await measure();
    samples.push(elapsed);
    console.info(`cold start ${run}: ${Math.round(elapsed)} ms`);
  }
  const middle = median(samples);
  console.info(
    `cold start: median ${Math.round(middle)} ms over ${RUNS} runs (budget ${COLD_START_BUDGET_MS} ms)`,
  );
  if (middle > COLD_START_BUDGET_MS) {
    console.error("cold start: median over budget");
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await main();
}
