export interface SiteMessage {
  readonly what: string;
  readonly next: string;
}

export const messages = {
  loading: {
    what: "Loading launch data.",
    next: "Wait for the forecast, or return to {home_url}.",
  },
  pendingPublication: {
    what: "Launch weather assessments are pending publication.",
    next: "Return to {home_url} after the next publication.",
  },
  dataFetchFailed: {
    what: "Couldn't load launch data.",
    next: "Reload at {reload_url}; if it persists, return to {home_url}.",
  },
  unsupportedSchema: {
    what: "This data uses schema version {version}; Scrubcast supports version {supported}.",
    next: "Reload at {reload_url} to get the current site.",
  },
  invalidData: {
    what: "The published launch data could not be read.",
    next: "Reload at {reload_url}; if it persists, return to {home_url}.",
  },
  noTierA: {
    what: "No Florida or California launch in the next 10 days. Showing the next launch.",
    next: "Browse the full launch list at {home_url}.",
  },
  noLaunches: {
    what: "No orbital launches in the next 10 days.",
    next: "Read the forecast audit at {audit_url}.",
  },
  refreshDeferred: {
    what: "Forecast from {forecast_at} UTC; this refresh was deferred by the request budget or upstream rate limit.",
    next: "Check forecast fetch times at {operations_url}.",
  },
  scheduleStale: {
    what: "Launch Library 2 did not answer the last refresh. The launch schedule may be out of date.",
    next: "Check the published launch record at {launch_url}.",
  },
  beyondForecastRange: {
    what: "Rules appear about 10 days before launch. Forecast data for this window are not available yet.",
    next: "This page rebuilds hourly; subscribe at {calendar_url} to see it fill in.",
  },
  notFound: {
    what: "Launch not found or older than 90 days.",
    next: "Return to {home_url} or read the forecast audit at {audit_url}.",
  },
} as const satisfies Record<string, SiteMessage>;

export const siteCopy = {
  title: "Launch weather",
  description: "Read the official forecast alongside modelled weather rules, hour by hour.",
  homeLink: "the launch list",
  auditLink: "the audit",
} as const;
