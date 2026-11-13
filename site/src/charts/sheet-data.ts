import { minusSign } from "../format.ts";
import { models, sortedRules } from "../launch-data.ts";
import type { LaunchAssessment, RuleRisk } from "../types";
import type { Model } from "./scrubber-data";

export interface Member {
  model: Model;
  index: number;
}

/** A string is printed the same on every page; a number points at a slot that varies. */
export type Part = string | number;

export interface Fan {
  hour: string;
  values: (number | null)[];
  limit: number;
  comparator: string;
  unit: string;
  decimals: number;
  t0: boolean;
}

export interface Slot {
  values: string[];
  /** What the page shows before it prints, and in forced colours: each group's typical value. */
  typical: string;
  /** The slot read in its sentence by a screen reader. */
  label: string;
  /** Members whose printing of this slot breaks a rule; they print in the second ink. */
  alarm: boolean[];
  numeric: boolean;
  /**
   * The slot prints each group in its own place, so nothing overprints a different word or
   * a figure from another value cluster: a word slot groups by word, a figure by its digit
   * in the limit's leading place ("2,072" apart from "3,311" under a 1,400 m limit).
   */
  groups: string[];
  groupOf: number[];
  /** Ink multiplier per member: a group under one page in ten still prints at that share. */
  weight: number[];
  /** The page-number slot prints only the page on the press, at full ink. */
  ticker: boolean;
  fan: Fan | null;
}

export interface Sheet {
  members: Member[];
  paragraphs: { kind: "who" | "lead" | "figures" | "status" | "verdict"; parts: Part[] }[];
  slots: Slot[];
  figureRule: RuleRisk | null;
  complete: boolean;
}

export const MAX_FIGURE_HOURS = 6;
/** Between a slot's groups, printed in the shared ink: "0, 1 or 3", so no two counts read as one. */
export function between(group: number, count: number): string {
  return group === count - 2 ? " or " : ", ";
}
/** A group fewer pages print still shows, faintly, at this share; the fan and facts carry its count. */
export const MIN_SHARE = 0.12;
/** A group that breaks a rule never prints fainter than this, so the alarm is the easiest to read. */
export const ALARM_SHARE = 0.35;
/** A figure's typical value never prints its own digits fainter than this, so the figure reads. */
export const TYPICAL_SHARE = 0.35;
/** The least a differing digit is misregistered, in em: far enough that it never reads as in place. */
const MIN_RISE_EM = 0.3;
/** How much further it rises for each doubling of the gap between its value and the typical one. */
const RISE_PER_DOUBLING_EM = 0.025;
/** shortcut: a gap of 16 display steps or more rises this far, so wide spreads stack there. */
const MAX_RISE_EM = 0.4;

const figureNumber = (text: string) => Number(text.replaceAll(",", ""));

/**
 * Where each character of a member's figure prints against its cluster's typical value.
 * Every character keeps its own place, so nothing prints outside the typical figure. A digit
 * that agrees prints in register; every digit that differs is lifted for a higher value and
 * dropped for a lower one, further the wider the gap, so a member's ghosts read as a value
 * above or below the typical one and never as a digit in register.
 */
export function register(
  typical: string,
  value: string,
): { char: string; place: number; rise: number }[] {
  const decimals = typical.split(".")[1]?.length ?? 0;
  const gap = figureNumber(value) - figureNumber(typical);
  const steps = Math.abs(gap) * 10 ** decimals;
  const rise =
    Math.sign(gap) *
    Math.min(MAX_RISE_EM, MIN_RISE_EM + RISE_PER_DOUBLING_EM * Math.log2(Math.max(1, steps)));
  return [...value].map((char, place) => ({
    char,
    place,
    rise: typical[place] === char ? 0 : rise,
  }));
}

/**
 * A value's cluster: its digit in the limit's leading place, thousands for 1,400 m. Below
 * that place values split by how many whole digits they have, "0.1" for 7 and "0.3" for 350,
 * so every figure in a cluster has the same places.
 */
function cluster(value: number | null, limit: number): string {
  if (value === null) return "missing";
  const lead = 10 ** Math.floor(Math.log10(limit));
  if (value >= lead) return String(Math.floor(value / lead));
  return `0.${value < 1 ? 1 : Math.floor(Math.log10(value)) + 1}`;
}

/** The value most members print within one display step of, nearer the median on a tie. */
export function densest(values: number[], step: number): number {
  const sorted = [...values].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)] ?? 0;
  const near = (at: number) =>
    sorted.filter((value) => Math.abs(value - at) <= step * 1.001).length;
  return sorted.reduce((best, value) =>
    near(value) > near(best) ||
    (near(value) === near(best) && Math.abs(value - median) < Math.abs(best - median))
      ? value
      : best,
  );
}

export const SHORT_NAMES: Record<string, string> = {
  thick_cloud: "Thick cloud",
  cumulus: "Cumulus",
  anvil: "Anvil",
  disturbed_weather: "Disturbed weather",
  flight_through_precip: "Rain in flight",
  liftoff_wind: "Liftoff wind",
};

export function decimalsFor(limit: number): number {
  return limit < 1 ? 2 : limit < 100 ? 1 : 0;
}

export function formatValue(value: number | null, decimals: number): string {
  if (value === null) return "missing";
  return new Intl.NumberFormat("en", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function limitText(limit: number): string {
  return new Intl.NumberFormat("en", { maximumSignificantDigits: 3 }).format(limit);
}

function subject(rule: RuleRisk): string {
  const phrase = rule.plot.readout_phrase;
  switch (rule.plot.variable) {
    case "wind_at_reference_height": {
      const height = /\(([\d.]+) m above/.exec(phrase)?.[1];
      return height ? `the wind ${height} m above the pad` : "the wind at the pad";
    }
    case "qualifying_layer_thickness": {
      const band = /between (.+? °C)/.exec(phrase)?.[1];
      return band
        ? `the thickest cloud layer between ${minusSign(band)}`
        : "the thickest cloud layer";
    }
    case "cape":
      return "CAPE";
    case "precipitation":
      return "rain at the pad";
    default:
      return rule.title;
  }
}

export function localTime(iso: string, zone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(iso));
}

function localDate(iso: string, zone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  })
    .format(new Date(iso))
    .replace(",", "");
}

function peakRisk(rule: RuleRisk): number {
  return Math.max(
    0,
    ...Object.values(rule.risk_by_hour)
      .flatMap((series) => series ?? [])
      .map((value) => value ?? 0),
  );
}

function closeness(rule: RuleRisk): number {
  const limit = rule.threshold?.value;
  if (!limit) return 0;
  const values = Object.values(rule.member_values_by_hour)
    .flatMap((matrix) => matrix?.flat() ?? [])
    .filter((value): value is number => value !== null);
  if (values.length === 0) return 0;
  return rule.threshold?.comparator === "<="
    ? limit / Math.max(Math.min(...values), Number.EPSILON)
    : Math.max(...values) / limit;
}

/** The rule whose figures go on the page: the most broken, then the most direct, then the closest. */
export function figureRule(assessment: LaunchAssessment): RuleRisk | null {
  const candidates = assessment.rules.filter((rule) => rule.threshold !== null);
  const rank = (rule: RuleRisk) => [
    peakRisk(rule),
    rule.confidence === "direct" ? 1 : 0,
    closeness(rule),
  ];
  return (
    [...candidates].sort((a, b) => {
      const left = rank(a);
      const right = rank(b);
      return (
        (right[0] ?? 0) - (left[0] ?? 0) ||
        (right[1] ?? 0) - (left[1] ?? 0) ||
        (right[2] ?? 0) - (left[2] ?? 0)
      );
    })[0] ?? null
  );
}

/** Up to six hours, evenly spread, always including T-0. */
export function figureHours(count: number, t0: number): number[] {
  if (count <= MAX_FIGURE_HOURS) return [...Array(count).keys()];
  const picked = new Set([t0]);
  for (let step = 0; picked.size < MAX_FIGURE_HOURS; step++) {
    picked.add(Math.round((step * (count - 1)) / (MAX_FIGURE_HOURS - 1)));
  }
  return [...picked].sort((a, b) => a - b);
}

function evaluable(rule: RuleRisk, model: Model): boolean {
  return (rule.by_model[model]?.evaluable_members ?? 0) > 0;
}

function hasMembers(rule: RuleRisk, model: Model): boolean {
  return !evaluable(rule, model) || Array.isArray(rule.member_violated_by_hour[model]);
}

/** Typeset the same page once per ensemble member: shared words, and slots that differ by member. */
export function buildSheet(assessment: LaunchAssessment): Sheet {
  const { launch } = assessment;
  const zone = launch.pad.location.timezone_name || "UTC";
  const members: Member[] = models.flatMap((model) => {
    const count = Math.max(
      0,
      ...assessment.rules.map((rule) => rule.by_model[model]?.members ?? 0),
    );
    return [...Array(count).keys()].map((index) => ({ model, index }));
  });
  const complete = assessment.rules.every((rule) =>
    models.every((model) => hasMembers(rule, model)),
  );
  const slots: Slot[] = [];
  function slot(
    values: string[],
    numeric = false,
    fan: Fan | null = null,
    alarmed: (value: string, member: number) => boolean = (value) => value.startsWith("breaks"),
    ticker = false,
  ) {
    // Clusters and offsets work on the figures as printed, not on unprinted decimals.
    const raw = (fan?.values ?? []).map((value) =>
      value === null || !fan ? null : Number(value.toFixed(fan.decimals)),
    );
    const keys = values.map((value, member) =>
      ticker ? "" : fan ? cluster(raw[member] ?? null, fan.limit) : value,
    );
    const order = byCount(keys);
    // Counts and clusters read in order, "0  1  3", not by how common each is.
    if (keys.every((key) => /^\d+(\.\d)?$/.test(key))) order.sort((a, b) => Number(a) - Number(b));
    const groupOf = keys.map((key) => order.indexOf(key));
    const centres = order.map((key) => {
      const present = raw.filter((value, member) => value !== null && keys[member] === key);
      return fan && present.length ? densest(present as number[], 10 ** -fan.decimals) : null;
    });
    const groups = order.map((key, group) => {
      const centre = centres[group];
      if (ticker) return values.at(-1) ?? "";
      if (centre === null || centre === undefined || !fan)
        return values.find((_, member) => keys[member] === key) ?? "";
      return formatValue(centre, fan.decimals);
    });
    const sizes = order.map((key) => keys.filter((other) => other === key).length);
    const alarm = values.map(alarmed);
    const breaking = order.map((_, group) =>
      alarm.some((alarmed, member) => alarmed && groupOf[member] === group),
    );
    slots.push({
      values,
      typical: groups
        .map(
          (text, group) => text + (group < groups.length - 1 ? between(group, groups.length) : ""),
        )
        .join(""),
      alarm,
      label: fan ? figureLabel(fan, members.length) : wordLabel(values),
      numeric,
      groups,
      groupOf,
      weight: groupOf.map((group) =>
        Math.max(
          1,
          ((breaking[group] ? ALARM_SHARE : MIN_SHARE) * values.length) / (sizes[group] ?? 1),
        ),
      ),
      fan,
      ticker,
    });
    return slots.length - 1;
  }
  const perMember = (text: (member: Member) => string) =>
    complete ? members.map(text) : members.map(() => "");

  const paragraphs: Sheet["paragraphs"] = [];
  const numbers = members.map((_, order) => String(order + 1));
  paragraphs.push({
    kind: "who",
    parts: ["No. ", slot(numbers, true, null, () => false, true)],
  });
  const [vehicle, mission] = launch.name.split(" | ");
  const pad = launch.pad.name.replace("Space Launch Complex ", "SLC-");
  const site = launch.pad.location.name.split(",")[0] ?? launch.pad.location.name;
  paragraphs.push({
    kind: "lead",
    parts: [
      `${mission ? `${vehicle}, ${mission}` : launch.name}. ${pad}, ${site}.\n${localDate(launch.net, zone)}. The window opens at ${localTime(launch.window_start, zone)}.`,
    ],
  });

  const figure = figureRule(assessment);
  if (figure?.threshold) {
    const limit = figure.threshold.value;
    const decimals = decimalsFor(limit);
    const unit = figure.threshold.unit;
    const parts: Part[] = [];
    for (const [position, hour] of figureHours(
      figure.hours.length,
      assessment.t0_index,
    ).entries()) {
      const at = localTime(figure.hours[hour] ?? launch.net, zone);
      const raw = members.map(
        ({ model, index }) => figure.member_values_by_hour[model]?.[hour]?.[index] ?? null,
      );
      const values = complete
        ? raw.map((value) => formatValue(value, decimals))
        : raw.map(() => "");
      const fan = {
        hour: at,
        values: raw,
        limit,
        comparator: figure.threshold.comparator,
        unit,
        decimals,
        t0: hour === assessment.t0_index,
      };
      const index = slot(values, true, fan, (_, member) => {
        const value = raw[member];
        return value !== null && value !== undefined && breaks(fan, value);
      });
      parts.push(
        position === 0
          ? `At ${at} ${subject(figure)} is `
          : position === 1
            ? `\nAt ${at} it is `
            : // Non-breaking, so an hour never wraps away from its figure ("3.3." alone on a line).
              ` At\u00a0${at},\u00a0`,
        index,
        position === 0 ? `\u00a0${unit}.` : ".",
      );
    }
    parts.push(`\nThe limit is ${limitText(limit)}.`);
    paragraphs.push({ kind: "figures", parts });
  }

  const others = assessment.rules.filter((rule) => rule !== figure);
  if (others.length) {
    const parts: Part[] = [];
    for (const [position, rule] of others.entries()) {
      parts.push(
        `${position ? "  " : ""}${SHORT_NAMES[rule.rule_id] ?? rule.title}: `,
        slot(
          perMember(({ model, index }) => {
            if (!evaluable(rule, model)) return "no field";
            const first = (rule.member_violated_by_hour[model] ?? []).findIndex(
              (row) => row?.[index] === 1,
            );
            return first < 0
              ? "clear"
              : `breaks at ${localTime(rule.hours[first] ?? launch.net, zone)}`;
          }),
        ),
        ".",
      );
    }
    paragraphs.push({ kind: "status", parts });
  }

  paragraphs.push({
    kind: "verdict",
    parts: [
      "Members break ",
      slot(
        perMember(({ model, index }) =>
          String(
            assessment.rules.filter((rule) =>
              (rule.member_violated_by_hour[model] ?? []).some((row) => row?.[index] === 1),
            ).length,
          ),
        ),
        false,
        null,
        (value) => value !== "0",
      ),
      ` of ${assessment.rules.length} rules.`,
    ],
  });
  return { members, paragraphs, slots, figureRule: figure, complete };
}

function byCount(values: string[]): string[] {
  const counts = new Map<string, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1]).map(([value]) => value);
}

/** The board's rules, riskiest first; on a clean night the sheet's figure rule leads, so the plot has values to draw. */
export function openingRules(assessment: LaunchAssessment): RuleRisk[] {
  const sorted = sortedRules(assessment);
  const figure = figureRule(assessment);
  const clean = sorted.every((rule) => !membersBreaking(rule).broken);
  const drawn = figure?.member_violated_by_hour.ecmwf?.some((hour) =>
    hour?.some((verdict) => verdict !== null),
  );
  return figure && clean && drawn ? [figure, ...sorted.filter((rule) => rule !== figure)] : sorted;
}

/** How many members break a rule at any hour of the window, out of those with evidence in that window. */
export function membersBreaking(rule: RuleRisk): { broken: number; of: number } {
  let broken = 0;
  let of = 0;
  for (const model of models) {
    const risk = rule.by_model[model];
    if (!risk) continue;
    const rows = rule.member_violated_by_hour[model] ?? [];
    for (let member = 0; member < risk.members; member++) {
      if (rows.some((row) => row?.[member] === 0 || row?.[member] === 1)) of++;
      if (rows.some((row) => row?.[member] === 1)) broken++;
    }
  }
  return { broken, of };
}

function wordLabel(values: string[]): string {
  const counts = new Map<string, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  const rows = [...counts].sort((a, b) => b[1] - a[1]);
  if (rows.length === 1) return `${rows[0]?.[0] ?? ""} on all ${values.length} pages`;
  return rows.map(([value, count]) => `${value} on ${count}`).join(", ");
}

export function breaks(fan: Fan, value: number): boolean {
  return fan.comparator === "<="
    ? value <= fan.limit
    : fan.comparator === ">="
      ? value >= fan.limit
      : value > fan.limit;
}

function figureLabel(fan: Fan, total: number): string {
  const present = fan.values.filter((value): value is number => value !== null);
  if (present.length === 0) return "missing on every page";
  const low = formatValue(Math.min(...present), fan.decimals);
  const high = formatValue(Math.max(...present), fan.decimals);
  const missing = total - present.length;
  return `${low === high ? low : `between ${low} and ${high}`}${missing ? ` (${missing} missing)` : ""}`;
}

/** One sentence that carries the fan's numbers for readers who never see it. */
export function fanSummary(fan: Fan, total: number): string {
  const present = fan.values.filter((value): value is number => value !== null);
  const over = present.filter((value) => breaks(fan, value)).length;
  const range =
    present.length === 0
      ? "no values"
      : `${formatValue(Math.min(...present), fan.decimals)} to ${formatValue(Math.max(...present), fan.decimals)} ${fan.unit}`;
  const verdict =
    over === 0
      ? `None break the ${limitText(fan.limit)} ${fan.unit} limit`
      : `${over} of ${present.length} break the ${limitText(fan.limit)} ${fan.unit} limit`;
  return `${fan.hour}, all ${total} members: ${range}. ${verdict}.`;
}

/** One scale for every hour, so the limit line stays put while the fans change. */
export function fanTop(sheet: Sheet): number {
  const fans = sheet.slots.flatMap((slot) => (slot.fan ? [slot.fan] : []));
  const values = fans
    .flatMap((fan) => fan.values)
    .filter((value): value is number => value !== null);
  return Math.max(fans[0]?.limit ?? 0, ...values) * 1.08;
}

export interface FanPlacement {
  column: number;
  row: number;
}

/** How many columns the fan's scale is cut into, in data units, at every viewport. */
export const FAN_COLUMNS = 14;

/** Stack each value in its column of the shared scale, lowest value at the base. */
export function fanColumns(values: (number | null)[], top: number, columns = FAN_COLUMNS) {
  const heights = new Array<number>(columns).fill(0);
  const placements: (FanPlacement | null)[] = values.map(() => null);
  const order = values
    .map((value, member) => ({ value, member }))
    .filter((entry): entry is { value: number; member: number } => entry.value !== null)
    .sort((a, b) => a.value - b.value || a.member - b.member);
  for (const { value, member } of order) {
    const column = fanColumn(value, top, columns);
    placements[member] = { column, row: heights[column] ?? 0 };
    heights[column] = (heights[column] ?? 0) + 1;
  }
  return { placements, heights };
}

export function fanColumn(value: number, top: number, columns = FAN_COLUMNS): number {
  return Math.min(columns - 1, Math.max(0, Math.floor((value / top) * columns)));
}

/**
 * Each fan column's label: the sheet's own typical value for a cluster that falls in it, the
 * largest cluster first, otherwise the value most of the column's members are near.
 */
export function fanLabels(slot: Slot, top: number, columns = FAN_COLUMNS): (string | null)[] {
  const fan = slot.fan;
  if (!fan) return [];
  const step = 10 ** -fan.decimals;
  const size = slot.groups.map((_, group) => slot.groupOf.filter((key) => key === group).length);
  return [...Array(columns).keys()].map((column) => {
    const sheet = slot.groups
      .map((text, group) => ({ text, group }))
      .filter(({ text }) => fanColumn(figureNumber(text), top, columns) === column)
      .sort((a, b) => (size[b.group] ?? 0) - (size[a.group] ?? 0))[0];
    if (sheet) return sheet.text;
    const members = fan.values.flatMap((value, member) =>
      value !== null && fanColumn(value, top, columns) === column ? [member] : [],
    );
    if (!members.length) return null;
    const typical = densest(
      members.map((member) => fan.values[member] ?? 0),
      step,
    );
    return slot.values[members.find((member) => fan.values[member] === typical) ?? -1] ?? null;
  });
}

/** The hour most members break a rule, or null when none do. */
export function peakHour(rule: RuleRisk): number | null {
  let best: number | null = null;
  let most = 0;
  rule.hours.forEach((_, hour) => {
    let count = 0;
    for (const model of models)
      count += (rule.member_violated_by_hour[model]?.[hour] ?? []).filter((v) => v === 1).length;
    if (count > most) {
      most = count;
      best = hour;
    }
  });
  return best;
}

/** Press-run timing: the first pages land slowly enough to read, then the run speeds up. */
export function pressSchedule(count: number): { start: number; duration: number }[] {
  let start = 300;
  return [...Array(count).keys()].map((index) => {
    const duration = 240 + 760 * 0.9 ** index;
    const row = { start, duration };
    start += 26 + 430 * 0.84 ** index;
    return row;
  });
}
