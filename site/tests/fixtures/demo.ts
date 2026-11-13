import { readFileSync } from "node:fs";
import { isLatest } from "../../src/data";
import { isLaunchAssessment } from "../../src/launch-data";
import type { RuleRisk } from "../../src/types";

const value: unknown = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/demo/assessment.json", import.meta.url), "utf8"),
);
const index: unknown = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/demo/latest.json", import.meta.url), "utf8"),
);
if (!isLaunchAssessment(value) || !isLatest(index)) throw new Error("Invalid demo recording");
export const demo = value;
export const demoIndex = index;
const launch = index.launches.find((row) => row.id === demo.launch.id);
if (!launch) throw new Error("Missing demo summary");
export const demoSummary = launch;

// Expected display values come from recorded evidence, independently of the render helpers.
export function riskiestFirst(rules: RuleRisk[]): RuleRisk[] {
  return [...rules].sort(
    (left, right) =>
      (right.by_model.ecmwf?.risk_fraction ?? -1) - (left.by_model.ecmwf?.risk_fraction ?? -1),
  );
}
// On a night no member breaks anything the plot opens on liftoff wind, which has values to draw.
export function openingOrder(rules: RuleRisk[]): RuleRisk[] {
  const sorted = riskiestFirst(rules);
  const clean = sorted.every((rule) =>
    Object.values(rule.by_model).every((risk) => !risk?.risk_fraction),
  );
  const wind = sorted.find((rule) => rule.rule_id === "liftoff_wind");
  return clean && wind ? [wind, ...sorted.filter((rule) => rule !== wind)] : sorted;
}
export const demoRules = openingOrder(demo.rules);

export function recordedCount(rule: RuleRisk, model: "ecmwf" | "gfs", hour: number) {
  const row = rule.member_violated_by_hour[model]?.[hour] ?? [];
  const valid = row.filter((value) => value !== null);
  return valid.length
    ? `${valid.filter((value) => value === 1).length} of ${valid.length}`
    : "Not evaluable";
}

export function recordedReadout(rule: RuleRisk, model: "ecmwf" | "gfs", hour: number) {
  if (!rule.hours[hour]) throw new Error("Missing recorded hour");
  const count = recordedCount(rule, model, hour);
  return count === "Not evaluable"
    ? `${model.toUpperCase()}: not evaluable.`
    : // The page sets negative figures with a real minus sign.
      `${count} ${model.toUpperCase()} members ${rule.plot.readout_phrase.replace(/(^|[\s(])-(?=\d)/g, "$1\u2212")}.`;
}

export function recordedLocal(timestamp: string, zone: string) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZoneName: "short",
  }).format(new Date(timestamp));
}
