import { element, link } from "../dom";
import {
  countdown,
  launchTitle,
  padLocalDate,
  padLocalTime,
  utcSchedule,
  utcTime,
} from "../format";
import { messages, siteCopy } from "../messages";
import { routeHref } from "../router";
import type { Latest, LaunchSummary } from "../types";
import { publicationState } from "./state";

const HORIZON_MS = 10 * 24 * 60 * 60 * 1000;

export function upcomingLaunches(latest: Latest, now: Date): LaunchSummary[] {
  const start = now.getTime();
  return latest.launches
    .filter((launch) => {
      const net = Date.parse(launch.net);
      return net >= start && net <= start + HORIZON_MS;
    })
    .sort((a, b) => Date.parse(a.net) - Date.parse(b.net));
}

export function launchSchedule(launch: LaunchSummary): string {
  const net = new Date(launch.net);
  const zone = launch.pad.location.timezone_name;
  return zone
    ? `${padLocalDate(net, zone)}, ${padLocalTime(net, zone)} / ${utcSchedule(net, zone)}`
    : `${padLocalDate(net, "UTC")}, ${utcTime(net)}. Pad-local time not published`;
}

export function scheduleNotice(latest: Latest): HTMLElement | null {
  if (!latest.schedule_stale) return null;
  const launch = [...latest.launches].sort((a, b) => Date.parse(a.net) - Date.parse(b.net))[0];
  return publicationState(messages.scheduleStale, {
    launch_url: launch
      ? `https://ll.thespacedevs.com/2.4.0/launches/${encodeURIComponent(launch.id)}/`
      : "https://thespacedevs.com/llapi",
  });
}

export function recordingNotice(latest: Latest): HTMLElement | null {
  return import.meta.env.DEV
    ? element("p", `Recorded demo. Schedule shown as of ${latest.generated_at}.`, "notice")
    : null;
}

export function renderHome(app: HTMLElement, latest: Latest, now: Date): void {
  performance.mark("home-render-start");
  const launches = upcomingLaunches(latest, now);
  const introduction = element("header", "", "home-intro");
  introduction.append(
    element("h1", "Upcoming launches"),
    element("p", `Next 10 days. ${siteCopy.description}`, "introduction"),
    element("p", "Model member shares are not launch probabilities.", "meta"),
  );
  app.replaceChildren(introduction);
  const recording = recordingNotice(latest);
  if (recording) app.prepend(recording);
  const stale = scheduleNotice(latest);
  if (stale) app.append(stale);
  if (!launches.length) app.append(publicationState(messages.noLaunches));
  else {
    const list = element("ol", "", "launch-list");
    list.setAttribute("aria-label", "Upcoming launches");
    for (const [index, launch] of launches.entries()) {
      const row = element("li", "", `launch-row schedule${index === 0 ? " lead-launch" : ""}`);
      row.dataset.launchId = launch.id;
      const time = element("time", countdown(new Date(launch.net), now), "countdown meta value");
      time.dateTime = launch.net;
      if (index === 0) time.prepend(element("span", "Next launch", "badge"));
      const content = element("div", "", "mission");
      const title = element("h2");
      title.append(link(launch.name, routeHref(`launch/${encodeURIComponent(launch.id)}/`)));
      const status = element("div", "", "launch-status schedule");
      status.append(
        element("span", `Tier ${launch.tier}`, "tier-label meta"),
        element("span", launch.worst_rule.label, "weather-finding"),
      );
      content.append(
        title,
        element("p", `${launch.pad.name}, ${launch.pad.location.name}`, "meta"),
        element("p", launchSchedule(launch), "meta value"),
        status,
      );
      if (index === 0 && launch.probability !== null) {
        const forecast = element("p", "", "lead-forecast");
        forecast.append(
          element("span", `${launch.probability}%`, "lead-probability"),
          " Official probability of GO",
        );
        content.insertBefore(forecast, status);
      }
      row.append(time, content);
      list.append(row);
    }
    app.append(list);
  }
  document.title = "Upcoming launches | Scrubcast";
  performance.measure("home-render", "home-render-start");
}

export function renderLaunchSummary(app: HTMLElement, launch: LaunchSummary): void {
  app.replaceChildren(
    element("h1", launchTitle(launch.name)),
    element("p", `${launch.pad.name}, ${launch.pad.location.name}`, "meta"),
    element("p", launchSchedule(launch), "meta value"),
    element("p", launch.worst_rule.label, "introduction"),
  );
  document.title = `${launch.name} | Scrubcast`;
}
