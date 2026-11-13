import { readFile, rm } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { renderCaption } from "../../scripts/record-demo";
import { demo } from "../fixtures/demo";

test("caption pixels stay identical after a frozen viewport resizes", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 810 });
  await page.goto(`/launch/${demo.launch.id}/`);
  await expect(page.locator(".spread")).toHaveAttribute("data-printed", "true");
  const time = new Date(demo.evaluated_at).getTime();
  await page.clock.install({ time });
  await page.clock.pauseAt(time + 1000);
  const first = info.outputPath("caption-first.png");
  const second = info.outputPath("caption-second.png");
  const text = "Fixture night, not a launch: every ensemble member writes the same page";
  try {
    await renderCaption(page, text, first);
    await renderCaption(page, text, second);
    const before = await readFile(first);
    const after = await readFile(second);
    await info.attach("caption-first", { body: before, contentType: "image/png" });
    await info.attach("caption-second", { body: after, contentType: "image/png" });
    expect(before.readUInt32BE(16)).toBe(1280);
    expect(before.readUInt32BE(20)).toBe(96);
    expect(before.byteLength).toBeGreaterThan(1000);
    expect(before).toEqual(after);
  } finally {
    await Promise.all([rm(first, { force: true }), rm(second, { force: true })]);
  }
});
