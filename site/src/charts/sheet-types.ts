/** Ink a fanned copy prints with; the copies stand apart, so each must read on its own. */
export const FAN_INK = 0.9;
export const FAN_GAP_PX = 4;
/** The least a fan column rises per extra member, so a cluster of six stands above a cluster of two. */
export const FAN_SHEAR_PX = 3;
export const ATLAS_WIDTH_PX = 1024;
export const ATLAS_PAD_PX = 2;
/** The most members the GL press addresses; a larger ensemble prints with the 2D renderer. */
export const MAX_MEMBERS = 128;
export const CROP_OFFSET_PX = 12;
export const CROP_LENGTH_PX = 16;
/** A group no page has printed yet keeps its place with a hairline this far below the baseline. */
export const BLANK_DROP_EM = 0.18;
export const BLANK_INK = 0.5;
/** A solid square kept at the atlas origin and stretched into each hairline; sampled inside its edge. */
export const BLOCK_PX = 8;
export const BLOCK_UV = { x: 2, y: 2, w: 4, h: 4 };
/** Glyph kinds besides a fan index: a word of one page, the page-number ticker, a blank. */
export const PAGE_GLYPH = -1;
export const TICKER_GLYPH = -2;
/** A hairline that holds a group's place until its first page prints. */
export const BLANK_GLYPH = -3;
/** A figure's typical value, printed at `TYPICAL_SHARE` from its group's first page. */
export const FLOOR_GLYPH = -4;
/** A differing digit; its kind counts down from here to name its place, `GHOST_GLYPH - place`. */
export const GHOST_GLYPH = -100;
/** The most figure places the GL press scales; a busier sheet prints with the 2D renderer. */
export const MAX_PLACES = 128;
/** A place's typical digit always carries at least this many times its ghosts' ink. */
export const GHOST_RATIO = 2;

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** One member's printing of one slot, or one fanned copy of it, or a fan's overflow count. */
export interface Glyph {
  member: number;
  at: Rect;
  uv: Rect;
  kind: number;
  to: Rect;
  rank: number;
  red: boolean;
  /** Ink multiplier for a page glyph, from `Slot.weight`. */
  weight: number;
}

/** One digit place of a figure: its typical floor and the members printing in and out of it. */
export interface Place {
  first: number;
  agree: [member: number, weight: number][];
  ghosts: [member: number, weight: number][];
}

export interface Layout {
  width: number;
  height: number;
  dpr: number;
  page: HTMLCanvasElement;
  atlas: HTMLCanvasElement;
  glyphs: Glyph[];
  paper: string;
  ink: string;
  alarm: string;
  members: number;
  places: Place[];
}

export interface Frame {
  /** Each member's ink: 0 before its page comes down, 1 as it strikes, its share once settled. */
  inks: number[];
  /** Pages on the sheet, counting the one on the press. */
  pages: number;
  /** The shared words' ink: every page's added, up to solid. */
  share: number;
  fan: number[];
  /** Per figure place, how far its ghosts are scaled down to stay under the typical digit. */
  ghost: number[];
}

export interface Renderer {
  draw(frame: Frame): void;
  dispose(): void;
}
