import {
  between,
  densest,
  FAN_COLUMNS,
  fanColumns,
  fanLabels,
  fanTop,
  register,
  type Sheet,
  type Slot,
  TYPICAL_SHARE,
} from "./sheet-data";
import {
  ATLAS_PAD_PX,
  ATLAS_WIDTH_PX,
  BLANK_DROP_EM,
  BLANK_GLYPH,
  BLANK_INK,
  BLOCK_PX,
  BLOCK_UV,
  CROP_LENGTH_PX,
  CROP_OFFSET_PX,
  FAN_GAP_PX,
  FAN_SHEAR_PX,
  FLOOR_GLYPH,
  GHOST_GLYPH,
  type Glyph,
  type Layout,
  PAGE_GLYPH,
  type Place,
  type Rect,
  TICKER_GLYPH,
} from "./sheet-types";

export function fontOf(node: Element): { font: string; size: number } {
  const style = getComputedStyle(node);
  return {
    font: `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`,
    size: Number.parseFloat(style.fontSize),
  };
}

function textRect(node: Node, start: number, end: number): DOMRect | undefined {
  const range = document.createRange();
  range.setStart(node, start);
  range.setEnd(node, end);
  return range.getClientRects()[0];
}

// Canvas text has no font-feature control, so figures are set one by one on a fixed advance.
function digitAdvance(pen: CanvasRenderingContext2D): number {
  return Math.max(..."0123456789".split("").map((digit) => pen.measureText(digit).width));
}

/** The width of a number set in tabular figures in the pen's current font. */
export function tabularWidth(pen: CanvasRenderingContext2D, text: string): number {
  const advance = digitAdvance(pen);
  let width = 0;
  for (const char of text) width += /\d/.test(char) ? advance : pen.measureText(char).width;
  return width;
}

/** The separators between a slot's groups and their widths, set in the sentence's own weight. */
function separators(pen: CanvasRenderingContext2D, node: HTMLElement, count: number) {
  pen.font = fontOf(node.parentElement ?? node).font;
  const texts = [...Array(Math.max(0, count - 1)).keys()].map((group) => between(group, count));
  return {
    font: pen.font,
    texts,
    widths: texts.map((text) => pen.measureText(text).width),
  };
}

interface Mark {
  char: string;
  place: number;
  left: number;
  /** How far the mark shakes up from the baseline, in em; zero in register. */
  rise: number;
}

/**
 * A figure group set character by character on its typical value's tabular places: each
 * member's marks from `register`, every one inside the typical figure's box.
 */
function figureLayout(pen: CanvasRenderingContext2D, slot: Slot, group: number) {
  const typical = slot.groups[group] ?? "";
  const advance = digitAdvance(pen);
  const widthOf = (char: string) => (/\d/.test(char) ? advance : pen.measureText(char).width);
  const centres: number[] = [];
  let width = 0;
  for (const char of typical) {
    centres.push(width + widthOf(char) / 2);
    width += widthOf(char);
  }
  const set = (value: string): Mark[] =>
    register(typical, value).map(({ char, place, rise }) => ({
      char,
      place,
      left: (centres[place] ?? 0) - widthOf(char) / 2,
      rise,
    }));
  const marks = slot.values.map((value, member) =>
    value && slot.groupOf[member] === group ? set(value) : [],
  );
  return { width, marks, typical: set(typical) };
}

/** Each group's box in a slot: its widest member, figures with every mark they print. */
export function groupWidths(pen: CanvasRenderingContext2D, slot: Slot): number[] {
  return slot.groups.map((_, group) => {
    if (slot.fan) return figureLayout(pen, slot, group).width;
    return Math.max(
      0,
      ...slot.values
        .filter((_, member) => slot.groupOf[member] === group)
        .map((value) => (slot.numeric ? tabularWidth(pen, value) : pen.measureText(value).width)),
    );
  });
}

function fillTabular(pen: CanvasRenderingContext2D, text: string, x: number, y: number) {
  const advance = digitAdvance(pen);
  for (const char of text) {
    const width = /\d/.test(char) ? advance : pen.measureText(char).width;
    pen.fillText(char, x + (width - pen.measureText(char).width) / 2, y);
    x += width;
  }
}

/** Measure the typeset DOM page and rasterise its shared words and every member's slot strings. */
export function typeset(spread: HTMLElement, sheet: Sheet): Layout {
  const box = spread.getBoundingClientRect();
  const dpr = spread.classList.contains("narrow") ? 1 : Math.min(2, window.devicePixelRatio || 1);
  const styles = getComputedStyle(spread);
  const ink = styles.getPropertyValue("--ink").trim() || "#000";
  const paper = styles.getPropertyValue("--bg").trim() || "#fff";
  const alarm = styles.getPropertyValue("--alarm").trim() || ink;
  const page = document.createElement("canvas");
  page.width = Math.ceil(box.width * dpr);
  page.height = Math.ceil(box.height * dpr);
  const pen = page.getContext("2d");
  if (!pen) throw new Error("Canvas 2D is unavailable");
  pen.scale(dpr, dpr);
  pen.fillStyle = ink;

  const pageNode = spread.querySelector(".sheet-page");
  if (!pageNode) throw new Error("Missing sheet layout");
  const walker = document.createTreeWalker(pageNode, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      node.parentElement?.closest(".slot, .sr-only")
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT,
  });
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const parent = node.parentElement;
    if (!parent) continue;
    const { font } = fontOf(parent);
    const style = getComputedStyle(parent);
    pen.font = font;
    pen.letterSpacing = style.letterSpacing === "normal" ? "0px" : style.letterSpacing;
    // A line may break after a hyphen, so each hyphenated part is set where the DOM put it.
    for (const word of (node.textContent ?? "").matchAll(/[^\s\u00a0-]*-|[^\s\u00a0-]+/g)) {
      const range = document.createRange();
      range.setStart(node, word.index);
      range.setEnd(node, word.index + word[0].length);
      // A long token can wrap within a word; paint each character at its DOM position then.
      const parts = range.getClientRects().length > 1 ? [...word[0]] : [word[0]];
      let offset = word.index;
      for (const part of parts) {
        const rect = textRect(node, offset, offset + part.length);
        offset += part.length;
        if (!rect) continue;
        const text = style.textTransform === "uppercase" ? part.toUpperCase() : part;
        const ascent = pen.measureText(text).fontBoundingBoxAscent;
        pen.fillText(text, rect.left - box.left, rect.top - box.top + ascent);
      }
    }
  }
  // Every page carries the same crop marks, so they register and build up with the type.
  // They need a margin to stand in; where one would be cut off, as on a phone, none print.
  const frame = pageNode.getBoundingClientRect();
  const left = frame.left - box.left - CROP_OFFSET_PX;
  const right = frame.right - box.left + CROP_OFFSET_PX;
  const top = frame.top - box.top - CROP_OFFSET_PX;
  const bottom = frame.bottom - box.top + CROP_OFFSET_PX;
  const fits =
    Math.min(left, top) >= CROP_LENGTH_PX &&
    right + CROP_LENGTH_PX <= box.width &&
    bottom + CROP_LENGTH_PX <= box.height;
  for (const [x, y, dx, dy] of fits
    ? ([
        [left, top, -1, -1],
        [right, top, 1, -1],
        [left, bottom, -1, 1],
        [right, bottom, 1, 1],
      ] as const)
    : []) {
    pen.fillRect(Math.min(x, x + dx * CROP_LENGTH_PX), y, CROP_LENGTH_PX, 1);
    pen.fillRect(x, Math.min(y, y + dy * CROP_LENGTH_PX), 1, CROP_LENGTH_PX);
  }

  // Shelf-pack each distinct string once per font; members share entries.
  const measurer = document.createElement("canvas").getContext("2d");
  if (!measurer) throw new Error("Canvas 2D is unavailable");
  const atlasPen: CanvasRenderingContext2D = measurer;
  type Entry = {
    font: string;
    text: string;
    red: boolean;
    tabular: boolean;
    ascent: number;
    rect: Rect;
  };
  const entries = new Map<string, Entry>();
  let cursorX = BLOCK_PX;
  let cursorY = 0;
  let shelf = BLOCK_PX;
  function entry(font: string, text: string, red = false, tabular = false): Entry {
    const key = `${font}\n${text}\n${red}\n${tabular}`;
    const known = entries.get(key);
    if (known) return known;
    atlasPen.font = font;
    const metrics = atlasPen.measureText(text);
    const w = Math.ceil(tabular ? tabularWidth(atlasPen, text) : metrics.width) + 2 * ATLAS_PAD_PX;
    const h =
      Math.ceil(metrics.fontBoundingBoxAscent + metrics.fontBoundingBoxDescent) + 2 * ATLAS_PAD_PX;
    if (cursorX + w > ATLAS_WIDTH_PX) {
      cursorX = 0;
      cursorY += shelf;
      shelf = 0;
    }
    const made = {
      font,
      text,
      red,
      tabular,
      ascent: metrics.fontBoundingBoxAscent,
      rect: { x: cursorX, y: cursorY, w, h },
    };
    cursorX += w;
    shelf = Math.max(shelf, h);
    entries.set(key, made);
    return made;
  }

  const glyphs: Glyph[] = [];
  const places: Place[] = [];
  const fanNode = spread.querySelector(".fan-plot");
  const band = fanNode?.getBoundingClientRect();
  const fanFont = fontOf(fanNode ?? pageNode).font;
  // Overflow counts are set smaller and in italic so they never read as one more value.
  const fanStyle = getComputedStyle(fanNode ?? pageNode);
  const countFont = `italic 400 ${Number.parseFloat(fanStyle.fontSize) * 0.85}px ${fanStyle.fontFamily}`;
  const scaleTop = fanTop(sheet);
  let fans = 0;
  for (const node of pageNode.querySelectorAll<HTMLElement>(".slot")) {
    const slot = sheet.slots[Number(node.dataset.slot)];
    if (!slot) continue;
    const groups = [...node.querySelectorAll<HTMLElement>(".slot-group")];
    const { font, size } = fontOf(node);
    const baseline = (group: number) => {
      const node = groups[group];
      const text = node?.firstChild;
      const rect = text ? textRect(text, 0, text.textContent?.length ?? 0) : undefined;
      return (
        (rect?.top ?? node?.getBoundingClientRect().top ?? box.top) -
        box.top +
        entry(font, slot.typical).ascent
      );
    };
    // Each group prints in its own box along the line the DOM set.
    atlasPen.font = font;
    const widths = groupWidths(atlasPen, slot);
    const layouts = slot.fan
      ? slot.groups.map((_, group) => figureLayout(atlasPen, slot, group))
      : [];
    const gaps = separators(atlasPen, node, widths.length);
    // A separator lands solid with the first page of the group after it, so a cluster
    // and its "or" arrive together and leave together on a rewind.
    for (const [group, text] of gaps.texts.entries()) {
      const member = slot.groupOf.findIndex(
        (key, index) => key === group + 1 && slot.values[index],
      );
      if (member < 0) continue;
      const item = entry(gaps.font, text);
      const separator = node.querySelectorAll<HTMLElement>(".slot-separator")[group];
      const textNode = separator?.firstChild;
      const rect = textNode ? textRect(textNode, 0, text.length) : undefined;
      if (!rect) continue;
      const at = {
        x: rect.left - box.left - ATLAS_PAD_PX,
        y: baseline(group + 1) - item.ascent - ATLAS_PAD_PX,
        w: item.rect.w,
        h: item.rect.h,
      };
      glyphs.push({
        member,
        at,
        uv: item.rect,
        kind: PAGE_GLYPH,
        to: at,
        rank: 0,
        red: false,
        weight: slot.values.length,
      });
    }
    const kind = slot.ticker ? TICKER_GLYPH : PAGE_GLYPH;
    const groupLeft = (group: number) =>
      (groups[group]?.getBoundingClientRect().left ?? box.left) - box.left;
    const ats: Rect[] = [];
    // Each figure group's places, numbered across the sheet so the press can scale their ghosts.
    const firstPlace = layouts.map((layout, group) => {
      const start = places.length;
      const first = slot.values.findIndex((value, index) => value && slot.groupOf[index] === group);
      for (const _ of layout.typical) places.push({ first, agree: [], ghosts: [] });
      return start;
    });
    for (const [member, value] of slot.values.entries()) {
      const group = slot.groupOf[member] ?? 0;
      if (!value) continue;
      const red = slot.alarm[member] ?? false;
      const weight = slot.weight[member] ?? 1;
      const layout = layouts[group];
      // A figure prints character by character, so only agreeing digits share a place.
      const pieces = layout
        ? (layout.marks[member] ?? []).map((mark) => {
            const place = (firstPlace[group] ?? 0) + mark.place;
            places[place]?.[mark.rise ? "ghosts" : "agree"].push([member, weight]);
            return {
              item: entry(font, mark.char, red, true),
              x: groupLeft(group) + mark.left,
              rise: mark.rise * size,
              kind: mark.rise ? GHOST_GLYPH - place : kind,
            };
          })
        : [
            {
              item: entry(font, value, red, slot.numeric),
              x: groupLeft(group),
              rise: 0,
              kind,
            },
          ];
      for (const { item, x, rise, kind } of pieces) {
        const { w, h } = item.rect;
        // Counts sit flush right in their group's box; words and figure marks sit where set.
        const flush =
          slot.numeric && !slot.ticker && !layout ? (widths[group] ?? 0) - w + 2 * ATLAS_PAD_PX : 0;
        const at = {
          x: x - ATLAS_PAD_PX + flush,
          y: baseline(group) - item.ascent - ATLAS_PAD_PX - rise,
          w,
          h,
        };
        ats[member] ??= at;
        glyphs.push({
          member,
          at,
          uv: item.rect,
          kind,
          to: at,
          rank: 0,
          red,
          weight,
        });
      }
    }
    // The typical value prints from its group's first page, so a lone early page never reads
    // as the figure; its ghosts sit above or below it.
    for (const [group, layout] of layouts.entries()) {
      const typical = slot.groups[group];
      const holder = slot.values.findIndex(
        (value, index) => value === typical && slot.groupOf[index] === group,
      );
      for (const mark of layout.typical) {
        const place = places[(firstPlace[group] ?? 0) + mark.place];
        if (!place || place.first < 0) continue;
        const item = entry(font, mark.char, slot.alarm[holder] ?? false, true);
        const at = {
          x: groupLeft(group) + mark.left - ATLAS_PAD_PX,
          y: baseline(group) - item.ascent - ATLAS_PAD_PX,
          w: item.rect.w,
          h: item.rect.h,
        };
        glyphs.push({
          member: place.first,
          at,
          uv: item.rect,
          kind: FLOOR_GLYPH,
          to: at,
          rank: 0,
          red: slot.alarm[holder] ?? false,
          weight: TYPICAL_SHARE,
        });
      }
    }
    // Until a group's first page prints, a hairline holds its place in the sentence.
    for (const group of slot.ticker ? [] : slot.groups.keys()) {
      const member = slot.values.findIndex(
        (value, index) => value && slot.groupOf[index] === group,
      );
      if (member < 0) continue;
      const at = {
        x: groupLeft(group),
        y: baseline(group) + size * BLANK_DROP_EM,
        w: widths[group] ?? 0,
        h: 1,
      };
      glyphs.push({
        member,
        at,
        uv: BLOCK_UV,
        kind: BLANK_GLYPH,
        to: at,
        rank: 0,
        red: false,
        weight: BLANK_INK,
      });
    }
    if (!slot.fan || !band) continue;

    // The fan: each member's copy on a shared scale, binned into columns that rise from the
    // axis as tall as their share of members. Copies overprint up the column, sheared a few
    // pixels apart, and the column's typical value prints clear above them as its label.
    const fan = slot.fan;
    const fanIndex = fans++;
    const copies = slot.values.map((value, member) =>
      entry(fanFont, value, slot.alarm[member], true),
    );
    const columns = FAN_COLUMNS;
    const { placements, heights } = fanColumns(fan.values, scaleTop, columns);
    const labels = fanLabels(slot, scaleTop, columns);
    // On a narrow scale neighbouring columns' copies would collide, so a column too close to
    // the one before it joins it, under the label of the one holding a sheet figure, or more members.
    const widest = Math.max(...copies.map((item) => item.rect.w - 2 * ATLAS_PAD_PX));
    const owner = [...Array(columns).keys()];
    const onSheet = (column: number) => slot.groups.includes(labels[column] ?? "");
    let kept = -1;
    for (const [column, count] of heights.entries()) {
      if (!count) continue;
      if (kept < 0 || ((column - kept) * band.width) / columns >= widest + FAN_GAP_PX) {
        kept = column;
        continue;
      }
      const wins =
        onSheet(column) === onSheet(kept) ? count > (heights[kept] ?? 0) : onSheet(column);
      const [from, to] = wins ? [kept, column] : [column, kept];
      for (const [index, held] of owner.entries()) if (held === from) owner[index] = to;
      heights[to] = (heights[to] ?? 0) + (heights[from] ?? 0);
      heights[from] = 0;
      kept = to;
    }
    const rowHeight = (copies[0]?.rect.h ?? 14) - 2 * ATLAS_PAD_PX;
    // Two rows are kept above the tallest column, for its typical value and its count.
    const room = band.height - FAN_GAP_PX - 2 * rowHeight;
    const tallest = Math.max(1, ...heights);
    const rise = heights.map((count) =>
      count > 2
        ? (Math.min(
            room,
            Math.max(rowHeight + (count - 2) * FAN_SHEAR_PX, (room * count) / tallest),
          ) -
            rowHeight) /
          (count - 2)
        : 0,
    );
    const step = 10 ** -fan.decimals;
    const rounded = fan.values.map((value) =>
      value === null ? null : Number(value.toFixed(fan.decimals)),
    );
    const stacks = heights.map((_, column) => {
      const members = placements.flatMap((place, member) =>
        place && owner[place.column] === column ? [member] : [],
      );
      const values = members.map((member) => rounded[member] ?? 0);
      const label = labels[column];
      const typical = label
        ? Number(label.replaceAll(",", ""))
        : values.length
          ? densest(values, step)
          : 0;
      // Farthest from the typical value at the foot, the typical value itself last.
      return members.sort(
        (a, b) =>
          Math.abs((rounded[b] ?? 0) - typical) - Math.abs((rounded[a] ?? 0) - typical) || a - b,
      );
    });
    const order = fan.values
      .map((value, member) => ({
        value: value ?? Number.NEGATIVE_INFINITY,
        member,
      }))
      .sort((a, b) => a.value - b.value)
      .map((row) => row.member);
    const centre = (column: number) =>
      band.left - box.left + ((column + 0.5) * band.width) / columns;
    const foot = band.bottom - box.top - FAN_GAP_PX - rowHeight - ATLAS_PAD_PX;
    for (const [column, members] of stacks.entries()) {
      const label = members.length > 1 ? rowHeight : 0;
      const top = foot - Math.max(0, members.length - 2) * (rise[column] ?? 0) - label;
      for (const [height, member] of members.entries()) {
        const copy = copies[member];
        if (!copy || !ats[member]) continue;
        const x = centre(column) - copy.rect.w / 2;
        const y = height === members.length - 1 ? top : foot - height * (rise[column] ?? 0);
        glyphs.push({
          member,
          // Copies start on the axis under their column, so the fan never crosses the page.
          at: { x, y: foot, w: copy.rect.w, h: copy.rect.h },
          uv: copy.rect,
          kind: fanIndex,
          to: { x, y, w: copy.rect.w, h: copy.rect.h },
          rank: order.indexOf(member) / order.length,
          red: slot.alarm[member] ?? false,
          weight: 1,
        });
      }
      if (members.length < 2) continue;
      const count = entry(countFont, `\u00d7${members.length}`);
      const to = {
        x: centre(column) - count.rect.w / 2,
        y: top - rowHeight,
        w: count.rect.w,
        h: count.rect.h,
      };
      // Printed by the last page, so the count only shows on the full sheet it describes.
      glyphs.push({
        member: sheet.members.length - 1,
        at: to,
        uv: count.rect,
        kind: fanIndex,
        to,
        rank: 1,
        red: false,
        weight: 1,
      });
    }
  }

  const atlas = document.createElement("canvas");
  atlas.width = Math.ceil(ATLAS_WIDTH_PX * dpr);
  atlas.height = Math.max(1, Math.ceil((cursorY + shelf) * dpr));
  const atlasDraw = atlas.getContext("2d");
  if (!atlasDraw) throw new Error("Canvas 2D is unavailable");
  atlasDraw.scale(dpr, dpr);
  atlasDraw.fillStyle = ink;
  atlasDraw.fillRect(0, 0, BLOCK_PX, BLOCK_PX);
  for (const item of entries.values()) {
    atlasDraw.font = item.font;
    atlasDraw.fillStyle = item.red ? alarm : ink;
    const x = item.rect.x + ATLAS_PAD_PX;
    const y = item.rect.y + ATLAS_PAD_PX + item.ascent;
    if (item.tabular) fillTabular(atlasDraw, item.text, x, y);
    else atlasDraw.fillText(item.text, x, y);
  }

  return {
    width: box.width,
    height: box.height,
    dpr,
    page,
    atlas,
    glyphs,
    paper,
    ink,
    alarm,
    members: sheet.members.length,
    places,
  };
}
