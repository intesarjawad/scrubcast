import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { checkCardPng } from "../../scripts/card-files";
import { isLaunchAssessment } from "../../src/launch-data";
import { CARD_LIMIT_BYTES, cardLaunches, cardSchedule } from "../../src/share-card";
import type { Latest, LaunchSummary } from "../../src/types";

const value: unknown = JSON.parse(
  await readFile(new URL("../../../tests/fixtures/demo/assessment.json", import.meta.url), "utf8"),
);
if (!isLaunchAssessment(value)) throw new Error("Invalid recorded assessment");
const summary: LaunchSummary = {
  ...value.launch,
  tier: value.tier,
  assessment: true,
  page_url: `/launch/${value.launch.id}/`,
  worst_rule: { label: "Flight Through Precipitation" },
};
const fixture = new URL("../fixtures/card.png", import.meta.url);
const temporary = await mkdtemp(join(tmpdir(), "scrubcast-cards-"));
afterAll(async () => rm(temporary, { recursive: true, force: true }));

describe("card schedule", () => {
  const launch: LaunchSummary = {
    ...summary,
    id: "9e27a1ed-e81a-4918-b32b-0380cf3a9f8f",
    name: "Mir | Demo Flight",
    tier: "C",
    assessment: false,
    net: "2026-11-10T06:00:00Z",
    net_precision: "HR",
    window_start: "2026-11-10T06:00:00Z",
    window_end: "2026-11-10T09:00:00Z",
    probability: null,
    pad: {
      id: 216,
      name: "ADD Offshore launch platform",
      latitude: 33.216667,
      longitude: 126.366667,
      location: { id: 3, name: "Sea Launch", timezone_name: "" },
    },
  };

  it("formats an unassessed hour-precision launch without a published pad timezone", () => {
    expect(cardSchedule(launch)).toEqual({
      date: "Nov 10, 2026",
      localTime: null,
      utcDate: "Nov 10, 2026",
      utcTime: "06:00 UTC",
    });
  });

  it.each([
    ["America/New_York", "Nov 10, 2026", "01:00 EST"],
    ["Asia/Shanghai", "Nov 10, 2026", "14:00 GMT+8"],
    ["America/Los_Angeles", "Nov 9, 2026", "22:00 PST"],
  ])("keeps the pad date and zone for %s", (zone, date, localTime) => {
    expect(
      cardSchedule({
        ...launch,
        pad: { ...launch.pad, location: { ...launch.pad.location, timezone_name: zone } },
      }),
    ).toEqual({ date, localTime, utcDate: "Nov 10, 2026", utcTime: "06:00 UTC" });
  });
});

describe("share card selection", () => {
  it("keeps scheduled launches and uses generated_at for seven days of retained launches", () => {
    const latest: Latest = {
      schema_version: 1,
      generated_at: "2026-11-05T12:00:00Z",
      schedule_stale: false,
      members_total: 82,
      launches: [
        { ...summary, id: "future", net: "2026-11-12T12:00:00Z" },
        { ...summary, id: "recent", net: "2026-11-04T12:00:00Z" },
        { ...summary, id: "stale", net: "2026-10-20T12:00:00Z" },
      ],
    };
    const past = {
      generated_at: "2026-11-04T12:00:00Z",
      launches: [
        { ...summary, id: "recent", net: "2026-11-04T12:00:00Z" },
        { ...summary, id: "boundary", assessment: false, net: "2026-10-29T12:00:00Z" },
        { ...summary, id: "old", net: "2026-10-29T11:59:59Z" },
        { ...summary, id: "future-retained", net: "2026-11-06T12:00:00Z" },
      ],
    };
    expect(cardLaunches(latest, past).map((launch) => launch.id)).toEqual([
      "future",
      "recent",
      "stale",
      "boundary",
    ]);
    expect(cardLaunches(latest, past)[1]).toBe(latest.launches[1]);
    expect(cardLaunches({ ...latest, launches: [] }, { ...past, launches: [] })).toEqual([]);
  });
});

describe("saved PNG budget", () => {
  it("reports a missing PNG as a named CLI failure without a stack trace", () => {
    const path = join(temporary, "missing-card.png");
    const result = spawnSync(
      process.execPath,
      [new URL("../../scripts/cards.ts", import.meta.url).pathname, "--check", path],
      { encoding: "utf8" },
    );
    expect(result.status).toBe(1);
    expect(result.stderr.trim()).toBe(`${path}: card failed: Missing PNG`);
  });

  it("validates a saved fixture PNG path", async () => {
    const png = await readFile(fixture);
    expect(await checkCardPng(fixture.pathname)).toBe(png.byteLength);
    expect(png.byteLength).toBeLessThanOrEqual(CARD_LIMIT_BYTES);
  });

  it("rejects an oversized PNG at 300001 bytes but accepts the exact limit", async () => {
    const png = await readFile(fixture);
    const path = join(temporary, "budget.png");
    await writeFile(path, Buffer.concat([png, Buffer.alloc(CARD_LIMIT_BYTES - png.length)]));
    expect(await checkCardPng(path)).toBe(CARD_LIMIT_BYTES);
    await writeFile(path, Buffer.concat([png, Buffer.alloc(CARD_LIMIT_BYTES + 1 - png.length)]));
    await expect(checkCardPng(path)).rejects.toThrow("limit is 300000");
  });

  it("rejects a wrong-size PNG, a truncated header and a different format", async () => {
    const png = await readFile(fixture);
    png.writeUInt32BE(600, 16);
    const path = join(temporary, "invalid.png");
    await writeFile(path, png);
    await expect(checkCardPng(path)).rejects.toThrow("1200x630");
    await writeFile(path, png.subarray(0, 24));
    await expect(checkCardPng(path)).rejects.toThrow("must be a PNG");
    await writeFile(path, "<html>not a PNG</html>");
    await expect(checkCardPng(path)).rejects.toThrow("must be a PNG");
  });
});

import { spawnSync } from "node:child_process";
