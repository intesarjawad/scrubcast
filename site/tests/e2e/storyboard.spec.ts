import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { isLaunchAssessment } from "../../src/launch-data";
import { demo, openingOrder, recordedCount, recordedReadout } from "../fixtures/demo";

// Read the delivered assessment independently of the page and its formatting functions.
const data: unknown = JSON.parse(
  readFileSync(
    new URL(`../../public/data/launches/${demo.launch.id}.json`, import.meta.url),
    "utf8",
  ),
);
if (!isLaunchAssessment(data))
  throw new Error("Missing built demo assessment; run npm run fixtures");
const assessment = data;
const rules = openingOrder(assessment.rules);
const top = rules[0];
if (!top) throw new Error("The recorded demo has no rule results");
const models = ["ecmwf", "gfs"] as const;
const confidence = {
  direct: "Direct threshold",
  medium: "Medium confidence proxy",
  low: "Low confidence proxy",
};

test.use({ viewport: { width: 1280, height: 720 } });

test("recorded forecast follows every storyboard beat", async ({ page }, info) => {
  await page.clock.setFixedTime(new Date(assessment.evaluated_at));
  await page.goto(`/launch/${assessment.launch.id}/`);
  const board = page.locator(".board");
  const flagged = (rule: (typeof rules)[number]) =>
    models.some((model) => (rule.by_model[model]?.risk_fraction ?? 0) > 0);
  const limits = page.getByRole("region", { name: /^Left blank on all \d+ pages$/ });
  const slider = page.getByRole("slider", { name: "Selected hour" });
  const capture = async (name: string) =>
    info.attach(name, {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });

  await test.step("0.0 to 1.5 seconds: mission, official evidence and first rule", async () => {
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      assessment.launch.name.replace(" | ", ", "),
    );
    await expect(page.locator(".schedule")).toContainText(assessment.launch.pad.name);
    const probability = assessment.launch.probability;
    const concern = assessment.launch.weather_concerns;
    if (probability === null && !concern) {
      await expect(page.locator(".sheet-facts")).toContainText("Not published");
      info.annotations.push({
        type: "recording",
        description:
          "The source did not publish an official forecast. See the recording provenance.",
      });
    } else {
      if (probability !== null)
        await expect(page.locator(".sheet-facts")).toContainText(
          `${probability}% probability of GO`,
        );
      if (concern) await expect(page.locator(".sheet-facts")).toContainText(`Concern: ${concern}`);
    }
    await expect(board.locator(`.rule-pick[data-rule-id="${top.rule_id}"]`)).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await capture("01-poster");
  });

  await test.step("1.5 to 3.5 seconds: remaining rules, confidence and limits", async () => {
    await expect(board.locator(".rule-pick")).toHaveCount(rules.length);
    await expect(board.locator("tbody tr")).toHaveCount(rules.filter(flagged).length);
    for (const rule of rules.filter(flagged)) {
      const row = board.locator(`tr[data-rule-id="${rule.rule_id}"]`);
      await expect(row.getByRole("rowheader")).toContainText(confidence[rule.confidence]);
      for (const [column, model] of models.entries()) {
        await expect(row.getByRole("cell").nth(column)).toContainText(
          recordedCount(rule, model, assessment.t0_index),
        );
      }
    }
    for (const rule of rules.filter((rule) => !flagged(rule)))
      await expect(
        board.locator(`.board-clear .rule-pick[data-rule-id="${rule.rule_id}"]`),
      ).toHaveCount(1);
    for (const omitted of assessment.not_evaluable) {
      await expect(limits.getByRole("listitem").filter({ hasText: omitted.title })).toContainText(
        omitted.reason,
      );
    }
    await capture("02-rules-and-limits");
  });

  await test.step("3.5 to 5.0 seconds: inspect the leading rule and both models", async () => {
    await board.locator(`.rule-pick[data-rule-id="${top.rule_id}"]`).click();
    for (const model of models) {
      await expect(page.locator(`.pane-count[data-model="${model}"]`)).toHaveText(
        recordedCount(top, model, assessment.t0_index),
      );
    }
    await expect(page.locator(".proxy")).toContainText(top.approximation_note);
    await capture("03-leading-rule");
  });

  await test.step("5.0 to 9.0 seconds: step every hour and inspect member verdicts", async () => {
    await slider.focus();
    await slider.press("Home");
    for (const [hour, timestamp] of top.hours.entries()) {
      if (hour > 0) await slider.press("ArrowRight");
      await expect(slider).toHaveValue(String(hour));
      await expect(slider).toHaveAttribute("aria-valuetext", new RegExp(timestamp.slice(11, 16)));
      await expect(page.getByRole("status")).toContainText(recordedReadout(top, "ecmwf", hour));
      for (const model of models) {
        await expect(page.locator(`.pane-count[data-model="${model}"]`)).toHaveText(
          recordedCount(top, model, hour),
        );
        const verdicts = top.member_violated_by_hour[model]?.[hour] ?? [];
        const paths = page.locator(`.pane-${model} path.member`);
        await expect(paths).toHaveCount(verdicts.length);
        for (const [member, verdict] of verdicts.entries()) {
          await expect(paths.nth(member)).toHaveClass(verdict === 1 ? "member exceed" : "member");
        }
      }
    }
    if (assessment.lowest_union_hour) {
      await expect(page.locator(".lowest-risk-marker")).toBeVisible();
      await expect(page.locator(".chart-notes")).toContainText(
        assessment.lowest_union_hour.hour.slice(11, 16),
      );
    } else {
      await expect(page.locator(".chart-notes")).toContainText(
        "No materially lower hour established",
      );
      await expect(page.locator(".lowest-risk-marker")).toHaveCount(0);
    }
    await capture("04-hourly-cursor");
  });

  await test.step("9.0 to 10.0 seconds: hold at the greatest recorded violation count", async () => {
    const counts = top.hours.map(
      (_, hour) =>
        (top.member_violated_by_hour.ecmwf?.[hour] ?? []).filter((value) => value === 1).length,
    );
    const most = counts.indexOf(Math.max(...counts));
    await slider.press("Home");
    for (let hour = 0; hour < most; hour++) await slider.press("ArrowRight");
    await expect(page.getByRole("status")).toContainText(recordedReadout(top, "ecmwf", most));
    await page.getByRole("button", { name: "GFS", exact: true }).click();
    await expect(page.getByRole("status")).toContainText(recordedReadout(top, "gfs", most));
    await page.getByRole("button", { name: "ECMWF", exact: true }).click();
    await expect(page.getByRole("status")).toContainText(recordedReadout(top, "ecmwf", most));
    await expect(limits).toBeVisible();
    for (const omitted of assessment.not_evaluable)
      await expect(limits).toContainText(omitted.title);
    await capture("05-final-readout");
  });
});
