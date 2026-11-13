import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { isLatest, isPast, nextFeatured } from "../src/data.ts";
import { isLaunchAssessment, sortedRules } from "../src/launch-data.ts";
import type { LaunchAssessment, LaunchSummary } from "../src/types.ts";

const FIRST_PAINT_LIMIT_BYTES = 40_000;

function escapeAttribute(text: string): string {
  return text.replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] ?? char,
  );
}

export function firstPaint(assessment: LaunchAssessment): string {
  const top = sortedRules(assessment)[0]?.rule_id;
  const inline = {
    ...assessment,
    rules: assessment.rules.map((rule) =>
      rule.rule_id === top
        ? rule
        : { ...rule, member_values_by_hour: {}, member_violated_by_hour: {} },
    ),
  };
  const json = JSON.stringify(inline).replace(/</g, "\\u003c");
  if (Buffer.byteLength(json) > FIRST_PAINT_LIMIT_BYTES)
    throw new Error("First paint exceeds 40 KB");
  return `<script type="application/json" id="first-paint">${json}</script>`;
}

/** Write independent path entries so shared URLs carry their own metadata. */
export async function writeStubs(directory: string, siteUrl = ""): Promise<void> {
  const template = await readFile(resolve(directory, "index.html"), "utf8");
  const latest: unknown = JSON.parse(
    await readFile(resolve(directory, "data/latest.json"), "utf8"),
  );
  const past: unknown = JSON.parse(await readFile(resolve(directory, "data/past.json"), "utf8"));
  if (!isLatest(latest)) throw new Error("Invalid latest launch index");
  if (!isPast(past)) throw new Error("Invalid retained launch index");
  const assetPath = /<script[^>]+src="([^"]+)assets\//.exec(template)?.[1];
  if (assetPath === undefined) throw new Error("Missing bundled entry asset");
  const base = assetPath;
  const origin = siteUrl ? new URL(siteUrl).origin : "";
  const absolute = (path: string): string => `${origin}${base}${path}`;

  async function writePage(
    path: string,
    title: string,
    description: string,
    canonical: string,
    assessment?: LaunchAssessment,
  ): Promise<void> {
    const image = absolute("social-preview.png");
    const metadata = [
      `<link rel="canonical" href="${escapeAttribute(canonical)}">`,
      ...Object.entries({
        "og:title": title,
        "og:description": description,
        "og:url": canonical,
        "og:type": "website",
        "og:image": image,
      }).map(
        ([property, content]) =>
          `<meta property="${property}" content="${escapeAttribute(content)}">`,
      ),
      `<meta name="twitter:card" content="summary_large_image">`,
      `<meta name="twitter:title" content="${escapeAttribute(title)}">`,
      `<meta name="twitter:description" content="${escapeAttribute(description)}">`,
      `<meta name="twitter:image" content="${escapeAttribute(image)}">`,
    ].join("\n");
    const html = template
      .replace(/<title>[^<]*<\/title>/, () => `<title>${escapeAttribute(title)}</title>`)
      .replace(
        /<meta\s+name="description"[^>]*>/,
        () => `<meta name="description" content="${escapeAttribute(description)}">`,
      )
      .replace("</head>", () => `${metadata}</head>`)
      .replace("</body>", () => `${assessment ? firstPaint(assessment) : ""}</body>`);
    const target = resolve(directory, path);
    await mkdir(resolve(target, ".."), { recursive: true });
    await writeFile(target, html);
  }

  const pages = new Map<string, { launch: LaunchSummary; assessment?: LaunchAssessment }>();
  for (const launch of [...latest.launches, ...past.launches]) {
    if (pages.has(launch.id)) continue;
    let assessment: LaunchAssessment | undefined;
    if (launch.assessment) {
      const value: unknown = JSON.parse(
        await readFile(
          resolve(directory, `data/launches/${encodeURIComponent(launch.id)}.json`),
          "utf8",
        ),
      );
      if (!isLaunchAssessment(value) || value.launch.id !== launch.id)
        throw new Error(`Invalid assessment: ${launch.id}`);
      assessment = value;
    }
    const page = assessment ? { launch, assessment } : { launch };
    pages.set(launch.id, page);
    await writePage(
      `launch/${encodeURIComponent(launch.id)}/index.html`,
      `${launch.name} | Scrubcast`,
      description(launch),
      absolute(`launch/${encodeURIComponent(launch.id)}/`),
      assessment,
    );
  }
  const featured = nextFeatured(latest, new Date(latest.generated_at));
  const page = featured.kind === "empty" ? undefined : pages.get(featured.launch.id);
  await writePage(
    "next/index.html",
    page ? `${page.launch.name} | Scrubcast` : "Next launch | Scrubcast",
    page ? description(page.launch) : "No orbital launches in the next 10 days.",
    page ? absolute(`launch/${encodeURIComponent(page.launch.id)}/`) : absolute("next/"),
    page?.assessment,
  );
  await writePage(
    "audit/index.html",
    "Audit | Scrubcast",
    "Launch weather audit and provenance.",
    absolute("audit/"),
  );
  await writePage(
    "404.html",
    "Launch not found | Scrubcast",
    "Launch not found or older than 90 days.",
    absolute("404.html"),
  );
}

function description(launch: LaunchSummary): string {
  return `${launch.worst_rule.label}.${launch.probability === null ? "" : ` Official: ${launch.probability}% probability of GO`}`;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await writeStubs(resolve("dist"), process.env.SITE_URL);
}
