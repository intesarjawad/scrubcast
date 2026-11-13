import { padLocalDate, padLocalTime, utcTime } from "./format.ts";
import type { Latest, Launch, LaunchSummary, Past } from "./types.ts";

export const CARD_WIDTH_PX = 1200;
export const CARD_HEIGHT_PX = 630;
export const CARD_LIMIT_BYTES = 300_000;
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000;

export function cardSchedule(launch: Launch) {
  const net = new Date(launch.net);
  const zone = launch.pad.location.timezone_name;
  return {
    date: padLocalDate(net, zone || "UTC"),
    localTime: zone ? padLocalTime(net, zone) : null,
    utcDate: padLocalDate(net, "UTC"),
    utcTime: utcTime(net),
  };
}

/** Use the publication clock so the same build always selects the same cards. */
export function cardLaunches(latest: Latest, past: Past): LaunchSummary[] {
  const cutoff = Date.parse(latest.generated_at) - RETENTION_MS;
  const launches = new Map<string, LaunchSummary>();
  for (const launch of latest.launches) launches.set(launch.id, launch);
  for (const launch of past.launches) {
    const net = Date.parse(launch.net);
    if (net >= cutoff && net <= Date.parse(latest.generated_at) && !launches.has(launch.id))
      launches.set(launch.id, launch);
  }
  return [...launches.values()];
}
