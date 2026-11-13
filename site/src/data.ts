import { messages } from "./messages.ts";
import { routeHref } from "./router.ts";
import type { Latest, LaunchSummary, Past, WorstRule } from "./types";

export const SCHEMA_VERSION = 1;
const FEATURED_GRACE_MS = 60 * 60 * 1000;

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function hasSupportedSchema(
  value: unknown,
): value is Record<string, unknown> & { schema_version: typeof SCHEMA_VERSION } {
  return isRecord(value) && value.schema_version === SCHEMA_VERSION;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isTimestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function isWorstRule(value: unknown): value is WorstRule {
  if (!isRecord(value) || typeof value.label !== "string") return false;
  return (
    (value.confidence === undefined ||
      value.confidence === null ||
      value.confidence === "direct" ||
      value.confidence === "medium" ||
      value.confidence === "low") &&
    (value.model === undefined ||
      value.model === null ||
      value.model === "ecmwf" ||
      value.model === "gfs") &&
    (value.risk_fraction === undefined ||
      value.risk_fraction === null ||
      (isFiniteNumber(value.risk_fraction) &&
        value.risk_fraction >= 0 &&
        value.risk_fraction <= 1)) &&
    (value.rule_id === undefined || isNullableString(value.rule_id))
  );
}

function isAuditRule(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.rule_id === "string" &&
    typeof value.title === "string" &&
    isFiniteNumber(value.risk_fraction) &&
    value.risk_fraction >= 0 &&
    value.risk_fraction <= 1
  );
}

function isAuditFooter(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.attempt_id === "string" &&
    isTimestamp(value.attempt_net) &&
    Array.isArray(value.official_concerns) &&
    value.official_concerns.every((item) => typeof item === "string") &&
    Array.isArray(value.scrubcast_24h) &&
    value.scrubcast_24h.every(isAuditRule) &&
    ["launched", "launched_later", "new_t0_pending", "hold", "unknown"].includes(
      String(value.outcome),
    ) &&
    (value.net_now === undefined || value.net_now === null || isTimestamp(value.net_now)) &&
    (value.note === undefined ||
      value.note === null ||
      (isRecord(value.note) &&
        isTimestamp(value.note.created_on) &&
        typeof value.note.text === "string"))
  );
}

function isLaunchSummary(value: unknown): value is LaunchSummary {
  if (!isRecord(value)) return false;
  const pad = value.pad;
  const mission = value.mission;
  return (
    typeof value.assessment === "boolean" &&
    ["id", "launch_service_provider_name", "name", "page_url", "rocket_name", "slug"].every(
      (key) => typeof value[key] === "string",
    ) &&
    [value.net, value.last_updated, value.window_start, value.window_end].every(isTimestamp) &&
    isNullableString(value.net_precision) &&
    isNullableString(value.weather_concerns) &&
    (value.probability === null ||
      (isFiniteNumber(value.probability) && value.probability >= 0 && value.probability <= 100)) &&
    typeof value.status === "string" &&
    [
      "Go",
      "TBD",
      "Success",
      "Failure",
      "Hold",
      "In Flight",
      "Partial Failure",
      "TBC",
      "Payload Deployed",
    ].includes(value.status) &&
    (value.tier === "A" || value.tier === "B" || value.tier === "C") &&
    isRecord(pad) &&
    isFiniteNumber(pad.id) &&
    isFiniteNumber(pad.latitude) &&
    isFiniteNumber(pad.longitude) &&
    typeof pad.name === "string" &&
    isRecord(pad.location) &&
    isFiniteNumber(pad.location.id) &&
    typeof pad.location.name === "string" &&
    typeof pad.location.timezone_name === "string" &&
    (mission === null ||
      (isRecord(mission) &&
        (mission.orbit === null ||
          (isRecord(mission.orbit) && typeof mission.orbit.abbrev === "string")))) &&
    isWorstRule(value.worst_rule)
  );
}

export function isLatest(value: unknown): value is Latest {
  return (
    hasSupportedSchema(value) &&
    isTimestamp(value.generated_at) &&
    typeof value.schedule_stale === "boolean" &&
    isFiniteNumber(value.members_total) &&
    Number.isInteger(value.members_total) &&
    value.members_total >= 0 &&
    Array.isArray(value.launches) &&
    value.launches.every(isLaunchSummary)
  );
}

export function isPast(value: unknown): value is Past {
  return (
    isRecord(value) &&
    Array.isArray(value.launches) &&
    isLatest({ ...value, schedule_stale: false, members_total: 0 }) &&
    value.launches.every(
      (launch) =>
        isLaunchSummary(launch) &&
        (launch.audit === undefined ||
          (Array.isArray(launch.audit) && launch.audit.every(isAuditFooter))),
    )
  );
}

export class DataError extends Error {
  readonly messageKey: "dataFetchFailed" | "unsupportedSchema" | "invalidData";
  readonly version: string | undefined;
  readonly builtAt: string | undefined;

  constructor(
    messageKey: "dataFetchFailed" | "unsupportedSchema" | "invalidData",
    options?: ErrorOptions & { version?: string; builtAt?: string },
  ) {
    super(messages[messageKey].what, options);
    this.messageKey = messageKey;
    this.version = options?.version;
    this.builtAt = options?.builtAt;
    this.name = "DataError";
  }
}

/** Read a versioned data file beneath the deployed site base. */
export async function fetchData<T>(
  file: string,
  guard: (value: unknown) => value is T,
  {
    base = import.meta.env.BASE_URL,
    fetcher = fetch,
  }: { base?: string; fetcher?: typeof fetch } = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetcher(routeHref(`data/${file}`, base));
  } catch (cause) {
    throw new DataError("dataFetchFailed", { cause });
  }
  if (!response.ok) throw new DataError("dataFetchFailed");
  let value: unknown;
  try {
    value = await response.json();
  } catch (cause) {
    throw new DataError("invalidData", { cause });
  }
  const builtAt =
    isRecord(value) && isTimestamp(value.generated_at) ? value.generated_at : undefined;
  if (!hasSupportedSchema(value)) {
    const version =
      isRecord(value) &&
      (typeof value.schema_version === "number" || typeof value.schema_version === "string")
        ? String(value.schema_version)
        : "missing";
    throw new DataError("unsupportedSchema", { version, ...(builtAt && { builtAt }) });
  }
  if (!guard(value)) throw new DataError("invalidData", builtAt ? { builtAt } : undefined);
  return value;
}

export type FeaturedLaunch =
  | { kind: "tierA"; launch: LaunchSummary }
  | { kind: "fallback"; launch: LaunchSummary; message: typeof messages.noTierA }
  | { kind: "empty"; message: typeof messages.noLaunches };

export function nextFeatured(latest: Latest, now: Date): FeaturedLaunch {
  const featured = latest.launches.find(
    (launch) =>
      launch.tier === "A" &&
      launch.assessment &&
      Date.parse(launch.net) > now.getTime() - FEATURED_GRACE_MS,
  );
  if (featured) return { kind: "tierA", launch: featured };
  const launch = latest.launches
    .filter((launch) => Date.parse(launch.net) >= now.getTime())
    .sort((a, b) => Date.parse(a.net) - Date.parse(b.net))[0];
  return launch
    ? { kind: "fallback", launch, message: messages.noTierA }
    : { kind: "empty", message: messages.noLaunches };
}
