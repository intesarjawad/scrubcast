import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { SHORT_NAMES } from "../../src/charts/sheet-data";
import { ruleNote } from "../../src/launch-comparison";
import { isLaunchAssessment } from "../../src/launch-data";
import { demoRules, recordedCount, riskiestFirst } from "../fixtures/demo";
import { plotSettled } from "./plot";

const models = ["ecmwf", "gfs"] as const;

const data: unknown = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/demo/assessment.json", import.meta.url), "utf8"),
);
if (!isLaunchAssessment(data)) throw new Error("Invalid recorded assessment");
const assessment = data;
const path = `/launch/${assessment.launch.id}/`;
// Launch Library separates vehicle and mission with a bar; the page prints a comma.
const title = assessment.launch.name.replace(" | ", ", ");

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date(assessment.evaluated_at));
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
});

test("the board lists the breaking rules and names the clear ones in one sentence", async ({
  page,
}) => {
  const probability = assessment.launch.probability;
  await expect(page.locator(".sheet-facts")).toContainText(
    probability === null ? "Not published" : `${probability}% probability of GO`,
  );
  await expect(page.locator(".source-note")).toHaveCount(0);
  await page.locator('.board .rule-pick[data-rule-id="thick_cloud"]').click();
  await expect(page.locator(".proxy")).not.toContainText("Falcon");
  const flagged = demoRules.filter((rule) =>
    models.some((model) => (rule.by_model[model]?.risk_fraction ?? 0) > 0),
  );
  const table = page.getByRole("table", { name: "Members breaking each rule at T-0" });
  await expect(table).toHaveCount(flagged.length ? 1 : 0);
  for (const rule of flagged) {
    const row = table.locator(`tr[data-rule-id="${rule.rule_id}"]`);
    for (const [column, model] of models.entries()) {
      const count = recordedCount(rule, model, assessment.t0_index);
      await expect(row.getByRole("cell").nth(column)).toContainText(count);
    }
  }
  const clear = page.locator(".board-clear");
  for (const rule of demoRules.filter((rule) => !flagged.includes(rule)))
    await expect(clear.locator(`[data-rule-id="${rule.rule_id}"]`)).toHaveCount(1);
  await expect(clear).toContainText("Anvil (GFS cannot evaluate it)");
  await expect(
    page.getByText("Scrubcast is not the launch weather officer", { exact: true }),
  ).toBeVisible();
});

test("cannot-evaluate entries include their reasons", async ({ page }) => {
  const limits = page.getByRole("region", { name: /^Left blank on all \d+ pages$/ });
  for (const rule of assessment.not_evaluable) {
    const item = limits.getByRole("listitem").filter({ hasText: rule.title });
    await expect(item).toContainText(rule.reason);
  }
});

test("published official values retain the source probability and concern", async ({ page }) => {
  const published = {
    ...assessment,
    launch: { ...assessment.launch, probability: 95, weather_concerns: "Cumulus Cloud Rule" },
    official: { ...assessment.official, probability_go_pct: 95, concerns: ["cumulus"] },
  };
  await page.route(`**/data/launches/${assessment.launch.id}.json`, (route) =>
    route.fulfill({ json: published }),
  );
  await page.reload();
  await expect(page.locator(".sheet-facts")).toContainText(
    `${published.launch.probability}% probability of GO, via Launch Library 2. Concern: ${published.launch.weather_concerns}`,
  );
  await expect(page.locator(".source-note")).toContainText(
    `Official concern: ${published.launch.weather_concerns}.`,
  );
});

test("missing official values and reference rules keep explicit labels", async ({ page }) => {
  const reference = {
    ...assessment,
    tier: "B",
    launch: { ...assessment.launch, weather_concerns: null },
    official: { ...assessment.official, probability_go_pct: null, concerns: [] },
    rules: assessment.rules.map((rule) => ({ ...rule, reference_only: true })),
  };
  await page.route(`**/data/launches/${assessment.launch.id}.json`, (route) =>
    route.fulfill({ json: reference }),
  );
  await page.reload();
  await expect(page.locator(".board-clear")).toContainText(
    "No evaluable member breaks any LLCC reference rule at T-0",
  );
  await expect(page.locator(".sheet-facts")).toContainText("Not published");
  await expect(page.locator(".source-note")).toHaveCount(0);
});

test("first paint remains readable when the full assessment cannot be fetched", async ({
  page,
}) => {
  await page.route(`**/data/launches/${assessment.launch.id}.json`, (route) => route.abort());
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
  // Without member values there is no figure to open on, so the riskiest rule leads.
  const top = riskiestFirst(assessment.rules)[0];
  if (!top) throw new Error("Missing top rule");
  await expect(page.locator(".board")).toContainText(SHORT_NAMES[top.rule_id] ?? top.title);
  await expect(page.locator(".readout").first()).toContainText(
    recordedCount(top, "ecmwf", assessment.t0_index),
  );
});

test("keyboard navigation reaches rule methods", async ({ page, browserName }) => {
  // Safari only tabs to links with Option held unless full keyboard access is on.
  const tab = browserName === "webkit" ? "Alt+Tab" : "Tab";
  await page.keyboard.press(tab);
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
  const figures = page.locator("button.figure");
  expect(await figures.count()).toBeGreaterThan(0);
  for (const figure of await figures.all()) {
    await page.keyboard.press(tab);
    await expect(figure).toBeFocused();
  }
  await page.keyboard.press(tab);
  await expect(page.getByRole("slider", { name: "Pages on the sheet" })).toBeFocused();
  await page.keyboard.press(tab);
  await expect(page.getByRole("link", { name: "Read the audit" })).toBeFocused();
  for (const pick of await page.locator(".board .rule-pick").all()) {
    await page.keyboard.press(tab);
    await expect(pick).toBeFocused();
  }
  for (const model of ["ECMWF", "GFS"]) {
    await page.keyboard.press(tab);
    await expect(page.getByRole("button", { name: model, exact: true })).toBeFocused();
  }
  await page.keyboard.press(tab);
  await expect(page.getByRole("slider", { name: "Selected hour" })).toBeFocused();
  await page.keyboard.press(tab);
  await expect(page.getByText("Each hour in figures", { exact: true })).toBeFocused();
  await page.keyboard.press(tab);
  await expect(
    page.getByText("Rule thresholds and approximation notes", { exact: true }),
  ).toBeFocused();
});

for (const colorScheme of ["light", "dark"] as const) {
  for (const width of [1280, 390, 320]) {
    test(`${colorScheme} at ${width}px has no overflow or axe violations`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
      await page.evaluate(() => document.fonts.ready);
      await plotSettled(page);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      const readable = await page
        .locator(
          ".annotation-lane, .annotation-lane small, .threshold-label, .badge, .rule-board td, .rule-board th, .axis-label, .utc-tick, .handle-utc",
        )
        .evaluateAll((nodes) =>
          nodes.every((node) => Number.parseFloat(getComputedStyle(node).fontSize) >= 13),
        );
      expect(readable).toBe(true);
      // On a phone the facts follow the sheet, so only the sheet's opening must fit.
      for (const selector of [".sheet-title", "button.figure"]) {
        const bounds = await page.locator(selector).first().boundingBox();
        expect(bounds).not.toBeNull();
        expect((bounds?.y ?? Infinity) + (bounds?.height ?? Infinity)).toBeLessThanOrEqual(900);
      }
      const wholeLinks = await page.locator(".site-footer nav a").evaluateAll((links) =>
        links.every((link) => {
          const range = document.createRange();
          range.selectNodeContents(link);
          return range.getClientRects().length === 1;
        }),
      );
      expect(wholeLinks).toBe(true);
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
      await expect(page).toHaveScreenshot(`launch-${colorScheme}-${width}.png`, { fullPage: true });
    });
  }
}

test("forced colours keep the board and plot readable", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 900 });
  await expect(page.locator(".board")).toBeVisible();
  // The page loaded with motion, so the fan only fades in once that press run ends.
  await expect(page.locator(".spread")).toHaveAttribute("data-phase", "set", { timeout: 15_000 });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await expect(page).toHaveScreenshot("launch-forced-colours.png", { fullPage: true });
});

test("200 percent zoom reflows the plot, annotations and expanded table", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "2";
  });
  await page.getByText("Each hour in figures", { exact: true }).click();
  await expect(page.locator(".hour-table")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  for (const selector of [".annotation-lane", ".hour-table", ".rule-board", ".plot"]) {
    for (const node of await page.locator(selector).all()) {
      const box = await node.boundingBox();
      expect(box).not.toBeNull();
      expect(box?.x).toBeGreaterThanOrEqual(0);
      expect((box?.x ?? Infinity) + (box?.width ?? Infinity)).toBeLessThanOrEqual(1280);
    }
  }
});

test("source concern wording survives unfamiliar terms without fallback labels", async ({
  page,
}) => {
  const source = "Coastal showers; cumulus near the flight path";
  await page.route(`**/data/launches/${assessment.launch.id}.json`, (route) =>
    route.fulfill({
      json: { ...assessment, launch: { ...assessment.launch, weather_concerns: source } },
    }),
  );
  await page.reload();
  await expect(page.locator(".sheet-facts")).toContainText(`Concern: ${source}`);
  await expect(page.locator(".source-note")).toContainText(`Official concern: ${source}.`);
  await expect(page.locator(".sheet-facts")).not.toContainText("Unknown concern");
});

test("the header offers the same navigation on launch and home views", async ({ page }) => {
  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  await expect(navigation).toBeVisible();
  const launchLinks = await navigation
    .getByRole("link")
    .evaluateAll((links) =>
      links.map((link) => ({ text: link.textContent, href: link.getAttribute("href") })),
    );
  await navigation.getByRole("link", { name: "Launches", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Upcoming launches", exact: true })).toBeVisible();
  expect(
    await navigation
      .getByRole("link")
      .evaluateAll((links) =>
        links.map((link) => ({ text: link.textContent, href: link.getAttribute("href") })),
      ),
  ).toEqual(launchLinks);
});

test("unavailable assessments never claim members are clear", async ({ page }) => {
  const rules = assessment.rules.map((rule) => ({
    ...rule,
    by_model: Object.fromEntries(
      Object.entries(rule.by_model).map(([model, risk]) => [
        model,
        { ...risk, risk_fraction: null, evaluable_members: 0 },
      ]),
    ),
    member_violated_by_hour: {},
  }));
  await page.route(`**/data/launches/${assessment.launch.id}.json`, (route) =>
    route.fulfill({ json: { ...assessment, rules } }),
  );
  await page.reload();
  await expect(page.getByText("Rule assessment not available", { exact: true })).toHaveCount(1);
  await expect(page.locator("#app")).not.toContainText("No member breaks");
});

test("reference and Tier C assessments do not present rules as launch criteria", async ({
  page,
}) => {
  await page.route(`**/data/launches/${assessment.launch.id}.json`, (route) =>
    route.fulfill({
      json: {
        ...assessment,
        tier: "B",
        rules: assessment.rules.map((rule) => ({ ...rule, reference_only: true })),
      },
    }),
  );
  await page.reload();
  await expect(page.locator(".sheet-facts")).toContainText("Reference only");
  await page.unroute(`**/data/launches/${assessment.launch.id}.json`);
  await page.route(`**/data/launches/${assessment.launch.id}.json`, (route) =>
    route.fulfill({ json: { ...assessment, tier: "C" } }),
  );
  await page.reload();
  await expect(page.getByText("No rule assessment is published for this pad.")).toBeVisible();
  await expect(page.locator(".sheet-facts")).toContainText("Official");
  await expect(page.locator(".sheet-facts")).not.toContainText("Breaking");
});

test("forecast fetch date and time both use UTC", async ({ page }) => {
  await expect(page.locator(".sheet-facts")).toContainText("Fetched Nov 6, 2026, 01:30 UTC");
});

test("share cards label reference rules and suppress Tier C rule headlines", async ({ page }) => {
  let tier: "B" | "C" = "B";
  await page.route(`**${path}*`, async (route) => {
    const response = await route.fetch();
    const html = await response.text();
    const data = {
      ...assessment,
      tier,
      rules: assessment.rules.map((rule) => ({ ...rule, reference_only: true })),
    };
    await route.fulfill({
      response,
      body: html.replace(
        /<script type="application\/json" id="first-paint">.*?<\/script>/,
        `<script type="application/json" id="first-paint">${JSON.stringify(data)}</script>`,
      ),
    });
  });
  await page.route(`**/data/launches/${assessment.launch.id}.json`, (route) =>
    route.fulfill({
      json: {
        ...assessment,
        tier,
        rules: assessment.rules.map((rule) => ({ ...rule, reference_only: true })),
      },
    }),
  );
  await page.goto(`${path}?card`);
  await expect(page.locator("#app")).toContainText("Reference only");
  tier = "C";
  await page.reload();
  await expect(page.locator("#app")).toContainText("No rule assessment is published for this pad.");
  await expect(page.locator(".card-verdict")).toHaveCount(0);
  await expect(page.locator("#app")).toContainText("Official");
});

for (const state of ["unavailable", "C"] as const) {
  test(`${state} keeps limitations, provenance and attempt history`, async ({ page }) => {
    const rules = assessment.rules.map((rule) => ({
      ...rule,
      by_model: Object.fromEntries(
        Object.entries(rule.by_model).map(([model, risk]) => [
          model,
          {
            ...risk,
            risk_fraction: null,
            evaluable_members: 0,
          },
        ]),
      ),
      member_violated_by_hour: {},
    }));
    await page.route(`**/data/launches/${assessment.launch.id}.json`, (route) =>
      route.fulfill({
        json: {
          ...assessment,
          tier: state === "C" ? "C" : assessment.tier,
          rules,
          audit: [
            {
              attempt_id: "recorded-attempt",
              attempt_net: assessment.launch.net,
              official_concerns: [],
              scrubcast_24h: [],
              outcome: "unknown",
              net_now: null,
              note: null,
            },
          ],
        },
      }),
    );
    await page.reload();
    await expect(page.getByRole("heading", { name: "What happened" })).toBeVisible();
    for (const rule of assessment.not_evaluable)
      await expect(page.locator(".evidence")).toContainText(rule.reason);
    await expect(page.getByText("How it works", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Data and provenance", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Per-launch JSON" })).toBeVisible();
    await page.getByText("Rule thresholds and approximation notes", { exact: true }).click();
    for (const rule of assessment.rules)
      await expect(page.locator("#methods")).toContainText(ruleNote(rule));
  });
}
