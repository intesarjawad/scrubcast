import { element } from "../dom";
import { memberPercent, padLocalDate, padLocalTime, utcTime } from "../format";
import { models } from "../launch-data";
import type { LaunchAssessment, RuleRisk } from "../types";
import { hourEvidence, type Model, scrubberHours } from "./scrubber-data";
import { scrubberPlot } from "./scrubber-plot";

const ANNOUNCE_INTERVAL_MS = 250;
const INITIAL_WIDTH_PX = 358;

function evidenceTable(rule: RuleRisk, zone: string): HTMLDetailsElement {
  const details = element("details");
  details.append(element("summary", "Each hour in figures"));
  const table = element("table", "", "rule-board hour-table");
  table.append(element("caption", `${rule.title}: hourly member evidence`));
  const head = table.createTHead().insertRow();
  for (const label of ["Pad local / UTC", "ECMWF", "GFS"]) {
    const th = element("th", label);
    th.scope = "col";
    head.append(th);
  }
  const body = table.createTBody();
  for (const [hour, timestamp] of rule.hours.entries()) {
    const row = body.insertRow();
    const date = new Date(timestamp);
    const th = element("th", padLocalTime(date, zone));
    th.scope = "row";
    th.append(element("span", utcTime(date), "badge"));
    row.append(th);
    for (const model of models) {
      const evidence = hourEvidence(rule, model, hour);
      row.insertCell().append(evidence.count, element("span", evidence.risk, "badge"));
    }
  }
  details.append(table);
  return details;
}

export function windowScrubber(assessment: LaunchAssessment, rule: RuleRisk, signal: AbortSignal) {
  const zone = assessment.launch.pad.location.timezone_name;
  const hours = scrubberHours(rule, zone);
  const root = element("div", "", "window-scrubber");
  const inspection = element("div", "", "inspection");
  const choice = element("p", "Read the members of ", "models");
  choice.setAttribute("role", "group");
  choice.setAttribute("aria-label", "Inspect model");
  let model: Model = "ecmwf";
  let hour = Math.min(assessment.t0_index, Math.max(0, hours.length - 1));
  const buttons = models.map((name) => {
    const button = element("button", name.toUpperCase(), "rule-pick");
    button.type = "button";
    button.setAttribute("aria-pressed", String(name === model));
    button.addEventListener(
      "click",
      () => {
        model = name;
        for (const other of buttons) other.setAttribute("aria-pressed", String(other === button));
        update();
      },
      { signal },
    );
    return button;
  });
  choice.append(buttons[0] ?? "", " or ", buttons[1] ?? "", ". Both share one time axis.");
  inspection.append(choice);
  const annotations = element("div", "", "annotation-lane");
  const windowStart = new Date(assessment.launch.window_start);
  const windowEnd = new Date(assessment.launch.window_end);
  const startDate = padLocalDate(windowStart, zone);
  const endDate = padLocalDate(windowEnd, zone);
  // A window that crosses pad-local midnight needs both dates to stay unambiguous.
  const windowLabel =
    startDate === endDate
      ? `Window ${padLocalTime(windowStart, zone)} to ${padLocalTime(windowEnd, zone)}`
      : `Window ${padLocalTime(windowStart, zone)} to ${padLocalTime(windowEnd, zone)} (${startDate} to ${endDate})`;
  const window = element("span", windowLabel);
  window.append(element("small", `${utcTime(windowStart)} to ${utcTime(windowEnd)}`));
  annotations.append(window);
  const figure = element("figure");
  const wrap = element("div", "", "plot-wrap");
  let plot = scrubberPlot(assessment, rule, INITIAL_WIDTH_PX);
  const input = element("input", "", "cursor-control");
  input.type = "range";
  input.min = "0";
  input.max = String(Math.max(0, hours.length - 1));
  input.step = "1";
  input.value = String(hour);
  input.disabled = hours.length === 0;
  input.setAttribute("aria-label", "Selected hour");
  input.setAttribute("aria-describedby", "keyboard-hint");
  wrap.append(plot.svg, input);
  const status = element("div", "", "readout");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.setAttribute("aria-atomic", "true");
  const local = element("span", "", "readout-local");
  const localText = document.createTextNode("");
  local.append(localText);
  const readout = element("span");
  const readoutText = document.createTextNode("");
  readout.append(readoutText);
  status.append(local, readout);
  figure.append(status, annotations, wrap);
  const notes = element("div", "", "chart-notes");
  notes.append(element("p", "Thick red traces flag the rule."));
  const lowest = assessment.lowest_union_hour;
  notes.append(
    element(
      "p",
      lowest
        ? `Lowest modelled risk in the window: ${utcTime(new Date(lowest.hour))} (${memberPercent(lowest.union_risk)} of members, ${lowest.members_below_t0} fewer than at T-0). ${assessment.lowest_hour_verified ? "Verified against observed precipitation only." : "Modelled, not yet verified against observed precipitation."}`
        : "No materially lower hour established",
    ),
  );
  const hint = element(
    "p",
    "Arrow keys: step an hour. Home / End: first / last hour.",
    "keyboard-hint",
  );
  hint.id = "keyboard-hint";
  root.append(inspection, figure, notes, hint, evidenceTable(rule, zone));
  let lastAnnouncement = -Infinity;
  let pending: ReturnType<typeof setTimeout> | undefined;
  function announce() {
    pending = undefined;
    const selected = hours[hour];
    if (!selected) {
      readoutText.nodeValue = "Hourly evidence unavailable";
      return;
    }
    localText.nodeValue = `At ${selected.local} / ${selected.utc}`;
    readoutText.nodeValue = selected.byModel[model]?.readout ?? "Hourly evidence unavailable";
    readout.className = selected.byModel[model]?.violated ? "signal" : "";
    lastAnnouncement = performance.now();
  }
  function update() {
    const selected = hours[hour];
    if (selected) {
      plot.update(hour, selected.local, selected.utc);
      input.setAttribute("aria-valuetext", `${selected.local} / ${selected.utc}`);
    }
    const delay = Math.max(0, ANNOUNCE_INTERVAL_MS - (performance.now() - lastAnnouncement));
    if (pending !== undefined) clearTimeout(pending);
    if (delay === 0) announce();
    else pending = setTimeout(announce, delay);
  }
  input.addEventListener(
    "input",
    () => {
      hour = Number(input.value);
      update();
    },
    { signal },
  );
  // The visible handle accepts pointer input while the native range keeps keyboard semantics.
  function point(event: PointerEvent) {
    const box = plot.svg.getBoundingClientRect();
    const pane = plot.svg.querySelector<SVGGElement>(".model-pane");
    const left = Number(pane?.dataset.plotLeft);
    const right = Number(pane?.dataset.plotRight);
    const fraction = (event.clientX - box.left - left) / (right - left);
    hour = Math.max(0, Math.min(hours.length - 1, Math.round(fraction * (hours.length - 1))));
    input.value = String(hour);
    update();
  }
  wrap.addEventListener(
    "pointerdown",
    (event) => {
      if (!hours.length) return;
      wrap.setPointerCapture(event.pointerId);
      input.focus({ preventScroll: true });
      point(event);
    },
    { signal },
  );
  wrap.addEventListener(
    "pointermove",
    (event) => {
      if (wrap.hasPointerCapture(event.pointerId)) point(event);
    },
    { signal },
  );
  wrap.addEventListener(
    "pointerup",
    (event) => {
      if (wrap.hasPointerCapture(event.pointerId)) wrap.releasePointerCapture(event.pointerId);
    },
    { signal },
  );
  const observer = new ResizeObserver(([entry]) => {
    const width = Math.round(entry?.contentRect.width ?? INITIAL_WIDTH_PX);
    if (width <= 0) return;
    const replacement = scrubberPlot(assessment, rule, width);
    root.classList.toggle("compact", replacement.compact);
    plot.svg.replaceWith(replacement.svg);
    plot = replacement;
    const selected = hours[hour];
    if (selected) plot.update(hour, selected.local, selected.utc);
  });
  observer.observe(wrap);
  signal.addEventListener(
    "abort",
    () => {
      observer.disconnect();
      clearTimeout(pending);
    },
    { once: true },
  );
  update();
  return root;
}
