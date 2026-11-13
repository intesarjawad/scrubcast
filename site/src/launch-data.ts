import { hasSupportedSchema, isLatest, isRecord } from "./data.ts";
import type { LaunchAssessment, ModelRisk, RuleRisk } from "./types";

export const models = ["ecmwf", "gfs"] as const;

function fraction(value: unknown): value is number | null {
  return (
    value === null ||
    (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1)
  );
}

function count(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function timestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function modelRisk(value: unknown): value is ModelRisk {
  return (
    isRecord(value) &&
    count(value.members) &&
    count(value.evaluable_members) &&
    value.evaluable_members <= value.members &&
    fraction(value.risk_fraction) &&
    (value.evaluable_members === 0) === (value.risk_fraction === null)
  );
}

function matrix(value: unknown, verdicts: boolean): boolean {
  return (
    value === null ||
    (Array.isArray(value) &&
      value.every(
        (row) =>
          Array.isArray(row) &&
          row.every(
            (cell) =>
              cell === null ||
              (typeof cell === "number" &&
                Number.isFinite(cell) &&
                (!verdicts || cell === 0 || cell === 1)),
          ),
      ))
  );
}

function ruleRisk(value: unknown): value is RuleRisk {
  if (
    !isRecord(value) ||
    !isRecord(value.by_model) ||
    !isRecord(value.plot) ||
    !isRecord(value.risk_by_hour) ||
    !isRecord(value.member_values_by_hour) ||
    !isRecord(value.member_violated_by_hour)
  )
    return false;
  const threshold = value.threshold;
  const plot = value.plot;
  return (
    ["rule_id", "title", "approximation_note", "rule_set_version"].every(
      (key) => typeof value[key] === "string",
    ) &&
    typeof value.source_url === "string" &&
    /^https:\/\//.test(value.source_url) &&
    ["direct", "medium", "low"].includes(String(value.confidence)) &&
    typeof value.reference_only === "boolean" &&
    Array.isArray(value.llccr) &&
    value.llccr.every(count) &&
    Array.isArray(value.hours) &&
    value.hours.every(timestamp) &&
    ["unit", "variable", "readout_phrase"].every((key) => typeof plot[key] === "string") &&
    (value.plot.origin === "source" || value.plot.origin === "scrub") &&
    (threshold === null ||
      (isRecord(threshold) &&
        typeof threshold.value === "number" &&
        Number.isFinite(threshold.value) &&
        typeof threshold.unit === "string" &&
        [">", ">=", "<="].includes(String(threshold.comparator)))) &&
    Object.values(value.by_model).every(modelRisk) &&
    Object.values(value.risk_by_hour).every(
      (series) => Array.isArray(series) && series.every(fraction),
    ) &&
    Object.values(value.member_values_by_hour).every((series) => matrix(series, false)) &&
    Object.values(value.member_violated_by_hour).every((series) => matrix(series, true))
  );
}

/** Validate the published assessment before using it or its inline first paint. */
export function isLaunchAssessment(value: unknown): value is LaunchAssessment {
  if (
    !hasSupportedSchema(value) ||
    !isRecord(value.launch) ||
    !isRecord(value.official) ||
    !isRecord(value.fetched_at) ||
    !isRecord(value.grid_point) ||
    !isRecord(value.context) ||
    !isRecord(value.union_risk_t0)
  )
    return false;
  const grid = value.grid_point;
  return (
    isLatest({
      schema_version: 1,
      generated_at: value.evaluated_at,
      schedule_stale: false,
      members_total: 0,
      launches: [
        {
          ...value.launch,
          tier: value.tier,
          assessment: true,
          page_url: "",
          worst_rule: { label: "" },
        },
      ],
    }) &&
    count(value.t0_index) &&
    typeof value.refresh_deferred === "boolean" &&
    Object.values(value.fetched_at).every((at) => at === null || timestamp(at)) &&
    ["lat", "lon", "elevation_m"].every(
      (key) => typeof grid[key] === "number" && Number.isFinite(grid[key]),
    ) &&
    Object.values(value.context).every(
      (item) => item === null || (typeof item === "number" && Number.isFinite(item)),
    ) &&
    Object.values(value.union_risk_t0).every(fraction) &&
    (value.lowest_union_hour === null ||
      (isRecord(value.lowest_union_hour) &&
        timestamp(value.lowest_union_hour.hour) &&
        count(value.lowest_union_hour.members_below_t0) &&
        fraction(value.lowest_union_hour.union_risk))) &&
    (value.lowest_hour_verified === undefined || typeof value.lowest_hour_verified === "boolean") &&
    (value.audit === undefined || Array.isArray(value.audit)) &&
    (value.official.source === undefined || value.official.source === "Launch Library 2") &&
    (value.official.probability_go_pct === null ||
      (count(value.official.probability_go_pct) && value.official.probability_go_pct <= 100)) &&
    [value.official.concerns, value.official.unmapped_concerns].every(
      (items) => Array.isArray(items) && items.every((item) => typeof item === "string"),
    ) &&
    Array.isArray(value.not_evaluable) &&
    value.not_evaluable.every(
      (item) =>
        isRecord(item) &&
        [item.rule_id, item.title, item.reason].every(
          (field) => typeof field === "string" && field.length > 0,
        ),
    ) &&
    Array.isArray(value.rules) &&
    value.rules.every(ruleRisk)
  );
}

/** Stable ordering preserves the published order when risks tie. */
export function sortedRules(assessment: LaunchAssessment): RuleRisk[] {
  return [...assessment.rules].sort(
    (a, b) => (b.by_model.ecmwf?.risk_fraction ?? -1) - (a.by_model.ecmwf?.risk_fraction ?? -1),
  );
}

export function memberCount(risk: ModelRisk): number {
  return Math.round((risk.risk_fraction ?? 0) * risk.evaluable_members);
}

export function confidenceLabel(rule: RuleRisk): string {
  return rule.confidence === "direct"
    ? "Direct threshold"
    : `${rule.confidence === "low" ? "Low" : "Medium"} confidence proxy`;
}

export function modelAgreement(rule: RuleRisk): string {
  const ecmwf = rule.by_model.ecmwf?.risk_fraction;
  const gfs = rule.by_model.gfs?.risk_fraction;
  if (ecmwf == null || gfs == null) return "Model comparison unavailable";
  return ecmwf > 0 !== gfs > 0
    ? "Models disagree at launch time"
    : ecmwf === 0
      ? "Neither model flags this rule at launch time"
      : "Both models flag this rule at launch time";
}

/** Quote the source wording rather than the normalised rule labels. */
export function officialConcern(assessment: LaunchAssessment): string | null {
  const source = assessment.launch.weather_concerns;
  return source?.trim() ? source : null;
}
