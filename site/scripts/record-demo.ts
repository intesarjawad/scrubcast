import { execFileSync } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium, type Page } from "@playwright/test";
import { preview } from "vite";
import { pressSchedule } from "../src/charts/sheet-data.ts";
import { isLatest } from "../src/data.ts";
import { isLaunchAssessment } from "../src/launch-data.ts";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const DIST = resolve(ROOT, "site/dist");
const GIF = resolve(ROOT, "docs/demo.gif");
const CLIP = resolve(ROOT, "docs/demo-clip.mp4");
const SOCIAL_PREVIEW = resolve(ROOT, "site/public/social-preview.png");
const STORM = resolve(ROOT, "tests/fixtures/worst_case/storm-night.json");

const PORT = 43872;
const FPS = 12;
// The sheet is composed for a laptop screen; frames are taken at 1440×810 and scaled to 1280×720.
const VIEWPORT = { width: 1440, height: 810 };
const FRAME = { width: 1280, height: 720 };
const CAPTION_HEIGHT_PX = 96;
// 1600×800 CSS px at 0.8 device scale saves a 1280×640 preview with the sheet's full height.
const SOCIAL_VIEWPORT = { width: 1600, height: 800 };
const SOCIAL_SCALE = 0.8;
const GIF_LIMIT_BYTES = 6_000_000;
const PRINT_TIMEOUT_MS = 20_000;

function run(command: string, args: string[]): void {
  try {
    execFileSync(command, args, { stdio: ["ignore", "ignore", "inherit"] });
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT")
      throw new Error(`${command} is not installed; install it and rerun npm run record-demo`);
    throw error;
  }
}

class Recorder {
  frames = 0;
  readonly captions: { from_s: number; text: string }[] = [];
  readonly page: Page;
  readonly directory: string;

  constructor(page: Page, directory: string) {
    this.page = page;
    this.directory = directory;
  }

  caption(text: string): void {
    this.captions.push({ from_s: this.frames / FPS, text });
  }

  async shoot(): Promise<void> {
    this.frames += 1;
    await this.page.clock.runFor(1000 / FPS);
    await this.page.screenshot({
      path: join(this.directory, `${String(this.frames).padStart(4, "0")}.png`),
      animations: "disabled",
      caret: "initial",
    });
  }

  async hold(seconds: number): Promise<void> {
    for (let frame = 0; frame < Math.round(seconds * FPS); frame++) await this.shoot();
  }
}

/** Stops page time so that it moves only by the frame steps, however long a screenshot takes. */
async function freezeClock(page: Page, at: string): Promise<void> {
  const time = new Date(at).getTime();
  await page.clock.install({ time });
  await page.clock.pauseAt(time + 1000);
}

/** Steps the page's frozen clock until the sheet has typeset and its renderer is ready. */
async function waitForSheet(page: Page): Promise<void> {
  await page.locator(".spread").waitFor();
  const deadline = Date.now() + PRINT_TIMEOUT_MS;
  while ((await page.locator(".spread").getAttribute("data-printed")) !== "true") {
    if (Date.now() > deadline) throw new Error("The sheet never printed");
    await page.clock.runFor(16);
    await page.waitForTimeout(20);
  }
}

/** Four beats over ten seconds: the press run, the sheet, a fanned blur, and its reading. */
async function recordStoryboard(page: Page, recorder: Recorder, members: number): Promise<void> {
  const schedule = pressSchedule(members);
  const last = schedule.at(-1);
  const pressSeconds = last ? (last.start + last.duration) / 1000 : 0;
  const figures = page.locator("button.figure");

  recorder.caption("Fixture night, not a launch: every ensemble member writes the same page");
  await recorder.hold(Math.min(pressSeconds + 0.2, 5.5));

  recorder.caption(`All ${members} pages on one sheet: agreement prints solid, disagreement blurs`);
  await recorder.hold(1);

  recorder.caption("Point at a blur and its values fan out against the limit");
  const count = await figures.count();
  await figures.nth(Math.min(2, count - 1)).hover();
  await recorder.hold(1.5);

  const reading = (await page.locator(".fan-caption").textContent())?.trim();
  if (!reading) throw new Error("The fan caption is empty");
  recorder.caption(reading);
  await recorder.hold(10 - recorder.frames / FPS);
}

export async function renderCaption(page: Page, text: string, path: string): Promise<void> {
  const browser = page.context().browser();
  if (!browser) throw new Error("Missing caption browser");
  // A resized frozen WebGL page can retain its old compositor surface.
  const caption = await browser.newPage({
    viewport: { width: FRAME.width, height: CAPTION_HEIGHT_PX },
    colorScheme: "light",
    locale: "en-US",
    timezoneId: "UTC",
    serviceWorkers: "block",
  });
  try {
    await caption.goto(new URL("/", page.url()).href);
    await caption.evaluate((text) => {
      document.body.className = "";
      document.body.innerHTML = "";
      document.body.style.cssText =
        "margin:0;height:100vh;display:flex;align-items:center;padding:0 48px;box-sizing:border-box;" +
        "font:500 28px/1.25 'Public Sans',sans-serif;color:var(--ink);background:var(--bg);" +
        "border-top:1px solid var(--line)";
      document.body.textContent = text;
    }, text);
    await caption.screenshot({ path, scale: "css" });
  } finally {
    await caption.close();
  }
}

/** The repository preview is the finished sheet under reduced motion, cropped below the header. */
async function renderSocialPreview(page: Page, url: string): Promise<void> {
  await page.goto(url);
  await waitForSheet(page);
  await page.clock.runFor(500);
  await page.addStyleTag({ content: ".unseen { visibility: hidden; }" });
  await page
    .locator(".spread")
    .evaluate((node) => window.scrollTo(0, node.getBoundingClientRect().top + window.scrollY));
  await page.clock.runFor(100);
  await page.screenshot({ path: SOCIAL_PREVIEW, scale: "device" });
}

async function main(): Promise<void> {
  const assessment: unknown = JSON.parse(
    await readFile(resolve(ROOT, "tests/fixtures/demo/assessment.json"), "utf8"),
  );
  const latest: unknown = JSON.parse(await readFile(resolve(DIST, "data/latest.json"), "utf8"));
  if (!isLaunchAssessment(assessment)) throw new Error("Invalid demo assessment");
  if (!isLatest(latest))
    throw new Error("Missing fixture build; run npm run fixtures && npm run build");
  if (!latest.launches.some((launch) => launch.id === assessment.launch.id))
    throw new Error(
      "The build does not hold the demo launch; run npm run fixtures && npm run build",
    );
  const url = `http://127.0.0.1:${PORT}/launch/${encodeURIComponent(assessment.launch.id)}/`;
  const storm: unknown = JSON.parse(await readFile(STORM, "utf8"));
  if (!isLaunchAssessment(storm)) throw new Error("Invalid storm fixture");
  const stormPath = `/launch/${encodeURIComponent(storm.launch.id)}/`;

  const frames = await mkdtemp(join(tmpdir(), "scrubcast-demo-"));
  const server = await preview({
    configFile: false,
    build: { outDir: DIST },
    preview: { host: "127.0.0.1", port: PORT, strictPort: true, open: false },
  });
  try {
    const browser = await chromium.launch({ channel: "chromium" });
    try {
      const settings = {
        locale: "en-US",
        timezoneId: "UTC",
        colorScheme: "light",
        serviceWorkers: "block",
      } as const;
      const context = await browser.newContext({ ...settings, viewport: VIEWPORT });
      const page = await context.newPage();
      // The clip shows the recorded storm night, served beside the build: a calm night never
      // shows red. The sheet and the first caption both name it a fixture.
      const listed = {
        ...latest,
        launches: [
          ...latest.launches,
          {
            ...storm.launch,
            tier: storm.tier,
            assessment: true,
            page_url: stormPath,
            worst_rule: { label: "" },
          },
        ],
      };
      await page.route("**/data/latest.json", (route) => route.fulfill({ json: listed }));
      await page.route(`**/data/launches/${encodeURIComponent(storm.launch.id)}.json`, (route) =>
        route.fulfill({ json: storm }),
      );
      await freezeClock(page, storm.evaluated_at);
      await page.goto(`http://127.0.0.1:${PORT}${stormPath}`);
      await waitForSheet(page);
      const recorder = new Recorder(page, frames);
      await recordStoryboard(page, recorder, latest.members_total);
      if (recorder.frames !== 10 * FPS)
        throw new Error(`Storyboard recorded ${recorder.frames} frames, expected ${10 * FPS}`);
      for (const [index, { text }] of recorder.captions.entries())
        await renderCaption(page, text, join(frames, `caption-${index}.png`));
      await context.close();

      const social = await browser.newContext({
        ...settings,
        viewport: SOCIAL_VIEWPORT,
        deviceScaleFactor: SOCIAL_SCALE,
        reducedMotion: "reduce",
      });
      const still = await social.newPage();
      await freezeClock(still, assessment.evaluated_at);
      await renderSocialPreview(still, url);
      await social.close();

      const sequence = ["-framerate", String(FPS), "-i", join(frames, "%04d.png")];
      // The sheet is near-neutral paper and ink; 48 undithered colours keep the paper grain from
      // turning every moving page into noise, which holds the 10 s GIF under 6 MB.
      run("ffmpeg", [
        "-y",
        "-loglevel",
        "error",
        ...sequence,
        "-vf",
        `fps=${FPS},scale=${FRAME.width}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=48:stats_mode=diff[p];[s1][p]paletteuse=dither=none:diff_mode=rectangle`,
        GIF,
      ]);

      const inputs = recorder.captions.flatMap((_, index) => [
        "-i",
        join(frames, `caption-${index}.png`),
      ]);
      const overlays = recorder.captions.map(({ from_s }, index) => {
        const to_s = recorder.captions[index + 1]?.from_s ?? 10;
        return `[v${index}][${index + 1}]overlay=0:${FRAME.height}:enable='between(t,${from_s},${to_s})'[v${index + 1}]`;
      });
      run("ffmpeg", [
        "-y",
        "-loglevel",
        "error",
        ...sequence,
        ...inputs,
        "-filter_complex",
        [
          `[0]scale=${FRAME.width}:${FRAME.height}:flags=lanczos,pad=${FRAME.width}:${FRAME.height + CAPTION_HEIGHT_PX}[v0]`,
          ...overlays,
        ].join(";"),
        "-map",
        `[v${recorder.captions.length}]`,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        CLIP,
      ]);
    } finally {
      await browser.close();
    }
  } finally {
    await new Promise<void>((accept, reject) => {
      server.httpServer.close((error) => (error ? reject(error) : accept()));
      if ("closeAllConnections" in server.httpServer) server.httpServer.closeAllConnections();
    });
    await rm(frames, { recursive: true, force: true });
  }

  const gif = (await readFile(GIF)).byteLength;
  if (gif > GIF_LIMIT_BYTES)
    throw new Error(`docs/demo.gif is ${gif} bytes, over ${GIF_LIMIT_BYTES}`);
  console.info(`docs/demo.gif: ${FRAME.width}x${FRAME.height}, 10 s, ${gif} bytes`);
  console.info(`docs/demo-clip.mp4: ${(await readFile(CLIP)).byteLength} bytes`);
  console.info(
    `site/public/social-preview.png: ${SOCIAL_VIEWPORT.width * SOCIAL_SCALE}x${SOCIAL_VIEWPORT.height * SOCIAL_SCALE}`,
  );
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await main();
}
