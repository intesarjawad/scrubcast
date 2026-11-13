import { expect, type Page, test } from "@playwright/test";
import { scrubberFixture, sweepFixture, twoHourFixture } from "../fixtures/scrubber";
import { plotSettled } from "./plot";

async function open(page: Page, assessment = scrubberFixture()) {
  // Bypass the inline first paint so controlled hourly evidence is used immediately.
  await page.route(`**/launch/${assessment.launch.id}/`, async (route) => {
    const response = await route.fetch();
    const html = (await response.text()).replaceAll(
      'id="first-paint"',
      'id="first-paint-disabled"',
    );
    await route.fulfill({ response, body: html });
  });
  await page.route(`**/data/launches/${assessment.launch.id}.json`, (route) =>
    route.fulfill({ json: assessment }),
  );
  await page.goto(`/launch/${assessment.launch.id}/`);
  await expect(page.locator(".board .rule-pick").first()).toBeVisible();
  // The sheet above typesets and prints once on load; these checks time the scrubber alone.
  await expect(page.locator(".spread")).toHaveAttribute("data-phase", "set", { timeout: 15_000 });
}

async function selectRule(page: Page, id: string) {
  await page.locator(`.board .rule-pick[data-rule-id="${id}"]`).click();
  await plotSettled(page);
  const range = page.getByRole("slider", { name: "Selected hour" });
  await range.focus();
  return range;
}

test("wind and cloud golden readouts use verdicts and retain member nodes", async ({ page }) => {
  await open(page);
  const range = await selectRule(page, "liftoff_wind");
  await expect(range).toHaveValue("0");
  await range.press("ArrowRight");
  await range.press("ArrowRight");
  await expect(page.getByRole("status")).toHaveText(
    "At 19:00 PST / 03:00 UTC19 of 51 ECMWF members exceed 13.4 m/s (49.4 m above the pad).",
  );
  await expect(page.locator(".pane-ecmwf .exceed")).toHaveCount(19);
  const member = await page.locator('.pane-ecmwf [data-member="0"]').elementHandle();
  await range.press("Home");
  expect(await member?.evaluate((node) => node.isConnected)).toBe(true);
  await expect(page.getByRole("status")).toContainText("/ 01:00 UTC");
  await range.press("End");
  await expect(range).toHaveValue("4");
  await expect(page.getByRole("status")).toContainText("/ 05:00 UTC");
  const cloud = await selectRule(page, "thick_cloud");
  await cloud.press("ArrowRight");
  await cloud.press("ArrowRight");
  await expect(page.getByRole("status")).toHaveText(
    "At 19:00 PST / 03:00 UTC1 of 51 ECMWF members have a cloud layer 1,400 m or thicker between 0 and \u221220 °C.",
  );
  await expect(page.locator('.pane-ecmwf [data-member="0"]')).toHaveAttribute("class", "member");
  const aboveClear = page.locator('.pane-ecmwf [data-member="0"]');
  const thresholdY = Number(await page.locator(".pane-ecmwf .threshold").getAttribute("y1"));
  const valueY = await aboveClear.evaluate((node) => {
    if (!(node instanceof SVGPathElement)) throw new Error("Expected member path");
    const points = [...(node.getAttribute("d") ?? "").matchAll(/[ML]([\d.]+),([\d.]+)/g)];
    return Number(points[2]?.[2]);
  });
  expect(valueY).toBeLessThan(thresholdY);
  await page.getByRole("button", { name: "GFS", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("0 of 31 GFS members");
  await page.getByText("Each hour in figures", { exact: true }).click();
  const table = page.getByRole("table", {
    name: "Thick Cloud Layers Rule: hourly member evidence",
  });
  await expect(table.getByRole("row").filter({ hasText: "03:00 UTC" })).toContainText("1 of 51");
});

test("two-hour window with a five-point difference makes no lowest-hour claim", async ({
  page,
}) => {
  const assessment = twoHourFixture();
  const wind = assessment.rules.find((rule) => rule.rule_id === "liftoff_wind");
  expect(wind?.risk_by_hour.ecmwf).toEqual([0.2, 0.175, 0.15]);
  expect(
    Date.parse(assessment.launch.window_end) - Date.parse(assessment.launch.window_start),
  ).toBe(2 * 3_600_000);
  await open(page, assessment);
  await expect(
    page.getByText("No materially lower hour established", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".lowest-risk-marker")).toHaveCount(0);
});

test("lowest-risk marker and exact-minute T-0 use the shared time scale", async ({ page }) => {
  const assessment = twoHourFixture([20, 12, 18]);
  assessment.lowest_union_hour = {
    hour: "2026-11-07T02:00:00Z",
    members_below_t0: 8,
    union_risk: 0.3,
  };
  await open(page, assessment);
  const marker = page.locator(".lowest-risk-marker");
  await expect(marker).toHaveAttribute("data-hour", "2026-11-07T02:00:00Z");
  const coordinates = await page.locator(".plot").evaluate((svg) => {
    const pane = svg.querySelector<SVGGElement>(".model-pane");
    const left = Number(pane?.dataset.plotLeft);
    const right = Number(pane?.dataset.plotRight);
    const start = Number(svg.getAttribute("data-domain-start"));
    const end = Number(svg.getAttribute("data-domain-end"));
    const x = (time: string) =>
      left + ((Date.parse(time) - start) / (end - start)) * (right - left);
    return {
      marker: Number(svg.querySelector(".lowest-risk-marker")?.getAttribute("x1")),
      expected: x("2026-11-07T02:00:00Z"),
      t0: Number(svg.querySelector(".t-zero-line")?.getAttribute("x1")),
      expectedT0: x("2026-11-07T01:07:00Z"),
    };
  });
  expect(coordinates.marker).toBeCloseTo(coordinates.expected, 5);
  expect(coordinates.t0).toBeCloseTo(coordinates.expectedT0, 5);
  await expect(page.getByText(/Lowest modelled risk in the window: 02:00 UTC/)).toContainText(
    "not yet verified against observed precipitation",
  );
});

for (const width of [1280, 390, 320]) {
  test(`scrubber at ${width}px respects reduced motion and has no horizontal scroll`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
    await open(page);
    const range = await selectRule(page, "liftoff_wind");
    await expect(page.locator(".plot")).toHaveCSS("height", "400px");
    await expect(page.locator(".threshold-key")).toHaveCount(0);
    await expect(page.locator(".threshold-label")).toHaveText(["13.4 m/s", "13.4 m/s"]);
    const count = page.locator('.pane-count[data-model="ecmwf"]');
    const firstX = Number(await count.getAttribute("x"));
    for (let hour = 0; hour < 5; hour++) {
      if (hour) await range.press("ArrowRight");
      await expect(count).toHaveText(hour === 2 ? "19 of 51" : "0 of 51");
      await expect(page.locator('.pane-count[data-model="gfs"]')).toHaveText("0 of 31");
      const separated = await page.locator(".plot").evaluate((svg) => {
        for (const model of ["ecmwf", "gfs"]) {
          const pane = svg.querySelector<SVGGElement>(`.model-pane[data-model="${model}"]`);
          const count = svg.querySelector<SVGTextElement>(`.pane-count[data-model="${model}"]`);
          const threshold = svg.querySelector<SVGTextElement>(
            `.threshold-label[data-model="${model}"]`,
          );
          if (!pane || !count || !threshold) throw new Error("Missing direct labels");
          const a = count.getBBox();
          const b = threshold.getBBox();
          if (
            a.x < b.x + b.width &&
            a.x + a.width > b.x &&
            a.y < b.y + b.height &&
            a.y + a.height > b.y
          )
            return false;
          const axes = [...pane.querySelectorAll(".axis")].map((axis) =>
            Number(axis.getAttribute("y1")),
          );
          for (const label of [a, b]) {
            if (
              label.x - 4 < Number(pane.dataset.plotLeft) ||
              label.x + label.width + 4 > Number(pane.dataset.plotRight) ||
              label.y - 4 < Math.min(...axes) ||
              label.y + label.height + 4 > Math.max(...axes)
            )
              return false;
          }
        }
        return true;
      });
      expect(separated).toBe(true);
    }
    expect(Number(await count.getAttribute("x"))).toBeGreaterThan(firstX);
    await range.press("Home");
    expect(
      await page
        .locator(".member")
        .evaluateAll((nodes) =>
          nodes.every((node) => getComputedStyle(node).transitionDuration === "0s"),
        ),
    ).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await expect(page).toHaveScreenshot(`scrubber-${width}.png`, { fullPage: true });
  });
}

test("forced colours distinguish threshold, cursor and violating traces", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await open(page);
  const range = await selectRule(page, "liftoff_wind");
  await range.press("ArrowRight");
  await range.press("ArrowRight");
  const dash = async (selector: string) =>
    page
      .locator(selector)
      .first()
      .evaluate((node) => getComputedStyle(node).strokeDasharray);
  expect(await dash(".threshold")).not.toBe(await dash(".cursor"));
  expect(await dash(".exceed")).not.toBe(await dash(".threshold"));
  await expect(page).toHaveScreenshot("scrubber-forced-colours.png", { fullPage: true });
});

test("24 hourly steps reuse traces within the 50 ms long-task budget", async ({
  page,
  browserName,
  context,
}) => {
  await open(page, sweepFixture());
  const range = await selectRule(page, "liftoff_wind");
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
  });
  const session = browserName === "chromium" ? await context.newCDPSession(page) : null;
  await session?.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  const monitor = await page.evaluateHandle(() => {
    const durations: number[] = [];
    const supported = PerformanceObserver.supportedEntryTypes.includes("longtask");
    const observer = supported
      ? new PerformanceObserver((list) => {
          durations.push(...list.getEntries().map((entry) => entry.duration));
        })
      : null;
    observer?.observe({ type: "longtask" });
    const root = document.querySelector(".plot");
    if (!root) throw new Error("Missing plot");
    const members = [...root.querySelectorAll(".member")];
    let additions = 0;
    const mutations = new MutationObserver((records) => {
      additions += records.reduce(
        (sum, record) => sum + record.addedNodes.length + record.removedNodes.length,
        0,
      );
    });
    mutations.observe(root, { childList: true, subtree: true });
    return { durations, supported, observer, members, mutations, additions: () => additions };
  });
  for (let hour = 1; hour <= 24; hour++) {
    await range.press("ArrowRight");
    await expect(range).toHaveValue(String(hour));
  }
  await expect(page.getByRole("status")).toContainText("/ 01:00 UTC");
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  const result = await monitor.evaluate((state) => {
    state.observer?.disconnect();
    state.mutations.disconnect();
    return {
      durations: state.durations,
      supported: state.supported,
      connected: state.members.every((node) => node.isConnected),
      additions: state.additions(),
    };
  });
  expect(result.connected).toBe(true);
  expect(result.additions).toBe(0);
  if (browserName === "chromium") {
    expect(result.supported).toBe(true);
    expect(Math.max(0, ...result.durations)).toBeLessThanOrEqual(50);
  }
  await monitor.dispose();
  await session?.send("Emulation.setCPUThrottlingRate", { rate: 1 });
});

test("the hour handle stays draggable and focused at the fixed T-0 marker", async ({ page }) => {
  const assessment = scrubberFixture();
  assessment.launch.net = assessment.rules[0]?.hours[0] ?? assessment.launch.net;
  await open(page, assessment);
  const range = await selectRule(page, "liftoff_wind");
  const cursor = page.locator(".cursor");
  const fixed = page.locator(".t-zero-line");
  expect(await cursor.getAttribute("x1")).toBe(await fixed.getAttribute("x1"));
  await expect(page.locator(".t-zero-mark")).toBeVisible();
  await expect(page.locator(".t-zero-label")).toHaveText("T-0");
  await expect(page.locator(".plot-wrap")).toHaveCSS("cursor", "grab");
  await expect(page.locator(".handle-grip")).toHaveCount(0);
  await range.press("ArrowRight");
  expect(await cursor.getAttribute("x1")).not.toBe(await fixed.getAttribute("x1"));
  // Resolve the colour token in the same context as the SVG stroke.
  expect(
    await page.locator(".cursor-handle").evaluate((node) => {
      const sample = document.createElement("span");
      sample.style.color = "var(--focus)";
      document.body.append(sample);
      const expected = getComputedStyle(sample).color;
      sample.remove();
      return getComputedStyle(node).stroke === expected;
    }),
  ).toBe(true);
  const pane = page.locator(".model-pane").first();
  const left = Number(await pane.getAttribute("data-plot-left"));
  const right = Number(await pane.getAttribute("data-plot-right"));
  // The mouse does not scroll, and the handle sits below the fold at this height.
  await page.locator(".cursor-handle").scrollIntoViewIfNeeded();
  const box = await page.locator(".plot").boundingBox();
  if (!box) throw new Error("Missing plot bounds");
  const handle = await page.locator(".cursor-handle").boundingBox();
  if (!handle) throw new Error("Missing handle bounds");
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  // Drag past the last hour so a resize between measuring and dragging cannot miss it.
  await page.mouse.move(box.x + box.width - 1, handle.y + handle.height / 2);
  await page.mouse.up();
  await expect(range).toHaveValue("4");
  expect(right).toBeGreaterThan(left);
});
