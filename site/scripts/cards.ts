import { appendFile, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";
import { preview } from "vite";
import { routeHref } from "../src/router.ts";
import { CARD_HEIGHT_PX, CARD_WIDTH_PX } from "../src/share-card.ts";
import { cardPublication, checkCardPng, checkCards, writeLaunchCard } from "./card-files.ts";

export const CARD_PREVIEW_PORT = 43871;
const CAPTURE_TIMEOUT_MS = 15_000;

export async function generateCards(directory: string): Promise<void> {
  let failures = 0;
  const { latest, launches } = await cardPublication(directory);
  const template = await readFile(resolve(directory, "index.html"), "utf8");
  const base = /<script[^>]+src="([^"]+)assets\//.exec(template)?.[1];
  if (!base) throw new Error("Missing bundled entry asset; build the site first");
  const server = await preview({
    configFile: false,
    base,
    build: { outDir: directory },
    preview: { host: "127.0.0.1", port: CARD_PREVIEW_PORT, strictPort: true, open: false },
  });
  try {
    const browser = await chromium.launch({ channel: "chromium" });
    try {
      for (const launch of launches) {
        try {
          const bytes = await writeLaunchCard(directory, launch.id, async () => {
            const context = await browser.newContext({
              viewport: { width: CARD_WIDTH_PX, height: CARD_HEIGHT_PX },
              deviceScaleFactor: 1,
              colorScheme: "light",
              reducedMotion: "reduce",
              locale: "en-US",
              timezoneId: "UTC",
              serviceWorkers: "block",
            });
            try {
              await context.clock.setFixedTime(new Date(latest.generated_at));
              const page = await context.newPage();
              page.setDefaultTimeout(CAPTURE_TIMEOUT_MS);
              const url = `http://127.0.0.1:${CARD_PREVIEW_PORT}${routeHref(`launch/${encodeURIComponent(launch.id)}/?card`, base)}`;
              const response = await page.goto(url, { waitUntil: "load" });
              if (!response?.ok())
                throw new Error(`Card route returned ${response?.status() ?? "no response"}`);
              await page.waitForFunction(
                (id) => document.querySelector<HTMLElement>("#app")?.dataset.cardReady === id,
                launch.id,
              );
              await page.evaluate(async () => {
                await document.fonts.ready;
                if (
                  !document.fonts.check('500 42px "EB Garamond"') ||
                  !document.fonts.check('400 21px "Public Sans"')
                )
                  throw new Error("Card fonts did not load");
                const app = document.querySelector("#app");
                if (!app) throw new Error("Missing card layout");
                const bounds = app.getBoundingClientRect();
                for (const child of app.children) {
                  const box = child.getBoundingClientRect();
                  if (
                    box.bottom > bounds.bottom ||
                    box.right > bounds.right ||
                    child.scrollHeight > child.clientHeight ||
                    child.scrollWidth > child.clientWidth
                  )
                    throw new Error("Card content exceeds its frame");
                }
              });
              return await page.locator("body.card-page").screenshot({
                type: "png",
                animations: "disabled",
                scale: "css",
              });
            } finally {
              await context.close();
            }
          });
          console.info(`${launch.id}: ${CARD_WIDTH_PX}x${CARD_HEIGHT_PX}, ${bytes} bytes`);
        } catch (error) {
          failures += 1;
          const message = `${launch.id}: card failed: ${error instanceof Error ? error.message : String(error)}`;
          console.error(message);
          if (process.env.GITHUB_STEP_SUMMARY)
            await appendFile(
              process.env.GITHUB_STEP_SUMMARY,
              `${message.replace(/[\r\n]/g, " ")}\n\n`,
            );
        }
      }
    } finally {
      await browser.close();
    }
  } finally {
    await new Promise<void>((accept, reject) => {
      server.httpServer.close((error) => (error ? reject(error) : accept()));
      if ("closeAllConnections" in server.httpServer) server.httpServer.closeAllConnections();
    });
  }
  if (failures) throw new Error(`${failures} cards failed`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const directory = fileURLToPath(new URL("../dist/", import.meta.url));
  try {
    if (process.argv[2] === "--check") {
      const paths = process.argv.slice(3);
      if (paths.length) {
        for (const path of paths) {
          try {
            console.info(`${path}: ${await checkCardPng(resolve(path))} bytes`);
          } catch (error) {
            console.error(
              `${path}: card failed: ${error instanceof Error ? error.message : String(error)}`,
            );
            process.exitCode = 1;
          }
        }
      } else console.info(`${await checkCards(directory)} cards and preview metadata pass`);
    } else await generateCards(directory);
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
