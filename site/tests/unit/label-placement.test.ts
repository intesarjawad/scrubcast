import { describe, expect, it } from "vitest";
import { type LabelBox, placeBandLabels } from "../../src/charts/label-placement";

function overlaps(a: LabelBox, b: LabelBox): boolean {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

describe("direct band labels", () => {
  for (const viewport of [320, 390, 1280]) {
    it(`keeps labels separated and inside both bands at ${viewport}px`, () => {
      const width = viewport - 32 - 44 - 16;
      for (const y of [34, 214]) {
        const band = { x: 44, y, width, height: 140 };
        for (const fraction of [0, 0.01, 0.25, 0.5, 0.99, 1]) {
          for (const thresholdFraction of [0, 0.01, 0.1, 0.5, 0.99, 1]) {
            for (const countWidth of [128, 203]) {
              const labels = placeBandLabels(band, 44 + width * fraction, countWidth, {
                y: y + 140 * thresholdFraction,
                width: 151,
              });
              if (!labels.threshold) throw new Error("Missing threshold label");
              expect(overlaps(labels.count, labels.threshold)).toBe(false);
              for (const label of [labels.count, labels.threshold]) {
                expect(label.x).toBeGreaterThan(band.x);
                expect(label.y).toBeGreaterThan(band.y);
                expect(label.x + label.width).toBeLessThan(band.x + band.width);
                expect(label.y + label.height).toBeLessThan(band.y + band.height);
              }
            }
          }
        }
      }
    });
  }

  it("tracks the cursor until an edge requires clamping, with or without a threshold", () => {
    const band = { x: 44, y: 34, width: 1000, height: 140 };
    const first = placeBandLabels(band, 400, 120, null);
    const next = placeBandLabels(band, 500, 120, null);
    expect(first.threshold).toBeNull();
    expect(next.count.x - first.count.x).toBe(100);
    const labelled = placeBandLabels(band, 500, 120, { y: 120, width: 151 });
    expect(labelled.threshold?.y).toBe(108);
  });
});
