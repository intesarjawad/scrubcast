import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import { isLatest } from "../../src/data";
import { isLaunchAssessment } from "../../src/launch-data";
import type { Latest, LaunchAssessment } from "../../src/types";
import { demo } from "../fixtures/demo";

const FIXTURES = new URL("../../../tests/fixtures/worst_case/", import.meta.url);

// The recorded demo page is the only built launch path these fixtures can reuse.
const DEMO_ID = "54d471e8-695c-4fa7-a3cf-dbd8b389e8ae";

// Authentic edge cases are recorded as JSON so the browser sees the exact
// contract the build publishes, including nulls for unavailable members.
function load(name: string): unknown {
  return JSON.parse(readFileSync(new URL(name, FIXTURES), "utf8"));
}

function latestFixture(name: string): Latest {
  const value = load(name);
  if (!isLatest(value)) throw new Error(`Invalid latest fixture: ${name}`);
  return value;
}

function assessmentFixture(name: string): LaunchAssessment {
  const value = load(name);
  if (!isLaunchAssessment(value)) throw new Error(`Invalid assessment fixture: ${name}`);
  return value;
}

function latestFor(assessment: LaunchAssessment): Latest {
  return {
    schema_version: 1,
    generated_at: assessment.evaluated_at,
    schedule_stale: false,
    members_total: 5,
    launches: [
      {
        ...assessment.launch,
        tier: assessment.tier,
        assessment: true,
        page_url: `/launch/${assessment.launch.id}/`,
        worst_rule: { label: "Thick Cloud 33% (ECMWF)", risk_fraction: 1 / 3 },
      },
    ],
  };
}

async function expectNoOverflow(page: Page): Promise<void> {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
}

async function expectNoMissingNumbers(page: Page): Promise<void> {
  const text = await page.locator("body").textContent();
  expect(text ?? "").not.toMatch(/\bNaN\b/);
  expect(text ?? "").not.toMatch(/\bundefined\b/);
}

async function showHome(page: Page, latest: Latest): Promise<void> {
  await page.clock.setFixedTime(new Date(latest.generated_at));
  await page.route("**/data/latest.json", (route) => route.fulfill({ json: latest }));
  await page.goto("/");
}

async function showAssessment(page: Page, assessment: LaunchAssessment): Promise<void> {
  await page.clock.setFixedTime(new Date(assessment.evaluated_at));
  // Bypass the inline first paint so every fixture supplies its own data.
  await page.route(`**/launch/${DEMO_ID}/`, async (route) => {
    const response = await route.fetch();
    const html = (await response.text()).replaceAll(
      'id="first-paint"',
      'id="first-paint-disabled"',
    );
    await route.fulfill({ response, body: html });
  });
  await page.route("**/data/latest.json", (route) =>
    route.fulfill({ json: latestFor(assessment) }),
  );
  await page.route(`**/data/launches/${DEMO_ID}.json`, (route) =>
    route.fulfill({ json: assessment }),
  );
  await page.goto(`/launch/${DEMO_ID}/`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    assessment.launch.name.replace(" | ", ", "),
  );
}

test.use({ viewport: { width: 320, height: 900 } });

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

test("thirty launches in ten days keep their order without overflow", async ({ page }) => {
  const latest = latestFixture("thirty-launches.json");
  await showHome(page, latest);
  await expect(page.locator(".launch-row")).toHaveCount(30);
  await expectNoOverflow(page);
  await expectNoMissingNumbers(page);
  await expect(page).toHaveScreenshot("worst-thirty-launches-320.png", { fullPage: true });
});

test("a 120-character mission name wraps and stays whole", async ({ page }) => {
  const latest = latestFixture("long-mission-name.json");
  const name = latest.launches[0]?.name ?? "";
  expect(name).toHaveLength(120);
  await showHome(page, latest);
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(name);
  await expectNoOverflow(page);
  await expectNoMissingNumbers(page);
  await expect(page).toHaveScreenshot("worst-long-mission-name-320.png", { fullPage: true });
});

test("non-Latin mission names render in both scripts", async ({ page }) => {
  const latest = latestFixture("non-latin-name.json");
  await showHome(page, latest);
  for (const launch of latest.launches) {
    await expect(page.getByRole("heading", { level: 2, name: launch.name })).toBeVisible();
  }
  await expectNoOverflow(page);
  await expectNoMissingNumbers(page);
  await expect(page).toHaveScreenshot("worst-non-latin-name-320.png", { fullPage: true });
});

test("a stale schedule warns before the launch list", async ({ page }) => {
  const latest = latestFixture("schedule-stale.json");
  await showHome(page, latest);
  await expect(
    page.getByRole("heading", {
      level: 2,
      name: "Launch Library 2 did not answer the last refresh. The launch schedule may be out of date.",
    }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Launch Library 2 launch page" })).toBeVisible();
  await expect(page.locator(".launch-row")).toHaveCount(1);
  await expectNoOverflow(page);
  await expectNoMissingNumbers(page);
  await expect(page).toHaveScreenshot("worst-schedule-stale-320.png", { fullPage: true });
});

test("a window beyond the forecast horizon states the horizon", async ({ page }) => {
  const latest = latestFixture("window-beyond-horizon.json");
  await page.clock.setFixedTime(new Date(latest.generated_at));
  await page.route(`**/launch/${DEMO_ID}/`, async (route) => {
    const response = await route.fetch();
    const html = (await response.text()).replaceAll(
      'id="first-paint"',
      'id="first-paint-disabled"',
    );
    await route.fulfill({ response, body: html });
  });
  await page.route("**/data/latest.json", (route) => route.fulfill({ json: latest }));
  await page.goto(`/launch/${DEMO_ID}/`);
  await expect(
    page.getByRole("heading", {
      level: 2,
      name: "Rules appear about 10 days before launch. Forecast data for this window are not available yet.",
    }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "the launch calendar" })).toBeVisible();
  await expectNoOverflow(page);
  await expectNoMissingNumbers(page);
  await expect(page).toHaveScreenshot("worst-window-beyond-horizon-320.png", { fullPage: true });
});

test("a 24-hour window exposes every hour on the slider and in the table", async ({ page }) => {
  const assessment = assessmentFixture("window-24h.json");
  expect(assessment.rules[0]?.hours).toHaveLength(24);
  await showAssessment(page, assessment);
  const slider = page.getByRole("slider", { name: "Selected hour" });
  await expect(slider).toHaveAttribute("max", "23");
  await slider.focus();
  await slider.press("End");
  await expect(slider).toHaveValue("23");
  await page.getByText("Each hour in figures", { exact: true }).click();
  const table = page.getByRole("table", {
    name: "Thick Cloud Layers Rule: hourly member evidence",
  });
  await expect(table.getByRole("row")).toHaveCount(25);
  await expectNoOverflow(page);
  await expectNoMissingNumbers(page);
  await expect(page).toHaveScreenshot("worst-window-24h-320.png", { fullPage: true });
});

test("a window crossing pad-local midnight labels both dates", async ({ page }) => {
  const assessment = assessmentFixture("window-crosses-midnight.json");
  await showAssessment(page, assessment);
  await expect(page.getByText("Window 23:00 PST to 01:00 PST", { exact: false })).toBeVisible();
  const slider = page.getByRole("slider", { name: "Selected hour" });
  await slider.focus();
  await expect(page.getByRole("status")).toContainText("At 00:00 PST");
  await slider.press("Home");
  await expect(page.getByRole("status")).toContainText("At 23:00 PST");
  await slider.press("End");
  await expect(page.getByRole("status")).toContainText("At 01:00 PST");
  await expectNoOverflow(page);
  await expectNoMissingNumbers(page);
  await expect(page).toHaveScreenshot("worst-crosses-midnight-320.png", { fullPage: true });
});

test("missing official fields leave the official block out", async ({ page }) => {
  const assessment = assessmentFixture("missing-official-fields.json");
  expect(assessment.official.probability_go_pct).toBeNull();
  expect(assessment.launch.weather_concerns).toBeNull();
  await showAssessment(page, assessment);
  await expect(page.locator(".sheet-facts")).toContainText("Not published");
  await expect(page.locator(".board")).toBeVisible();
  await expectNoOverflow(page);
  await expectNoMissingNumbers(page);
  await expect(page).toHaveScreenshot("worst-missing-official-320.png", { fullPage: true });
});

test("an hour with no evaluable members reads as unavailable", async ({ page }) => {
  const assessment = assessmentFixture("member-nan-hour.json");
  expect(assessment.rules[0]?.by_model.ecmwf?.risk_fraction).not.toBeNull();
  await showAssessment(page, assessment);
  const slider = page.getByRole("slider", { name: "Selected hour" });
  await slider.focus();
  await slider.press("ArrowRight");
  await slider.press("ArrowRight");
  await expect(page.getByRole("status")).toContainText("/ 03:00 UTC");
  await expect(page.getByRole("status")).toContainText("ECMWF: not evaluable.");
  await page.getByText("Each hour in figures", { exact: true }).click();
  const table = page.getByRole("table", {
    name: "Thick Cloud Layers Rule: hourly member evidence",
  });
  await expect(table.getByRole("row").filter({ hasText: "03:00 UTC" })).toContainText(
    "Not evaluable",
  );
  await expectNoOverflow(page);
  await expectNoMissingNumbers(page);
  await expect(page).toHaveScreenshot("worst-member-nan-hour-320.png", { fullPage: true });
});

test("a missing ECMWF ensemble is named in the row and provenance", async ({ page }) => {
  const assessment = assessmentFixture("ecmwf-missing.json");
  await showAssessment(page, assessment);
  const row = page.locator('tr[data-rule-id="thick_cloud"]');
  await expect(row.getByRole("cell").first()).toContainText("Not evaluable");
  await page.getByText("Data and provenance", { exact: true }).click();
  await expect(page.getByText("ECMWF fetch time unavailable.", { exact: true })).toBeVisible();
  await expectNoOverflow(page);
  await expectNoMissingNumbers(page);
  await expect(page).toHaveScreenshot("worst-ecmwf-missing-320.png", { fullPage: true });
});

test("a deferred refresh says which forecast is shown", async ({ page }) => {
  const assessment = assessmentFixture("refresh-deferred.json");
  await showAssessment(page, assessment);
  await expect(
    page.getByRole("heading", {
      level: 2,
      name: "Forecast from 2026-11-05 18:00 UTC; this refresh was deferred by the request budget or upstream rate limit.",
    }),
  ).toBeVisible();
  await expectNoOverflow(page);
  await expectNoMissingNumbers(page);
  await expect(page).toHaveScreenshot("worst-refresh-deferred-320.png", { fullPage: true });
});

test("an unmapped official concern is quoted rather than dropped", async ({ page }) => {
  const assessment = assessmentFixture("unmapped-concern.json");
  expect(assessment.official.unmapped_concerns).toEqual(["Space Debris Rule"]);
  await showAssessment(page, assessment);
  await expect(page.locator(".sheet-facts")).toContainText("Concern: Space Debris Rule");
  await expectNoOverflow(page);
  await expectNoMissingNumbers(page);
  await expect(page).toHaveScreenshot("worst-unmapped-concern-320.png", { fullPage: true });
});

test.describe("printed figures", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test.beforeEach(async ({ page }) => {
    // The 2D press shares the layout with GL; its draw calls expose every glyph's atlas cell
    // and box, and its canvas the pixels a reader sees.
    await page.addInitScript(() => {
      const ink: number[][] = [];
      Object.assign(window, { ink });
      const getContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (
        this: HTMLCanvasElement,
        ...args: unknown[]
      ) {
        return args[0] === "webgl2" ? null : Reflect.apply(getContext, this, args);
      } as typeof getContext;
      const drawImage = CanvasRenderingContext2D.prototype.drawImage;
      CanvasRenderingContext2D.prototype.drawImage = function (
        this: CanvasRenderingContext2D,
        ...args: unknown[]
      ) {
        if (args.length === 9) {
          Object.assign(window, { atlas: args[0] });
          ink.push(args.slice(1) as number[]);
        }
        return Reflect.apply(drawImage, this, args);
      } as typeof drawImage;
    });
  });

  const storm = assessmentFixture("storm-night.json");
  const nights = [
    ["storm night", { ...storm, launch: { ...storm.launch, id: DEMO_ID } }],
    ["calm demo night", demo],
  ] as const;

  // Prints the sheet at half its pages and then all of them, and checks each print.
  async function pressAt(
    page: Page,
    assessment: LaunchAssessment,
    check: (pages: number, total: number) => Promise<void>,
  ): Promise<void> {
    await showAssessment(page, assessment);
    await expect(page.locator(".spread")).toHaveAttribute("data-printed", "true");
    const range = page.getByLabel("Pages on the sheet");
    const total = Number(await range.getAttribute("max"));
    for (const pages of [Math.round(total / 2), total]) {
      await page.evaluate(() => {
        (window as unknown as { ink: number[][] }).ink.length = 0;
      });
      await range.fill(String(pages));
      await page.evaluate(
        () => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))),
      );
      await check(pages, total);
    }
  }

  for (const [name, assessment] of nights)
    test(`every ${name} glyph prints inside its figure, mid-press and with every page`, async ({
      page,
    }) => {
      await pressAt(page, assessment, async (pages, total) => {
        const stray = await page.evaluate(() => {
          const ink = (window as unknown as { ink: number[][] }).ink.map((call) => call.slice(4));
          const canvas = document.querySelector(".sheet-canvas")?.getBoundingClientRect();
          if (!canvas || ink.length === 0) return ["nothing printed"];
          const dpr = Math.min(2, devicePixelRatio || 1);
          // An atlas cell carries 2 px of padding on each side of the glyph.
          const pad = 3;
          const out: string[] = [];
          const boxes = [...document.querySelectorAll<HTMLElement>(".sheet-page .slot")].map(
            (node) => ({
              box: node.getBoundingClientRect(),
              figure: node.classList.contains("figure"),
              text: node.querySelector(".slot-text")?.textContent,
            }),
          );
          for (const [x = 0, y = 0, w = 0, h = 0] of ink) {
            const left = canvas.left + x / dpr;
            const right = left + w / dpr;
            const middle = canvas.top + (y + h / 2) / dpr;
            // A line's glyph cells are taller than its boxes, so each belongs to the line
            // holding its middle. Every glyph on a figure's line must sit inside one slot.
            const line = boxes.filter(({ box }) => middle >= box.top && middle <= box.bottom);
            if (!line.some(({ figure }) => figure)) continue;
            const home = line.find(({ box }) => left >= box.left - pad && right <= box.right + pad);
            if (!home)
              out.push(
                `${left.toFixed(1)}..${right.toFixed(1)} beside ${line.map(({ text, box }) => `${text} ${box.left.toFixed(1)}..${box.right.toFixed(1)}`).join(", ")}`,
              );
          }
          return out;
        });
        expect(stray, `${pages} of ${total} pages`).toEqual([]);
      });
    });

  for (const [name, assessment] of nights)
    test(`every ${name} typical digit outreads its ghosts, mid-press and with every page`, async ({
      page,
    }) => {
      await pressAt(page, assessment, async (pages, total) => {
        const misread = await page.evaluate(() => {
          const { ink, atlas } = window as unknown as { ink: number[][]; atlas: HTMLCanvasElement };
          const sheet = document.querySelector<HTMLCanvasElement>(".sheet-canvas");
          const pen = sheet?.getContext("2d");
          const glyphs = atlas?.getContext("2d");
          if (!sheet || !pen || !glyphs || ink.length === 0) return ["nothing printed"];
          const dpr = Math.min(2, devicePixelRatio || 1);
          const canvas = sheet.getBoundingClientRect();
          const paper = pen.getImageData(1, 1, 1, 1).data;
          const light = (r = 0, g = 0, b = 0) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
          const blank = light(paper[0], paper[1], paper[2]);
          // What a reader sees in a cell: the darkness of every pixel against the paper.
          const seen = (x: number, y: number, w: number, h: number) => {
            const data = pen.getImageData(Math.round(x), Math.round(y), w, h).data;
            return Array.from({ length: w * h }, (_, i) =>
              Math.max(0, 1 - light(data[i * 4], data[i * 4 + 1], data[i * 4 + 2]) / blank),
            );
          };
          // How a digit is shaped: its coverage in the atlas.
          const shape = (x: number, y: number, w: number, h: number) =>
            Array.from(glyphs.getImageData(x, y, w, h).data.filter((_, i) => i % 4 === 3));
          const likeness = (a: number[], b: number[]) => {
            const mean = (v: number[]) => v.reduce((t, x) => t + x, 0) / v.length;
            const [ma, mb] = [mean(a), mean(b)];
            let ab = 0;
            let aa = 0;
            let bb = 0;
            a.forEach((x, i) => {
              const y = (b[i] ?? 0) - mb;
              ab += (x - ma) * y;
              aa += (x - ma) ** 2;
              bb += y ** 2;
            });
            return aa && bb ? ab / Math.sqrt(aa * bb) : 0;
          };
          const out: string[] = [];
          for (const node of document.querySelectorAll<HTMLElement>(".sheet-page .slot.figure")) {
            const box = node.getBoundingClientRect();
            const calls = ink.filter(([, , , , x = 0, y = 0, w = 0, h = 0]) => {
              const middle = canvas.top + (y + h / 2) / dpr;
              const centre = canvas.left + (x + w / 2) / dpr;
              return (
                middle > box.top - box.height / 2 &&
                middle < box.bottom + box.height / 2 &&
                centre > box.left &&
                centre < box.right
              );
            });
            // The line's own baseline: the cell top most glyphs share.
            const tops = new Map<number, number>();
            for (const call of calls) {
              const top = Math.round(call[5] ?? 0);
              tops.set(top, (tops.get(top) ?? 0) + 1);
            }
            const line = [...tops].sort((a, b) => b[1] - a[1])[0]?.[0] ?? 0;
            const places = new Map<number, number[][]>();
            for (const call of calls) {
              const x = Math.round(call[4] ?? 0);
              places.set(x, [...(places.get(x) ?? []), call]);
            }
            for (const [x, cells] of places) {
              const typical = cells.find((call) => Math.abs((call[5] ?? 0) - line) < 1);
              const ghosts = cells.filter((call) => Math.abs((call[5] ?? 0) - line) >= 1);
              if (!typical || !ghosts.length) continue;
              const [sx = 0, sy = 0, sw = 0, sh = 0, , dy = 0, dw = 0, dh = 0] = typical;
              const read = seen(x, dy, Math.round(dw), Math.round(dh));
              const own = shape(sx, sy, sw, sh);
              const score = likeness(read, own);
              for (const [gx = 0, gy = 0] of ghosts) {
                const other = shape(gx, gy, sw, sh);
                // A ghost of the same digit in the alarm ink has the typical digit's shape.
                if (likeness(own, other) > 0.98) continue;
                const rival = likeness(read, other);
                if (rival >= score)
                  out.push(
                    `${node.querySelector(".slot-text")?.textContent} at x ${x}: typical ${score.toFixed(2)}, ghost ${rival.toFixed(2)}`,
                  );
              }
            }
          }
          return out;
        });
        expect(misread, `${pages} of ${total} pages`).toEqual([]);
      });
    });
});
