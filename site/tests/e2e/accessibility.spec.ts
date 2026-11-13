import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import type { Hindcast } from "../../src/types";
import { demo, demoRules, recordedCount } from "../fixtures/demo";
import { HOME_NOW } from "../fixtures/home";

const hindcast = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/hindcast/full.json", import.meta.url), "utf8"),
) as Hindcast;

const launchPath = `/launch/${demo.launch.id}/`;
const tabKey = (browserName: string): string => (browserName === "webkit" ? "Alt+Tab" : "Tab");

async function skipToMain(page: Page, browserName: string): Promise<void> {
  await page.keyboard.press(tabKey(browserName));
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
}

async function expectFocusRing(page: Page): Promise<void> {
  const outline = await page.evaluate(() => {
    const active = document.activeElement;
    return active instanceof HTMLElement ? getComputedStyle(active).outlineStyle : "none";
  });
  expect(outline).not.toBe("none");
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

test("keyboard walk reaches the home launch links with a visible ring", async ({
  page,
  browserName,
}) => {
  await page.clock.setFixedTime(HOME_NOW);
  await page.goto("/");
  const list = page.getByRole("list", { name: "Upcoming launches" });
  await expect(list).toBeVisible();
  await skipToMain(page, browserName);
  await page.keyboard.press(tabKey(browserName));
  const firstLink = page.locator(".launch-row").first().getByRole("link");
  await expect(firstLink).toBeFocused();
  await expectFocusRing(page);
});

test("keyboard walk reaches the sheet, the rule select, scrubber and table disclosure", async ({
  page,
  browserName,
}) => {
  await page.clock.setFixedTime(new Date(demo.evaluated_at));
  await page.goto(launchPath);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    demo.launch.name.replace(" | ", ", "),
  );
  await skipToMain(page, browserName);
  for (const figure of await page.locator("button.figure").all()) {
    await page.keyboard.press(tabKey(browserName));
    await expect(figure).toBeFocused();
    await expectFocusRing(page);
  }
  await page.keyboard.press(tabKey(browserName));
  await expect(page.getByRole("slider", { name: "Pages on the sheet" })).toBeFocused();
  await page.keyboard.press(tabKey(browserName));
  await expect(page.getByRole("link", { name: "Read the audit" })).toBeFocused();
  for (const pick of await page.locator(".board .rule-pick").all()) {
    await page.keyboard.press(tabKey(browserName));
    await expect(pick).toBeFocused();
    await expectFocusRing(page);
  }
  for (const model of ["ECMWF", "GFS"]) {
    await page.keyboard.press(tabKey(browserName));
    await expect(page.getByRole("button", { name: model, exact: true })).toBeFocused();
  }
  await page.keyboard.press(tabKey(browserName));
  const slider = page.getByRole("slider", { name: "Selected hour" });
  await expect(slider).toBeFocused();
  await expectFocusRing(page);
  await page.keyboard.press(tabKey(browserName));
  const disclosure = page.locator("summary", { hasText: "Each hour in figures" });
  await expect(disclosure).toBeFocused();
  await page.keyboard.press("Enter");
  const table = page.getByRole("table", {
    name: `${demoRules[0]?.title ?? ""}: hourly member evidence`,
  });
  await expect(table).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(table).toBeHidden();
});

test("keyboard walk reaches the audit tables and a visible focus ring", async ({
  page,
  browserName,
}) => {
  await page.route("**/data/hindcast.json", (route) => route.fulfill({ json: hindcast }));
  await page.goto("/audit/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Forecast audit");
  await skipToMain(page, browserName);
  await page.keyboard.press(tabKey(browserName));
  await expectFocusRing(page);
  await expect(page.getByRole("table").first()).toBeVisible();
});

test("the rule board names every rule as a toggle that picks the plotted rule", async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date(demo.evaluated_at));
  await page.goto(launchPath);
  const picks = page.locator(".board .rule-pick");
  await expect(picks).toHaveCount(demoRules.length);
  const top = demoRules[0];
  const next = demoRules[1];
  if (!top || !next) throw new Error("The recorded demo needs two rules");
  const pick = (id: string) => page.locator(`.board .rule-pick[data-rule-id="${id}"]`);
  await expect(pick(top.rule_id)).toHaveAttribute("aria-pressed", "true");
  await pick(next.rule_id).click();
  await expect(pick(next.rule_id)).toHaveAttribute("aria-pressed", "true");
  await expect(pick(top.rule_id)).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByRole("status")).toContainText(recordedCount(next, "ecmwf", demo.t0_index));
});

test("the scrubber readout is a polite atomic status with a described slider", async ({ page }) => {
  await page.clock.setFixedTime(new Date(demo.evaluated_at));
  await page.goto(launchPath);
  const status = page.getByRole("status");
  await expect(status).toHaveAttribute("aria-live", "polite");
  await expect(status).toHaveAttribute("aria-atomic", "true");
  const slider = page.getByRole("slider", { name: "Selected hour" });
  await expect(slider).toHaveAttribute("aria-describedby", "keyboard-hint");
  await expect(slider).toHaveAttribute("aria-valuetext", /UTC/);
  await slider.focus();
  await slider.press("ArrowRight");
  await expect(status).toContainText(/At \d\d:\d\d/);
});

test("the table disclosure opens with the keyboard and keeps its caption", async ({ page }) => {
  await page.clock.setFixedTime(new Date(demo.evaluated_at));
  await page.goto(launchPath);
  const disclosure = page.locator("summary", { hasText: "Each hour in figures" });
  await disclosure.focus();
  await page.keyboard.press("Enter");
  const table = page.getByRole("table", {
    name: `${demoRules[0]?.title ?? ""}: hourly member evidence`,
  });
  await expect(table).toBeVisible();
  await expect(table.getByRole("rowheader").first()).toContainText("UTC");
  await page.keyboard.press("Space");
  await expect(table).toBeHidden();
});

for (const [name, path, now] of [
  ["home", "/", HOME_NOW],
  ["launch", launchPath, new Date(demo.evaluated_at)],
  ["audit", "/audit/", new Date(demo.evaluated_at)],
] as const) {
  test(`${name} reflows at 200 percent zoom without horizontal scrolling`, async ({ page }) => {
    await page.clock.setFixedTime(now);
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(path);
    await page.evaluate(() => {
      document.documentElement.style.zoom = "2";
    });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });
}
