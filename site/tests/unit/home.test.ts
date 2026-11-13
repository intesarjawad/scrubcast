import { describe, expect, it } from "vitest";
import { isLatest } from "../../src/data";
import { launchSchedule, upcomingLaunches } from "../../src/views/home";
import { messageText } from "../../src/views/state";
import { recordedLocal } from "../fixtures/demo";
import {
  CAPE_CHIP,
  HOME_NOW,
  homeFixture,
  RECORDED_HOME_NOW,
  recordedLatest,
} from "../fixtures/home";

const latest = homeFixture();
const cape = latest.launches[0];
if (!cape) throw new Error("Missing Cape launch");

describe("home launch list", () => {
  it("keeps the recorded index separate from synthetic stress content", () => {
    expect(isLatest(recordedLatest)).toBe(true);
    const launches = upcomingLaunches(recordedLatest, RECORDED_HOME_NOW);
    expect(launches).toHaveLength(recordedLatest.launches.length);
    expect(launches.every((launch) => !launch.id.startsWith("mission-"))).toBe(true);
    expect(launches[0]?.name).toBe(recordedLatest.launches[0]?.name);
  });
  it("uses valid twelve- and thirty-launch schedules with all coverage tiers", () => {
    for (const count of [12, 30]) {
      const fixture = homeFixture(count);
      expect(isLatest(fixture)).toBe(true);
      expect(upcomingLaunches(fixture, HOME_NOW)).toHaveLength(count);
      expect(new Set(fixture.launches.map((launch) => launch.tier))).toEqual(
        new Set(["A", "B", "C"]),
      );
    }
    expect(cape.worst_rule.label).toBe(CAPE_CHIP);
  });

  it("sorts by launch time without altering the published rows", () => {
    const reversed = { ...latest, launches: [...latest.launches].reverse() };
    const original = reversed.launches.map((launch) => launch.id);
    const sorted = upcomingLaunches(reversed, HOME_NOW);
    expect(sorted.map((launch) => launch.id)).toEqual(latest.launches.map((launch) => launch.id));
    expect(reversed.launches.map((launch) => launch.id)).toEqual(original);
    expect(sorted[0]?.worst_rule).toBe(cape.worst_rule);
  });

  it("includes both horizon boundaries and excludes passed and distant launches", () => {
    const offsets = [-1, 0, 10 * 24 * 3_600_000, 10 * 24 * 3_600_000 + 1];
    const rows = offsets.map((offset, index) => ({
      ...cape,
      id: `${index}`,
      net: new Date(HOME_NOW.getTime() + offset).toISOString(),
    }));
    expect(upcomingLaunches({ ...latest, launches: rows }, HOME_NOW).map((row) => row.id)).toEqual([
      "1",
      "2",
    ]);
    expect(upcomingLaunches({ ...latest, launches: [] }, HOME_NOW)).toEqual([]);
  });

  it("shows the pad's local date and UTC, including missing timezone metadata", () => {
    const net = new Date(cape.net);
    const date = (timeZone: string) =>
      new Intl.DateTimeFormat("en", {
        timeZone,
        month: "short",
        day: "numeric",
        year: "numeric",
      }).format(net);
    const local = recordedLocal(cape.net, cape.pad.location.timezone_name);
    const utc = `${cape.net.slice(11, 16)} UTC`;
    expect(launchSchedule(cape)).toBe(
      `${date(cape.pad.location.timezone_name)}, ${local} / ${date("UTC")}, ${utc}`,
    );
    expect(
      launchSchedule({
        ...cape,
        pad: { ...cape.pad, location: { ...cape.pad.location, timezone_name: "" } },
      }),
    ).toBe(`${date("UTC")}, ${utc}. Pad-local time not published`);
  });
});

describe("state message interpolation", () => {
  it("substitutes timestamps without leaving unresolved placeholders", () => {
    expect(messageText("Forecast from {forecast_at} UTC.", { forecast_at: "12:00" })).toBe(
      "Forecast from 12:00 UTC.",
    );
    expect(messageText("Last build {built_at}.", {})).toBe("Last build unavailable.");
  });
});
