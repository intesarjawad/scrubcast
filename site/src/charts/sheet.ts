import { element } from "../dom";
import type { LaunchAssessment } from "../types";
import { buildSheet, fanSummary, pressSchedule } from "./sheet-data";
import { fontOf, groupWidths, typeset } from "./sheet-layout";
import { createSpread } from "./sheet-page";
import { drawStill, ghostScales } from "./sheet-still";
import type { Frame, Layout, Renderer } from "./sheet-types";

const FAN_MS = 900;
/** A page strikes at full ink this long before it settles to its share. */
const STRIKE_MS = 80;
const NARROW_PX = 700;
const SLOW_FRAMES = 5;

export interface SheetOptions {
  signal: AbortSignal;
  still?: boolean;
  onPrinted?: () => void;
}

/** The first viewport: every member's page for the evening, overprinted on one sheet. */
export function sheetSpread(
  assessment: LaunchAssessment,
  notes: { intro: HTMLElement; facts: HTMLElement },
  options: SheetOptions,
): HTMLElement {
  if (
    assessment.tier === "C" ||
    assessment.rules.every((rule) =>
      Object.values(rule.by_model).every((risk) => risk.risk_fraction === null),
    )
  ) {
    const state = element("section");
    state.append(
      notes.intro,
      element(
        "p",
        assessment.tier === "C"
          ? "No rule assessment is published for this pad."
          : "Rule assessment not available.",
      ),
    );
    state.append(notes.facts);
    options.onPrinted?.();
    return state;
  }
  const sheet = buildSheet(assessment);
  const total = sheet.members.length;
  const {
    spread,
    page,
    caption,
    range,
    fanSlots,
    showCount,
    canvas: initialCanvas,
  } = createSpread(assessment, sheet, notes);
  let canvas = initialCanvas;

  if (!sheet.complete || total === 0) {
    range.disabled = true;
    return spread;
  }

  const fanState = fanSlots.map(() => 0);
  const fanStart = fanSlots.map(() => 0);
  const fanFrom = fanSlots.map(() => 0);
  let fanTarget = Math.max(
    0,
    fanSlots.findIndex((slot) => slot.fan?.t0),
  );
  let active = -1;
  let captioned = -1;
  const showCaption = (index: number) => {
    const fan = fanSlots[index]?.fan;
    if (fan) caption.textContent = fanSummary(fan, total);
    captioned = index;
  };

  // Forced colours hide the canvas, so there is no press run to wait through.
  let still = options.still === true;
  const preferences = matchMedia("(prefers-reduced-motion: reduce), (forced-colors: active)");
  const theme = matchMedia("(prefers-color-scheme: dark)");
  let reduced = still || preferences.matches;
  const schedule = pressSchedule(total);
  const pressEnd = Math.max(...schedule.map((slot) => slot.start + slot.duration)) + STRIKE_MS;
  let slowFrames = 0;
  let clock = 0;
  let last = 0;
  let running = !reduced;
  // Every page printed so far holds an equal share, so the sheet reads the same densities
  // at 38 pages as at 82: of the pages on it.
  let pages = reduced ? total : 0;
  const inks = schedule.map(() => (reduced ? 1 / total : 0));
  const rewind = (count: number) => {
    pages = count;
    for (const member of inks.keys()) inks[member] = member < count ? 1 / count : 0;
  };
  const showLanded = () => {
    showCount(Math.max(1, pages));
    range.value = String(Math.max(1, pages));
  };
  let renderer: Renderer | null = null;
  let layout: Layout | null = null;
  let frameId = 0;
  let visible = true;

  function frame(): Frame {
    if (running) {
      // A page strikes heavier than its share, then settles to it over its own duration. Every
      // printed page keeps its share, and the pages still striking share one page more between
      // them, so a burst of strikes never over-inks the sheet or fades the settled pages.
      pages = schedule.filter((slot) => clock >= slot.start).length;
      const share = 1 / Math.max(1, pages);
      const surplus = schedule.map((slot) => {
        const elapsed = clock - slot.start;
        const strike = Math.max(0, 1 - Math.max(0, elapsed - STRIKE_MS) / slot.duration);
        return elapsed < 0 ? 0 : (1 - share) * strike;
      });
      const extra = Math.max(
        1,
        surplus.reduce((total, value) => total + value, 0),
      );
      for (const [member, slot] of schedule.entries())
        inks[member] = clock < slot.start ? 0 : share + (surplus[member] ?? 0) / extra;
      showLanded();
      if (clock >= pressEnd) {
        rewind(total);
        running = false;
        spread.dataset.phase = "set";
        setFan(fanTarget);
      }
    }
    const ink = inks.reduce((sum, value) => sum + value, 0);
    return {
      inks: [...inks],
      pages,
      share: Math.min(1, ink),
      fan: [...fanState],
      ghost: layout ? ghostScales(layout.places, inks) : [],
    };
  }

  function animating(): boolean {
    return running || fanState.some((value, index) => value !== (index === active ? 1 : 0));
  }

  function tick(now: number) {
    frameId = 0;
    const step = last ? Math.min(now - last, 50) : 16;
    // A renderer that cannot hold 20 fps for five frames running (software GL, a weak GPU)
    // gets the finished sheet, and the fan stops travelling.
    slowFrames = last && now - last > 50 ? slowFrames + 1 : 0;
    if (!still && slowFrames >= SLOW_FRAMES) {
      still = true;
      reprint();
      return;
    }
    last = now;
    clock += step;
    for (const [index] of fanState.entries()) {
      const goal = index === active ? 1 : 0;
      const elapsed = clock - (fanStart[index] ?? 0);
      const from = fanFrom[index] ?? 0;
      fanState[index] = reduced ? goal : from + (goal - from) * Math.min(1, elapsed / FAN_MS);
    }
    // The caption names the new hour only once the old hour's columns are off the scale.
    if (
      active >= 0 &&
      captioned !== active &&
      fanState.every((value, index) => index === active || value === 0)
    )
      showCaption(active);
    renderer?.draw(frame());
    if (animating() && visible) frameId = requestAnimationFrame(tick);
    else last = 0;
  }

  function wake() {
    if (!frameId && renderer) frameId = requestAnimationFrame(tick);
  }

  function setFan(index: number) {
    if (index === active || !fanSlots[index]) return;
    for (const [order, node] of figureNodes.entries())
      node.toggleAttribute("data-active", order === index);
    for (const [slot, value] of fanState.entries()) {
      fanFrom[slot] = value;
      fanStart[slot] = clock;
    }
    active = index;
    fanTarget = index;
    wake();
  }

  const figureNodes = [...page.querySelectorAll<HTMLButtonElement>("button.figure")];
  for (const node of figureNodes) {
    const index = fanSlots.indexOf(
      sheet.slots[Number(node.dataset.slot)] as (typeof fanSlots)[number],
    );
    const pick = () => {
      if (!running) setFan(index);
      else fanTarget = index;
    };
    node.addEventListener("pointerenter", pick);
    node.addEventListener("focus", pick);
    node.addEventListener("click", pick);
  }
  showCaption(fanTarget);

  range.addEventListener("input", () => {
    running = false;
    spread.dataset.phase = "set";
    rewind(Number(range.value));
    showLanded();
    if (active < 0) setFan(fanTarget);
    wake();
  });

  let revision = 0;
  async function start() {
    const version = ++revision;
    await document.fonts.ready;
    if (options.signal.aborted || !spread.isConnected || version !== revision) return;
    spread.dataset.printed = "false";
    spread.classList.toggle("narrow", spread.getBoundingClientRect().width < NARROW_PX);
    const pen = document.createElement("canvas").getContext("2d");
    if (!pen) return;
    // Every slot is as wide as its printed groups and separators, not its DOM text.
    for (const node of page.querySelectorAll<HTMLElement>(".slot")) {
      const slot = sheet.slots[Number(node.dataset.slot)];
      if (!slot) continue;
      pen.font = fontOf(node).font;
      const widths = groupWidths(pen, slot);
      for (const [group, cluster] of [
        ...node.querySelectorAll<HTMLElement>(".slot-group"),
      ].entries())
        cluster.style.width = `${Math.ceil(widths[group] ?? 0)}px`;
    }
    layout = typeset(spread, sheet);
    renderer?.dispose();
    renderer = null;
    // A lost context stays lost on its canvas, so each layout gets a fresh one.
    const fresh = element("canvas", "", "sheet-canvas");
    fresh.setAttribute("aria-hidden", "true");
    canvas.replaceWith(fresh);
    canvas = fresh;
    if (!still) {
      const { createRenderer } = await import("./sheet-gl");
      if (options.signal.aborted || version !== revision) return;
      try {
        renderer = createRenderer(canvas, layout);
      } catch {
        renderer = null;
      }
    }
    if (!renderer) {
      still = true;
      reduced = true;
      if (running) rewind(total);
      running = false;
      showLanded();
      // A canvas that acquired WebGL cannot also supply a 2D context.
      const fallback = element("canvas", "", "sheet-canvas");
      fallback.setAttribute("aria-hidden", "true");
      canvas.replaceWith(fallback);
      canvas = fallback;
    }
    const current = layout;
    const target = canvas;
    renderer ??= {
      draw: (state) => drawStill(target, current, state),
      dispose: () => undefined,
    };
    if (reduced) {
      active = fanTarget;
      fanState[active] = 1;
    }
    renderer.draw(frame());
    spread.dataset.printed = "true";
    spread.dataset.phase = running ? "press" : "set";
    wake();
    options.onPrinted?.();
  }

  function reprint() {
    void start().catch(() => {
      spread.dataset.printed = "false";
    });
  }

  const changed = () => {
    reduced = still || preferences.matches;
    if (reduced && running) {
      running = false;
      rewind(total);
      showLanded();
    }
    reprint();
  };
  theme.addEventListener("change", changed);
  preferences.addEventListener("change", changed);

  const resize = new ResizeObserver(() => {
    const bounds = spread.getBoundingClientRect();
    spread.classList.toggle("narrow", bounds.width < NARROW_PX);
    if (
      layout &&
      (Math.abs(bounds.width - layout.width) > 1 || Math.abs(bounds.height - layout.height) > 1)
    )
      reprint();
  });
  const seen = new IntersectionObserver(([entry]) => {
    visible = entry?.isIntersecting ?? true;
    if (visible && animating()) wake();
  });
  const hidden = () => {
    if (document.hidden) last = 0;
  };
  document.addEventListener("visibilitychange", hidden);
  options.signal.addEventListener(
    "abort",
    () => {
      cancelAnimationFrame(frameId);
      resize.disconnect();
      seen.disconnect();
      document.removeEventListener("visibilitychange", hidden);
      theme.removeEventListener("change", changed);
      preferences.removeEventListener("change", changed);
      renderer?.dispose();
    },
    { once: true },
  );
  requestAnimationFrame(() => {
    resize.observe(spread);
    seen.observe(spread);
    reprint();
  });
  return spread;
}
