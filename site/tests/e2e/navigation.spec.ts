import { expect, test } from "@playwright/test";
import { demo } from "../fixtures/demo";

test("a launch opens after a forced-colour context closes", async ({ browser, baseURL }) => {
  if (!baseURL) throw new Error("Missing browser server URL");
  for (let visit = 0; visit < 2; visit++) {
    const context = await browser.newContext({ baseURL });
    try {
      const page = await context.newPage();
      await page.clock.setFixedTime(new Date(demo.evaluated_at));
      await page.goto(`/launch/${demo.launch.id}/`);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        demo.launch.name.replace(" | ", ", "),
      );
      await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
      await page.setViewportSize({ width: 390, height: 844 });
      await expect(page.locator(".fan")).toHaveCSS("opacity", "1");
      await expect(page.locator(".unseen")).toHaveCSS("opacity", "1");
    } finally {
      await context.close();
    }
  }
});
