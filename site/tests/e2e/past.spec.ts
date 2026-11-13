import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// The fixture build retains `fixture-past` from tests/fixtures/past; its T-0 is two days
// before the recording time.
const recordedAt = new Date(
  readFileSync(new URL("../../../tests/fixtures/RECORDED_AT", import.meta.url), "utf8").trim(),
);

test("a launch two days past T-0 keeps its audit footer and drops the member board", async ({
  page,
}) => {
  await page.clock.setFixedTime(recordedAt);
  await page.goto("/launch/fixture-past/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Falcon 9 Block 5, Retained Fixture",
  );
  await expect(
    page.getByRole("heading", { level: 2, name: "Rule risks at 24 hours" }),
  ).toBeVisible();
  await expect(page.locator(".audit-footer")).toHaveCount(1);
  await expect(page.locator(".audit-footer")).toContainText("Outcome:");
  await expect(page.getByText("This launch page is retained for 90 days")).toBeVisible();
  await expect(page.locator(".rule-board")).toHaveCount(0);
  await expect(page.getByRole("slider")).toHaveCount(0);
});
