import { reliabilityChart } from "../charts/reliability";
import { element, link } from "../dom";
import { percent, utcTime } from "../format";
import { routeHref } from "../router";
import { scrollableTable } from "../table";
import type {
  AttemptEvaluation,
  AuditMetric,
  Evaluation1 as Evaluation,
  Hindcast,
  LowestHourEvaluation,
} from "../types";

const INSUFFICIENT = "insufficient data";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isHindcast(value: unknown): value is Hindcast {
  return (
    isRecord(value) &&
    value.schema_version === 1 &&
    typeof value.generated_at === "string" &&
    Number.isFinite(Date.parse(value.generated_at)) &&
    (value.lowest_hour_verified === undefined || typeof value.lowest_hour_verified === "boolean") &&
    (value.summary === undefined ||
      (Array.isArray(value.summary) && value.summary.every((item) => typeof item === "string"))) &&
    (value.forecast_audit === undefined ||
      value.forecast_audit === null ||
      isRecord(value.forecast_audit))
  );
}

function intervalText(interval: [unknown, unknown] | null | undefined, n: number): string {
  if (!interval) return "not estimated";
  return `[${Number(interval[0]).toFixed(3)}, ${Number(interval[1]).toFixed(3)}] (n=${n})`;
}

function metricText(metric: AuditMetric): string {
  if (metric.sufficient === false || metric.value === null || metric.value === undefined) {
    return `${INSUFFICIENT} (n=${metric.n})`;
  }
  const value = metric.label.includes("%")
    ? `${Math.round(metric.value)}%`
    : metric.value.toFixed(2);
  const unit = metric.label.includes("CRPS (m/s)") ? " m/s" : "";
  return `${value}${unit} (n=${metric.n})`;
}

function metricRow(metric: AuditMetric): HTMLTableRowElement {
  const row = element("tr");
  row.dataset.metric = metric.label;
  row.append(element("th", metric.label));
  row.firstElementChild?.setAttribute("scope", "row");
  row.append(
    element("td", metricText(metric)),
    element("td", `n=${metric.n}`),
    element(
      "td",
      metric.baseline === null || metric.baseline === undefined
        ? `insufficient data (n=${metric.n})`
        : metricText({ ...metric, value: metric.baseline, sufficient: true }),
    ),
    element("td", intervalText(metric.interval, metric.n)),
  );
  return row;
}

function summaryText(text: string): string {
  return text.replace(
    /(-?\d+(?:\.\d+)?)(%?) (?=\(n=)/g,
    (_, value: string, unit: string) =>
      `${unit ? Math.round(Number(value)) : Number(value).toFixed(2)}${unit} `,
  );
}

function evaluationSection(evaluation: Evaluation): HTMLElement {
  const section = element("section", "", "evaluation");
  const heading = element("h2", evaluation.title);
  heading.id = `audit-${evaluation.key}`;
  section.setAttribute("aria-labelledby", heading.id);
  section.append(heading, element("p", evaluation.label, "meta"));
  const table = element("table", "", "audit-table");
  table.append(element("caption", summaryText(evaluation.summary)));
  const head = table.createTHead().insertRow();
  for (const label of ["Metric", "Value", "n", "Baseline", "95% interval"]) {
    const cell = element("th", label);
    cell.scope = "col";
    head.append(cell);
  }
  const body = table.createTBody();
  for (const metric of evaluation.rows) body.append(metricRow(metric));
  const scroll = scrollableTable(table, "Scrollable audit table");
  section.append(scroll);
  if (evaluation.rank_histograms) {
    for (const [model, histogram] of Object.entries(evaluation.rank_histograms))
      section.append(
        element(
          "p",
          `${model} rank histogram (n=${histogram.reduce((total, count) => total + count, 0).toFixed(0)}): ${histogram.map((count) => count.toFixed(2)).join(", ")}`,
        ),
      );
  } else {
    section.append(element("p", `Rank histogram ${INSUFFICIENT} (n=${evaluation.n})`));
  }
  if (evaluation.reliability) {
    section.append(reliabilityChart(evaluation.reliability, evaluation.n));
  } else {
    section.append(element("p", `Reliability table ${INSUFFICIENT} (n=${evaluation.n})`));
  }
  return section;
}

function attemptsSection(attempts: AttemptEvaluation): HTMLElement {
  const section = element("section", "", "attempts");
  section.setAttribute("aria-labelledby", "audit-attempts-title");
  const heading = element("h2", "Attempt outcomes");
  heading.id = "audit-attempts-title";
  section.append(heading, element("p", attempts.label, "meta"));
  if (attempts.message) {
    section.append(element("p", attempts.message));
  } else if (attempts.auc !== null && attempts.auc !== undefined) {
    const interval = intervalText(attempts.interval, attempts.n);
    section.append(
      element("p", `AUC ${attempts.auc.toFixed(3)} (n=${attempts.n}); 95% interval ${interval}.`),
    );
  }
  section.append(
    element(
      "p",
      `Attempts n=${attempts.n}; launched n=${attempts.launched}; did not launch n=${attempts.not_launched}; unknown n=${attempts.unknown}.`,
      "meta",
    ),
  );
  const table = element("table", "", "audit-attempts");
  table.append(element("caption", `Audited attempts (n=${attempts.n})`));
  const head = table.createTHead().insertRow();
  for (const label of [
    "Attempt",
    "Scrubcast union risk at 24 h",
    "Official GO",
    "Outcome",
    "LL2 note",
  ]) {
    const cell = element("th", label);
    cell.scope = "col";
    head.append(cell);
  }
  const body = table.createTBody();
  for (const row of attempts.rows) {
    const item = body.insertRow();
    item.dataset.attemptId = row.attempt_id;
    item.append(
      element("th", `${row.attempt_id}, ${utcTime(new Date(row.net))}`),
      element(
        "td",
        row.union_risk === null
          ? `${INSUFFICIENT} (n=${attempts.n})`
          : `${percent(row.union_risk)} (n=${attempts.n})`,
      ),
      element(
        "td",
        row.official_go_pct === null
          ? `${INSUFFICIENT} (n=${attempts.n})`
          : `${row.official_go_pct}% (n=${attempts.n})`,
      ),
      element("td", row.outcome.replaceAll("_", " ")),
      element("td", row.note ?? ""),
    );
    item.firstElementChild?.setAttribute("scope", "row");
  }
  const scroll = scrollableTable(table, "Scrollable audit table");
  section.append(scroll);
  return section;
}

function lowestHourSection(lowest: LowestHourEvaluation): HTMLElement {
  const section = element("section", "", "lowest-hour");
  section.setAttribute("aria-labelledby", "audit-lowest-title");
  const heading = element("h2", "Lowest-risk hour");
  heading.id = "audit-lowest-title";
  const n = `(n=${lowest.n})`;
  section.append(
    heading,
    element("p", lowest.label, "meta"),
    element(
      "p",
      `Union risk at the marked hour ${lowest.risk_at_lowest === null ? "not estimated" : percent(lowest.risk_at_lowest)} ${n}, at T-0 ${lowest.risk_at_t0 === null ? "not estimated" : percent(lowest.risk_at_t0)} ${n}.`,
    ),
    element(
      "p",
      `Observed precipitation event rate at the marked hour ${lowest.precipitation_at_lowest === null ? "not estimated" : percent(lowest.precipitation_at_lowest)} ${n}, at T-0 ${lowest.precipitation_at_t0 === null ? "not estimated" : percent(lowest.precipitation_at_t0)} ${n}.`,
    ),
    element(
      "p",
      lowest.interval === null
        ? `${INSUFFICIENT} ${n}`
        : `Difference ${lowest.difference === null ? "not estimated" : lowest.difference.toFixed(3)} ${n}, 95% interval ${intervalText(lowest.interval, lowest.n)}.`,
    ),
    element(
      "p",
      lowest.verified
        ? `Lowest hour verified against observed precipitation ${n}.`
        : `Lowest hour not verified against observed precipitation ${n}.`,
      "badge",
    ),
  );
  return section;
}

export function renderAudit(app: HTMLElement, hindcast: Hindcast): void {
  const heading = element("h1", "Forecast audit");
  const generated = `Generated ${utcTime(new Date(hindcast.generated_at))} on ${hindcast.generated_at.slice(0, 10)}.`;
  const audit = hindcast.forecast_audit;
  app.replaceChildren(heading, element("p", generated, "meta"));
  if (!audit) {
    app.append(
      element(
        "p",
        `No forward audit yet (n=0). Scrubcast keeps the forecast audit separate from the retrospective checks.`,
      ),
      link("Return to the launch list", routeHref("")),
    );
    document.title = "Forecast audit | Scrubcast";
    return;
  }
  const summary = hindcast.summary?.length
    ? hindcast.summary
    : audit.evaluations.map((evaluation) => evaluation.summary);
  const summarySection = element("section", "", "audit-summary");
  summarySection.setAttribute("aria-labelledby", "audit-summary-title");
  const summaryHeading = element("h2", "Summary");
  summaryHeading.id = "audit-summary-title";
  const list = element("ul");
  for (const line of summary) list.append(element("li", summaryText(line)));
  summarySection.append(summaryHeading, list);
  app.append(summarySection);
  for (const evaluation of audit.evaluations) app.append(evaluationSection(evaluation));
  app.append(attemptsSection(audit.attempts), lowestHourSection(audit.lowest_hour));
  app.append(
    element(
      "p",
      "Official concerns are another forecast, not observed truth. Agreement with them is an agreement measure, not an outcome check. The lowest-hour check is against observed precipitation only, not cloud or wind.",
      "source-note",
    ),
  );
  document.title = "Forecast audit | Scrubcast";
}
