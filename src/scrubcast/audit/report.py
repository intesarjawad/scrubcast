"""Markdown and badge-facing summaries of the forward forecast audit."""

from typing import TYPE_CHECKING

from scrubcast.audit.forecast_audit import (
    INSUFFICIENT,
    AttemptEvaluation,
    AuditMetric,
    Evaluation,
    ForecastAudit,
    LowestHourEvaluation,
)

if TYPE_CHECKING:
    from datetime import datetime


def _number(value: float | None) -> str:
    return f"{value:.6g}" if value is not None else "not estimated"


def _interval(interval: tuple[float, float] | None) -> str:
    return "not estimated" if interval is None else f"[{interval[0]:.6g}, {interval[1]:.6g}]"


def _metric_row(metric: AuditMetric) -> str:
    value = (
        f"{metric.value:.6g}"
        if metric.sufficient and metric.value is not None
        else f"{INSUFFICIENT} (n={metric.n})"
    )
    baseline = _number(metric.baseline) if metric.value is not None else "not estimated"
    return f"| {metric.label} | {metric.n} | {value} | {baseline} | {_interval(metric.interval)} |"


def _evaluation_lines(evaluation: Evaluation) -> list[str]:
    lines = [
        f"## {evaluation.title}",
        "",
        evaluation.label,
        "",
        "| Metric | n | Value | Baseline | 95% interval |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    lines.extend(_metric_row(metric) for metric in evaluation.rows)
    if evaluation.rank_histograms:
        for model, histogram in evaluation.rank_histograms.items():
            lines.extend(
                [
                    "",
                    f"{model} rank histogram n={sum(histogram):.6g}: "
                    + ", ".join(f"{count:.6g}" for count in histogram),
                ]
            )
    else:
        lines.extend(["", f"Rank histogram {INSUFFICIENT} (n={evaluation.n})"])
    if evaluation.reliability is not None:
        lines.extend(
            [
                "",
                "### Reliability",
                "",
                "| Predicted bin | n | Mean predicted | Observed frequency |",
                "| --- | ---: | ---: | ---: |",
                *(
                    f"| {bucket.lower:.1f} to {bucket.upper:.1f} | {bucket.n} | "
                    f"{_number(bucket.predicted)} | {_number(bucket.observed)} |"
                    for bucket in evaluation.reliability
                ),
            ]
        )
    else:
        lines.extend(["", f"Reliability table {INSUFFICIENT} (n={evaluation.n})"])
    lines.append("")
    return lines


def _attempt_lines(attempts: AttemptEvaluation) -> list[str]:
    lines = [
        "## Attempt outcomes",
        "",
        attempts.label,
        "",
        (
            f"Attempts n={attempts.n}; launched {attempts.launched}, "
            f"did not launch {attempts.not_launched}, unknown {attempts.unknown}."
        ),
        "",
    ]
    if attempts.message is not None:
        lines.extend([attempts.message, ""])
    else:
        lines.extend(
            [
                (
                    f"AUC {_number(attempts.auc)} (n={attempts.n}), "
                    f"95% interval {_interval(attempts.interval)}."
                ),
                "",
            ]
        )
    lines.extend(
        [
            "| Attempt | Scrubcast union risk at 24 h | Official GO% | Outcome | LL2 note |",
            "| --- | ---: | ---: | --- | --- |",
        ]
    )
    for row in attempts.rows:
        risk = _number(row.union_risk) if row.union_risk is not None else "not estimated"
        go = "unknown" if row.official_go_pct is None else str(row.official_go_pct)
        note = row.note.replace("|", "/") if row.note else ""
        lines.append(f"| {row.attempt_id} | {risk} | {go} | {row.outcome} | {note} |")
    lines.append("")
    return lines


def _lowest_lines(lowest: LowestHourEvaluation) -> list[str]:
    return [
        "## Lowest-risk hour",
        "",
        lowest.label,
        "",
        (
            f"Paired launches n={lowest.n}; union risk at the marked hour "
            f"{_number(lowest.risk_at_lowest)}, at T-0 {_number(lowest.risk_at_t0)}; "
            f"observed precipitation event rate at the marked hour "
            f"{_number(lowest.precipitation_at_lowest)}, at T-0 "
            f"{_number(lowest.precipitation_at_t0)}."
        ),
        "",
        (
            f"Difference {_number(lowest.difference)} with 95% interval "
            f"{_interval(lowest.interval)}; lowest_hour_verified "
            f"{'true' if lowest.verified else 'false'}."
        ),
        "",
    ]


def render_validation(audit: ForecastAudit, generated_at: datetime) -> str:
    """Render the forward audit with an explicit sample size beside every metric."""
    lines = [
        "# Forecast audit",
        "",
        f"Generated at {generated_at.isoformat()}; launches n={audit.n_launches}.",
        "",
        (
            "Intervals use 2,000 paired percentile resamples with seed 20261104. "
            "Any metric with fewer than 10 samples prints insufficient data."
        ),
        "",
    ]
    for evaluation in audit.evaluations:
        lines.extend(_evaluation_lines(evaluation))
    lines.extend(_attempt_lines(audit.attempts))
    lines.extend(_lowest_lines(audit.lowest_hour))
    return "\n".join(lines)
