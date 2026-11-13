import { element } from "../dom";
import type { LaunchAssessment } from "../types";
import { between, fanTop, limitText, type Sheet } from "./sheet-data";

function slotNode(sheet: Sheet, index: number): HTMLElement {
  const slot = sheet.slots[index];
  const node = slot?.fan ? element("button", "", "slot figure") : element("span", "", "slot");
  if (slot?.numeric) node.classList.add("num");
  node.dataset.slot = String(index);
  if (node instanceof HTMLButtonElement) node.type = "button";
  const text = element("span", "", "slot-text");
  text.setAttribute("aria-hidden", "true");
  for (const [group, value] of (slot?.groups ?? []).entries()) {
    const cluster = element("span", "", "slot-cluster");
    if (group)
      cluster.append(
        element("span", between(group - 1, slot?.groups.length ?? 0), "slot-separator"),
      );
    cluster.append(element("span", value, "slot-group"));
    text.append(cluster);
  }
  node.append(text, element("span", slot?.label ?? "", "sr-only"));
  return node;
}

export function createSpread(
  assessment: LaunchAssessment,
  sheet: Sheet,
  notes: { intro: HTMLElement; facts: HTMLElement },
) {
  const total = sheet.members.length;
  const spread = element("section", "", "spread");
  spread.setAttribute("aria-labelledby", "sheet-title");
  const canvas = element("canvas", "", "sheet-canvas");
  canvas.setAttribute("aria-hidden", "true");

  const page = element("div", "", "sheet-page");
  page.dataset.state = sheet.complete ? "typeset" : "pending";
  for (const paragraph of sheet.paragraphs) {
    const block = element("p", "", `page-${paragraph.kind}`);
    if (paragraph.kind === "who") block.setAttribute("aria-hidden", "true");
    let rest = "";
    for (const [order, part] of paragraph.parts.entries()) {
      if (typeof part === "string") {
        block.append(part.slice(rest.length));
        rest = "";
        continue;
      }
      // A slot keeps its unit and punctuation on its line.
      const next = paragraph.parts[order + 1];
      rest = typeof next === "string" ? (/^[^ \n]*/.exec(next)?.[0] ?? "") : "";
      const keep = element("span", "", "keep");
      keep.append(slotNode(sheet, part), rest);
      block.append(keep);
    }
    page.append(block);
  }

  const fanSlots = sheet.slots.filter((slot) => slot.fan);
  const fanFigure = element("figure", "", "fan");
  const plot = element("div", "", "fan-plot");
  plot.setAttribute("aria-hidden", "true");
  const limit = fanSlots[0]?.fan;
  if (limit) {
    const top = fanTop(sheet);
    const mark = element("span", `limit ${limitText(limit.limit)} ${limit.unit}`, "fan-limit");
    const at = (limit.limit / top) * 100;
    // Past three quarters of the scale the label hangs to the left of its line.
    if (at > 75) {
      mark.classList.add("flip");
      mark.style.right = `${100 - at}%`;
    } else mark.style.left = `${at}%`;
    // Ticks at 1, 2 or 5 times a power of ten, no more than eight across the scale.
    const power = 10 ** Math.floor(Math.log10(top / 8));
    const step = [1, 2, 5, 10].map((unit) => unit * power).find((size) => top / size <= 8) ?? top;
    for (let value = 0; value < top; value += step) {
      const tick = element("span", limitText(value), "fan-tick");
      tick.style.left = `${(value / top) * 100}%`;
      plot.append(tick);
    }
    plot.append(mark);
  }
  const caption = element("figcaption", "", "fan-caption");
  caption.setAttribute("aria-live", "polite");
  fanFigure.append(plot, caption);

  const unseen = element("section", "", "unseen");
  unseen.setAttribute("aria-labelledby", "unseen-title");
  const unseenTitle = element("h2", `Left blank on all ${total} pages`);
  unseenTitle.id = "unseen-title";
  const unseenList = element("ul");
  for (const omitted of assessment.not_evaluable) {
    const item = element("li");
    item.append(element("span", omitted.title), element("small", omitted.reason));
    unseenList.append(item);
  }
  unseen.append(
    unseenTitle,
    element(
      "p",
      `Each page checks ${assessment.rules.length} rules. These ${assessment.not_evaluable.length} have no model field or no published limit for this launch, so a clean page cannot clear them.`,
    ),
    unseenList,
  );

  const sheetColumn = element("div", "", "sheet");
  sheetColumn.append(page);
  if (limit) sheetColumn.append(fanFigure);

  const aside = element("div", "", "sheet-notes");
  const title = element("p", "One launch window, ", "sheet-title");
  title.id = "sheet-title";
  title.append(element("em", `printed ${total} times.`));
  const legend = element(
    "p",
    "Every ensemble member writes the same page for the launch window, and all of them are printed on one sheet. Where the members agree the ink is solid. Where they disagree it blurs.",
    "sheet-legend",
  );
  const control = element("div", "", "pages-control");
  const label = element("label");
  label.htmlFor = "pages";
  // Not an <output>: its implicit live region would announce every page of the press run.
  const output = element("span", "", "pages-count");
  output.setAttribute("aria-hidden", "true");
  label.append(element("span", "Pages on the sheet"), output);
  const range = element("input");
  range.type = "range";
  range.id = "pages";
  range.min = "1";
  range.max = String(total);
  const showCount = (count: number) => {
    output.textContent = `${count} of ${total}`;
    range.setAttribute("aria-valuetext", `${count} of ${total} pages`);
  };
  showCount(total);
  range.value = String(total);
  control.append(label, range);
  aside.append(notes.intro);
  if (assessment.tier === "B")
    aside.append(
      element(
        "p",
        "Reference only: these rules are not established launch criteria for this pad.",
        "badge",
      ),
    );
  aside.append(title, legend, control, notes.facts);
  const grid = element("div", "", "spread-grid");
  grid.append(sheetColumn, aside);
  if (assessment.not_evaluable.length) grid.append(unseen);
  spread.append(canvas, grid);

  return { spread, canvas, page, caption, range, fanSlots, showCount };
}
