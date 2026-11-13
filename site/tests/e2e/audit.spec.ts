import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { AuditFooter, Hindcast, Outcome } from "../../src/types";
import { demo } from "../fixtures/demo";

const path = `/launch/${demo.launch.id}/`;
const hindcast = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/hindcast/full.json", import.meta.url), "utf8"),
) as Hindcast;

type OutcomeCase = {
  ledger: {
    official_concerns: string[];
    rules: Record<string, [number | null, number | null]>;
  }[];
  expected: {
    outcome: Outcome;
    net_now: string | null;
    note: { created_on: string; text: string } | null;
  }[];
};

function outcomeCase(name: string): OutcomeCase {
  return JSON.parse(
    readFileSync(new URL(`../../../tests/fixtures/outcomes/${name}.json`, import.meta.url), "utf8"),
  ) as OutcomeCase;
}

function footers(name: string): AuditFooter[] {
  const value = outcomeCase(name);
  return value.ledger.map((ledger, index) => {
    const expected = value.expected[index];
    if (!expected) throw new Error(`Missing expected outcome ${index}`);
    return {
      attempt_id: `attempt-${index}`,
      attempt_net: ledgerAttemptNet(name, index),
      official_concerns: ledger.official_concerns,
      scrubcast_24h: Object.entries(ledger.rules)
        .filter(([, risk]) => (risk[0] ?? 0) > 0)
        .map(([rule_id, risk]) => ({
          rule_id,
          title: rule_id === "cumulus" ? "Cumulus cloud" : rule_id,
          risk_fraction: risk[0] ?? 0,
        })),
      outcome: expected.outcome,
      net_now: expected.net_now,
      note: expected.note,
    };
  });
}

function ledgerAttemptNet(name: string, index: number): string {
  const value = JSON.parse(
    readFileSync(new URL(`../../../tests/fixtures/outcomes/${name}.json`, import.meta.url), "utf8"),
  ) as { ledger: { net: string }[] };
  const row = value.ledger[index];
  if (!row) throw new Error(`Missing ledger row ${index}`);
  return row.net;
}

async function show(page: import("@playwright/test").Page, audit: AuditFooter[]): Promise<void> {
  const launch = {
    ...demo.launch,
    net: "2026-11-01T00:00:00Z",
    window_start: "2026-11-01T00:00:00Z",
    window_end: "2026-11-01T04:00:00Z",
  };
  await page.route(`**/data/launches/${demo.launch.id}.json`, (route) =>
    route.fulfill({ json: { ...demo, launch, audit } }),
  );
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    demo.launch.name.replace(" | ", ", "),
  );
}

test("audit view prints three summaries, three evaluations, baselines and an n on every number", async ({
  page,
}) => {
  await page.route("**/data/hindcast.json", (route) => route.fulfill({ json: hindcast }));
  await page.goto("/audit/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Forecast audit");
  const summary = page.getByRole("region", { name: "Summary" });
  await expect(summary).toContainText("ECMWF wind CRPS skill 0.87 (n=12) (best model)");
  await expect(summary).toContainText("Precipitation Brier skill 0.00 (n=12)");
  await expect(page.locator(".audit-table").first()).toContainText("1.00 m/s (n=12)");
  for (const title of [
    "Wind input against observation",
    "Rule against observation",
    "Agreement with the official forecast",
  ]) {
    await expect(page.getByRole("heading", { level: 2, name: title })).toBeVisible();
  }
  expect(await page.getByRole("columnheader", { name: "Baseline" }).count()).toBe(3);
  const rows = page.locator(".audit-table tbody tr");
  expect(await rows.count()).toBeGreaterThan(3);
  for (const row of await rows.all()) {
    const text = (await row.textContent()) ?? "";
    expect(text).toMatch(/n=\d+/);
    for (const match of text.matchAll(/\d+(?:\.\d+)?%/g)) {
      const after = text.slice((match.index ?? 0) + match[0].length);
      expect(after).toMatch(/n=\d+/);
    }
  }
  await expect(page.getByRole("heading", { level: 2, name: "Attempt outcomes" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Lowest-risk hour" })).toBeVisible();
});

for (const [row, name, outcome] of [
  [1, "launched", "Outcome: launched in the window."],
  [
    2,
    "launched_later",
    "Outcome: did not launch in the window; launched later at 2026-11-06 08:00 UTC.",
  ],
  [3, "new_t0", "Outcome: did not launch in the window; new T-0 pending at 2026-11-06 08:00 UTC."],
  [4, "hold", "Outcome: did not launch in the window; launch on hold."],
  [5, "unknown", "Outcome: unknown."],
] as const) {
  test(`outcome table row ${row} shows its exact footer`, async ({ page }) => {
    await show(page, footers(name));
    const footer = page.locator(".audit-footer");
    await expect(footer).toHaveCount(1);
    await expect(footer).toContainText(
      `Official concerns: Cumulus Cloud Rule. Scrubcast at 24 h: Cumulus cloud 40%. ${outcome}`,
    );
    if (row >= 2 && row <= 4) await expect(footer).toContainText("LL2 note: Launch delayed.");
    else await expect(footer).not.toContainText("LL2 note");
  });
}

test("an in-window launch never shows an LL2 note", async ({ page }) => {
  const launch = footers("launched_later");
  const withoutNote = launch.map((footer) => ({ ...footer, note: null }));
  await show(page, withoutNote);
  await expect(page.locator(".audit-footer")).not.toContainText("LL2 note");
});

test("two attempts render newest first", async ({ page }) => {
  await show(page, footers("two_attempts"));
  const items = page.locator(".audit-footer");
  await expect(items).toHaveCount(2);
  await expect(items.first()).toContainText("Outcome: launched in the window.");
  await expect(items.last()).toContainText(
    "Outcome: did not launch in the window; launched later at 2026-11-06 08:00 UTC.",
  );
});

test("audit tables stay inside a narrow viewport and chart has themed scales", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ colorScheme: "dark" });
  const populated = structuredClone(hindcast);
  const evaluation = populated.forecast_audit?.evaluations[0];
  if (!evaluation) throw new Error("Missing evaluation");
  evaluation.reliability = [{ lower: 0, upper: 1, predicted: 0.5, observed: 0.75, n: 12 }];
  await page.route("**/data/hindcast.json", (route) => route.fulfill({ json: populated }));
  await page.goto("/audit/");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await expect(page.locator(".audit-table").first()).toContainText("not estimated");
  const chart = page.locator(".reliability svg").first();
  await expect(chart).toContainText("Observed frequency");
  await expect(chart).toContainText("100%");
  expect(
    await chart.locator("line.reference").evaluate((line) => getComputedStyle(line).stroke),
  ).not.toBe("none");
});

test("missing lowest-hour estimates have explicit text beside their sample sizes", async ({
  page,
}) => {
  const audit = hindcast.forecast_audit;
  if (!audit) throw new Error("Missing audit fixture");
  await page.route("**/data/hindcast.json", (route) =>
    route.fulfill({
      json: {
        ...hindcast,
        forecast_audit: {
          ...audit,
          lowest_hour: {
            ...audit.lowest_hour,
            n: 0,
            risk_at_lowest: null,
            risk_at_t0: null,
            precipitation_at_lowest: null,
            precipitation_at_t0: null,
            difference: null,
            interval: null,
            verified: false,
          },
        },
      },
    }),
  );
  await page.goto("/audit/");
  await expect(page.locator(".lowest-hour")).toContainText("not estimated (n=0)");
  await expect(page.locator(".lowest-hour")).not.toContainText("undefined");
});
