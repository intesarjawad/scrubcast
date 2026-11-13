import { execFileSync } from "node:child_process";
import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { checkCards, writeLaunchCard } from "../../scripts/card-files";
import { firstPaint, writeStubs } from "../../scripts/stubs";
import { isLaunchAssessment, sortedRules } from "../../src/launch-data";
import type { Latest, LaunchAssessment, LaunchSummary } from "../../src/types";
import { demoSummary } from "../fixtures/demo";

const fixture: unknown = JSON.parse(
  await readFile(new URL("../../../tests/fixtures/demo/assessment.json", import.meta.url), "utf8"),
);
if (!isLaunchAssessment(fixture)) throw new Error("Invalid recorded assessment");
const assessment = fixture;
const site = fileURLToPath(new URL("../../", import.meta.url));
const temporary = await mkdtemp(join(tmpdir(), "scrubcast-stubs-"));

function summary(value: LaunchAssessment): LaunchSummary {
  return {
    ...value.launch,
    tier: value.tier,
    assessment: true,
    page_url: `/launch/${value.launch.id}/`,
    worst_rule: demoSummary.worst_rule,
  };
}

beforeAll(async () => {
  execFileSync(
    process.execPath,
    ["node_modules/vite/bin/vite.js", "build", "--outDir", temporary, "--emptyOutDir"],
    {
      cwd: site,
      stdio: "pipe",
      env: { ...process.env, SITE_URL: "https://example.org/weather/" },
    },
  );
  await mkdir(join(temporary, "data/launches"), { recursive: true });
  const latest: Latest = {
    schema_version: 1,
    generated_at: "2026-11-05T12:00:00Z",
    schedule_stale: false,
    members_total: 82,
    launches: [summary(assessment)],
  };
  const archived = {
    ...assessment,
    launch: {
      ...assessment.launch,
      id: "archived",
      net: "2026-11-04T19:00:00Z",
      name: '<Mission & "payload"> </script><script>alert(1)</script>',
    },
  };
  await writeFile(join(temporary, "data/latest.json"), JSON.stringify(latest));
  const retained = {
    ...summary(archived),
    id: "retained",
    assessment: false,
    net: "2026-10-01T00:00:00Z",
    window_start: "2026-10-01T00:00:00Z",
    window_end: "2026-10-01T01:00:00Z",
    audit: [
      {
        attempt_id: "retained@2026-10-01T00:00:00Z",
        attempt_net: "2026-10-01T00:00:00Z",
        official_concerns: ["Cumulus Cloud Rule"],
        scrubcast_24h: [{ rule_id: "cumulus", title: "Cumulus cloud", risk_fraction: 0.4 }],
        outcome: "launched",
        net_now: "2026-10-01T00:00:00Z",
        note: null,
      },
    ],
  };
  await writeFile(
    join(temporary, "data/past.json"),
    JSON.stringify({
      schema_version: 1,
      generated_at: latest.generated_at,
      launches: [summary(archived), retained],
    }),
  );
  for (const value of [assessment, archived])
    await writeFile(
      join(temporary, `data/launches/${value.launch.id}.json`),
      JSON.stringify(value),
    );
  await writeStubs(temporary, "https://example.org/weather/");
});

// The page budget reads "JS ≤ 60 KB gzipped, CSS ≤ 12 KB": both figures are gzipped.
it("keeps the delivered CSS within 12 KB gzipped", async () => {
  const assets = join(temporary, "assets");
  const files = (await readdir(assets)).filter((name) => name.endsWith(".css"));
  const css = Buffer.concat(await Promise.all(files.map((name) => readFile(join(assets, name)))));
  const gzipped = gzipSync(css, { level: 9 }).byteLength;
  console.info(`CSS ${css.byteLength} B raw, ${gzipped} B gzipped`);
  expect(gzipped).toBeLessThanOrEqual(12_000);
});

afterAll(async () => {
  await rm(temporary, { recursive: true, force: true });
});

describe("shared launch pages", () => {
  it("writes each launch, next, audit and not-found entry from a real bundle", async () => {
    for (const path of [
      `launch/${assessment.launch.id}/index.html`,
      "launch/archived/index.html",
      "launch/retained/index.html",
      "next/index.html",
      "audit/index.html",
      "404.html",
    ]) {
      const html = await readFile(join(temporary, path), "utf8");
      expect(html).toContain("/weather/assets/");
      expect(html).toContain('<meta name="twitter:card" content="summary_large_image">');
    }
    const launch = await readFile(
      join(temporary, `launch/${assessment.launch.id}/index.html`),
      "utf8",
    );
    const next = await readFile(join(temporary, "next/index.html"), "utf8");
    for (const html of [launch, next]) {
      expect(html).toContain(`<title>${assessment.launch.name} | Scrubcast</title>`);
      expect(html).toContain(
        `<link rel="canonical" href="https://example.org/weather/launch/${assessment.launch.id}/">`,
      );
      expect(html).toContain(
        `<meta name="description" content="${demoSummary.worst_rule.label}.">`,
      );
      expect(html).toContain(
        '<meta property="og:image" content="https://example.org/weather/social-preview.png">',
      );
      expect(html).toContain(
        '<meta name="twitter:image" content="https://example.org/weather/social-preview.png">',
      );
      expect(html).toContain(
        `<meta name="twitter:title" content="${assessment.launch.name} | Scrubcast">`,
      );
      expect(html).toContain(
        `<meta name="twitter:description" content="${demoSummary.worst_rule.label}.">`,
      );
      expect(html).toContain(`https://example.org/weather/launch/${assessment.launch.id}/`);
      expect(html).not.toContain("Official:");
      const block = /<script type="application\/json" id="first-paint">(.*?)<\/script>/.exec(
        html,
      )?.[1];
      if (!block) throw new Error("Missing first paint");
      expect(Buffer.byteLength(block)).toBeLessThanOrEqual(40_000);
      const inline: unknown = JSON.parse(block);
      expect(isLaunchAssessment(inline)).toBe(true);
      if (!isLaunchAssessment(inline)) throw new Error("Invalid first paint");
      const top = sortedRules(inline)[0];
      expect(top?.member_values_by_hour).toEqual(sortedRules(assessment)[0]?.member_values_by_hour);
      for (const rule of inline.rules.filter((rule) => rule.rule_id !== top?.rule_id)) {
        expect(rule.member_values_by_hour).toEqual({});
        expect(rule.member_violated_by_hour).toEqual({});
      }
    }
  });

  it("escapes attribute text and script-closing input in metadata and first paint", async () => {
    const html = await readFile(join(temporary, "launch/archived/index.html"), "utf8");
    expect(html).toContain("&lt;Mission &amp; &quot;payload&quot;&gt;");
    expect(html).not.toContain("</script><script>alert(1)</script>");
    expect(html).toContain("\\u003c/script>");
  });

  it("writes a retained page stub without member evidence", async () => {
    const html = await readFile(join(temporary, "launch/retained/index.html"), "utf8");
    expect(html).toContain('<meta name="twitter:card" content="summary_large_image">');
    expect(html).not.toContain('id="first-paint"');
  });

  it("publishes validated card images and resets failed recaptures to the generic preview", async () => {
    const png = await readFile(new URL("../fixtures/card.png", import.meta.url));
    for (const id of [assessment.launch.id, "archived"])
      expect(await writeLaunchCard(temporary, id, async () => png)).toBe(png.byteLength);
    expect(await checkCards(temporary)).toBe(2);
    for (const path of [`launch/${assessment.launch.id}/index.html`, "next/index.html"]) {
      const html = await readFile(join(temporary, path), "utf8");
      const image = `https://example.org/weather/launch/${assessment.launch.id}/card.png`;
      expect(html).toContain(`<meta property="og:image" content="${image}">`);
      expect(html).toContain(`<meta name="twitter:image" content="${image}">`);
    }
    await expect(
      writeLaunchCard(temporary, assessment.launch.id, async () => {
        throw new Error("Capture unavailable");
      }),
    ).rejects.toThrow("Capture unavailable");
    for (const path of [`launch/${assessment.launch.id}/index.html`, "next/index.html"]) {
      const html = await readFile(join(temporary, path), "utf8");
      expect(html).toContain(
        '<meta property="og:image" content="https://example.org/weather/social-preview.png">',
      );
      expect(html).toContain(
        '<meta name="twitter:image" content="https://example.org/weather/social-preview.png">',
      );
    }
    await expect(
      readFile(join(temporary, `launch/${assessment.launch.id}/card.png`)),
    ).rejects.toThrow();
    await expect(checkCards(temporary)).rejects.toThrow(
      `${assessment.launch.id}: card failed: Missing PNG`,
    );
    const archived = await readFile(join(temporary, "launch/archived/index.html"), "utf8");
    expect(archived).toContain('content="https://example.org/weather/launch/archived/card.png"');
    await expect(
      writeLaunchCard(temporary, "archived", async () => Buffer.alloc(300_001)),
    ).rejects.toThrow("must be a PNG");
    await expect(readFile(join(temporary, "launch/archived/card.pending.png"))).rejects.toThrow();
  });

  it("rejects an oversized first paint rather than shipping over budget", () => {
    expect(() =>
      firstPaint({ ...assessment, launch: { ...assessment.launch, name: "x".repeat(40_001) } }),
    ).toThrow("First paint exceeds 40 KB");
  });
});
