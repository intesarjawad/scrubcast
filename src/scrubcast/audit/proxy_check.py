"""Paired launch evidence and percentile intervals for near-analysis proxies."""

from collections import Counter
from datetime import date
from typing import TYPE_CHECKING, Literal

import numpy as np
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from numpy.typing import NDArray


SPLIT_DATE = date(2025, 7, 1)
BOOTSTRAP_SEED = 20261104
BOOTSTRAP_RESAMPLES = 2000
PROXY_LABEL = (
    "Proxy check on near-analysis data. This tests Scrubcast's rule proxies, not its forecasts. "
    "Official concerns are the forecaster's final list, "
    "not an observation that a rule was violated."
)
RULE_IDS = (
    "thick_cloud",
    "cumulus",
    "anvil",
    "disturbed_weather",
    "flight_through_precip",
    "liftoff_wind",
)


class Evidence(BaseModel):
    """One launch/model pair, with missing measurements kept separate from zero."""

    model_config = ConfigDict(allow_inf_nan=False)

    launch_id: str
    net: AwareDatetime
    model: Literal["ecmwf", "gfs"]
    lead_hours: Literal[0, 24, 48, 72] = 0
    concerns: list[str] | None = None
    unevaluable_concerns: list[str] = Field(default_factory=list)
    verdicts: dict[str, bool | None] = Field(default_factory=dict)
    window_verdicts: dict[str, bool | None] = Field(default_factory=dict)
    wind_mps: float | None = None
    precipitation_mm: float | None = None
    observation_present: bool = False
    observed_wind_mps: float | None = None
    observed_precipitation_in: float | None = None
    climatology_wind_mps: float | None = None
    analysis_wind_verdict: bool | None = None


class Metric(BaseModel):
    """Undefined denominators stay null, with the paired sample count attached."""

    n: int
    value: float | None
    interval: tuple[float, float] | None = None
    valid_resamples: int = 0


def measure(values: list[list[float]], kind: str) -> Metric:
    """Resample launches as whole rows, omitting undefined bootstrap denominators."""
    if not values:
        return Metric(n=0, value=None)
    data = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.integers(len(data), size=(BOOTSTRAP_RESAMPLES, len(data)))
    samples = np.concatenate((data[None, :, :], data[draws]), axis=0)
    predicted, observed = samples[:, :, 0], samples[:, :, 1]
    if kind in {"mae", "bias", "mae_skill", "agreement"}:
        if kind == "bias":
            results = np.mean(predicted - observed, axis=1)
        elif kind == "agreement":
            results = np.mean(predicted == observed, axis=1)
        else:
            results = np.mean(np.abs(predicted - observed), axis=1)
            if kind == "mae_skill":
                reference = np.mean(np.abs(samples[:, :, 2] - observed), axis=1)
                results = 1 - np.divide(
                    results, reference, out=np.full_like(results, np.nan), where=reference != 0
                )
    else:
        hits = np.count_nonzero((predicted == 1) & (observed == 1), axis=1)
        misses = np.count_nonzero((predicted == 0) & (observed == 1), axis=1)
        false = np.count_nonzero((predicted == 1) & (observed == 0), axis=1)
        correct = np.count_nonzero((predicted == 0) & (observed == 0), axis=1)

        def ratio(
            numerator: NDArray[np.int64], denominator: NDArray[np.int64]
        ) -> NDArray[np.float64]:
            return np.divide(
                numerator,
                denominator,
                out=np.full(numerator.shape, np.nan),
                where=denominator != 0,
            )

        recall = ratio(hits, hits + misses)
        specificity = ratio(correct, correct + false)
        results = {
            "precision": ratio(hits, hits + false),
            "recall": recall,
            "false_alarm_ratio": ratio(false, hits + false),
            "balanced_accuracy": (recall + specificity) / 2,
            "peirce": recall + specificity - 1,
        }[kind]
    value = float(results[0]) if np.isfinite(results[0]) else None
    valid = results[1:][np.isfinite(results[1:])]
    interval = tuple(float(x) for x in np.quantile(valid, [0.025, 0.975])) if len(valid) else None
    return Metric(
        n=len(data),
        value=value,
        interval=None if interval is None else (interval[0], interval[1]),
        valid_resamples=len(valid),
    )


def precipitation_metrics(rows: list[Evidence]) -> dict[str, dict[str, Metric]]:
    """Use measurable rainfall and a second threshold excluding light precipitation."""
    return {
        label: {
            name: measure(
                [
                    [
                        float(row.precipitation_mm >= model),
                        float(row.observed_precipitation_in >= station),
                    ]
                    for row in rows
                    if row.precipitation_mm is not None
                    and row.observed_precipitation_in is not None
                ],
                name,
            )
            for name in ("recall", "false_alarm_ratio", "peirce")
        }
        for label, model, station in (("measurable", 0.3, 0.01), ("0.5_mm", 0.5, 0.02))
    }


def observation_metrics(rows: list[Evidence]) -> dict[str, Metric]:
    """Compare finite wind pairs without filling station gaps."""
    pairs = [
        [row.wind_mps, row.observed_wind_mps]
        for row in rows
        if row.wind_mps is not None and row.observed_wind_mps is not None
    ]
    return {name: measure(pairs, name) for name in ("mae", "bias")}


def proxy_check(rows: list[Evidence]) -> dict[str, object]:
    """Keep models, periods and window sensitivity in separate tables."""
    tables: list[dict[str, object]] = []
    for model in ("ecmwf", "gfs"):
        for period in ("held_out", "development"):
            selected = [
                row
                for row in rows
                if row.model == model
                and row.lead_hours == 0
                and (row.net.date() >= SPLIT_DATE) == (period == "held_out")
            ]
            for scope in ("nearest_net", "any_window_hour"):
                rules: dict[str, object] = {}
                for rule in RULE_IDS:
                    pairs = [
                        [float(verdict), float(rule in row.concerns)]
                        for row in selected
                        if row.concerns is not None
                        and (
                            verdict := (
                                row.verdicts if scope == "nearest_net" else row.window_verdicts
                            ).get(rule)
                        )
                        is not None
                    ]
                    positives = sum(int(pair[1]) for pair in pairs)
                    rules[rule] = {
                        "n": len(pairs),
                        "positives": positives,
                        "always_flag_precision": positives / len(pairs) if pairs else None,
                        "always_flag_recall": 1.0 if positives else None,
                        "balanced_accuracy_chance": 0.5,
                        **{
                            name: measure(pairs, name).model_dump(mode="json")
                            for name in ("precision", "recall", "balanced_accuracy")
                        },
                    }
                tables.append({"model": model, "period": period, "scope": scope, "rules": rules})
    unique = {row.launch_id: row for row in rows if row.lead_hours == 0}
    coverage = Counter(concern for row in unique.values() for concern in row.concerns or [])
    return {
        "label": PROXY_LABEL,
        "tables": tables,
        "concern_coverage": dict(sorted(coverage.items())),
        "concern_lists": sum(row.concerns is not None for row in unique.values()),
        "unevaluable_concern_launches": sum(
            bool(row.unevaluable_concerns) for row in unique.values()
        ),
        "unevaluable_concern_share": (
            sum(bool(row.unevaluable_concerns) for row in unique.values())
            / sum(row.concerns is not None for row in unique.values())
            if any(row.concerns is not None for row in unique.values())
            else None
        ),
        "observations": [
            {
                "model": model,
                "period": period,
                "n": len(selected),
                "missing_metar": sum(not row.observation_present for row in selected),
                "wind": {
                    key: value.model_dump(mode="json")
                    for key, value in observation_metrics(selected).items()
                },
                "precipitation": {
                    key: {name: value.model_dump(mode="json") for name, value in metrics.items()}
                    for key, metrics in precipitation_metrics(selected).items()
                },
            }
            for model in ("ecmwf", "gfs")
            for period in ("held_out", "development")
            for selected in [
                [
                    row
                    for row in rows
                    if row.model == model
                    and row.lead_hours == 0
                    and (row.net.date() >= SPLIT_DATE) == (period == "held_out")
                ]
            ]
        ],
    }
