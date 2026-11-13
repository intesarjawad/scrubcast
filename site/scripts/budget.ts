import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const DIST = fileURLToPath(new URL("../dist/", import.meta.url));

type Budget = {
  readonly label: string;
  readonly limitBytes: number;
  readonly extension: string;
};

// A cold first load stays well under 100 kB gzip.
const BUDGETS: readonly Budget[] = [
  { label: "html", limitBytes: 8_000, extension: ".html" },
  { label: "css", limitBytes: 12_000, extension: ".css" },
  { label: "js", limitBytes: 64_000, extension: ".js" },
];

function files(extension: string): string[] {
  const assets = join(DIST, "assets");
  const paths = extension === ".html" ? [join(DIST, "index.html")] : readdirSync(assets);
  return paths
    .filter((name) => name.endsWith(extension))
    .map((name) => (name.startsWith(DIST) ? name : join(assets, name)));
}

function gzipBytes(path: string): number {
  return gzipSync(readFileSync(path), { level: 9 }).byteLength;
}

const kilobytes = (bytes: number): string => `${(bytes / 1_000).toFixed(1)} kB`;

let failed = false;
for (const budget of BUDGETS) {
  const paths = files(budget.extension);
  if (paths.length === 0) {
    console.error(`${budget.label}: no ${budget.extension} file in dist; run the build first`);
    failed = true;
    continue;
  }
  const bytes = paths.reduce((total, path) => total + gzipBytes(path), 0);
  const within = bytes <= budget.limitBytes;
  failed ||= !within;
  console.info(
    `${budget.label}: ${kilobytes(bytes)} gzip (budget ${kilobytes(budget.limitBytes)}) ${within ? "OK" : "OVER"}`,
  );
}

if (failed) process.exitCode = 1;
