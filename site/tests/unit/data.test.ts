import { describe, expect, it, vi } from "vitest";
import { fetchData, hasSupportedSchema, isLatest, nextFeatured } from "../../src/data";
import { messages } from "../../src/messages";
import type { Latest, LaunchSummary } from "../../src/types";

const now = new Date("2026-11-05T12:00:00Z");
const launch: LaunchSummary = {
  id: "mission-17",
  name: "Mission 17",
  assessment: true,
  tier: "A",
  net: "2026-11-05T19:20:00Z",
  last_updated: "2026-11-05T10:00:00Z",
  launch_service_provider_name: "Provider",
  mission: { orbit: { abbrev: "LEO" } },
  net_precision: null,
  pad: {
    id: 1,
    name: "Pad",
    latitude: 28.5,
    longitude: -80.5,
    location: { id: 1, name: "Cape Canaveral", timezone_name: "America/New_York" },
  },
  page_url: "https://example.org/launch/mission-17",
  probability: 90,
  rocket_name: "Rocket",
  slug: "mission-17",
  status: "Go",
  weather_concerns: null,
  window_start: "2026-11-05T19:20:00Z",
  window_end: "2026-11-05T20:20:00Z",
  worst_rule: {
    label: "Thick cloud",
    confidence: "medium",
    model: "ecmwf",
    risk_fraction: 0.31,
    rule_id: "thick_cloud",
  },
};
function latest(launches: LaunchSummary[]): Latest {
  return {
    schema_version: 1,
    generated_at: now.toISOString(),
    members_total: 51,
    schedule_stale: false,
    launches,
  };
}

describe("next featured launch", () => {
  it("prefers the first assessed Tier A launch over other tiers and unassessed launches", () => {
    const data = latest([
      { ...launch, id: "tier-b", tier: "B" },
      { ...launch, assessment: false },
      launch,
    ]);
    expect(nextFeatured(data, now)).toEqual({ kind: "tierA", launch });
    expect(data.launches[0]?.id).toBe("tier-b");
  });
  it("includes a Tier A launch less than one hour ago", () => {
    const recent = { ...launch, net: "2026-11-05T11:00:01Z" };
    expect(nextFeatured(latest([recent]), now)).toEqual({ kind: "tierA", launch: recent });
  });
  it("excludes Tier A launches at and before the one-hour cutoff", () => {
    const old = { ...launch, net: "2026-11-05T11:00:00Z" };
    expect(nextFeatured(latest([old, launch]), now)).toEqual({ kind: "tierA", launch });
  });
  it("falls back to the first launch with the full-list message", () => {
    const next = { ...launch, tier: "C" as const, assessment: false };
    expect(nextFeatured(latest([next]), now)).toEqual({
      kind: "fallback",
      launch: next,
      message: messages.noTierA,
    });
  });
  it("returns an actionable empty state", () => {
    expect(nextFeatured(latest([]), now)).toEqual({ kind: "empty", message: messages.noLaunches });
  });
  it("never falls back to a passed launch, including an assessed Tier A", () => {
    const old = { ...launch, net: "2026-11-05T10:00:00Z" };
    const future = { ...launch, id: "future", tier: "C" as const };
    expect(nextFeatured(latest([old, future]), now)).toEqual({
      kind: "fallback",
      launch: future,
      message: messages.noTierA,
    });
    expect(nextFeatured(latest([old]), now)).toEqual({
      kind: "empty",
      message: messages.noLaunches,
    });
  });
});

describe("versioned launch data", () => {
  it.each([null, [], {}, { schema_version: "1" }, { schema_version: 2 }])(
    "rejects unsupported envelopes: %j",
    (value) => {
      expect(hasSupportedSchema(value)).toBe(false);
    },
  );
  it("validates the schedule and its nested fields", () => {
    expect(isLatest(latest([launch]))).toBe(true);
    expect(isLatest(latest([]))).toBe(true);
    expect(isLatest({ ...latest([]), launches: [null] })).toBe(false);
    expect(isLatest({ ...latest([]), launches: [{ ...launch, pad: null }] })).toBe(false);
    expect(
      isLatest({
        ...latest([]),
        launches: [{ ...launch, worst_rule: { label: "Cloud", risk_fraction: 31 } }],
      }),
    ).toBe(false);
    expect(isLatest({ ...latest([]), generated_at: "not a timestamp" })).toBe(false);
    expect(isLatest({ schema_version: 1 })).toBe(false);
  });
  it("fetches relative to a non-root deployment and returns checked data", async () => {
    const data = latest([launch]);
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(data));
    await expect(
      fetchData("latest.json", isLatest, { base: "/scrubcast/", fetcher }),
    ).resolves.toEqual(data);
    expect(fetcher).toHaveBeenCalledWith("/scrubcast/data/latest.json");
  });
  it.each([
    [new Response("unavailable", { status: 503 }), "dataFetchFailed"],
    [new Response("not json"), "invalidData"],
    [Response.json({ schema_version: 2 }), "unsupportedSchema"],
    [Response.json({ schema_version: 1 }), "invalidData"],
  ])("reports an unusable response", async (response, messageKey) => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response);
    await expect(fetchData("latest.json", isLatest, { fetcher })).rejects.toMatchObject({
      name: "DataError",
      messageKey,
    });
  });
  it("retains unsupported version and known build time", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        Response.json({ schema_version: 2, generated_at: "2026-11-05T12:00:00Z" }),
      );
    await expect(fetchData("latest.json", isLatest, { fetcher })).rejects.toMatchObject({
      version: "2",
      builtAt: "2026-11-05T12:00:00Z",
    });
  });
  it("reports a connection failure without losing the cause", async () => {
    const cause = new TypeError("offline");
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(cause);
    await expect(fetchData("latest.json", isLatest, { fetcher })).rejects.toMatchObject({
      messageKey: "dataFetchFailed",
      cause,
    });
  });
});
