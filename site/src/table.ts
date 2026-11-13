import { element } from "./dom";

export function scrollableTable(table: HTMLTableElement, label: string): HTMLElement {
  const scroll = element("div");
  scroll.style.overflowX = "auto";
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", label);
  table.style.borderSpacing = "1rem 0.5rem";
  table.style.whiteSpace = "nowrap";
  const caption = table.querySelector("caption");
  if (caption) caption.style.textAlign = "left";
  scroll.append(table);
  return scroll;
}
