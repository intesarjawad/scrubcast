import { readFileSync } from "node:fs";
import { isLaunchAssessment } from "../../src/launch-data";
import type { Latest, LaunchSummary } from "../../src/types";
import { demoIndex, demoSummary } from "./demo";

const recorded: unknown = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/demo/assessment.json", import.meta.url), "utf8"),
);
if (!isLaunchAssessment(recorded)) throw new Error("Invalid recorded assessment");
export const capeAssessment = recorded;
export const HOME_NOW = new Date(Date.parse(recorded.launch.net) - 7 * 3_600_000);
export const CAPE_CHIP = demoSummary.worst_rule.label;

const cape: LaunchSummary = {
  ...capeAssessment.launch,
  assessment: true,
  tier: capeAssessment.tier,
  page_url: `/launch/${capeAssessment.launch.id}/`,
  worst_rule: demoSummary.worst_rule,
};

/**
 * Synthetic schedule rows exercise coverage labels and long mission names.
 * Pass `now` to move the whole schedule so it stays upcoming on a real clock.
 */
export function homeFixture(count = 12, now = HOME_NOW): Latest {
  const latest = scheduleFixture(count);
  const shift = now.getTime() - HOME_NOW.getTime();
  if (!shift) return latest;
  const moved = (time: string) => new Date(Date.parse(time) + shift).toISOString();
  for (const launch of latest.launches) {
    launch.net = moved(launch.net);
    if (launch.window_start) launch.window_start = moved(launch.window_start);
    if (launch.window_end) launch.window_end = moved(launch.window_end);
  }
  latest.generated_at = moved(latest.generated_at);
  return latest;
}

function scheduleFixture(count: number): Latest {
  const launches = Array.from({ length: count }, (_, index): LaunchSummary => {
    if (index === 0) return structuredClone(cape);
    const net = new Date(HOME_NOW.getTime() + (index + 1) * 6 * 3_600_000).toISOString();
    const tier = index % 3 === 0 ? "A" : index % 3 === 1 ? "B" : "C";
    return {
      ...structuredClone(cape),
      id: `mission-${index}`,
      slug: `mission-${index}`,
      name: `Mission ${index} | ${index === 11 ? "Communications and Earth observation rideshare with extended payload description" : "Orbital flight"}`,
      net,
      window_start: net,
      window_end: net,
      probability: null,
      tier,
      assessment: tier !== "C",
      pad: {
        ...cape.pad,
        name: index % 2 ? "Launch Complex 1" : "Space Launch Complex 4 East",
        location: {
          ...cape.pad.location,
          name: index % 2 ? "Mahia Peninsula, New Zealand" : "Vandenberg SFB, CA, USA",
          timezone_name: index % 2 ? "Pacific/Auckland" : "America/Los_Angeles",
        },
      },
      page_url: `/launch/mission-${index}/`,
      worst_rule:
        tier === "C"
          ? { label: "No published rules" }
          : tier === "B"
            ? { label: "Cumulus 22% (LLCC reference)", risk_fraction: 0.22 }
            : { label: "No rule above 5%" },
    };
  });
  return {
    schema_version: 1,
    generated_at: HOME_NOW.toISOString(),
    schedule_stale: false,
    members_total: 82,
    launches,
  };
}

export const recordedLatest = demoIndex;
export const RECORDED_HOME_NOW = new Date(recordedLatest.generated_at);
