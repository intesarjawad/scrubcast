import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import { buildSheet } from "../../src/charts/sheet-data";
import { isLaunchAssessment } from "../../src/launch-data";
import type { LaunchAssessment } from "../../src/types";
import { demo } from "../fixtures/demo";

function recorded(name: string): LaunchAssessment {
  const value: unknown = JSON.parse(
    readFileSync(
      new URL(`../../../tests/fixtures/launch_windows/${name}.json`, import.meta.url),
      "utf8",
    ),
  );
  if (!isLaunchAssessment(value)) throw new Error(`Invalid window: ${name}`);
  return { ...value, launch: { ...value.launch, id: demo.launch.id } };
}

async function show(page: Page, assessment: LaunchAssessment, card = false): Promise<void> {
  await page.route("**/data/latest.json", (route) =>
    route.fulfill({
      json: {
        schema_version: 1,
        generated_at: assessment.evaluated_at,
        schedule_stale: false,
        members_total: 82,
        launches: [
          {
            ...assessment.launch,
            tier: assessment.tier,
            assessment: true,
            page_url: `/launch/${assessment.launch.id}/`,
            worst_rule: { label: "Forecast" },
          },
        ],
      },
    }),
  );
  await page.route(`**/data/launches/${demo.launch.id}.json`, (route) =>
    route.fulfill({ json: assessment }),
  );
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`/launch/${demo.launch.id}/${card ? "?card" : ""}`);
  await expect(page.locator("h1")).toHaveText(assessment.launch.name.replace(" | ", ", "));
  await expect(page.locator(".spread")).toHaveAttribute("data-printed", "true");
  await expect(page.locator(".sheet-facts")).toContainText("Fetched Nov 12, 2026");
}

for (const name of ["daytime", "reference", "precipitation"]) {
  test(`${name} window fits the share frame with all printed values`, async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 630 });
    const assessment = recorded(name);
    await show(page, assessment, true);
    await expect(page.locator("#app")).toHaveAttribute("data-card-ready", demo.launch.id);
    expect(
      await page.locator("#app").evaluate((app) => {
        const bounds = app.getBoundingClientRect();
        return [
          ...app.querySelectorAll<HTMLElement>(
            ".spread, .sheet-page, .fan, .sheet-facts, .card-verdict",
          ),
        ].every((child) => {
          const box = child.getBoundingClientRect();
          return (
            box.bottom <= bounds.bottom &&
            box.right <= bounds.right &&
            (child.className !== "spread" ||
              (child.scrollHeight <= child.clientHeight && child.scrollWidth <= child.clientWidth))
          );
        });
      }),
    ).toBe(true);
    for (const [index, slot] of buildSheet(assessment).slots.entries())
      await expect(page.locator(`.slot[data-slot="${index}"] .slot-text`)).toHaveText(slot.typical);
  });
}

for (const width of [1440, 390]) {
  test(`crowded precipitation wraps inside ${width}px with a readable 2D fallback`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const assessment = recorded("precipitation");
    await show(page, assessment);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(
      await page.locator(".sheet-canvas").evaluate((canvas: HTMLCanvasElement) => {
        const pen = canvas.getContext("2d");
        if (!pen) return false;
        const pixels = pen.getImageData(0, 0, canvas.width, canvas.height).data;
        let ink = 0;
        for (let offset = 0; offset < pixels.length; offset += 4)
          if ((pixels[offset] ?? 255) < 100 && (pixels[offset + 3] ?? 0) > 0) ink++;
        return ink > 100;
      }),
    ).toBe(true);
    for (const [index, slot] of buildSheet(assessment).slots.entries())
      await expect(page.locator(`.slot[data-slot="${index}"] .slot-text`)).toHaveText(slot.typical);
    const figures = page.locator("button.figure");
    await figures.last().click();
    await expect(page.locator(".fan-caption")).toContainText("all 82 members");
  });
}

for (const width of [1440, 390]) {
  test(`long mission tokens reflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const assessment = recorded("daytime");
    assessment.launch.name = `Vulcan | ${"Intercontinental".repeat(15)}`;
    await show(page, assessment);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await expect(page.locator(".sheet-page")).toContainText(
      assessment.launch.name.split(" | ")[1] ?? "",
    );
  });
}

test("a failed float target uses a fresh 2D canvas", async ({ page }) => {
  await page.addInitScript(() => {
    const getExtension = WebGL2RenderingContext.prototype.getExtension;
    WebGL2RenderingContext.prototype.getExtension = new Proxy(getExtension, {
      apply(target, context, args) {
        return args[0] === "EXT_color_buffer_float" ? null : Reflect.apply(target, context, args);
      },
    });
  });
  await show(page, recorded("daytime"));
  expect(
    await page
      .locator(".sheet-canvas")
      .evaluate((canvas: HTMLCanvasElement) => canvas.getContext("2d") !== null),
  ).toBe(true);
});

test("DOM words remain visible when neither canvas renderer can draw", async ({ page }) => {
  await page.addInitScript(() => {
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = new Proxy(getContext, {
      apply(target, canvas: HTMLCanvasElement, args) {
        return canvas.classList.contains("sheet-canvas")
          ? null
          : Reflect.apply(target, canvas, args);
      },
    });
  });
  const assessment = recorded("daytime");
  await page.route(`**/data/launches/${demo.launch.id}.json`, (route) =>
    route.fulfill({ json: assessment }),
  );
  await page.goto(`/launch/${demo.launch.id}/`);
  await expect(page.locator("h1")).toHaveText(assessment.launch.name.replace(" | ", ", "));
  await expect(page.locator(".spread")).toHaveAttribute("data-printed", "false");
  expect(
    await page.locator(".sheet-page").evaluate((node) => getComputedStyle(node).color),
  ).not.toBe("rgba(0, 0, 0, 0)");
});

test("software graphics print the finished 2D sheet", async ({ page }) => {
  await page.addInitScript(() => {
    const parameter = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = new Proxy(parameter, {
      apply(target, context, args) {
        return args[0] === 0x9246 || args[0] === 0x1f01
          ? "ANGLE SwiftShader"
          : Reflect.apply(target, context, args);
      },
    });
  });
  await show(page, recorded("daytime"));
  expect(
    await page
      .locator(".sheet-canvas")
      .evaluate((canvas: HTMLCanvasElement) => canvas.getContext("2d") !== null),
  ).toBe(true);
  const pages = page.getByLabel("Pages on the sheet");
  expect(await pages.inputValue()).toBe(await pages.getAttribute("max"));
});

test("a slow hardware press switches to the finished 2D sheet", async ({ page }) => {
  await page.addInitScript(() => {
    const parameter = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = new Proxy(parameter, {
      apply(target, context, args) {
        return args[0] === 0x9246 || args[0] === 0x1f01
          ? "Hardware graphics"
          : Reflect.apply(target, context, args);
      },
    });
    const request = window.requestAnimationFrame;
    let time = 0;
    window.requestAnimationFrame = (callback) =>
      request(() => {
        time += 100;
        callback(time);
      });
  });
  const assessment = recorded("daytime");
  await page.route(`**/data/launches/${demo.launch.id}.json`, (route) =>
    route.fulfill({ json: assessment }),
  );
  await page.goto(`/launch/${demo.launch.id}/`);
  await expect(page.locator(".sheet-facts")).toContainText("Fetched Nov 12, 2026");
  await expect(page.locator(".spread")).toHaveAttribute("data-phase", "set");
  expect(
    await page
      .locator(".sheet-canvas")
      .evaluate((canvas: HTMLCanvasElement) => canvas.getContext("2d") !== null),
  ).toBe(true);
});

test("printed ink and notes follow color scheme changes", async ({ page }) => {
  await show(page, recorded("precipitation"));
  const pages = page.getByLabel("Pages on the sheet");
  const selected = String(Math.round(Number(await pages.getAttribute("max")) / 2));
  await pages.fill(selected);
  const paper = () =>
    page.locator(".sheet-canvas").evaluate((canvas: HTMLCanvasElement) => {
      const pen = canvas.getContext("2d");
      if (!pen) throw new Error("Missing 2D canvas");
      return pen.getImageData(0, 0, 1, 1).data[0];
    });
  expect(await paper()).toBe(232);
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await expect.poll(paper).toBe(25);
  await expect(pages).toHaveValue(selected);
  await expect(page.locator(".sheet-notes")).toHaveCSS("color", "rgb(236, 232, 223)");
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  await expect.poll(paper).toBe(232);
  await expect(pages).toHaveValue(selected);
});

test("canvas dimensions follow a height-only reflow", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await show(page, recorded("daytime"));
  const pages = page.getByLabel("Pages on the sheet");
  const selected = String(Math.round(Number(await pages.getAttribute("max")) / 2));
  await pages.fill(selected);
  await page.locator(".sheet-legend").evaluate((node) => {
    node.textContent = `${node.textContent} ${"A longer explanatory sentence. ".repeat(30)}`;
  });
  await expect
    .poll(() =>
      page.locator(".spread").evaluate((spread) => {
        const canvas = spread.querySelector<HTMLCanvasElement>(".sheet-canvas");
        const dpr = Math.min(2, devicePixelRatio || 1);
        return canvas?.height === Math.ceil(spread.getBoundingClientRect().height * dpr);
      }),
    )
    .toBe(true);
  await expect(pages).toHaveValue(selected);
});
