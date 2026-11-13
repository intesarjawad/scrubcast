import { windowScrubber } from "../charts/scrubber";
import { sheetSpread } from "../charts/sheet";
import {
  localTime,
  membersBreaking,
  openingRules,
  peakHour,
  SHORT_NAMES,
} from "../charts/sheet-data";
import { fetchData } from "../data";
import { element, link } from "../dom";
import {
  launchTitle,
  memberPercent,
  padLocalDate,
  padLocalTime,
  utcSchedule,
  utcTime,
} from "../format";
import { launchComparison, ruleNote } from "../launch-comparison";
import {
  confidenceLabel,
  memberCount,
  modelAgreement,
  models,
  officialConcern,
} from "../launch-data";
import { routeHref } from "../router";
import type { AuditFooter, Launch, LaunchAssessment, PastLaunch, RuleRisk } from "../types";
import { isHindcast } from "./audit";

const OUTCOME_ABSENT = "unknown";

function outcomeText(footer: AuditFooter): string {
  const when =
    footer.net_now === null
      ? "at an unrecorded time"
      : `at ${footer.net_now.slice(0, 10)} ${footer.net_now.slice(11, 16)} UTC`;
  switch (footer.outcome) {
    case "launched":
      return "launched in the window";
    case "launched_later":
      return `did not launch in the window; launched later ${when}`;
    case "new_t0_pending":
      return `did not launch in the window; new T-0 pending ${when}`;
    case "hold":
      return "did not launch in the window; launch on hold";
    default:
      return OUTCOME_ABSENT;
  }
}

function auditFooters(audit: AuditFooter[]): HTMLElement | null {
  if (audit.length === 0) return null;
  const section = element("section", "", "audit-footers");
  section.setAttribute("aria-labelledby", "audit-footers-title");
  const title = element("h2", "What happened");
  title.id = "audit-footers-title";
  section.append(title);
  const footers = [...audit].sort(
    (left, right) => Date.parse(right.attempt_net) - Date.parse(left.attempt_net),
  );
  for (const footer of footers) {
    const concerns = footer.official_concerns.length ? footer.official_concerns.join(", ") : "none";
    const rules = footer.scrubcast_24h.length
      ? footer.scrubcast_24h
          .map((rule) => `${rule.title} ${Math.round(rule.risk_fraction * 100)}%`)
          .join(", ")
      : "no rule above zero";
    const item = element("article", "", "audit-footer");
    item.dataset.attemptId = footer.attempt_id;
    item.append(
      element(
        "p",
        `Official concerns: ${concerns}. Scrubcast at 24 h: ${rules}. Outcome: ${outcomeText(footer)}.`,
      ),
    );
    if (footer.note && footer.outcome !== "launched" && footer.outcome !== "unknown") {
      item.append(element("p", `LL2 note: ${footer.note.text}`, "meta"));
    }
    section.append(item);
  }
  return section;
}

function ruleName(rule: RuleRisk): string {
  return SHORT_NAMES[rule.rule_id] ?? rule.title;
}

/** Members breaking each rule at T-0, printed like the sheet; each rule name inspects that rule. */
function ruleBoard(rules: RuleRisk[], inspect: (rule: RuleRisk) => void): HTMLElement {
  const board = element("div", "", "board");
  const picks: HTMLButtonElement[] = [];
  const pick = (rule: RuleRisk) => {
    const button = element("button", ruleName(rule), "rule-pick");
    button.type = "button";
    button.dataset.ruleId = rule.rule_id;
    button.setAttribute("aria-pressed", String(rule === rules[0]));
    button.addEventListener("click", () => {
      for (const other of picks) other.setAttribute("aria-pressed", String(other === button));
      inspect(rule);
    });
    picks.push(button);
    return button;
  };
  const flagged = rules.filter((rule) =>
    models.some((model) => (rule.by_model[model]?.risk_fraction ?? 0) > 0),
  );
  const unavailable = rules.filter((rule) =>
    models.every((model) => rule.by_model[model]?.risk_fraction == null),
  );
  const clear = rules.filter((rule) => !flagged.includes(rule) && !unavailable.includes(rule));
  if (flagged.length) {
    const table = element("table", "", "rule-board launch-rules");
    table.append(element("caption", "Members breaking each rule at T-0"));
    const head = table.createTHead().insertRow();
    for (const label of ["Rule", "ECMWF", "GFS"]) {
      const th = element("th", label);
      th.scope = "col";
      head.append(th);
    }
    const body = table.createTBody();
    for (const rule of flagged) {
      const row = body.insertRow();
      row.dataset.ruleId = rule.rule_id;
      const name = element("th");
      name.scope = "row";
      name.append(pick(rule), element("span", confidenceLabel(rule), "badge"));
      if (rule.reference_only) name.append(element("span", "LLCC reference", "badge"));
      row.append(name);
      for (const model of models) {
        const risk = rule.by_model[model];
        row
          .insertCell()
          .append(
            risk === undefined || risk.risk_fraction === null
              ? "Not evaluable"
              : `${memberCount(risk)} of ${risk.evaluable_members}, ${memberPercent(risk.risk_fraction)}`,
          );
      }
    }
    board.append(table);
  }
  if (clear.length) {
    const reference = clear.every((rule) => rule.reference_only) ? "LLCC reference " : "";
    const line = element(
      "p",
      flagged.length
        ? `No evaluable member breaks the other ${reference}rules at T-0: `
        : `No evaluable member breaks any ${reference}rule at T-0: `,
      "board-clear",
    );
    for (const [index, rule] of clear.entries()) {
      const notes = models
        .filter((model) => (rule.by_model[model]?.risk_fraction ?? null) === null)
        .map((model) => `${model.toUpperCase()} cannot evaluate it`);
      if (rule.reference_only && !reference) notes.push("LLCC reference");
      line.append(index ? ", " : "", pick(rule));
      if (notes.length) line.append(` (${notes.join("; ")})`);
    }
    line.append(".");
    board.append(line);
  }
  if (unavailable.length) {
    const line = element("p", "Assessment not available at T-0: ", "board-unavailable");
    for (const [index, rule] of unavailable.entries()) line.append(index ? ", " : "", pick(rule));
    line.append(".");
    board.append(line);
  }
  return board;
}

function methods(rules: RuleRisk[]): HTMLDetailsElement {
  const details = element("details");
  details.id = "methods";
  details.append(element("summary", "Rule thresholds and approximation notes"));
  for (const [index, rule] of rules.entries()) {
    const heading = element("h3", rule.title);
    heading.id = `method-${index}`;
    const threshold = rule.threshold;
    const label =
      threshold === null
        ? "No resolved threshold."
        : `${threshold.comparator} ${threshold.value} ${threshold.unit}${rule.plot.origin === "scrub" ? " / Scrubcast stand-in" : ""}.`;
    details.append(
      heading,
      element("p", `${label} ${ruleNote(rule)}`),
      link(
        `Source standard${rule.llccr.length ? `, LLCCR ${rule.llccr.join(", ")}` : ""}`,
        rule.source_url,
      ),
    );
  }
  return details;
}

function officialBlock(probability: number | null, concern: string | null): HTMLElement | null {
  if (probability === null && concern === null) return null;
  return element(
    "p",
    `${probability === null ? "Official forecast" : `Official: ${probability}% probability of GO`}.${concern ? ` Concern: ${concern}.` : ""} Forecast via Launch Library 2.`,
    "official",
  );
}

function retainedOfficial(launch: PastLaunch): HTMLElement | null {
  const concern = launch.weather_concerns?.trim() ? launch.weather_concerns : null;
  return officialBlock(launch.probability, concern);
}

export function launchHeader(launch: Launch): HTMLElement {
  const zone = launch.pad.location.timezone_name;
  const net = new Date(launch.net);
  const intro = element("section", "", "intro");
  const schedule = element("div", "", "schedule");
  for (const text of [`${launch.pad.name}, ${launch.pad.location.name}`, padLocalDate(net, zone)])
    schedule.append(element("span", text));
  schedule.append(element("b", `T-0 ${padLocalTime(net, zone)} / ${utcSchedule(net, zone)}`));
  intro.append(element("h1", launchTitle(launch.name)), schedule);
  return intro;
}

/** Counted the way the verdict line counts: a member breaks a rule at any hour of the window. */
function breakingRules(rules: RuleRisk[]) {
  return rules
    .map((rule) => ({ rule, ...membersBreaking(rule) }))
    .filter((row) => row.broken > 0)
    .sort((a, b) => b.broken - a.broken);
}

/** The share card's one-line verdict: the most broken rule, or none. */
export function verdictLine(rules: RuleRisk[]): string {
  const [worst] = breakingRules(rules);
  const reference = rules.some((rule) => rule.reference_only) ? "Reference only: " : "";
  if (!rules.length || rules.every((rule) => membersBreaking(rule).of === 0))
    return `${reference}Rule assessment not available.`;
  if (!worst && rules.some((rule) => membersBreaking(rule).of === 0))
    return `${reference}Some rule assessments are not available.`;
  return (
    reference +
    (worst
      ? `${worst.broken} of ${worst.of} members break the ${ruleName(worst.rule).toLowerCase()} rule.`
      : `No evaluable member breaks any of the ${rules.length} rules.`)
  );
}

export function sheetFacts(
  assessment: LaunchAssessment,
  rules: RuleRisk[],
  zone: string,
  record = true,
): HTMLElement {
  const facts = element("dl", "", "sheet-facts");
  const add = (term: string, detail: string | HTMLElement) => {
    const dd = element("dd");
    dd.append(detail);
    facts.append(element("dt", term), dd);
    return dd;
  };
  const probability = assessment.official.probability_go_pct;
  const concern = officialConcern(assessment);
  add(
    "Official",
    `${probability === null ? "Not published" : `${probability}% probability of GO`}, via ${assessment.official.source ?? "Launch Library 2"}${concern ? `. Concern: ${concern}` : ""}`,
  );
  const breaking = breakingRules(rules);
  if (assessment.tier === "B")
    add(
      "Coverage",
      "Reference only: these rules are not established launch criteria for this pad.",
    );
  if (assessment.tier !== "C")
    add(
      "Breaking",
      rules.length === 0 || rules.every((rule) => membersBreaking(rule).of === 0)
        ? "Rule assessment not available"
        : breaking.length
          ? breaking
              .map(({ rule, broken, of }) => {
                const peak = rule.hours[peakHour(rule) ?? -1];
                return `${SHORT_NAMES[rule.rule_id] ?? rule.title} ${broken} of ${of}${peak ? ` (peak ${localTime(peak, zone)})` : ""}`;
              })
              .join(". ")
          : rules.some((rule) => membersBreaking(rule).of === 0)
            ? "Some rule assessments are not available"
            : `No evaluable member breaks any of the ${rules.length} rules`,
    );
  if (record) {
    const detail = add("Track record", link("Read the audit", routeHref("audit/")));
    void fetchData("hindcast.json", isHindcast)
      .then((hindcast) => {
        const scored = hindcast.forecast_audit?.n_launches ?? 0;
        detail.prepend(
          scored === 0 ? "No launch scored yet (n=0). " : `${scored} launches scored. `,
        );
      })
      .catch(() => undefined);
  }
  const fetched = Object.values(assessment.fetched_at)
    .filter((value): value is string => typeof value === "string")
    .sort()[0];
  if (fetched) {
    const at = new Date(fetched);
    add("Forecast", `Fetched ${padLocalDate(at, "UTC")}, ${utcTime(at)}`);
  }
  return facts;
}

export function renderLaunch(app: HTMLElement, assessment: LaunchAssessment): void {
  app.dispatchEvent(new Event("launch-replace"));
  const { launch } = assessment;
  const zone = launch.pad.location.timezone_name;
  const rules = assessment.tier === "C" ? [] : openingRules(assessment);
  const available = rules.some((rule) => membersBreaking(rule).of > 0);
  const top = rules[0];
  const press = new AbortController();
  app.addEventListener("launch-replace", () => press.abort(), { once: true });
  const intro = launchHeader(launch);
  const spread = sheetSpread(
    assessment,
    { intro, facts: sheetFacts(assessment, rules, zone) },
    { signal: press.signal },
  );
  const evidence = element("section", "", "evidence");
  evidence.setAttribute("aria-labelledby", "board-title");
  const heading = element(
    "h2",
    available && top ? modelAgreement(top) : "Rule methods and limitations",
    "signature-title",
  );
  heading.id = "board-title";
  if (assessment.tier === "B")
    evidence.append(
      element(
        "p",
        "Reference only: these rules are not established launch criteria for this pad.",
        "badge",
      ),
    );
  evidence.append(heading);
  if (available && top) {
    const chart = element("div");
    const proxy = element("p", "", "proxy");
    proxy.id = "method";
    let controller = new AbortController();
    function inspect(rule: RuleRisk) {
      heading.textContent = modelAgreement(rule);
      controller.abort();
      controller = new AbortController();
      chart.replaceChildren(windowScrubber(assessment, rule, controller.signal));
      proxy.replaceChildren(
        element("b", `${confidenceLabel(rule)}. `),
        `${ruleNote(rule)} Member shares are not launch probabilities.`,
      );
    }
    app.addEventListener("launch-replace", () => controller.abort(), { once: true });
    inspect(top);
    const concern = officialConcern(assessment);
    evidence.append(ruleBoard(rules, inspect));
    if (concern) evidence.append(element("p", launchComparison(assessment), "source-note"));
    evidence.append(chart, proxy);
  }
  if (!available && assessment.not_evaluable.length) {
    const limits = element("ul");
    for (const rule of assessment.not_evaluable)
      limits.append(element("li", `${rule.title}: ${rule.reason}`));
    evidence.append(limits);
  }
  evidence.append(methods(assessment.rules));
  const how = element("details");
  how.id = "how";
  how.append(
    element("summary", "How it works"),
    element(
      "p",
      "ECMWF and GFS members are evaluated against rule proxies. Member shares describe model agreement. The official forecast is reported separately.",
    ),
  );
  const provenance = element("details");
  provenance.id = "provenance";
  provenance.append(element("summary", "Data and provenance"));
  for (const model of models) {
    const at = assessment.fetched_at[model];
    provenance.append(
      element(
        "p",
        at
          ? `${model.toUpperCase()} weather fetched ${padLocalDate(new Date(at), zone)} at ${padLocalTime(new Date(at), zone)} / ${utcTime(new Date(at))}.`
          : `${model.toUpperCase()} fetch time unavailable.`,
      ),
    );
  }
  app.replaceChildren(spread);
  const happened = auditFooters(assessment.audit ?? []);
  app.append(evidence);
  if (happened) app.append(happened);
  app.append(how, provenance);
  document.body.classList.add("launch-page");
  document.title = `${launch.name} | Scrubcast`;
  const footer = document.querySelector(".site-footer");
  if (footer) {
    const nav = element("nav");
    nav.setAttribute("aria-label", "Open data and documentation");
    const json = link(
      "Per-launch JSON",
      routeHref(`data/launches/${encodeURIComponent(launch.id)}.json`),
    );
    json.download = `${launch.id}.json`;
    nav.append(
      link("How it works", "#how"),
      link("Method", "#methods"),
      link("Data", "#provenance"),
      link("Audit", routeHref("audit/")),
      json,
    );
    footer.replaceChildren(
      nav,
      element(
        "p",
        "Launch schedule and official forecast: Launch Library 2. Ensemble weather: Open-Meteo, ECMWF and NOAA GFS. Weather-derived commercial reuse requires an Open-Meteo plan.",
        "footer-notes",
      ),
      element("p", "Scrubcast is not the launch weather officer", "footer-notes"),
    );
  }
}

function retainedRisks(audit: AuditFooter[]): HTMLElement {
  const section = element("section", "", "retained-risks");
  section.setAttribute("aria-labelledby", "retained-risks-title");
  const title = element("h2", "Rule risks at 24 hours");
  title.id = "retained-risks-title";
  section.append(
    title,
    element(
      "p",
      "The final forecast before each attempt and the rule risks the models carried. Member forecasts and the hourly scrubber are not published for past launches.",
      "meta",
    ),
  );
  const footers = [...audit].sort(
    (left, right) => Date.parse(right.attempt_net) - Date.parse(left.attempt_net),
  );
  if (footers.length === 0) {
    section.append(element("p", "No audited attempt is recorded for this launch."));
    return section;
  }
  const list = element("ul");
  for (const footer of footers) {
    const concerns = footer.official_concerns.length ? footer.official_concerns.join(", ") : "none";
    const rules = footer.scrubcast_24h.length
      ? footer.scrubcast_24h
          .map((rule) => `${rule.title} ${Math.round(rule.risk_fraction * 100)}%`)
          .join(", ")
      : "no rule above zero";
    list.append(
      element(
        "li",
        `T-0 ${footer.attempt_net.slice(0, 10)} ${footer.attempt_net.slice(11, 16)} UTC. Official concerns: ${concerns}. Rule risks: ${rules}.`,
      ),
    );
  }
  section.append(list);
  return section;
}

export function renderRetainedLaunch(app: HTMLElement, launch: PastLaunch): void {
  app.dispatchEvent(new Event("launch-replace"));
  const audit = launch.audit ?? [];
  app.replaceChildren(launchHeader(launch));
  const forecast = retainedOfficial(launch);
  if (forecast) app.append(forecast);
  app.append(retainedRisks(audit));
  const happened = auditFooters(audit);
  if (happened) app.append(happened);
  app.append(
    element(
      "p",
      "This launch page is retained for 90 days after its scheduled T-0.",
      "source-note",
    ),
  );
  document.body.classList.add("launch-page");
  document.title = `${launch.name} | Scrubcast`;
}
