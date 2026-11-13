import { describe, expect, it } from "vitest";
import {
  countdown,
  minusSign,
  padLocalTime,
  percent,
  utcSchedule,
  utcTime,
} from "../../src/format";

describe("launch display formats", () => {
  it.each([
    [0, "0%"],
    [0.314, "31%"],
    [0.315, "32%"],
    [1, "100%"],
  ])("formats the member fraction %s without decimals", (fraction, expected) => {
    expect(percent(Number(fraction))).toBe(expected);
  });

  it("sets negative figures with a minus sign and leaves ranges and words alone", () => {
    expect(minusSign("between 0 and -20 °C (-3 m)")).toBe("between 0 and \u221220 °C (\u22123 m)");
    expect(minusSign("T-0, 10-20 m, low-level")).toBe("T-0, 10-20 m, low-level");
  });

  it("uses a zero-padded 24-hour UTC clock including midnight", () => {
    expect(utcTime(new Date("2026-11-05T03:07:00Z"))).toBe("03:07 UTC");
    expect(utcTime(new Date("2026-11-05T00:00:00Z"))).toBe("00:00 UTC");
  });

  it("uses the pad timezone rather than the viewer timezone", () => {
    expect(padLocalTime(new Date("2026-11-05T19:07:00Z"), "Asia/Shanghai")).toBe("03:07 GMT+8");
  });

  it("names Cape Canaveral standard and daylight time", () => {
    expect(padLocalTime(new Date("2026-11-06T19:00:00Z"), "America/New_York")).toBe("14:00 EST");
    expect(padLocalTime(new Date("2026-07-06T19:00:00Z"), "America/New_York")).toBe("15:00 EDT");
  });

  it("skips the missing hour at the New York spring DST change", () => {
    expect(padLocalTime(new Date("2026-03-08T06:59:00Z"), "America/New_York")).toBe("01:59 EST");
    expect(padLocalTime(new Date("2026-03-08T07:00:00Z"), "America/New_York")).toBe("03:00 EDT");
  });

  it("keeps the two New York autumn 01:30 times distinguishable", () => {
    expect(padLocalTime(new Date("2026-11-01T05:30:00Z"), "America/New_York")).toBe("01:30 EDT");
    expect(padLocalTime(new Date("2026-11-01T06:30:00Z"), "America/New_York")).toBe("01:30 EST");
  });

  it("counts complete remaining minutes, and stops at zero", () => {
    const now = new Date("2026-11-05T00:00:00Z");
    expect(countdown(new Date("2026-11-05T19:20:59Z"), now)).toBe("in 19 h 20 m");
    expect(countdown(now, now)).toBe("in 0 h 0 m");
    expect(countdown(new Date("2026-11-04T23:00:00Z"), now)).toBe("in 0 h 0 m");
  });
});

it.each([
  ["2026-11-15T03:55:00Z", "America/Los_Angeles", "Nov 15, 2026, 03:55 UTC"],
  ["2026-11-05T19:07:00Z", "Asia/Shanghai", "Nov 5, 2026, 19:07 UTC"],
  ["2026-11-05T19:07:00Z", "America/New_York", "19:07 UTC"],
])("disambiguates the UTC day for %s in %s", (time, zone, expected) => {
  expect(utcSchedule(new Date(time), zone)).toBe(expected);
});
