import { sheetSpread } from "../charts/sheet";
import { element } from "../dom";
import { launchTitle } from "../format";
import { sortedRules } from "../launch-data";
import { cardSchedule } from "../share-card";
import type { Launch, LaunchAssessment } from "../types";
import { launchHeader, sheetFacts, verdictLine } from "./launch";

export function renderLaunchCard(
  app: HTMLElement,
  launch: Launch,
  assessment?: LaunchAssessment,
): void {
  const zone = launch.pad.location.timezone_name || "UTC";
  document.body.classList.add("card-page");
  document.title = `${launch.name} | Scrubcast`;
  if (assessment?.rules.length) {
    // The share card is the finished sheet itself, printed without a GPU so every build matches.
    const intro = launchHeader(launch);
    intro.prepend(element("p", "Scrubcast", "wordmark"));
    const spread = sheetSpread(
      assessment,
      {
        intro,
        facts: sheetFacts(assessment, sortedRules(assessment), zone, false),
      },
      {
        signal: new AbortController().signal,
        still: true,
        onPrinted: () => {
          app.dataset.cardReady = launch.id;
        },
      },
    );
    // The card has no room for the legend; its right column carries the verdict instead.
    spread
      .querySelector(".sheet-legend")
      ?.replaceWith(element("p", verdictLine(sortedRules(assessment)), "card-verdict"));
    app.replaceChildren(spread);
    return;
  }
  const schedule = cardSchedule(launch);
  const header = element("header", "", "card-header");
  const mission = element("div");
  mission.append(
    element("h1", launchTitle(launch.name)),
    element("p", `${launch.pad.name} / ${schedule.date}`, "card-meta"),
  );
  const official = element("div", "", "card-official");
  const probability = launch.probability;
  if (probability !== null) {
    const number = element("div", String(probability), "number");
    number.append(element("small", "%"));
    official.append(number, element("p", "Official probability of GO"));
  } else official.append(element("p", "No official forecast published"));
  header.append(mission, official);
  const timing = element("section", "", "card-schedule card-statement");
  timing.append(element("p", "T-0"));
  if (schedule.localTime) {
    timing.append(
      element("h2", `${schedule.date} / ${schedule.localTime}`),
      element("h2", `${schedule.utcDate} / ${schedule.utcTime}`),
    );
  } else {
    timing.append(
      element("h2", `${schedule.utcDate} / ${schedule.utcTime}`),
      element("p", "Pad-local time not published", "card-meta"),
    );
  }
  timing.append(element("p", "Scrubcast does not model weather rules for this pad yet."));
  const footer = element("footer", "", "card-footer");
  footer.append(element("p", "Schedule via Launch Library 2", "card-source"));
  app.replaceChildren(header, timing, footer);
  app.dataset.cardReady = launch.id;
}
