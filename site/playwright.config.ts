import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  // The sheet exercises the GPU; keep one rendering run active at a time.
  workers: 1,
  testDir: "./tests/e2e",
  snapshotPathTemplate: "{testDir}/__screenshots__/{testFilePath}/{arg}{ext}",
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.005 } },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], channel: "chromium" },
      ignoreSnapshots: !process.env.CI,
    },
    { name: "webkit", use: { ...devices["iPhone 15"] }, ignoreSnapshots: true },
  ],
  use: {
    baseURL: "http://127.0.0.1:43871",
  },
  webServer: {
    command:
      "npm run fixtures && npm run build && npm run preview -- --host 127.0.0.1 --port 43871 --strictPort",
    url: "http://127.0.0.1:43871",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
