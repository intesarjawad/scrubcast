import { expect, type Page, test } from "@playwright/test";
import { sweepFixture } from "../fixtures/scrubber";

// 50 ms is the longest acceptable frame at four times CPU throttling, the same
// ceiling the hourly scrubber already holds locally.
const FRAME_BUDGET_MS = 50;

type TimingWindow = Window & {
  scrubTimings?: { frameIntervals: number[]; longTasks: number[] };
};

async function open(page: Page): Promise<void> {
  const assessment = sweepFixture();
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
}

test.use({ viewport: { width: 390, height: 900 }, trace: "on" });

test("twenty-four hourly steps stay inside the frame budget at four times CPU throttling", async ({
  page,
  browserName,
  context,
}) => {
  // Only Chromium can throttle the CPU. Without it the frame times are the machine's, not the page's.
  test.skip(browserName !== "chromium", "CPU throttling needs the DevTools protocol");
  await open(page);
  const range = page.getByRole("slider", { name: "Selected hour" });
  await range.focus();
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
  });
  const session = await context.newCDPSession(page);
  await session.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await page.evaluate(() => {
    const holder = window as TimingWindow;
    holder.scrubTimings = { frameIntervals: [], longTasks: [] };
    let previous = performance.now();
    const frame = (now: number) => {
      holder.scrubTimings?.frameIntervals.push(now - previous);
      previous = now;
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
    if (PerformanceObserver.supportedEntryTypes.includes("longtask")) {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) holder.scrubTimings?.longTasks.push(entry.duration);
      });
      observer.observe({ type: "longtask" });
    }
  });
  for (let step = 0; step < 24; step++) await range.press("ArrowRight");
  const timings = await page.evaluate(
    () => (window as TimingWindow).scrubTimings ?? { frameIntervals: [], longTasks: [] },
  );
  const frames = timings.frameIntervals.slice(2);
  expect(frames.length).toBeGreaterThan(0);
  const sorted = [...frames].sort((left, right) => left - right);
  const p95 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] ?? 0;
  expect(p95).toBeLessThanOrEqual(FRAME_BUDGET_MS);
  expect(timings.longTasks.filter((duration) => duration > FRAME_BUDGET_MS)).toEqual([]);
  await test.info().attach("frame-budget.json", {
    body: JSON.stringify({ frames: frames.length, p95, longTasks: timings.longTasks }),
    contentType: "application/json",
  });
});
