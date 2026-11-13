import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  confidenceLabel,
  isLaunchAssessment,
  memberCount,
  modelAgreement,
  officialConcern,
  sortedRules,
} from "../../src/launch-data";
import { recordedCount, riskiestFirst } from "../fixtures/demo";

const fixture: unknown = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/demo/assessment.json", import.meta.url), "utf8"),
);
if (!isLaunchAssessment(fixture)) throw new Error("Invalid recorded assessment");
const assessment = fixture;

describe("launch evidence", () => {
  it("keeps the highest ECMWF risk first without mutating the published order", () => {
    const original = assessment.rules.map((rule) => rule.rule_id);
    const rules = sortedRules(assessment);
    expect(rules.map((rule) => rule.rule_id)).toEqual(
      riskiestFirst(assessment.rules).map((rule) => rule.rule_id),
    );
    expect(assessment.rules.map((rule) => rule.rule_id)).toEqual(original);
    const top = rules[0];
    if (!top?.by_model.ecmwf || !top.by_model.gfs) throw new Error("Missing top rule");
    expect(`${memberCount(top.by_model.ecmwf)} of ${top.by_model.ecmwf.evaluable_members}`).toBe(
      recordedCount(top, "ecmwf", assessment.t0_index),
    );
    expect(top.by_model.ecmwf.evaluable_members).toBe(51);
    expect(`${memberCount(top.by_model.gfs)} of ${top.by_model.gfs.evaluable_members}`).toBe(
      recordedCount(top, "gfs", assessment.t0_index),
    );
    expect(top.by_model.gfs.evaluable_members).toBe(31);
    expect(modelAgreement(top)).toBe("Neither model flags this rule at launch time");
    expect(confidenceLabel(top)).toBe("Medium confidence proxy");
  });

  it("preserves unavailable evidence separately from a clear rule", () => {
    const anvil = assessment.rules.find((rule) => rule.rule_id === "anvil");
    expect(anvil?.by_model.gfs?.risk_fraction).toBeNull();
    expect(anvil?.by_model.gfs?.evaluable_members).toBe(0);
    expect(assessment.not_evaluable.every((rule) => rule.reason.length > 0)).toBe(true);
    expect(assessment.official.probability_go_pct).toBe(assessment.launch.probability);
  });

  it("places unavailable ECMWF evidence after clear evidence and keeps tied rows stable", () => {
    const rule = assessment.rules[0];
    if (!rule) throw new Error("Missing rule");
    const rows = [
      {
        ...rule,
        rule_id: "unavailable",
        by_model: { ecmwf: { risk_fraction: null, members: 51, evaluable_members: 0 } },
      },
      { ...rule, rule_id: "clear-first" },
      { ...rule, rule_id: "clear-second" },
      {
        ...rule,
        rule_id: "risk",
        by_model: { ecmwf: { risk_fraction: 0.5, members: 10, evaluable_members: 10 } },
      },
    ];
    expect(sortedRules({ ...assessment, rules: rows }).map((item) => item.rule_id)).toEqual([
      "risk",
      "clear-first",
      "clear-second",
      "unavailable",
    ]);
  });

  it("rejects malformed nested evidence before rendering", () => {
    expect(isLaunchAssessment({ ...assessment, schema_version: 2 })).toBe(false);
    expect(isLaunchAssessment({ ...assessment, not_evaluable: [{ title: "Lightning" }] })).toBe(
      false,
    );
    expect(
      isLaunchAssessment({
        ...assessment,
        official: { ...assessment.official, probability_go_pct: 101 },
      }),
    ).toBe(false);
    const rule = assessment.rules[0];
    if (!rule) throw new Error("Missing rule");
    expect(
      isLaunchAssessment({
        ...assessment,
        rules: [
          { ...rule, by_model: { ecmwf: { members: 51, evaluable_members: 0, risk_fraction: 0 } } },
        ],
      }),
    ).toBe(false);
  });
});

describe("official concern wording", () => {
  it("quotes recognised and unfamiliar source text without normalising labels", () => {
    for (const source of [
      "cumulus",
      "Coastal showers near the flight path",
      "cumulus; launch-area winds",
    ]) {
      expect(
        officialConcern({
          ...assessment,
          launch: { ...assessment.launch, weather_concerns: source },
        }),
      ).toBe(source);
    }
  });

  it("omits a missing source even when normalised concerns contain a fallback", () => {
    for (const source of [null, "", "  "]) {
      expect(
        officialConcern({
          ...assessment,
          launch: { ...assessment.launch, weather_concerns: source },
        }),
      ).toBeNull();
    }
  });

  it("preserves the recorded absence of an official concern", () => {
    expect(assessment.launch.weather_concerns).toBeNull();
    expect(officialConcern(assessment)).toBe(assessment.launch.weather_concerns);
  });
});
