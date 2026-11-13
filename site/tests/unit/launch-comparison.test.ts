import { describe, expect, it } from "vitest";
import { launchComparison, ruleNote } from "../../src/launch-comparison";
import { scrubberFixture } from "../fixtures/scrubber";

const assessment = scrubberFixture();
const cumulus = assessment.rules.find((rule) => rule.rule_id === "cumulus");
const precipitation = assessment.rules.find((rule) => rule.rule_id === "flight_through_precip");
if (!cumulus || !precipitation) throw new Error("Missing comparison rules");
const modelled = {
  ...assessment,
  rules: [
    cumulus,
    {
      ...precipitation,
      by_model: {
        ecmwf: { members: 51, evaluable_members: 51, risk_fraction: 14 / 51 },
        gfs: { members: 31, evaluable_members: 31, risk_fraction: 0 },
      },
    },
  ],
};

describe("official and modelled comparison", () => {
  it("quotes the source and pairs a named concern with the leading modelled finding", () => {
    const fixture = {
      ...modelled,
      launch: { ...modelled.launch, weather_concerns: "cumulus cloud" },
    };
    expect(launchComparison(fixture)).toBe(
      "Official concern: cumulus cloud. Cumulus at T-0: 0 of 51 ECMWF members, 0 of 31 GFS members. Rain in flight at T-0: 14 of 51 ECMWF members, 0 of 31 GFS members.",
    );
  });

  it("omits official concerns without source text, even with stale normalised labels", () => {
    const fixture = {
      ...modelled,
      launch: { ...modelled.launch, weather_concerns: null },
    };
    expect(launchComparison(fixture)).toBe(
      "Rain in flight at T-0: 14 of 51 ECMWF members, 0 of 31 GFS members.",
    );
  });

  it("does not invent missing rules or turn unavailable members into clear evidence", () => {
    const fixture = {
      ...modelled,
      launch: { ...modelled.launch, weather_concerns: "Lightning; coastal showers" },
      rules: [
        {
          ...cumulus,
          by_model: { ecmwf: { members: 51, evaluable_members: 0, risk_fraction: null } },
        },
      ],
    };
    expect(launchComparison(fixture)).toBe(
      "Official concern: Lightning; coastal showers. Cumulus at T-0: ECMWF not evaluable, GFS not evaluable.",
    );
  });
});

describe("rule applicability notes", () => {
  it("presents the shared precipitation proxy without a vehicle-specific concern claim", () => {
    expect(assessment.launch.rocket_name).toMatch(/^Falcon 9/);
    expect(ruleNote(precipitation)).toBe(
      "No vehicle-specific threshold is inferred; this proxy uses the LLCC precipitation detection definition.",
    );
    expect(ruleNote({ ...precipitation, approximation_note: "A neutral source note." })).toBe(
      "A neutral source note.",
    );
  });

  it("preserves the explicit applicability of a vehicle-specific wind limit", () => {
    const wind = assessment.rules.find((rule) => rule.rule_id === "liftoff_wind");
    if (!wind) throw new Error("Missing wind rule");
    expect(ruleNote(wind)).toBe(wind.approximation_note);
    expect(ruleNote(wind)).toContain("published for crewed Falcon 9");
  });
});
