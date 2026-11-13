import { readdirSync, readFileSync, statSync } from "node:fs";
import { describe, expect, it } from "vitest";

const stylesheet = readFileSync(new URL("../../src/styles.css", import.meta.url), "utf8");
const scrubberStyles = readFileSync(
  new URL("../../src/charts/scrubber.css", import.meta.url),
  "utf8",
);
const cardStyles = readFileSync(new URL("../../src/views/card.css", import.meta.url), "utf8");
const homeStyles = readFileSync(new URL("../../src/views/home.css", import.meta.url), "utf8");
const sheetStyles = readFileSync(new URL("../../src/charts/sheet.css", import.meta.url), "utf8");
const direction = readFileSync(new URL("../../../docs/design/README.md", import.meta.url), "utf8");
const tokenBlocks = [...stylesheet.matchAll(/:root\s*\{([^}]+)\}/g)].map((match) => match[1] ?? "");
function tokens(block: string): Map<string, string> {
  return new Map(
    [...block.matchAll(/(--[\w-]+)\s*:\s*([^;\n}]+)/g)].map((match) => [
      match[1] ?? "",
      match[2]?.trim() ?? "",
    ]),
  );
}
function token(set: Map<string, string>, name: string): string {
  const value = set.get(name);
  if (value === undefined) throw new Error(`Missing token: ${name}`);
  return value;
}
function luminance(hex: string): number {
  if (!/^#[\da-f]{6}$/i.test(hex)) throw new Error(`Expected an opaque sRGB colour: ${hex}`);
  const channels = [1, 3, 5].map((offset) => {
    const srgb = Number.parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
  });
  const [red = 0, green = 0, blue = 0] = channels;
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}
function contrast(foreground: string, background: string): number {
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
const pairs: Record<string, readonly [string, string]> = {
  "Body text on ground": ["--ink", "--bg"],
  "Secondary text on ground": ["--muted", "--bg"],
  "Secondary text on panel": ["--muted", "--surface"],
  "Accent text on ground": ["--accent", "--bg"],
  "Alarm ink on ground": ["--alarm", "--bg"],
  "Member traces on ground": ["--graphic", "--bg"],
  "Threshold on ground": ["--rule", "--bg"],
};
const rows = [...direction.matchAll(/^\| ([^|]+) \| ([\d.]+):1 \| ([\d.]+):1 \| ([\d.]+):1 \|$/gm)];

describe("the published contrast table", () => {
  it("covers every listed pair in light and dark with a forced-colours override", () => {
    expect(rows.map((row) => row[1])).toEqual(Object.keys(pairs));
    expect(tokenBlocks).toHaveLength(3);
    expect(stylesheet).toMatch(/@media\s*\(prefers-color-scheme:\s*dark\)/);
    expect(stylesheet).toMatch(/@media\s*\(forced-colors:\s*active\)/);
    const forced = tokens(tokenBlocks[2] ?? "");
    for (const name of new Set(Object.values(pairs).flat())) {
      expect(token(forced, name)).toMatch(/^(Canvas|CanvasText|LinkText|Highlight)$/);
    }
    expect(token(forced, "--focus")).toBe("Highlight");
  });

  for (const row of rows) {
    const name = row[1] ?? "";
    const pair = pairs[name];
    if (pair === undefined) throw new Error(`Unmapped contrast pair: ${name}`);
    for (const [index, theme] of ["light", "dark"].entries()) {
      it(`${name}, ${theme}: meets the requirement and stays within 0.02 of the table`, () => {
        const set = tokens(tokenBlocks[index] ?? "");
        const actual = contrast(token(set, pair[0]), token(set, pair[1]));
        expect(actual).toBeGreaterThanOrEqual(Number(row[4]));
        expect(Math.abs(actual - Number(row[index + 2]))).toBeLessThanOrEqual(0.02);
      });
    }
  }
});

describe("token and asset budgets", () => {
  it("keeps raw sizes, spacing and colours inside the token block", () => {
    const rules = (stylesheet + scrubberStyles + cardStyles + homeStyles + sheetStyles).replace(
      /:root\s*\{[^}]+\}/g,
      "",
    );
    expect(rules).not.toMatch(/--[\w-]+\s*:/);
    expect(rules).not.toMatch(
      /#[\da-f]{3,8}\b|\b(?:rgb|hsl|oklch)\(|(?:\d*\.)?\d+(?:px|rem|em|ch|vw|vh|svh|%)\b/i,
    );
    for (const declaration of rules.matchAll(
      /(font-size|line-height|letter-spacing|(?:row-|column-)?gap|margin(?:-[\w-]+)?|padding(?:-[\w-]+)?)\s*:\s*([^;]+);/g,
    )) {
      const property = declaration[1];
      const scale =
        property === "font-size"
          ? /^var\(--text-[\w-]+\)$/
          : property === "line-height"
            ? /^var\(--leading-[\w-]+\)$/
            : property === "letter-spacing"
              ? /^var\(--tracking-[\w-]+\)$/
              : /^(?:var\(--s\d+\)|auto)$/;
      for (const value of (declaration[2] ?? "").split(/\s+/)) {
        expect(value).toMatch(scale);
        if (value !== "auto") {
          expect(tokens(tokenBlocks[0] ?? "").has(value.slice(4, -1))).toBe(true);
        }
      }
    }
  });

  it("preserves the approved type and spacing scales", () => {
    const set = tokens(tokenBlocks[0] ?? "");
    const sizes = [
      "xs",
      "sm",
      "base",
      "md",
      "lg",
      "xl",
      "title",
      "share",
      "display",
      "official",
    ].map((name) => token(set, `--text-${name}`));
    expect(sizes).toEqual([11, 13, 15, 17, 21, 28, 42, 48, 68, 88].map((size) => `${size}px`));
    expect([1, 2, 3, 4, 5, 6, 7, 8, 11].map((step) => token(set, `--s${step}`))).toEqual(
      [4, 8, 12, 16, 20, 24, 32, 40, 80].map((size) => `${size}px`),
    );
  });

  it("ships the licensed fonts within 160 KB and CSS within 12 KB", () => {
    const fonts = new URL("../../public/fonts/", import.meta.url);
    const fontNames = readdirSync(fonts)
      .filter((name) => name.endsWith(".woff2"))
      .sort();
    expect(fontNames).toEqual([
      "eb-garamond-italic-latin.woff2",
      "eb-garamond-latin.woff2",
      "public-sans-latin.woff2",
    ]);
    const bytes = fontNames.reduce((sum, name) => sum + statSync(new URL(name, fonts)).size, 0);
    expect(bytes).toBeLessThanOrEqual(160_000);
    expect(Buffer.byteLength(stylesheet)).toBeLessThanOrEqual(12_000);
    for (const name of ["eb-garamond-OFL.txt", "public-sans-OFL.txt"]) {
      expect(readFileSync(new URL(name, fonts), "utf8")).toContain("SIL OPEN FONT LICENSE");
    }
  });
});
