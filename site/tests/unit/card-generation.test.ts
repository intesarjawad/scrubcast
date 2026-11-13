import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, expect, it, vi } from "vitest";
import { generateCards } from "../../scripts/cards";
import { isLaunchAssessment } from "../../src/launch-data";

vi.mock("@playwright/test", () => ({
  chromium: {
    launch: async () => ({
      newContext: async () => {
        throw new Error("Capture unavailable");
      },
      close: async () => {},
    }),
  },
}));

vi.mock("vite", () => ({
  preview: async () => ({
    httpServer: { close: (callback: (error?: Error) => void) => callback() },
  }),
}));

const temporary = await mkdtemp(join(tmpdir(), "scrubcast-card-generation-"));
afterAll(async () => rm(temporary, { recursive: true, force: true }));

it("rejects a failed batch after restoring preview metadata for every failed launch", async () => {
  const value: unknown = JSON.parse(
    await readFile(
      new URL("../../../tests/fixtures/demo/assessment.json", import.meta.url),
      "utf8",
    ),
  );
  if (!isLaunchAssessment(value)) throw new Error("Invalid recorded assessment");
  const launches = ["first", "second"].map((id) => ({
    ...value.launch,
    id,
    page_url: `/launch/${id}/`,
    assessment: false,
    tier: "C",
    worst_rule: { label: "No published rules" },
  }));
  await mkdir(join(temporary, "data"));
  await mkdir(join(temporary, "next"));
  await writeFile(join(temporary, "index.html"), '<script src="/assets/main.js"></script>');
  await writeFile(
    join(temporary, "data/latest.json"),
    JSON.stringify({
      schema_version: 1,
      generated_at: "2026-11-05T12:00:00Z",
      schedule_stale: false,
      members_total: 82,
      launches,
    }),
  );
  await writeFile(
    join(temporary, "data/past.json"),
    JSON.stringify({ schema_version: 1, generated_at: "2026-11-05T12:00:00Z", launches: [] }),
  );
  await writeFile(join(temporary, "next/index.html"), "");
  for (const { id } of launches) {
    await mkdir(join(temporary, `launch/${id}`), { recursive: true });
    await writeFile(
      join(temporary, `launch/${id}/index.html`),
      `<link rel="canonical" href="https://example.org/launch/${id}/"><meta property="og:image" content="https://example.org/launch/${id}/card.png"><meta name="twitter:image" content="https://example.org/launch/${id}/card.png">`,
    );
  }
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    await expect(generateCards(temporary)).rejects.toThrow("2 cards failed");
    for (const { id } of launches) {
      const html = await readFile(join(temporary, `launch/${id}/index.html`), "utf8");
      expect(html).not.toContain("card.png");
      expect(html).toContain("https://example.org/social-preview.png");
    }
  } finally {
    errors.mockRestore();
  }
});
