import { padLocalTime, utcTime } from "../format";
import { models } from "../launch-data";
import type { LaunchAssessment, RuleRisk } from "../types";
import { type LabelBox, placeBandLabels } from "./label-placement";
import { hourEvidence, memberScale } from "./scrubber-data";
import { svgNode } from "./svg";

// Match the Public Sans count and caption tokens, with room for the opaque text halo.
const LABEL_METRICS = { countFontSize: 15, thresholdFontSize: 13, haloWidth: 8 };

// The compact geometry is also used by the fixed-size share cards.
const CARD_PLOT = {
  height: 280,
  mobileWidth: 600,
  left: 48,
  mobileLeft: 32,
  right: 16,
  top: 34,
  paneHeight: 74,
  paneOffset: 116,
  cursorBottom: 234,
  handleWidth: 168,
  mobileHandleWidth: 116,
  handleHeight: 44,
  handleRadius: 6,
  labelY: 22,
  tickY: 251,
  utcY: 273,
  handleLocalY: 252,
  handleUtcY: 271,
  countX: 148,
  frameInset: 8,
  modelNameWidth: 44,
  gapLabelY: 119,
  tZeroTop: 25,
  tZeroInset: 10,
  cardLeft: 226,
  cardModelY: 38,
  cardCountY: 82,
  cardRiskY: 108,
};

// Two 140 px data bands keep 280 px of evidence, with labels and controls outside.
const INTERACTIVE_PLOT = {
  ...CARD_PLOT,
  height: 400,
  mobileLeft: 44,
  paneHeight: 140,
  paneOffset: 180,
  cursorBottom: 354,
  tickY: 373,
  utcY: 394,
  handleLocalY: 373,
  handleUtcY: 392,
  mobileHandleWidth: 132,
  gapLabelY: 188,
};

function text(label: string, x: number, y: number, className: string, anchor = "start") {
  const node = svgNode("text", { x, y, class: className, "text-anchor": anchor });
  if (className === "axis-label") node.setAttribute("font-size", "var(--text-xs)");
  const value = document.createTextNode(label);
  node.append(value);
  return { node, value };
}

export function scrubberPlot(
  assessment: LaunchAssessment,
  rule: RuleRisk,
  width: number,
  presentation: "interactive" | "card" = "interactive",
) {
  const card = presentation === "card";
  const PLOT = card ? CARD_PLOT : INTERACTIVE_PLOT;
  const mobile = width < PLOT.mobileWidth;
  const left = card ? PLOT.cardLeft : mobile ? PLOT.mobileLeft : PLOT.left;
  const right = width - PLOT.right;
  const times = rule.hours.map(Date.parse);
  const net = Date.parse(assessment.launch.net);
  const first = Math.min(times[0] ?? net, net, Date.parse(assessment.launch.window_start));
  const last = Math.max(times.at(-1) ?? net, net, Date.parse(assessment.launch.window_end));
  const x = (time: number) => left + ((time - first) / (last - first || 1)) * (right - left);
  const scale = memberScale(rule);
  const { min, max } = scale;
  const svg = svgNode("svg", {
    viewBox: `0 0 ${width} ${PLOT.height}`,
    class: "plot",
    "data-domain-start": first,
    "data-domain-end": last,
    role: "img",
    "aria-label": `${rule.title}: ECMWF and GFS members on one time axis and ${rule.plot.unit} scale`,
    focusable: "false",
  });
  const traces: { node: SVGPathElement; classes: string[] }[] = [];
  const directLabels = svgNode("g", {
    class: "direct-labels",
    "paint-order": "stroke fill",
    stroke: "var(--bg)",
    "stroke-width": "var(--s2)",
    "stroke-linejoin": "round",
  });
  const counts: { node: Text; labels: string[]; parent: SVGTextElement; signals: boolean[] }[] = [];
  const placements: { count: SVGTextElement; positions: LabelBox[] }[] = [];
  const panes: SVGGElement[] = [];
  for (const [paneIndex, model] of models.entries()) {
    const top = PLOT.top + paneIndex * PLOT.paneOffset;
    const bottom = top + PLOT.paneHeight;
    const y = (value: number) => bottom - scale.fraction(value) * PLOT.paneHeight;
    const pane = svgNode("g", {
      class: `model-pane pane-${model}`,
      "data-model": model,
      "data-scale-max": max,
      "data-plot-left": left,
      "data-plot-right": right,
    });
    panes.push(pane);
    pane.append(
      text(
        model.toUpperCase(),
        // On a phone the first hour sits on the axis, so the name moves to the right edge.
        card ? 0 : mobile ? right : left,
        (card ? PLOT.cardModelY : PLOT.labelY) + paneIndex * PLOT.paneOffset,
        "model-name",
        mobile && !card ? "end" : "start",
      ).node,
    );
    const count = text(
      card ? "N/A" : "",
      card ? 0 : mobile ? right : PLOT.countX,
      (card ? PLOT.cardCountY : PLOT.labelY) + paneIndex * PLOT.paneOffset,
      "pane-count",
      mobile && !card ? "end" : "start",
    );
    counts.push({
      node: count.value,
      parent: count.node,
      signals: rule.hours.map((_, hour) => hourEvidence(rule, model, hour).violated > 0),
      labels: rule.hours.map((_, hour) => {
        const evidence = hourEvidence(rule, model, hour);
        if (card) return evidence.evaluable ? `${evidence.violated}/${evidence.evaluable}` : "N/A";
        return evidence.count;
      }),
    });
    if (card) pane.append(count.node);
    else {
      count.node.dataset.model = model;
      count.node.setAttribute("text-anchor", "middle");
      count.node.setAttribute("dominant-baseline", "central");
      const thresholdLabel = rule.threshold
        ? `${Number(rule.threshold.value.toPrecision(3))} ${rule.threshold.unit}`
        : null;
      // One font-size per character reserves more than a glyph advance, even before fonts load.
      const countWidth =
        Math.max(...rule.hours.map((_, hour) => hourEvidence(rule, model, hour).count.length)) *
          LABEL_METRICS.countFontSize +
        LABEL_METRICS.haloWidth;
      const positions = times.map((time) =>
        placeBandLabels(
          { x: left, y: top, width: right - left, height: PLOT.paneHeight },
          x(time),
          countWidth,
          rule.threshold && thresholdLabel
            ? {
                y: y(rule.threshold.value),
                width:
                  thresholdLabel.length * LABEL_METRICS.thresholdFontSize + LABEL_METRICS.haloWidth,
              }
            : null,
        ),
      );
      placements.push({
        count: count.node,
        positions: positions.map((position) => position.count),
      });
      const thresholdPosition = positions[0]?.threshold;
      if (thresholdLabel && thresholdPosition) {
        const label = text(
          thresholdLabel,
          thresholdPosition.x + thresholdPosition.width / 2,
          thresholdPosition.y + thresholdPosition.height / 2,
          "threshold-label",
          "middle",
        ).node;
        label.dataset.model = model;
        label.setAttribute("dominant-baseline", "central");
        directLabels.append(label);
      }
      directLabels.append(count.node);
    }
    if (card) {
      const evidence = hourEvidence(rule, model, assessment.t0_index);
      pane.append(
        text(
          evidence.evaluable ? evidence.risk : "No evaluable members",
          0,
          PLOT.cardRiskY + paneIndex * PLOT.paneOffset,
          "card-risk",
        ).node,
      );
    }
    for (const value of [min, max]) {
      pane.append(
        svgNode("line", {
          class: "axis",
          stroke: "var(--graphic)",
          x1: left,
          // The baseline runs the width; the top of the scale is only a tick.
          x2: value === min ? right : left + PLOT.frameInset,
          y1: y(value),
          y2: y(value),
        }),
        text(
          String(Number(value.toPrecision(3))),
          left - PLOT.frameInset,
          y(value) + PLOT.frameInset / 2,
          "axis-label",
          "end",
        ).node,
      );
    }
    const matrix = rule.member_values_by_hour[model] ?? [];
    for (const extreme of [Math.min, Math.max]) {
      const points = matrix.map((row, hour) => {
        const available = row.filter((v) => v !== null);
        return available.length ? `${x(times[hour] ?? first)},${y(extreme(...available))}` : null;
      });
      // Missing hours break the envelope rather than suggesting interpolated evidence.
      pane.append(
        svgNode("path", {
          class: "envelope",
          d: points
            .map((point, hour) =>
              point === null
                ? ""
                : `${hour === 0 || points[hour - 1] === null ? "M" : "L"}${point}`,
            )
            .join(" "),
        }),
      );
    }
    const members = Math.max(0, ...matrix.map((row) => row.length));
    for (let member = 0; member < members; member++) {
      let penDown = false;
      const d = matrix
        .map((row, hour) => {
          const value = row[member];
          if (value == null) {
            penDown = false;
            return "";
          }
          const segment = `${penDown ? "L" : "M"}${x(times[hour] ?? first)},${y(value)}`;
          penDown = true;
          return segment;
        })
        .join(" ");
      const node = svgNode("path", { class: "member", d, "data-member": member });
      const classes = rule.hours.map(
        (_, hour) =>
          `member${rule.member_violated_by_hour[model]?.[hour]?.[member] === 1 ? " exceed" : ""}`,
      );
      traces.push({ node, classes });
      pane.append(node);
    }
    if (rule.threshold)
      pane.append(
        svgNode("line", {
          class: "threshold",
          stroke: "var(--rule)",
          "stroke-width": "var(--stroke)",
          "stroke-dasharray": "8 5",
          "data-threshold": rule.threshold.value,
          x1: left,
          x2: right,
          y1: y(rule.threshold.value),
          y2: y(rule.threshold.value),
        }),
      );
    svg.append(pane);
  }
  const netX = x(Date.parse(assessment.launch.net));
  const fixedMarker = svgNode("g", { class: "t-zero" });
  fixedMarker.append(
    svgNode("line", {
      class: "t-zero-line",
      stroke: card ? "var(--ink)" : "var(--muted)",
      "stroke-width": card ? "var(--hair)" : "var(--stroke)",
      "stroke-dasharray": "4 3",
      x1: netX,
      x2: netX,
      y1: PLOT.tZeroTop,
      y2: PLOT.cursorBottom,
    }),
    svgNode("path", { class: "t-zero-mark", d: `M${netX},${PLOT.tZeroTop} l-4,6 h8 Z` }),
    text(
      "T-0",
      Math.min(
        right - PLOT.frameInset * 3,
        // The label shares the gap row with the GFS name, so it starts after that name.
        Math.max(netX + PLOT.tZeroInset, card ? 0 : left + PLOT.modelNameWidth),
      ),
      PLOT.gapLabelY,
      "t-zero-label",
    ).node,
  );
  svg.append(fixedMarker);
  if (assessment.lowest_union_hour) {
    const markerX = x(Date.parse(assessment.lowest_union_hour.hour));
    svg.append(
      svgNode("line", {
        class: "lowest-risk-marker",
        stroke: "var(--ink)",
        "stroke-width": "var(--hair)",
        "stroke-dasharray": "6 2 1 2",
        "data-hour": assessment.lowest_union_hour.hour,
        x1: markerX,
        x2: markerX,
        y1: PLOT.top,
        y2: PLOT.cursorBottom,
      }),
    );
  }
  const cursor = svgNode("line", {
    class: "cursor",
    stroke: "var(--ink)",
    "stroke-width": "var(--stroke)",
    y1: PLOT.top,
    y2: PLOT.cursorBottom,
  });
  svg.append(cursor);
  // Keep the fixed dashed marker visible over the cursor at the same hour.
  if (!card) svg.append(fixedMarker);
  if (!card) svg.append(directLabels);
  const ticks: { node: SVGTextElement; edge: number }[] = [];
  const zone = assessment.launch.pad.location.timezone_name;
  for (const [time, edge] of [
    [first, left],
    [last, right],
  ]) {
    const anchor = edge === left ? "start" : "end";
    for (const [label, y, className] of [
      [padLocalTime(new Date(time ?? first), zone), PLOT.tickY, "local-tick"],
      [utcTime(new Date(time ?? first)), PLOT.utcY, "utc-tick"],
    ] as const) {
      const tick = text(label, edge ?? left, y, className, anchor);
      svg.append(tick.node);
      ticks.push({ node: tick.node, edge: edge ?? left });
    }
  }
  const handleWidth = mobile ? PLOT.mobileHandleWidth : PLOT.handleWidth;
  const handle = svgNode("g", { class: "selected-hour" });
  const rect = svgNode("rect", {
    class: "cursor-handle",
    fill: "var(--bg)",
    stroke: "none",
    "stroke-width": "var(--stroke)",
    y: PLOT.cursorBottom,
    width: handleWidth,
    height: PLOT.handleHeight,
    rx: PLOT.handleRadius,
  });
  const local = text("", 0, PLOT.handleLocalY, "handle-local", "middle");
  const utc = text("", 0, PLOT.handleUtcY, "handle-utc", "middle");
  handle.append(rect, local.node, utc.node);
  svg.append(handle);
  const positions = times.map((time) => {
    const cursorX = x(time);
    const handleX = Math.max(left, Math.min(right - handleWidth, cursorX - handleWidth / 2));
    return {
      cursorX,
      handleX,
      textX: handleX + handleWidth / 2,
    };
  });
  return {
    svg,
    compact: mobile,
    update(hour: number, localTime: string, utcTime: string) {
      const position = positions[hour];
      if (!position) return;
      cursor.setAttribute("x1", String(position.cursorX));
      cursor.setAttribute("x2", String(position.cursorX));
      rect.setAttribute("x", String(position.handleX));
      for (const label of [local, utc]) label.node.setAttribute("x", String(position.textX));
      local.value.nodeValue = localTime;
      utc.value.nodeValue = utcTime;
      for (const tick of ticks)
        tick.node.setAttribute(
          "visibility",
          Math.abs(tick.edge - (position.handleX + handleWidth / 2)) < handleWidth
            ? "hidden"
            : "visible",
        );
      for (const trace of traces) trace.node.setAttribute("class", trace.classes[hour] ?? "member");
      for (const count of counts) {
        count.node.nodeValue = count.labels[hour] ?? "Not evaluable";
        count.parent.classList.toggle("signal", count.signals[hour] ?? false);
        // A zero is already in the readout; printed over an empty band it reads as a blank form.
        if (!card)
          count.parent.setAttribute("visibility", count.signals[hour] ? "visible" : "hidden");
      }
      for (const label of placements) {
        const box = label.positions[hour];
        if (!box) continue;
        label.count.setAttribute("x", String(box.x + box.width / 2));
        label.count.setAttribute("y", String(box.y + box.height / 2));
      }
    },
  };
}
