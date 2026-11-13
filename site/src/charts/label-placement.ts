export interface LabelBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

const LABEL_GAP = 6;
const LABEL_HEIGHT = 24;

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

/** Anchor the threshold to its line and shift a colliding count within the band. */
export function placeBandLabels(
  band: LabelBox,
  cursorX: number,
  countWidth: number,
  threshold: { y: number; width: number } | null,
): { count: LabelBox; threshold: LabelBox | null } {
  const left = band.x + LABEL_GAP;
  const right = band.x + band.width - LABEL_GAP;
  const top = band.y + LABEL_GAP;
  const bottom = band.y + band.height - LABEL_GAP;
  const count = {
    x: clamp(cursorX - countWidth / 2, left, right - countWidth),
    y: top,
    width: countWidth,
    height: LABEL_HEIGHT,
  };
  if (!threshold) return { count, threshold: null };
  const label = {
    x: left,
    y: clamp(threshold.y - LABEL_HEIGHT / 2, top, bottom - LABEL_HEIGHT),
    width: threshold.width,
    height: LABEL_HEIGHT,
  };
  const overlapX = count.x < label.x + label.width + LABEL_GAP;
  const overlapY = count.y + count.height + LABEL_GAP > label.y;
  if (overlapX && overlapY) count.y = label.y + label.height + LABEL_GAP;
  return { count, threshold: label };
}
