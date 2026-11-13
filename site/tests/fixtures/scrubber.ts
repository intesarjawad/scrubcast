import { readFileSync } from "node:fs";
import { isLaunchAssessment } from "../../src/launch-data";
import type { LaunchAssessment } from "../../src/types";

const recorded: unknown = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/demo/assessment.json", import.meta.url), "utf8"),
);
const wind: unknown = JSON.parse(
  readFileSync(new URL("./wind-rule.json", import.meta.url), "utf8"),
);
if (!isLaunchAssessment(recorded)) throw new Error("Invalid recorded assessment");
const combined: unknown = {
  ...recorded,
  rules: [...recorded.rules.filter((rule) => rule.rule_id !== "liftoff_wind"), wind],
};
if (!isLaunchAssessment(combined)) throw new Error("Invalid wind assessment");
const assessment = combined;

/** Controlled hourly evidence exercises crossings and conjunctions independently. */
export function scrubberFixture(): LaunchAssessment {
  const source = structuredClone(assessment);
  const wind = source.rules.find((rule) => rule.rule_id === "liftoff_wind");
  if (!wind) throw new Error("Missing wind rule");
  const hours = wind.hours;
  source.launch.net = "2026-11-07T01:07:00Z";
  source.launch.window_start = hours[0] ?? source.launch.net;
  source.launch.window_end = hours[2] ?? source.launch.net;
  source.t0_index = 0;
  source.lowest_union_hour = null;
  source.union_risk_t0.ecmwf = 0.2;
  source.rules = source.rules.map((rule) => {
    const copy = structuredClone(rule);
    copy.hours = hours;
    for (const model of ["ecmwf", "gfs"] as const) {
      const members = model === "ecmwf" ? 51 : 31;
      copy.member_values_by_hour[model] = hours.map(() => Array.from({ length: members }, () => 0));
      copy.member_violated_by_hour[model] = hours.map(() =>
        Array.from({ length: members }, () => 0),
      );
      copy.risk_by_hour[model] = hours.map(() => 0);
    }
    if (copy.rule_id === "thick_cloud") {
      const values = copy.member_values_by_hour.ecmwf?.[2];
      const verdicts = copy.member_violated_by_hour.ecmwf?.[2];
      if (!values || !verdicts) throw new Error("Missing cloud hour");
      values[0] = 1500;
      values[1] = 1600;
      verdicts[1] = 1;
      copy.risk_by_hour.ecmwf = [0, 0, 1 / 51, 0, 0];
    }
    if (copy.rule_id === "liftoff_wind") {
      const values = copy.member_values_by_hour.ecmwf?.[2];
      const verdicts = copy.member_violated_by_hour.ecmwf?.[2];
      if (!values || !verdicts) throw new Error("Missing wind hour");
      for (let member = 0; member < 19; member++) {
        values[member] = 14;
        verdicts[member] = 1;
      }
      copy.risk_by_hour.ecmwf = [0, 0, 19 / 51, 0, 0];
    }
    return copy;
  });
  return source;
}

export function twoHourFixture(
  counts: readonly [number, number, number] = [8, 7, 6],
): LaunchAssessment {
  const source = scrubberFixture();
  source.union_risk_t0.ecmwf = counts[0] / 40;
  source.rules = source.rules.map((rule) => {
    const hours = rule.hours.slice(0, 3);
    const violating = rule.rule_id === "liftoff_wind" ? counts : [0, 0, 0];
    return {
      ...rule,
      hours,
      by_model: {
        ecmwf: { members: 40, evaluable_members: 40, risk_fraction: (violating[0] ?? 0) / 40 },
        gfs: { members: 31, evaluable_members: 31, risk_fraction: 0 },
      },
      member_values_by_hour: {
        ecmwf: violating.map((count) =>
          Array.from({ length: 40 }, (_, member) => (member < count ? 14 : 0)),
        ),
        gfs: hours.map(() => Array.from({ length: 31 }, () => 0)),
      },
      member_violated_by_hour: {
        ecmwf: violating.map((count) =>
          Array.from({ length: 40 }, (_, member) => (member < count ? 1 : 0)),
        ),
        gfs: hours.map(() => Array.from({ length: 31 }, () => 0)),
      },
      risk_by_hour: { ecmwf: violating.map((count) => count / 40), gfs: hours.map(() => 0) },
    };
  });
  return source;
}

export function sweepFixture(): LaunchAssessment {
  const source = scrubberFixture();
  const hours = Array.from({ length: 25 }, (_, hour) =>
    new Date(Date.parse(source.launch.window_start) + hour * 3_600_000).toISOString(),
  );
  source.launch.window_end = hours.at(-1) ?? source.launch.window_end;
  for (const rule of source.rules) {
    rule.hours = hours;
    for (const model of ["ecmwf", "gfs"] as const) {
      const values = rule.member_values_by_hour[model] ?? [];
      const verdicts = rule.member_violated_by_hour[model] ?? [];
      const risks = rule.risk_by_hour[model] ?? [];
      rule.member_values_by_hour[model] = hours.map(
        (_, hour) => values[hour % values.length] ?? [],
      );
      rule.member_violated_by_hour[model] = hours.map(
        (_, hour) => verdicts[hour % verdicts.length] ?? [],
      );
      rule.risk_by_hour[model] = hours.map((_, hour) => risks[hour % risks.length] ?? null);
    }
  }
  return source;
}
