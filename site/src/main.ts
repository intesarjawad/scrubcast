import { DataError, fetchData, isLatest, isPast, nextFeatured, SCHEMA_VERSION } from "./data";
import { element } from "./dom";
import { isLaunchAssessment } from "./launch-data";
import { messages, siteCopy } from "./messages";
import { isCardRoute, resolveRoute } from "./router";
import type { Latest, LaunchAssessment, LaunchSummary, PastLaunch } from "./types";
import { isHindcast, renderAudit } from "./views/audit";
import { renderLaunchCard } from "./views/card";
import { recordingNotice, renderHome, renderLaunchSummary, scheduleNotice } from "./views/home";
import { renderLaunch, renderRetainedLaunch } from "./views/launch";
import { publicationState } from "./views/state";

const root = document.querySelector<HTMLElement>("#app");
if (root === null) throw new Error("The page must provide an app element.");
const app = root;
const route = resolveRoute(window.location.pathname);
const card = isCardRoute(route, window.location.search);
let lastBuild: string | undefined;
for (const link of document.querySelectorAll<HTMLAnchorElement>("nav a[data-route]")) {
  if (link.dataset.route === route.name) link.setAttribute("aria-current", "page");
}

function showMessage(message: (typeof messages)[keyof typeof messages]): void {
  app.replaceChildren(element("h1", siteCopy.title), publicationState(message));
}

function showAssessment(assessment: LaunchAssessment): void {
  if (card) {
    renderLaunchCard(app, assessment.launch, assessment);
    // Cards hide the second grid row, so the notes must occupy only the visible row.
    app.querySelector<HTMLElement>(".sheet-notes")?.style.setProperty("grid-row", "auto");
  } else {
    renderLaunch(app, assessment);
    if (assessment.refresh_deferred) {
      const fetched = Object.values(assessment.fetched_at)
        .filter((value): value is string => typeof value === "string")
        .sort();
      app.prepend(
        publicationState(messages.refreshDeferred, {
          forecast_at: fetched[0]
            ? new Date(fetched[0]).toISOString().slice(0, 16).replace("T", " ")
            : "unavailable",
        }),
      );
    }
  }
}

function showRetained(summary: PastLaunch): void {
  if (card) renderLaunchCard(app, summary);
  else renderRetainedLaunch(app, summary);
}

function showUnassessed(launch: LaunchSummary, latest: Latest): void {
  if (card) renderLaunchCard(app, launch);
  else {
    renderLaunchSummary(app, launch);
    if (launch.tier !== "C") {
      const horizon = new Date(latest.generated_at);
      horizon.setUTCDate(horizon.getUTCDate() + 10);
      app.append(
        publicationState(
          Date.parse(launch.window_end) > horizon.getTime()
            ? messages.beyondForecastRange
            : messages.pendingPublication,
        ),
      );
    }
  }
}

async function load(): Promise<void> {
  if (route.name === "notFound") {
    showMessage(messages.notFound);
    document.title = "Launch not found | Scrubcast";
    return;
  }
  if (route.name === "audit") {
    showMessage(messages.loading);
    renderAudit(app, await fetchData("hindcast.json", isHindcast));
    return;
  }
  showMessage(messages.loading);
  if (route.name === "home") {
    const latest = await fetchData("latest.json", isLatest);
    lastBuild = latest.generated_at;
    renderHome(app, latest, import.meta.env.DEV ? new Date(latest.generated_at) : new Date());
    return;
  }
  let id: string;
  let latest: Latest | undefined;
  let summary: LaunchSummary | undefined;
  let retainedLaunch: PastLaunch | undefined;
  let fallback = false;
  if (route.name === "next") {
    latest = await fetchData("latest.json", isLatest);
    lastBuild = latest.generated_at;
    const featured = nextFeatured(
      latest,
      import.meta.env.DEV ? new Date(latest.generated_at) : new Date(),
    );
    if (featured.kind === "empty") {
      showMessage(featured.message);
      return;
    }
    id = featured.launch.id;
    summary = featured.launch;
    fallback = featured.kind === "fallback";
  } else id = route.id;
  const inline = document.querySelector("#first-paint")?.textContent;
  let painted = false;
  if (inline && !card) {
    try {
      const value: unknown = JSON.parse(inline);
      if (isLaunchAssessment(value) && value.launch.id === id) {
        showAssessment(value);
        painted = true;
      }
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
    }
  }
  if (!painted || card) {
    latest ??= await fetchData("latest.json", isLatest);
    lastBuild = latest.generated_at;
    summary ??= latest.launches.find((launch) => launch.id === id);
    if (!summary) {
      const past = await fetchData("past.json", isPast);
      retainedLaunch = past.launches.find((launch) => launch.id === id);
      summary = retainedLaunch;
    }
    if (!summary) {
      showMessage(messages.notFound);
      return;
    }
  }
  if (retainedLaunch) showRetained(retainedLaunch);
  else if (summary && !summary.assessment && latest) showUnassessed(summary, latest);
  else {
    const assessment = await fetchData(
      `launches/${encodeURIComponent(id)}.json`,
      isLaunchAssessment,
    );
    if (assessment.launch.id !== id) throw new DataError("invalidData");
    showAssessment(assessment);
  }
  if (!card) {
    if (latest) {
      const stale = scheduleNotice(latest);
      if (stale) app.prepend(stale);
      const recording = recordingNotice(latest);
      if (recording) app.prepend(recording);
    }
    if (fallback) app.prepend(publicationState(messages.noTierA));
  }
}

void load().catch((error: unknown) => {
  const message = error instanceof DataError ? messages[error.messageKey] : messages.invalidData;
  const state = publicationState(message, {
    version: error instanceof DataError ? (error.version ?? "missing") : "missing",
    supported: String(SCHEMA_VERSION),
  });
  const builtAt = (error instanceof DataError ? error.builtAt : undefined) ?? lastBuild;
  if (builtAt) state.append(element("p", `Last build: ${builtAt}.`));
  const loading = app.querySelector('[role="status"]');
  if (loading?.classList.contains("notice")) loading.replaceWith(state);
  else app.append(state);
});
