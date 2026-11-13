import { spawn } from "node:child_process";
import { expect, test } from "@playwright/test";
import { demo } from "../fixtures/demo";

test("production cards fetch complete evidence before signalling readiness", async ({ page }) => {
  await page.setViewportSize({ width: 1200, height: 630 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const requested = page.waitForResponse(`**/data/launches/${demo.launch.id}.json`);
  await page.goto(`/launch/${demo.launch.id}/?card`);
  expect((await requested).ok()).toBe(true);
  await expect(page.locator("#app")).toHaveAttribute("data-card-ready", demo.launch.id);
  await page.evaluate(() => document.fonts.ready);
  expect(
    await page.locator("#app").evaluate((app) => {
      const bounds = app.getBoundingClientRect();
      return [...app.children].every((child) => {
        const box = child.getBoundingClientRect();
        return (
          box.bottom <= bounds.bottom &&
          box.right <= bounds.right &&
          child.scrollHeight <= child.clientHeight &&
          child.scrollWidth <= child.clientWidth
        );
      });
    }),
  ).toBe(true);
});

test("the development demo uses its recording clock and labels it", async ({ page }, testInfo) => {
  const port = 43930 + testInfo.workerIndex;
  const url = `http://127.0.0.1:${port}/`;
  const server = spawn(
    process.execPath,
    [
      "node_modules/vite/bin/vite.js",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
      "--strictPort",
    ],
    { stdio: "pipe" },
  );
  const stopped = new Promise<void>((resolve) => server.once("exit", () => resolve()));
  try {
    await expect
      .poll(async () => {
        try {
          return (await fetch(url)).status;
        } catch {
          return 0;
        }
      })
      .toBe(200);
    await page.clock.setFixedTime(new Date("2030-01-01T00:00:00Z"));
    await page.goto(url);
    await expect(page.locator(".launch-row")).toHaveCount(1);
    await expect(page.getByText(/Recorded demo.*as of/)).toBeVisible();
    await page.goto(`${url}next/`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      demo.launch.name.replace(" | ", ", "),
    );
    await expect(page.getByText(/Recorded demo.*as of/)).toBeVisible();
  } finally {
    server.kill();
    await stopped;
  }
});
