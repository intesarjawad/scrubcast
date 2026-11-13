import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { isRecord } from "../../src/data";

const root = new URL("../../../rules/", import.meta.url);
const contracts = readdirSync(root, { recursive: true }).flatMap((path) => {
  if (typeof path !== "string" || !path.endsWith(".json")) return [];
  const value: unknown = JSON.parse(readFileSync(new URL(path, root), "utf8"));
  if (!isRecord(value)) throw new Error(`Invalid rule file: ${path}`);
  if (Array.isArray(value.rules)) return value.rules.map((rule: unknown) => ({ path, rule }));
  return typeof value.rule_id === "string" ? [{ path, rule: value }] : [];
});

describe("published plot contracts", () => {
  it("finds source rules and vehicle wind limits", () => {
    expect(contracts.some(({ path }) => path.startsWith("llcc/"))).toBe(true);
    expect(contracts.some(({ path }) => path.startsWith("vehicles/"))).toBe(true);
  });

  for (const { path, rule } of contracts) {
    it(`${path}: ${isRecord(rule) ? String(rule.rule_id) : "invalid rule"} has a complete plot block`, () => {
      if (!isRecord(rule) || !isRecord(rule.plot)) throw new Error("Missing plot contract");
      const plot = rule.plot;
      for (const key of [
        "variable",
        "unit",
        "threshold_param",
        "comparator_param",
        "readout_phrase",
      ]) {
        expect(typeof plot[key]).toBe("string");
        expect(String(plot[key]).trim().length).toBeGreaterThan(0);
      }
      const parameters = isRecord(rule.proxy) ? rule.proxy : rule;
      expect(typeof parameters[String(plot.threshold_param)]).toBe("number");
      expect([">", ">=", "<="]).toContain(parameters[String(plot.comparator_param)]);
      const phrase = String(plot.readout_phrase);
      expect(phrase).toContain(`{${String(plot.threshold_param)}}`);
      expect(phrase.replaceAll(/\{\w+\}/g, "")).not.toMatch(/\d/);
      for (const match of phrase.matchAll(/\{(\w+)\}/g)) {
        expect(parameters[match[1] ?? ""]).toBeDefined();
      }
    });
  }
});
