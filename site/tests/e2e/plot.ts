import { expect, type Page } from "@playwright/test";

// The scrubber draws at a provisional width and replaces its SVG once the container is measured,
// so reads taken before that replacement can land on detached nodes.
export async function plotSettled(page: Page) {
  await expect
    .poll(() =>
      page
        .locator(".plot")
        .evaluate(
          (svg: SVGSVGElement) =>
            svg.viewBox.baseVal.width ===
            Math.round(svg.parentElement?.getBoundingClientRect().width ?? Number.NaN),
        ),
    )
    .toBe(true);
}
