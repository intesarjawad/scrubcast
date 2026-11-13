from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, TypeAdapter

from scrubcast.audit.forecast_check import forecast_check
from scrubcast.audit.proxy_check import Evidence, Metric, measure, proxy_check


class VerdictScores(BaseModel):
    n: int
    positives: int
    agreement: Metric


class ForecastTable(BaseModel):
    n: int
    wind: dict[str, Metric]
    precipitation: dict[str, dict[str, Metric]]
    liftoff_wind: VerdictScores


class ProxyScores(BaseModel):
    n: int
    positives: int
    recall: Metric
    balanced_accuracy: Metric
    always_flag_precision: float | None
    balanced_accuracy_chance: float


class ProxyTable(BaseModel):
    rules: dict[str, ProxyScores]


def test_five_launch_forecast_scores() -> None:
    rows = [
        Evidence(
            launch_id=str(index),
            net=datetime(2025, 8, 1, tzinfo=UTC),
            model="ecmwf",
            lead_hours=24,
            wind_mps=wind,
            observed_wind_mps=observed,
            climatology_wind_mps=0,
            precipitation_mm=rain,
            observed_precipitation_in=station_rain,
            observation_present=True,
            verdicts={"liftoff_wind": flag},
            analysis_wind_verdict=analysis,
        )
        for index, (wind, observed, rain, station_rain, flag, analysis) in enumerate(
            [
                (1, 2, 0.3, 0.01, True, True),
                (4, 2, 0.6, 0, False, False),
                (2, 4, 0, 0.02, True, False),
                (8, 6, 0.5, 0.02, True, True),
                (5, 6, 0, 0, False, False),
            ]
        )
    ]
    table = TypeAdapter(list[ForecastTable]).validate_python(forecast_check(rows)["tables"])
    first = table[0]
    assert first.n == 5
    assert first.wind["mae"].value == pytest.approx(1.6)
    assert first.wind["bias"].value == 0
    assert first.wind["mae_skill"].value == pytest.approx(0.6)
    assert first.wind["mae_skill"].n == 5
    assert first.precipitation["measurable"]["peirce"].value == pytest.approx(1 / 6)
    assert first.precipitation["measurable"]["recall"].value == pytest.approx(2 / 3)
    assert first.precipitation["measurable"]["false_alarm_ratio"].value == pytest.approx(1 / 3)
    assert first.precipitation["0.5_mm"]["recall"].value == 0.5
    assert first.liftoff_wind.positives == 2
    assert first.liftoff_wind.agreement.value == 0.8
    assert forecast_check(rows) == forecast_check(rows)


def test_missing_pairs_and_zero_reference_are_not_filled() -> None:
    score = measure([[2, 2, 2], [4, 4, 4]], "mae_skill")
    assert score.n == 2
    assert score.value is None
    assert score.interval is None
    assert score.valid_resamples == 0
    assert measure([], "mae").n == 0
    score = measure([[0, 0], [1, 0]], "recall")
    assert score.value is None
    assert score.interval is None


def test_proxy_split_baselines_and_unavailable_concerns() -> None:
    rows = [
        Evidence(
            launch_id="held",
            net=datetime(2025, 7, 1, tzinfo=UTC),
            model="ecmwf",
            concerns=["cumulus", "lightning", "Unknown"],
            unevaluable_concerns=["lightning", "Unknown"],
            verdicts={"cumulus": False},
            window_verdicts={"cumulus": True},
        ),
        Evidence(
            launch_id="development",
            net=datetime(2025, 6, 30, tzinfo=UTC),
            model="ecmwf",
            concerns=[],
            verdicts={"cumulus": True},
        ),
        Evidence(
            launch_id="probability_only",
            net=datetime(2025, 7, 1, tzinfo=UTC),
            model="ecmwf",
            verdicts={"cumulus": True},
        ),
    ]
    report = proxy_check(rows)
    tables = TypeAdapter(list[ProxyTable]).validate_python(report["tables"])
    held, sensitivity, development = tables[:3]
    assert held.rules["cumulus"].n == 1
    assert held.rules["cumulus"].recall.value == 0
    assert held.rules["cumulus"].always_flag_precision == 1
    assert held.rules["cumulus"].balanced_accuracy_chance == 0.5
    assert held.rules["cumulus"].balanced_accuracy.value is None
    assert sensitivity.rules["cumulus"].recall.value == 1
    assert development.rules["cumulus"].positives == 0
    assert report["concern_coverage"] == {"Unknown": 1, "cumulus": 1, "lightning": 1}
    assert report["unevaluable_concern_share"] == 0.5
