import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  ALARM_SHARE,
  buildSheet,
  FAN_COLUMNS,
  fanColumn,
  fanColumns,
  fanLabels,
  fanSummary,
  fanTop,
  figureHours,
  figureRule,
  MIN_SHARE,
  membersBreaking,
  openingRules,
  peakHour,
  pressSchedule,
  register,
  TYPICAL_SHARE,
} from "../../src/charts/sheet-data";
import { ghostScales } from "../../src/charts/sheet-still";
import type { Place } from "../../src/charts/sheet-types";
import { isLaunchAssessment } from "../../src/launch-data";
import { demo } from "../fixtures/demo";

const storm: unknown = JSON.parse(
  readFileSync(
    new URL("../../../tests/fixtures/worst_case/storm-night.json", import.meta.url),
    "utf8",
  ),
);
if (!isLaunchAssessment(storm)) throw new Error("Invalid storm fixture");

describe("the overprinted sheet", () => {
  it("counts window-wide violations against the members with window-wide evidence", () => {
    const rule = structuredClone(demo.rules[0]);
    if (!rule) throw new Error("Missing rule");
    for (const model of ["ecmwf", "gfs"] as const) {
      rule.by_model[model] = { members: 3, evaluable_members: 1, risk_fraction: 0 };
      rule.member_violated_by_hour[model] = [
        [0, null, null],
        [0, 1, null],
      ];
    }
    expect(membersBreaking(rule)).toEqual({ broken: 2, of: 4 });
    for (const model of ["ecmwf", "gfs"] as const) {
      rule.by_model[model] = { members: 3, evaluable_members: 0, risk_fraction: null };
      rule.member_violated_by_hour[model] = [
        [null, null, null],
        [1, 1, null],
      ];
    }
    expect(membersBreaking(rule)).toEqual({ broken: 4, of: 4 });
  });

  it("prints one page per ensemble member, ECMWF first", () => {
    const sheet = buildSheet(demo);
    expect(sheet.members).toHaveLength(82);
    expect(sheet.members.filter((member) => member.model === "ecmwf")).toHaveLength(51);
    expect(sheet.members[51]).toEqual({ model: "gfs", index: 0 });
    for (const slot of sheet.slots) expect(slot.values).toHaveLength(82);
  });

  it("puts liftoff wind on a calm night's page and reads each member's own values", () => {
    const sheet = buildSheet(demo);
    expect(sheet.figureRule?.rule_id).toBe("liftoff_wind");
    const wind = demo.rules.find((rule) => rule.rule_id === "liftoff_wind");
    const first = sheet.slots.find((slot) => slot.fan);
    expect(first?.values[3]).toBe(wind?.member_values_by_hour.ecmwf?.[0]?.[3]?.toFixed(1));
    expect(first?.values[51]).toBe(wind?.member_values_by_hour.gfs?.[0]?.[0]?.toFixed(1));
    expect(sheet.slots.every((slot) => slot.alarm.every((alarm) => !alarm))).toBe(true);
  });

  it("puts the riskiest rule on the page whenever one stands above the rest", () => {
    const rules = demo.rules.map((rule) =>
      rule.rule_id === "cumulus"
        ? { ...rule, risk_by_hour: { ...rule.risk_by_hour, ecmwf: [0, 0.2, 0, 0, 0] } }
        : rule,
    );
    expect(figureRule({ ...demo, rules })?.rule_id).toBe("cumulus");
  });

  it("names a missing field instead of calling it clear", () => {
    const status = buildSheet(demo).slots.find((slot) => slot.values.includes("no field"));
    expect(status?.values.slice(0, 51).every((value) => value === "clear")).toBe(true);
    expect(status?.values.slice(51).every((value) => value === "no field")).toBe(true);
  });

  it("marks the members that break a rule on a stormy night", () => {
    const sheet = buildSheet(storm);
    expect(sheet.figureRule?.rule_id).toBe("thick_cloud");
    const fan = sheet.slots.find((slot) => slot.fan?.t0);
    const broken = storm.rules[0]?.member_violated_by_hour;
    const expected = [...(broken?.ecmwf?.[0] ?? []), ...(broken?.gfs?.[0] ?? [])].map(
      (verdict) => verdict === 1,
    );
    expect(fan?.alarm).toEqual(expected);
    if (!fan?.fan) throw new Error("Missing T-0 fan");
    expect(fanSummary(fan.fan, 82)).toBe(
      `19:00, all 82 members: 0 to 4,770 m. ${expected.filter(Boolean).length} of 82 break the 1,400 m limit.`,
    );
  });

  it("prints the verdict count at the density each count really has", () => {
    const sheet = buildSheet(storm);
    const verdict = sheet.slots.at(-1);
    const thick = storm.rules.find((rule) => rule.rule_id === "thick_cloud");
    if (!verdict || !thick) throw new Error("Missing verdict or thick cloud rule");
    const clean = verdict.values.filter((value) => value === "0").length;
    expect(clean).toBeLessThanOrEqual(82 - membersBreaking(thick).broken);
    expect(membersBreaking(thick)).toEqual({ broken: 42, of: 82 });
    expect(verdict.alarm.filter(Boolean)).toHaveLength(82 - clean);
  });

  it("overprints only figures that agree on their leading digits", () => {
    for (const sheet of [buildSheet(demo), buildSheet(storm)]) {
      for (const slot of sheet.slots) {
        const fan = slot.fan;
        if (!fan) continue;
        // The limit's leading place: thousands for 1,400 m, tens for 13.4 m/s.
        const place = 10 ** Math.floor(Math.log10(fan.limit));
        slot.groups.forEach((_, group) => {
          const leads = fan.values
            .filter((value, member) => value !== null && slot.groupOf[member] === group)
            .map((value) => Math.floor((value ?? 0) / place));
          expect(new Set(leads).size).toBeLessThanOrEqual(1);
        });
      }
    }
    const first = buildSheet(storm).slots.find((slot) => slot.fan?.t0);
    expect(first?.groups.map((text) => text.slice(0, 1))).toEqual(["0", "2", "3", "4"]);
  });

  it("keeps every mark inside the typical value's own digit places", () => {
    for (const sheet of [buildSheet(demo), buildSheet(storm)]) {
      for (const slot of sheet.slots) {
        if (!slot.fan) continue;
        slot.groups.forEach((typical, group) => {
          slot.values.forEach((value, member) => {
            if (!value || slot.groupOf[member] !== group) return;
            const marks = register(typical, value);
            expect(marks).toHaveLength(typical.length);
            for (const mark of marks) {
              expect(Number.isInteger(mark.place)).toBe(true);
              expect(mark.place).toBeGreaterThanOrEqual(0);
              expect(mark.place).toBeLessThanOrEqual(typical.length - 1);
            }
          });
        });
      }
    }
  });

  it("never prints a differing digit in register, at any stage of the press", () => {
    for (const sheet of [buildSheet(demo), buildSheet(storm)]) {
      for (const slot of sheet.slots) {
        if (!slot.fan) continue;
        slot.groups.forEach((typical, group) => {
          const members = slot.values.flatMap((value, member) =>
            value && slot.groupOf[member] === group ? [member] : [],
          );
          for (let stage = 1; stage <= members.length; stage++)
            for (const member of members.slice(0, stage))
              for (const mark of register(typical, slot.values[member] ?? ""))
                if (mark.rise === 0) expect(mark.char).toBe(typical[mark.place]);
        });
      }
    }
  });

  it("lifts a ghost for a higher value and drops it for a lower one, further the wider the gap", () => {
    expect(register("2,069", "2,069").map((mark) => mark.rise)).toEqual([0, 0, 0, 0, 0]);
    // 2,078 is above 2,069, so both its differing digits rise, the 8 included.
    const above = register("2,069", "2,078");
    expect(above.map((mark) => mark.place)).toEqual([0, 1, 2, 3, 4]);
    expect(above[3]?.rise).toBeGreaterThanOrEqual(0.3);
    expect(above[4]?.rise).toBe(above[3]?.rise);
    expect(register("2,069", "2,060")[4]?.rise).toBeLessThanOrEqual(-0.3);
    expect(register("6.7", "6.5")[2]?.rise).toBeLessThan(0);
    const lift = (value: string) => register("2,069", value).find((mark) => mark.rise)?.rise ?? 0;
    expect(lift("2,070")).toBeGreaterThanOrEqual(0.3);
    expect(lift("2,071")).toBeGreaterThan(lift("2,070"));
    expect(lift("2,073")).toBeGreaterThan(lift("2,071"));
    expect(lift("2,077")).toBeGreaterThan(lift("2,073"));
    expect(lift("2,099")).toBeGreaterThanOrEqual(lift("2,077"));
    for (const gap of [1, 2, 5, 9, 30])
      expect(Math.sign(lift(String(2069 - gap).replace(/(\d)(\d{3})$/, "$1,$2")))).toBe(-1);
  });

  it("keeps every typical digit at least twice its ghosts' ink at every stage of the press", () => {
    for (const sheet of [buildSheet(demo), buildSheet(storm)]) {
      const places: Place[] = [];
      for (const slot of sheet.slots) {
        if (!slot.fan) continue;
        slot.groups.forEach((typical, group) => {
          const start = places.length;
          const first = slot.values.findIndex((v, m) => v && slot.groupOf[m] === group);
          for (const _ of typical) places.push({ first, agree: [], ghosts: [] });
          slot.values.forEach((value, member) => {
            if (!value || slot.groupOf[member] !== group) return;
            for (const mark of register(typical, value))
              places[start + mark.place]?.[mark.rise ? "ghosts" : "agree"].push([
                member,
                slot.weight[member] ?? 1,
              ]);
          });
        });
      }
      const total = sheet.members.length;
      const settled = (count: number) =>
        [...Array(total).keys()].map((m) => (m < count ? 1 / count : 0));
      // A page just struck holds most of the ink before it settles.
      const struck = (count: number) =>
        [...Array(total).keys()].map((m) =>
          m < count - 1
            ? 0.1 / Math.max(1, count - 1)
            : m === count - 1
              ? count > 1
                ? 0.9
                : 1
              : 0,
        );
      expect(pressSchedule(total)).toHaveLength(total);
      for (let count = 1; count <= total; count++)
        for (const inks of [settled(count), struck(count)]) {
          const scales = ghostScales(places, inks);
          places.forEach(({ first, agree, ghosts }, index) => {
            const ink = ([member, weight]: [number, number]) =>
              Math.min(1, (inks[member] ?? 0) * weight);
            const typical = Math.min(
              1,
              ((inks[first] ?? 0) > 0 ? TYPICAL_SHARE : 0) +
                agree.reduce((t, row) => t + ink(row), 0),
            );
            const ghost = ghosts.reduce((t, row) => t + ink(row), 0) * (scales[index] ?? 1);
            expect(2 * ghost).toBeLessThanOrEqual(typical + 1e-9);
          });
        }
    }
  });

  it("clusters figures by length as well as leading digit, so every member fits its cluster's places", () => {
    const sheet = buildSheet(storm);
    for (const slot of sheet.slots.filter((slot) => slot.fan))
      slot.values.forEach((value, member) => {
        if (value) expect(value.length).toBe(slot.groups[slot.groupOf[member] ?? 0]?.length);
      });
  });

  it("opens the plot on the figure rule only when no member breaks anything", () => {
    expect(openingRules(demo).map((rule) => rule.rule_id)[0]).toBe("liftoff_wind");
    expect(openingRules(storm)[0]?.rule_id).toBe("thick_cloud");
  });

  it("reads each calm-night wind figure as its typical value", () => {
    const winds = buildSheet(demo).slots.filter((slot) => slot.fan);
    expect(winds.map((slot) => slot.groups.join())).toEqual(["6.7", "6.1", "5.4", "4.2", "3.2"]);
  });

  it("prints a cluster that breaks the rule at a legible floor", () => {
    const sheet = buildSheet(storm);
    for (const slot of sheet.slots)
      slot.values.forEach((_, member) => {
        if (!slot.alarm[member]) return;
        const size = slot.groupOf.filter((group) => group === slot.groupOf[member]).length;
        expect(((slot.weight[member] ?? 0) * size) / slot.values.length).toBeGreaterThanOrEqual(
          ALARM_SHARE - 1e-9,
        );
      });
  });

  it("sets the verdict counts side by side and prints a rare group faintly but visibly", () => {
    const sheet = buildSheet(storm);
    expect(sheet.slots.at(-1)?.groups.slice(0, 2).sort()).toEqual(["0", "1"]);
    const cumulus = sheet.slots.find((slot) =>
      slot.values.some((value) => value.startsWith("breaks")),
    );
    if (!cumulus) throw new Error("Missing cumulus slot");
    const rare = cumulus.values.findIndex((value) => value !== "clear");
    expect(cumulus.groups).toEqual(["clear", cumulus.values[rare]]);
    expect((cumulus.weight[rare] ?? 0) / cumulus.values.length).toBeCloseTo(ALARM_SHARE);
    expect(cumulus.weight[rare === 0 ? 1 : 0]).toBe(1);
    const anvil = sheet.slots.find((slot) => slot.values.includes("no field"));
    const blank = anvil?.values.indexOf("no field") ?? -1;
    const blanks = anvil?.values.filter((value) => value === "no field").length ?? 0;
    expect(((anvil?.weight[blank] ?? 0) * blanks) / 82).toBeCloseTo(
      Math.max(MIN_SHARE, blanks / 82),
    );
  });

  it("prints the storm verdict's red count at its real share and above 3:1 on paper", () => {
    const verdict = buildSheet(storm).slots.at(-1);
    const share = (verdict?.values.filter((value) => value === "1").length ?? 0) / 82;
    expect(share).toBeCloseTo(41 / 82);
    // The final pass spreads ink as 1 - (1 - cover)^2 and mixes in sRGB, as sheet-gl.ts does.
    const cover = 1 - (1 - share) ** 2;
    const css = readFileSync(new URL("../../src/styles.css", import.meta.url), "utf8");
    const themes = (name: string) =>
      [...css.matchAll(new RegExp(`${name}: (#[0-9a-f]{6})`, "g"))].map((match) =>
        [1, 3, 5].map((at) => Number.parseInt(match[1]?.slice(at, at + 2) ?? "", 16)),
      );
    const luminance = (rgb: number[]) => {
      const [r = 0, g = 0, b = 0] = rgb.map((value) => {
        const srgb = value / 255;
        return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const ratios = themes("--bg").map((paper, theme) => {
      const alarm = themes("--alarm")[theme] ?? [];
      const ink = paper.map(
        (value, channel) => value * (1 - cover) + (alarm[channel] ?? 0) * cover,
      );
      const [high, low] = [luminance(paper), luminance(ink)].sort((x, y) => y - x);
      return ((high ?? 0) + 0.05) / ((low ?? 0) + 0.05);
    });
    // Light and dark, as docs/design/README.md states them; the verdict is large bold type.
    expect(ratios.map((ratio) => Math.round(ratio * 100) / 100)).toEqual([4.57, 4.6]);
    for (const ratio of ratios) expect(ratio).toBeGreaterThanOrEqual(3);
  });

  it("numbers the pages in the page-number slot", () => {
    const ticker = buildSheet(demo).slots.find((slot) => slot.ticker);
    expect(ticker?.values.slice(0, 2)).toEqual(["1", "2"]);
    expect(ticker?.typical).toBe("82");
  });

  it("keeps T-0 when it has to drop hours from a long window", () => {
    expect(figureHours(5, 0)).toEqual([0, 1, 2, 3, 4]);
    const picked = figureHours(25, 7);
    expect(picked).toHaveLength(6);
    expect(picked).toContain(7);
    expect(picked).toEqual([...picked].sort((a, b) => a - b));
  });

  it("waits for member data before printing", () => {
    const stripped = {
      ...demo,
      rules: demo.rules.map((rule) => ({
        ...rule,
        member_values_by_hour: {},
        member_violated_by_hour: {},
      })),
    };
    const sheet = buildSheet(stripped);
    expect(sheet.complete).toBe(false);
    expect(figureRule(stripped)?.rule_id).toBe("liftoff_wind");
  });
});

describe("the fan of one figure", () => {
  it("labels each figure's column with the sheet's own typical value, at a fixed data step", () => {
    for (const sheet of [buildSheet(demo), buildSheet(storm)]) {
      const top = fanTop(sheet);
      for (const slot of sheet.slots) {
        if (!slot.fan) continue;
        const labels = fanLabels(slot, top);
        expect(labels).toHaveLength(FAN_COLUMNS);
        const size = (group: number) => slot.groupOf.filter((key) => key === group).length;
        slot.groups.forEach((typical, group) => {
          const column = fanColumn(Number(typical.replaceAll(",", "")), top);
          const rival = slot.groups.some(
            (other, index) =>
              index !== group &&
              size(index) > size(group) &&
              fanColumn(Number(other.replaceAll(",", "")), top) === column,
          );
          if (!rival) expect(labels[column]).toBe(typical);
        });
      }
    }
    const wind = buildSheet(demo).slots.find((slot) => slot.fan?.t0);
    expect(wind && fanLabels(wind, fanTop(buildSheet(demo)))).toContain("6.7");
  });

  it("names the hour most members break a rule", () => {
    const thick = storm.rules.find((rule) => rule.rule_id === "thick_cloud");
    expect(thick && peakHour(thick)).toBe(0);
    const calm = demo.rules.find((rule) => rule.rule_id === "thick_cloud");
    expect(calm && peakHour(calm)).toBeNull();
  });

  it("stacks every value in its column, lowest first, and skips missing members", () => {
    const { placements, heights } = fanColumns([1, 9, 1.2, null, 9.5], 10, 10);
    expect(placements).toEqual([
      { column: 1, row: 0 },
      { column: 9, row: 0 },
      { column: 1, row: 1 },
      null,
      { column: 9, row: 1 },
    ]);
    expect(heights.reduce((sum, count) => sum + count, 0)).toBe(4);
  });
});
