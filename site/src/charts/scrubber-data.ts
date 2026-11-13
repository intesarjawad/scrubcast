import { memberPercent, minusSign, padLocalTime, utcTime } from "../format";
import type { models } from "../launch-data";
import type { RuleRisk } from "../types";

export type Model = (typeof models)[number];

export function hourEvidence(rule: RuleRisk, model: Model, hour: number) {
  const verdicts = rule.member_violated_by_hour[model]?.[hour] ?? [];
  const evaluable = verdicts.filter((value) => value !== null).length;
  const violated = verdicts.filter((value) => value === 1).length;
  return {
    evaluable,
    violated,
    count: evaluable ? `${violated} of ${evaluable}` : "Not evaluable",
    risk: evaluable ? memberPercent(violated / evaluable) : "Not evaluable",
  };
}

/** Prepare strings and verdicts outside the cursor's event path. */
export function scrubberHours(rule: RuleRisk, zone: string) {
  return rule.hours.map((hour, index) => {
    const date = new Date(hour);
    const local = padLocalTime(date, zone);
    const utc = utcTime(date);
    function evidenceFor(model: Model) {
      const evidence = hourEvidence(rule, model, index);
      return {
        ...evidence,
        readout: evidence.evaluable
          ? `${evidence.count} ${model.toUpperCase()} members ${minusSign(rule.plot.readout_phrase)}.`
          : `${model.toUpperCase()}: not evaluable.`,
      };
    }
    const byModel = { ecmwf: evidenceFor("ecmwf"), gfs: evidenceFor("gfs") };
    return { hour, local, utc, byModel };
  });
}

const SCALE_HEADROOM = 0.1;

/** Share one unclipped scale across both ensembles, including the threshold. */
export function memberScale(rule: RuleRisk) {
  const values = Object.values(rule.member_values_by_hour).flatMap(
    (matrix) => matrix?.flat() ?? [],
  );
  const available = values.filter((value) => value !== null);
  const low = Math.min(0, rule.threshold?.value ?? 0, ...available);
  const high = Math.max(0, rule.threshold?.value ?? 0, ...available);
  const padding = (high - low || 1) * SCALE_HEADROOM;
  const min = low < 0 ? low - padding : 0;
  const max = high + padding;
  return { min, max, fraction: (value: number) => (value - min) / (max - min) };
}
