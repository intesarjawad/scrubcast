import { TYPICAL_SHARE } from "./sheet-data";
import {
  BLANK_GLYPH,
  FAN_INK,
  FLOOR_GLYPH,
  type Frame,
  GHOST_GLYPH,
  GHOST_RATIO,
  type Glyph,
  type Layout,
  PAGE_GLYPH,
  type Place,
  TICKER_GLYPH,
} from "./sheet-types";

/**
 * Each place's ghost scale for this frame: ghosts keep their own shares until together they
 * would carry more than half the typical digit's ink, then they are scaled down to that.
 */
export function ghostScales(places: Place[], inks: number[]): number[] {
  const ink = ([member, weight]: [number, number]) => Math.min(1, (inks[member] ?? 0) * weight);
  return places.map(({ first, agree, ghosts }) => {
    const typical = Math.min(
      1,
      ((inks[first] ?? 0) > 0 ? TYPICAL_SHARE : 0) + agree.reduce((sum, row) => sum + ink(row), 0),
    );
    const ghost = ghosts.reduce((sum, row) => sum + ink(row), 0);
    return ghost * GHOST_RATIO > typical ? typical / GHOST_RATIO / ghost : 1;
  });
}

/** How much of a glyph's ink is on the sheet: shares add, so every word prints at its real share. */
export function glyphInk(glyph: Glyph, frame: Frame): number {
  if (glyph.kind === TICKER_GLYPH) return glyph.member === frame.pages - 1 ? 1 : 0;
  if (glyph.kind === BLANK_GLYPH) return (frame.inks[glyph.member] ?? 0) > 0 ? 0 : glyph.weight;
  const ink = frame.inks[glyph.member] ?? 0;
  if (glyph.kind === FLOOR_GLYPH) return ink > 0 ? glyph.weight : 0;
  if (glyph.kind <= GHOST_GLYPH)
    return Math.min(1, ink * glyph.weight) * (frame.ghost[GHOST_GLYPH - glyph.kind] ?? 1);
  if (glyph.kind === PAGE_GLYPH) return Math.min(1, ink * glyph.weight);
  return ink > 0 ? FAN_INK : 0;
}

/** The finished sheet without a GPU: the same shares, added up on one layer per ink. */
export function drawStill(canvas: HTMLCanvasElement, layout: Layout, frame: Frame): void {
  canvas.width = Math.ceil(layout.width * layout.dpr);
  canvas.height = Math.ceil(layout.height * layout.dpr);
  const pen = canvas.getContext("2d");
  if (!pen) throw new Error("Canvas 2D is unavailable");
  const layers = [0, 1].map(() => {
    const layer = document.createElement("canvas");
    layer.width = canvas.width;
    layer.height = canvas.height;
    const draw = layer.getContext("2d");
    if (!draw) throw new Error("Canvas 2D is unavailable");
    draw.globalCompositeOperation = "lighter";
    return { layer, draw };
  });
  const d = layout.dpr;
  const black = layers[0]?.draw;
  if (black) {
    black.globalAlpha = frame.share;
    black.drawImage(layout.page, 0, 0);
  }
  for (const glyph of layout.glyphs) {
    const done = glyph.kind < 0 || (frame.fan[glyph.kind] ?? 0) >= 1;
    const at = glyph.kind < 0 ? glyph.at : glyph.to;
    const alpha = glyphInk(glyph, frame);
    const target = layers[glyph.red ? 1 : 0]?.draw;
    if (!done || !target || alpha === 0 || at.w === 0) continue;
    target.globalAlpha = alpha;
    const { uv } = glyph;
    target.drawImage(
      layout.atlas,
      uv.x * d,
      uv.y * d,
      uv.w * d,
      uv.h * d,
      at.x * d,
      at.y * d,
      at.w * d,
      at.h * d,
    );
  }
  pen.fillStyle = layout.paper;
  pen.fillRect(0, 0, canvas.width, canvas.height);
  // Each layer lands twice: coverage c becomes 1 - (1 - c)², the press's dot gain, as in GL.
  for (const layer of [layers[1], layers[1], layers[0], layers[0]])
    if (layer) pen.drawImage(layer.layer, 0, 0);
}
