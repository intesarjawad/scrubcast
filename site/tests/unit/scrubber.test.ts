import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { hourEvidence, memberScale, scrubberHours } from "../../src/charts/scrubber-data";
import { isLaunchAssessment } from "../../src/launch-data";
import type { RuleRisk } from "../../src/types";
import { recordedCount, recordedLocal, recordedReadout } from "../fixtures/demo";

const data: unknown = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/demo/assessment.json", import.meta.url), "utf8"),
);
if (!isLaunchAssessment(data)) throw new Error("Invalid recorded assessment");
const rule = data.rules.find((rule) => rule.rule_id === "flight_through_precip");
if (!rule) throw new Error("Missing precipitation rule");
const precipitation = rule;

describe("hourly scrubber evidence", () => {
  it("matches the recorded precipitation counts and zone names", () => {
    const hours = scrubberHours(precipitation, "America/New_York");
    expect(hours.map((hour) => hour.byModel.ecmwf.count)).toEqual(
      precipitation.hours.map((_, index) => recordedCount(precipitation, "ecmwf", index)),
    );
    for (const [index, hour] of hours.entries()) {
      expect(hour.local).toBe(recordedLocal(hour.hour, "America/New_York"));
      for (const model of ["ecmwf", "gfs"] as const) {
        expect(hour.byModel[model].readout).toBe(recordedReadout(precipitation, model, index));
      }
    }
  });

  it("counts verdicts, including a clear member above the plotted threshold", () => {
    const multiCondition: RuleRisk = {
      ...precipitation,
      member_values_by_hour: { ecmwf: [[10, 10, null]] },
      member_violated_by_hour: { ecmwf: [[1, 0, null]] },
    };
    expect(hourEvidence(multiCondition, "ecmwf", 0)).toEqual({
      evaluable: 2,
      violated: 1,
      count: "1 of 2",
      risk: "50%",
    });
  });

  it("keeps unavailable evidence distinct from zero risk", () => {
    const missing = {
      ...precipitation,
      member_violated_by_hour: { ecmwf: [[null, null]], gfs: null },
    };
    expect(hourEvidence(missing, "ecmwf", 0).count).toBe("Not evaluable");
    expect(scrubberHours(missing, "UTC")[0]?.byModel.gfs.readout).toBe("GFS: not evaluable.");
  });
});

describe("member scale", () => {
  it("leaves headroom above every recorded member and the threshold", () => {
    const scale = memberScale(precipitation);
    const values = Object.values(precipitation.member_values_by_hour)
      .flatMap((matrix) => matrix?.flat() ?? [])
      .filter((value) => value !== null);
    expect(scale.max).toBeCloseTo(Math.max(precipitation.threshold?.value ?? 0, ...values) * 1.1);
    for (const matrix of Object.values(precipitation.member_values_by_hour)) {
      for (const value of matrix?.flat() ?? []) {
        if (value !== null) expect(scale.fraction(value)).toBeLessThan(1);
      }
    }
    expect(scale.fraction(0.254)).toBeGreaterThan(0);
    expect(scale.fraction(0.254)).toBeLessThan(1);
  });

  it("preserves distinct large values from either ensemble without clamping", () => {
    const scale = memberScale({
      ...precipitation,
      member_values_by_hour: { ecmwf: [[1, 5, 2]], gfs: [[null, 9, 3]] },
    });
    expect(scale.max).toBeCloseTo(9.9);
    expect(scale.fraction(1)).toBeLessThan(scale.fraction(5));
    expect(scale.fraction(5)).toBeLessThan(scale.fraction(9));
    expect(scale.fraction(9)).toBeLessThan(1);
    expect(scale.fraction(5) - scale.fraction(1)).toBeCloseTo(4 / 9.9);
  });

  it("includes a threshold above all members and handles unavailable and zero data", () => {
    for (const matrix of [null, [[null]], [[0]]]) {
      const scale = memberScale({ ...precipitation, member_values_by_hour: { ecmwf: matrix } });
      expect(scale.max).toBeGreaterThan(0.254);
      expect(Number.isFinite(scale.fraction(0))).toBe(true);
      expect(scale.fraction(0.254)).toBeLessThan(1);
    }
    const scale = memberScale({ ...precipitation, threshold: null, member_values_by_hour: {} });
    expect(scale.max).toBeGreaterThan(0);
  });

  it("preserves negative values and a zero threshold within the domain", () => {
    const scale = memberScale({
      ...precipitation,
      threshold: { value: 0, comparator: "<=", unit: "°C" },
      member_values_by_hour: { ecmwf: [[-10, -5, 2]] },
    });
    expect(scale.fraction(-10)).toBeGreaterThan(0);
    expect(scale.fraction(-5)).toBeLessThan(scale.fraction(2));
    expect(scale.fraction(0)).toBeGreaterThan(0);
    expect(scale.fraction(2)).toBeLessThan(1);
  });
});
