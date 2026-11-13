import { readFile, rename, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { isLatest, isPast } from "../src/data.ts";
import {
  CARD_HEIGHT_PX,
  CARD_LIMIT_BYTES,
  CARD_WIDTH_PX,
  cardLaunches,
} from "../src/share-card.ts";

const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const PNG_HEADER_BYTES = 33;

export async function cardPublication(directory: string) {
  const latest: unknown = JSON.parse(
    await readFile(resolve(directory, "data/latest.json"), "utf8"),
  );
  const past: unknown = JSON.parse(await readFile(resolve(directory, "data/past.json"), "utf8"));
  if (!isLatest(latest) || !isPast(past))
    throw new Error("Invalid launch indexes; rebuild the site first");
  return { latest, launches: cardLaunches(latest, past) };
}

/** Check the saved artifact, including the decimal 300 KB limit. */
export async function checkCardPng(path: string): Promise<number> {
  const png = await readFile(path).catch((error: unknown) => {
    if (error instanceof Error && "code" in error && error.code === "ENOENT")
      throw new Error("Missing PNG", { cause: error });
    throw error;
  });
  if (
    png.byteLength < PNG_HEADER_BYTES ||
    !png.subarray(0, PNG_SIGNATURE.length).equals(PNG_SIGNATURE) ||
    png.readUInt32BE(8) !== 13 ||
    png.toString("ascii", 12, 16) !== "IHDR"
  )
    throw new Error("Card must be a PNG");
  if (png.readUInt32BE(16) !== CARD_WIDTH_PX || png.readUInt32BE(20) !== CARD_HEIGHT_PX)
    throw new Error(`Card must be ${CARD_WIDTH_PX}x${CARD_HEIGHT_PX}`);
  if (png.byteLength > CARD_LIMIT_BYTES)
    throw new Error(`Card is ${png.byteLength} bytes; limit is ${CARD_LIMIT_BYTES}`);
  return png.byteLength;
}

function canonical(html: string): string {
  const url = /<link rel="canonical" href="([^"]+)">/.exec(html)?.[1];
  if (!url || !/\/launch\/[^/]+\/$/.test(url))
    throw new Error("Missing launch canonical URL; rebuild the site first");
  return url;
}

function previewImage(html: string, image: string): string {
  for (const tag of ['property="og:image"', 'name="twitter:image"']) {
    const pattern = new RegExp(`(<meta ${tag} content=")[^"]*(">)`, "g");
    if ([...html.matchAll(pattern)].length !== 1)
      throw new Error(`Expected one ${tag} tag; rebuild the site first`);
    html = html.replace(pattern, (_match, start: string, end: string) => `${start}${image}${end}`);
  }
  return html;
}

/** Verify every expected PNG and the metadata that announces it. */
export async function checkCards(directory: string): Promise<number> {
  const { launches } = await cardPublication(directory);
  const next = await readFile(resolve(directory, "next/index.html"), "utf8");
  for (const launch of launches) {
    try {
      const folder = resolve(directory, `launch/${encodeURIComponent(launch.id)}`);
      await checkCardPng(resolve(folder, "card.png"));
      const html = await readFile(resolve(folder, "index.html"), "utf8");
      const url = canonical(html);
      const pages = next.includes(`<link rel="canonical" href="${url}">`) ? [html, next] : [html];
      for (const page of pages) {
        if (previewImage(page, `${url}card.png`) !== page)
          throw new Error(`Preview metadata does not name the card for ${launch.id}`);
      }
    } catch (error) {
      throw new Error(
        `${launch.id}: card failed: ${error instanceof Error ? error.message : String(error)}`,
        { cause: error },
      );
    }
  }
  return launches.length;
}

/** Publish preview metadata only after the saved card passes its budget. */
export async function writeLaunchCard(
  directory: string,
  id: string,
  capture: () => Promise<Buffer>,
): Promise<number> {
  const folder = resolve(directory, `launch/${encodeURIComponent(id)}`);
  const path = resolve(folder, "card.png");
  const temporary = resolve(folder, "card.pending.png");
  const entry = resolve(folder, "index.html");
  const html = await readFile(entry, "utf8");
  const url = canonical(html);
  const nextPath = resolve(directory, "next/index.html");
  const next = await readFile(nextPath, "utf8");
  const pages = [{ path: entry, html }];
  if (next.includes(`<link rel="canonical" href="${url}">`))
    pages.push({ path: nextPath, html: next });
  const generic = url.replace(/launch\/[^/]+\/$/, "social-preview.png");
  async function setImages(image: string) {
    for (const page of pages) await writeFile(page.path, previewImage(page.html, image));
  }
  await setImages(generic);
  await rm(path, { force: true });
  try {
    await writeFile(temporary, await capture());
    const bytes = await checkCardPng(temporary);
    await rename(temporary, path);
    await setImages(`${url}card.png`);
    return bytes;
  } catch (error) {
    await setImages(generic);
    await rm(path, { force: true });
    throw error;
  } finally {
    await rm(temporary, { force: true });
  }
}
