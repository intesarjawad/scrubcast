from datetime import timedelta
from pathlib import Path

import pytest

from scrubcast.audit.forecast_audit import ForecastLaunch, ForecastLedger, audit_forecasts
from scrubcast.audit.report import render_validation

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _ledger(count: int = 12) -> ForecastLedger:
    ledger = ForecastLedger.model_validate_json((FIXTURES / "hindcast/ledger.json").read_bytes())
    launches: list[ForecastLaunch] = []
    for index in range(count):
        launch = ledger.launches[0].model_copy(deep=True)
        launch.outcome = ledger.launches[index % len(ledger.launches)].outcome
        launch.launch_id = f"sample-{index}"
        launch.station = launch.observations[0].station
        launches.append(launch)
    return ledger.model_copy(update={"launches": launches})


def test_precipitation_skill_divides_the_paired_aggregate_scores() -> None:
    ledger = _ledger()
    for index, launch in enumerate(ledger.launches):
        for run in launch.runs:
            run.precipitation_risk = 0.5
        launch.observations = [
            row.model_copy(update={"precipitation_in": 0.02 if index % 2 else 0.0})
            for row in launch.observations
        ]
    climate = ledger.climatology[0]
    ledger.climatology = [
        climate.model_copy(update={"precipitation_in": 0.02 if index == 0 else 0.0})
        for index in range(4)
    ]
    rows = audit_forecasts(ledger).evaluations[1].rows
    assert rows[0].value == pytest.approx(0.25)
    assert rows[0].baseline == pytest.approx(0.3125)
    assert rows[1].value == pytest.approx(0.2)
    assert rows[1].n == 12


def test_wind_skill_includes_individually_perfect_reference_cases() -> None:
    ledger = _ledger()
    for index, launch in enumerate(ledger.launches):
        for run in launch.runs:
            run.wind_members = {"ecmwf": [1.0], "gfs": [2.0]}
        launch.observations = [
            row.model_copy(update={"wind_speed_mps": 0.0 if index % 2 else 2.0})
            for row in launch.observations
        ]
    ledger.climatology = [ledger.climatology[0].model_copy(update={"wind_speed_mps": 0.0})]
    wind = audit_forecasts(ledger).evaluations[0]
    assert wind.rows[1].n == 12
    assert wind.rows[0].value is not None
    assert wind.rows[0].baseline is not None
    assert wind.rows[1].value == pytest.approx(1 - wind.rows[0].value / wind.rows[0].baseline)
    assert "ECMWF" in wind.summary


def test_attempt_classes_use_only_outcomes_with_forecast_risk() -> None:
    ledger = _ledger()
    for launch in ledger.launches:
        for run in launch.runs:
            run.union_risk = None
    attempts = audit_forecasts(ledger).attempts
    assert (attempts.n, attempts.launched, attempts.not_launched) == (0, 0, 0)
    assert all(not row.scored for row in attempts.rows)


def test_rank_histograms_include_late_cases_both_models_and_tied_ranks() -> None:
    ledger = _ledger(48)
    for launch in ledger.launches:
        for run in launch.runs:
            run.wind_members = {"ecmwf": [1.0, 1.0], "gfs": [0.0, 2.0]}
        launch.observations = [
            row.model_copy(update={"wind_speed_mps": 1.0}) for row in launch.observations
        ]
    wind = audit_forecasts(ledger).evaluations[0]
    assert wind.rank_histogram is not None
    assert sum(wind.rank_histogram) == pytest.approx(96)
    assert wind.rank_histograms is not None
    assert set(wind.rank_histograms) == {"ECMWF", "GFS"}
    assert sum(wind.rank_histograms["ECMWF"]) == pytest.approx(48)
    assert sum(value > 0 for value in wind.rank_histograms["ECMWF"]) == 3
    assert sum(wind.rank_histograms["GFS"]) == pytest.approx(48)


def test_station_filters_verification_and_climatology_even_at_equal_times() -> None:
    ledger = _ledger()
    original = audit_forecasts(ledger)
    wrong = [
        row.model_copy(update={"station": "TTS", "wind_speed_mps": 99.0, "precipitation_in": 1.0})
        for row in ledger.climatology
    ]
    ledger.climatology = wrong + ledger.climatology
    for launch in ledger.launches:
        launch.observations = [
            row.model_copy(
                update={"station": "TTS", "wind_speed_mps": 99.0, "precipitation_in": 1.0}
            )
            for row in launch.observations
        ] + launch.observations
    assert audit_forecasts(ledger) == original
    for launch in ledger.launches:
        launch.observations = [
            row.model_copy(update={"valid": row.valid + timedelta(hours=2)})
            for row in launch.observations
            if row.station == launch.station
        ]
    assert audit_forecasts(ledger).evaluations[0].n == 0


def test_zero_aggregate_reference_keeps_all_pairs_without_inventing_skill() -> None:
    ledger = _ledger()
    for launch in ledger.launches:
        launch.observations = [
            row.model_copy(update={"precipitation_in": 0.0}) for row in launch.observations
        ]
    ledger.climatology = [
        row.model_copy(update={"precipitation_in": 0.0}) for row in ledger.climatology
    ]
    skill = audit_forecasts(ledger).evaluations[1].rows[1]
    assert skill.n == 12
    assert skill.value is None


def test_missing_estimates_are_explicit_in_the_markdown() -> None:
    ledger = _ledger()
    for launch in ledger.launches:
        launch.observations = []
    rendered = render_validation(audit_forecasts(ledger), ledger.launches[0].net)
    assert "undefined" not in rendered
    assert "not estimated" in rendered
