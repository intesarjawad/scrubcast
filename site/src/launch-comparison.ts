import { SHORT_NAMES } from "./charts/sheet-data";
import { memberCount, models, officialConcern, sortedRules } from "./launch-data";
import type { LaunchAssessment, RuleRisk } from "./types";

/** Quote concerns verbatim and compare matching rules plus the leading T-0 finding. */
export function launchComparison(assessment: LaunchAssessment): string {
  const concern = officialConcern(assessment);
  const rules = sortedRules(assessment);
  const source = concern?.toLowerCase() ?? "";
  const matching = concern
    ? rules.filter((rule) => {
        const title = rule.title.toLowerCase().replace(/\s+rules?$/, "");
        return source.includes(title) || source.includes(rule.rule_id.replaceAll("_", " "));
      })
    : [];
  const top = rules[0];
  // The source wording is authoritative; normalised concern labels may include fallbacks.
  const selected = [...new Set([...matching, ...(top ? [top] : [])])];
  return [
    ...(concern ? [`Official concern: ${concern}${/[.!?]$/.test(concern) ? "" : "."}`] : []),
    ...selected.map((rule) => {
      const counts = models.map((model) => {
        const risk = rule.by_model[model];
        return risk?.risk_fraction == null
          ? `${model.toUpperCase()} not evaluable`
          : `${memberCount(risk)} of ${risk.evaluable_members} ${model.toUpperCase()} members`;
      });
      return `${SHORT_NAMES[rule.rule_id] ?? rule.title} at T-0: ${counts.join(", ")}.`;
    }),
  ].join(" ");
}

/** The precipitation proxy is shared; its historical concern preface is Falcon-specific. */
export function ruleNote(rule: RuleRisk): string {
  if (rule.rule_id !== "flight_through_precip") return rule.approximation_note;
  return rule.approximation_note
    .replace(/^Named in official Falcon concerns\.\s*/, "")
    .replace("The vehicle threshold is not public;", "No vehicle-specific threshold is inferred;");
}
