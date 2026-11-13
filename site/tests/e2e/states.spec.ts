import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import type { Latest, LaunchAssessment } from "../../src/types";
import {
  capeAssessment,
  HOME_NOW,
  homeFixture,
  RECORDED_HOME_NOW,
  recordedLatest,
} from "../fixtures/home";
import { twoHourFixture } from "../fixtures/scrubber";

type State =
  | "home"
  | "home-stress"
  | "launch"
  | "loading"
  | "empty"
  | "no-tier-a"
  | "data-error"
  | "unsupported-schema"
  | "invalid-data"
  | "schedule-stale"
  | "refresh-deferred"
  | "window-beyond-range"
  | "not-found"
  | "missing-official"
  | "tier-b"
  | "tier-c"
  | "lowest-hour"
  | "no-lower-hour"
  | "audit-pending";

const states: readonly State[] = [
  "home",
  "home-stress",
  "launch",
  "loading",
  "empty",
  "no-tier-a",
  "data-error",
  "unsupported-schema",
  "invalid-data",
  "schedule-stale",
  "refresh-deferred",
  "window-beyond-range",
  "not-found",
  "missing-official",
  "tier-b",
  "tier-c",
  "lowest-hour",
  "no-lower-hour",
  "audit-pending",
];

async function openState(page: Page, state: State): Promise<() => void> {
  const latest: Latest = state === "home" ? structuredClone(recordedLatest) : homeFixture();
  let assessment: LaunchAssessment = structuredClone(capeAssessment);
  let path = "/";
  let readyText = "Upcoming launches";
  let release = () => {};
  const gate =
    state === "loading"
      ? new Promise<void>((resolve) => {
          release = resolve;
        })
      : Promise.resolve();
  if (
    [
      "launch",
      "refresh-deferred",
      "missing-official",
      "tier-b",
      "lowest-hour",
      "no-lower-hour",
      "window-beyond-range",
      "tier-c",
    ].includes(state)
  ) {
    path = `/launch/${assessment.launch.id}/`;
    readyText = assessment.launch.name.replace(" | ", ", ");
  }
  switch (state) {
    case "loading":
      readyText = "Loading launch data.";
      break;
    case "empty":
      latest.launches = [];
      readyText = "No orbital launches in the next 10 days.";
      break;
    case "no-tier-a":
      latest.launches = latest.launches.filter((launch) => launch.tier === "C");
      path = "/next/";
      readyText = "No Florida or California launch in the next 10 days. Showing the next launch.";
      break;
    case "data-error":
      readyText = "Couldn't load launch data.";
      break;
    case "unsupported-schema":
      readyText = "This data uses schema version 2; Scrubcast supports version 1.";
      break;
    case "invalid-data":
      readyText = "The published launch data could not be read.";
      break;
    case "schedule-stale":
      latest.schedule_stale = true;
      break;
    case "refresh-deferred":
      assessment.refresh_deferred = true;
      break;
    case "missing-official":
      assessment.official = { ...assessment.official, probability_go_pct: null, concerns: [] };
      assessment.launch.weather_concerns = null;
      break;
    case "tier-b":
      assessment.tier = "B";
      assessment.rules = assessment.rules.map((rule) => ({ ...rule, reference_only: true }));
      break;
    case "tier-c":
    case "window-beyond-range":
      latest.launches = latest.launches.slice(0, 1).map((launch) => ({
        ...launch,
        tier: state === "tier-c" ? "C" : "A",
        assessment: false,
        net: state === "tier-c" ? launch.net : "2026-11-18T19:00:00Z",
        window_start: state === "tier-c" ? launch.window_start : "2026-11-18T19:00:00Z",
        window_end: state === "tier-c" ? launch.window_end : "2026-11-18T20:00:00Z",
        worst_rule: { label: state === "tier-c" ? "No published rules" : "Forecast unavailable" },
      }));
      break;
    case "not-found":
      path = "/404.html";
      readyText = "Launch not found or older than 90 days.";
      break;
    case "lowest-hour":
      assessment = twoHourFixture([20, 12, 18]);
      assessment.lowest_union_hour = {
        hour: "2026-11-07T02:00:00Z",
        members_below_t0: 8,
        union_risk: 0.3,
      };
      break;
    case "no-lower-hour":
      assessment = twoHourFixture();
      break;
    case "audit-pending":
      path = "/audit/";
      readyText = "Forecast audit";
      break;
  }
  await page.clock.setFixedTime(state === "home" ? RECORDED_HOME_NOW : HOME_NOW);
  await page.route("**/launch/*/", async (route) => {
    const response = await route.fetch();
    const body = (await response.text()).replaceAll(
      'id="first-paint"',
      'id="first-paint-disabled"',
    );
    await route.fulfill({ response, body });
  });
  await page.route("**/data/latest.json", async (route) => {
    await gate;
    if (state === "data-error") await route.abort();
    else if (state === "unsupported-schema")
      await route.fulfill({ json: { ...latest, schema_version: 2 } });
    else if (state === "invalid-data")
      await route.fulfill({ json: { ...latest, launches: [null] } });
    else await route.fulfill({ json: latest });
  });
  await page.route("**/data/launches/*.json", (route) => route.fulfill({ json: assessment }));
  await page.goto(path);
  await expect(page.getByRole("heading", { name: readyText, exact: true })).toBeVisible();
  if (state === "unsupported-schema")
    await expect(page.getByText(`Last build: ${latest.generated_at}.`)).toBeVisible();
  if (state === "home") {
    await expect(page.locator(".launch-row")).toHaveCount(recordedLatest.launches.length);
    await expect(page.locator(".launch-row").filter({ hasText: /Mission \d+ \|/ })).toHaveCount(0);
  }
  if (state === "launch" || state === "tier-b") await expect(page.locator(".board")).toBeVisible();
  if (state === "refresh-deferred")
    await expect(page.getByRole("heading", { name: /this refresh was deferred/ })).toBeVisible();
  if (state === "schedule-stale")
    await expect(
      page.getByRole("heading", { name: /did not answer the last refresh/ }),
    ).toBeVisible();
  if (state === "window-beyond-range")
    await expect(page.getByRole("heading", { name: /Rules appear about 10 days/ })).toBeVisible();
  if (state === "tier-c")
    await expect(page.getByText("No published rules", { exact: true })).toBeVisible();
  if (state === "missing-official") {
    await expect(page.locator(".sheet-facts")).toContainText("Not published");
    await expect(page.locator(".board .rule-pick").first()).toBeVisible();
  }
  if (state === "lowest-hour") await expect(page.locator(".lowest-risk-marker")).toHaveCount(1);
  if (state === "no-lower-hour")
    await expect(
      page.getByText("No materially lower hour established", { exact: true }),
    ).toBeVisible();
  return release;
}

for (const state of states) {
  for (const colorScheme of ["dark", "light"] as const) {
    for (const width of [1280, 390]) {
      test(`${state} ${colorScheme} ${width}px`, async ({ page }, testInfo) => {
        await page.setViewportSize({ width, height: 900 });
        await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
        const release = await openState(page, state);
        try {
          await page.evaluate(() => document.fonts.ready);
          const directory = resolve("test-results/states", testInfo.project.name);
          await mkdir(directory, { recursive: true });
          const path = resolve(directory, `${state}-${colorScheme}-${width}.png`);
          await page.screenshot({ path, fullPage: true, animations: "disabled" });
          await testInfo.attach(`${state}-${colorScheme}-${width}`, {
            path,
            contentType: "image/png",
          });
          expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
          ).toBe(true);
          expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
        } finally {
          release();
        }
      });
    }
  }
}
