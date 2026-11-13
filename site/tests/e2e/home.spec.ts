import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { CAPE_CHIP, HOME_NOW, homeFixture } from "../fixtures/home";

test.use({ trace: "on" });

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(HOME_NOW);
  await page.route("**/data/latest.json", (route) => route.fulfill({ json: homeFixture() }));
  await page.goto("/");
  await expect(page.getByRole("list", { name: "Upcoming launches" })).toBeVisible();
});

test("twelve launches show countdown, pad, tier and the published worst rule", async ({ page }) => {
  const rows = page.locator(".launch-row");
  await expect(rows).toHaveCount(12);
  await expect(rows.first()).toContainText("in 7 h 0 m");
  await expect(rows.first()).toContainText(homeFixture().launches[0]?.pad.name ?? "");
  await expect(rows.first().locator(".weather-finding")).toHaveText(CAPE_CHIP);
  await expect(rows.nth(1).locator(".weather-finding")).toHaveText("Cumulus 22% (LLCC reference)");
  await expect(rows.nth(2).locator(".weather-finding")).toHaveText("No published rules");
  await expect(rows.nth(3).locator(".weather-finding")).toHaveText("No rule above 5%");
  const cape = homeFixture().launches[0];
  if (!cape) throw new Error("Missing Cape launch");
  await rows.first().getByRole("link").click();
  await expect(page).toHaveURL(new RegExp(`/launch/${cape.id}/$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(cape.name.replace(" | ", ", "));
});

// A fixed clock replaces the Performance API, so the timing needs its own context
// and a schedule anchored to the real clock.
test("twelve launches render in under 100 ms", async ({ browser, baseURL }) => {
  if (!baseURL) throw new Error("Missing baseURL");
  const context = await browser.newContext({ baseURL });
  const page = await context.newPage();
  const latest = homeFixture(12, new Date());
  await page.route("**/data/latest.json", (route) => route.fulfill({ json: latest }));
  await page.goto("/");
  await expect(page.locator(".launch-row")).toHaveCount(12);
  const durations = await page.evaluate(() =>
    performance.getEntriesByName("home-render").map((entry) => entry.duration),
  );
  expect(durations).toHaveLength(1);
  expect(durations[0]).toBeLessThan(100);
  await test.info().attach("home-render-ms", {
    body: JSON.stringify(durations),
    contentType: "application/json",
  });
  await context.close();
});

test("Tab reaches every mission link in launch-time order", async ({ page, browserName }) => {
  // Safari only tabs to links with Option held unless full keyboard access is on.
  const tab = browserName === "webkit" ? "Alt+Tab" : "Tab";
  await page.keyboard.press(tab);
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
  for (const row of await page.locator(".launch-row").all()) {
    await page.keyboard.press(tab);
    const link = row.getByRole("link");
    await expect(link).toBeFocused();
    const outline = await link.evaluate((node) => getComputedStyle(node).outlineStyle);
    expect(outline).not.toBe("none");
  }
});

for (const colorScheme of ["dark", "light"] as const) {
  for (const width of [1280, 390, 320]) {
    test(`thirty launches at ${width}px in ${colorScheme} reflow and pass axe`, async ({
      page,
    }) => {
      await page.route("**/data/latest.json", (route) => route.fulfill({ json: homeFixture(30) }));
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
      await page.reload();
      await expect(page.locator(".launch-row")).toHaveCount(30);
      await page.evaluate(() => document.fonts.ready);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      expect(
        await page
          .locator(".countdown")
          .evaluateAll((nodes) =>
            nodes.every((node) => getComputedStyle(node).whiteSpace === "nowrap"),
          ),
      ).toBe(true);
      expect(
        await page
          .locator(".tier-label, .weather-finding")
          .evaluateAll((nodes) =>
            nodes.every((node) => getComputedStyle(node).borderStyle === "none"),
          ),
      ).toBe(true);
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    });
  }
}

test("forced colours keep row labels and keyboard focus legible", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 900 });
  await expect(page.locator(".launch-row").first().locator(".weather-finding")).toHaveText(
    CAPE_CHIP,
  );
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("the next launch leads with its official forecast and top rule", async ({ page }) => {
  const latest = homeFixture();
  const first = latest.launches[0];
  if (!first) throw new Error("Missing first launch");
  first.probability = 95;
  await page.route("**/data/latest.json", (route) => route.fulfill({ json: latest }));
  await page.reload();
  const rows = page.locator(".launch-row");
  await expect(rows.first()).toHaveClass(/lead-launch/);
  await expect(page.locator(".lead-launch")).toHaveCount(1);
  await expect(rows.first().locator(".countdown")).toContainText("Next launch");
  await expect(rows.first().locator(".lead-forecast")).toHaveText(
    `${first.probability}% Official probability of GO`,
  );
  await expect(rows.first().locator(".weather-finding")).toHaveText(CAPE_CHIP);
  const sizes = await rows
    .locator("h2")
    .evaluateAll((titles) =>
      titles.map((title) => Number.parseFloat(getComputedStyle(title).fontSize)),
    );
  expect(new Set(sizes).size).toBe(1);
  await expect(rows.nth(1).locator(".lead-forecast")).toHaveCount(0);
});

test("the lead row omits an unpublished probability and reflows at 200 percent zoom", async ({
  page,
}) => {
  const latest = homeFixture();
  const first = latest.launches[0];
  if (!first) throw new Error("Missing first launch");
  first.probability = null;
  await page.route("**/data/latest.json", (route) => route.fulfill({ json: latest }));
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.reload();
  await page.evaluate(() => {
    document.documentElement.style.zoom = "2";
  });
  await expect(page.locator(".lead-launch .weather-finding")).toHaveText(CAPE_CHIP);
  await expect(page.locator(".lead-forecast")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
