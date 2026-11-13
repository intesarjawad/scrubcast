import { describe, expect, it } from "vitest";
import { basePath, isCardRoute, resolveRoute, routeHref } from "../../src/router";

const base = "/weather/scrubcast/";

describe("path routing beneath a deployment base", () => {
  it("enables the card layout only on a valid launch path with a card query", () => {
    const launch = resolveRoute(`${base}launch/mission-17/`, base);
    expect(isCardRoute(launch, "?card")).toBe(true);
    expect(isCardRoute(launch, "?theme=dark&card=")).toBe(true);
    expect(isCardRoute(launch, "?card=1")).toBe(true);
    expect(isCardRoute(launch, "?discard")).toBe(false);
    expect(isCardRoute(launch, "")).toBe(false);
    for (const path of ["next/", "", "audit/", "launch/%2F/"])
      expect(isCardRoute(resolveRoute(`${base}${path}`, base), "?card")).toBe(false);
  });
  it.each([
    ["", { name: "home" }],
    ["next/", { name: "next" }],
    ["launch/mission-17/", { name: "launch", id: "mission-17" }],
    ["audit/", { name: "audit" }],
    ["missing/", { name: "notFound" }],
  ])("resolves %s", (path, expected) => {
    expect(resolveRoute(`${base}${path}`, base)).toEqual(expected);
  });

  it.each([
    "/",
    "/next/",
    "/weather/scrubcast-other/",
    `${base}launch/`,
    `${base}launch/a/b/`,
    `${base}launch/%2F/`,
    `${base}launch/%E0%A4/`,
  ])("rejects paths outside the route grammar: %s", (path) =>
    expect(resolveRoute(path, base)).toEqual({ name: "notFound" }),
  );

  it("decodes a launch identifier", () => {
    expect(resolveRoute(`${base}launch/mission%20name/`, base)).toEqual({
      name: "launch",
      id: "mission name",
    });
  });

  it("creates base-aware links without duplicate slashes", () => {
    expect(routeHref("/audit/", base)).toBe(`${base}audit/`);
    expect(routeHref("", base)).toBe(base);
    expect(basePath("/weather/scrubcast")).toBe(base);
    expect(basePath("/")).toBe("/");
    expect(basePath("")).toBe("/");
    expect(resolveRoute("/", "/")).toEqual({ name: "home" });
  });
});
