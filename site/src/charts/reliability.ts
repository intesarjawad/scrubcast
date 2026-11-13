import { element } from "../dom";
import { percent } from "../format";
import { scrollableTable } from "../table";
import type { ReliabilityBin } from "../types";
import { svgNode } from "./svg";

const WIDTH = 320;
const HEIGHT = 220;
const PADDING = 50;

function pointX(value: number): number {
  return PADDING + value * (WIDTH - PADDING * 2);
}

function pointY(value: number): number {
  return HEIGHT - PADDING - value * (HEIGHT - PADDING * 2);
}

export function reliabilityChart(bins: ReliabilityBin[], n: number): HTMLElement {
  const figure = element("figure", "", "reliability");
  const caption = element(
    "figcaption",
    `Reliability: predicted risk against observed frequency (n=${n}).`,
  );
  figure.append(caption);
  if (bins.every((bin) => bin.n === 0)) {
    figure.append(element("p", `insufficient data (n=${n})`));
    return figure;
  }
  const svg = svgNode("svg", {
    viewBox: `0 0 ${WIDTH} ${HEIGHT}`,
    role: "img",
    "aria-label": "Reliability diagram of predicted risk against observed frequency",
  });
  svg.style.maxWidth = "480px";
  svg.style.width = "100%";
  svg.append(
    svgNode("line", {
      x1: pointX(0),
      y1: pointY(0),
      x2: pointX(1),
      y2: pointY(1),
      class: "reference",
      stroke: "var(--ink)",
      "stroke-opacity": 0.65,
      "stroke-dasharray": "4 3",
    }),
  );
  for (const [index, bin] of bins.entries()) {
    if (bin.predicted === null || bin.observed === null || bin.n === 0) continue;
    const circle = svgNode("circle", {
      cx: pointX(bin.predicted),
      cy: pointY(bin.observed),
      r: String(4 + Math.min(8, bin.n / 10)),
      class: "bin",
      fill: "var(--ink)",
    });
    const title = svgNode("title");
    title.textContent = `Bin ${index + 1}: predicted ${percent(bin.predicted)}, observed ${percent(bin.observed)} (n=${bin.n})`;
    circle.append(title);
    svg.append(circle);
  }
  for (const tick of [0, 0.5, 1]) {
    for (const [x, y, anchor] of [
      [pointX(tick), pointY(0) + 16, "middle"],
      [pointX(0) - 5, pointY(tick) + 4, "end"],
    ] as const) {
      const label = svgNode("text", {
        x,
        y,
        "text-anchor": anchor,
        fill: "var(--ink)",
        "font-size": 10,
      });
      label.textContent = percent(tick);
      svg.append(label);
    }
  }
  const vertical = svgNode("text", {
    x: 10,
    y: HEIGHT / 2,
    transform: `rotate(-90 10 ${HEIGHT / 2})`,
    "text-anchor": "middle",
    fill: "var(--ink)",
    "font-size": 10,
  });
  vertical.textContent = "Observed frequency";
  svg.append(vertical);
  const axis = svgNode("text", {
    x: WIDTH / 2,
    y: HEIGHT - 6,
    "text-anchor": "middle",
    class: "axis-label",
    fill: "var(--ink)",
    "font-size": 10,
  });
  axis.textContent = "Predicted risk";
  svg.append(axis);
  figure.append(svg);
  const table = element("table", "", "reliability-table");
  table.append(element("caption", `Reliability bins (n=${n})`));
  const head = table.createTHead().insertRow();
  for (const label of ["Bin", "n", "Predicted", "Observed"]) {
    const cell = element("th", label);
    cell.scope = "col";
    head.append(cell);
  }
  const body = table.createTBody();
  for (const bin of bins) {
    const row = body.insertRow();
    row.insertCell().textContent = `${percent(bin.lower)} to ${percent(bin.upper)}`;
    row.insertCell().textContent = `n=${bin.n}`;
    row.insertCell().textContent =
      bin.predicted === null
        ? `insufficient data (n=${bin.n})`
        : `${percent(bin.predicted)} (n=${bin.n})`;
    row.insertCell().textContent =
      bin.observed === null
        ? `insufficient data (n=${bin.n})`
        : `${percent(bin.observed)} (n=${bin.n})`;
  }
  const scroll = scrollableTable(table, "Scrollable reliability table");
  figure.append(scroll);
  return figure;
}
