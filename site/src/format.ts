const MINUTE_MS = 60_000;
const MINUTES_PER_HOUR = 60;

/** Launch Library writes "Vehicle | Mission"; the bar is its field separator, not punctuation. */
export function launchTitle(name: string): string {
  return name.replace(" | ", ", ");
}

/** Typesets a negative figure with a real minus sign, which the sources write as a hyphen. */
export function minusSign(text: string): string {
  return text.replace(/(^|[\s(])-(?=\d)/g, "$1\u2212");
}

/** Format a model member fraction, without changing its interpretation. */
export function percent(fraction: number): string {
  return new Intl.NumberFormat("en", { style: "percent", maximumFractionDigits: 0 }).format(
    fraction,
  );
}

export function memberPercent(fraction: number): string {
  return new Intl.NumberFormat("en", { style: "percent", maximumFractionDigits: 1 }).format(
    fraction,
  );
}

export function padLocalDate(date: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en", {
    timeZone,
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function utcTime(date: Date): string {
  return `${new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date)} UTC`;
}

export function utcSchedule(date: Date, timeZone: string): string {
  const utcDate = padLocalDate(date, "UTC");
  return `${utcDate === padLocalDate(date, timeZone) ? "" : `${utcDate}, `}${utcTime(date)}`;
}

/** Use the pad's IANA time zone so historical DST offsets stay correct. */
export function padLocalTime(date: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZoneName: "short",
  }).format(date);
}

export function countdown(net: Date, now: Date): string {
  const minutes = Math.max(0, Math.floor((net.getTime() - now.getTime()) / MINUTE_MS));
  return `in ${Math.floor(minutes / MINUTES_PER_HOUR)} h ${minutes % MINUTES_PER_HOUR} m`;
}
