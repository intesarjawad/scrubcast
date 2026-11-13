import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from pydantic import TypeAdapter

from scrubcast.archive.slices import save_slices
from scrubcast.assess.climatology import Climatology
from scrubcast.assess.launch import AssessmentRun, assess_launch
from scrubcast.assess.ledger import ledger_row, slice_to_ledger
from scrubcast.assess.pipeline import assess_launches
from scrubcast.cli import Schedule, main
from scrubcast.forecast_cache import SavedForecast
from scrubcast.models.assessment import LaunchAssessment, LedgerRow
from scrubcast.models.launch import Launch
from scrubcast.models.weather import parse_ensemble
from scrubcast.rules.loader import load_rules
from scrubcast.sources.weather_source import ForecastResponse

FIXTURES = Path(__file__).parents[1] / "fixtures"
GOLDEN = Path(__file__).parents[1] / "golden/assessment_cape.json"
NOW = datetime(2026, 11, 5, 9, tzinfo=UTC)
LEDGER_KEYS = {
    "launch_id",
    "run_at",
    "fetched_at",
    "net",
    "tier",
    "rule_set_version",
    "rules",
    "union",
    "lowest_hour",
    "lowest_hour_union",
    "window_end",
    "official_go_pct",
    "official_concerns",
    "unmapped_concerns",
    "launch",
}


@pytest.fixture
def cape() -> Launch:
    launches = TypeAdapter(list[Launch]).validate_python(
        json.loads((FIXTURES / "ll2_upcoming.json").read_text())["results"]
    )
    launch = next(launch for launch in launches if launch.pad.location.id == 12)
    return launch.model_copy(
        update={
            "net": NOW + timedelta(hours=7),
            "window_start": NOW + timedelta(hours=6, minutes=52),
            "window_end": NOW + timedelta(hours=7, minutes=16),
            "probability": 95,
            "weather_concerns": "Cumulus Cloud Rule, Unknown concern",
        }
    )


@pytest.fixture
def forecast() -> ForecastResponse:
    return ForecastResponse(
        series=parse_ensemble(json.loads((FIXTURES / "open_meteo_cape.json").read_text())),
        fetched_at=NOW,
        cost_units=344.4,
        remaining_units=255.6,
        generationtime_ms=1,
    )


def run(forecast: ForecastResponse, now: datetime = NOW) -> AssessmentRun:
    return AssessmentRun(now, {series.model: forecast.fetched_at for series in forecast.series})


def test_cape_assessment_golden(cape: Launch, forecast: ForecastResponse) -> None:
    assessment = assess_launch(cape, forecast.series, load_rules(), run(forecast))
    assert assessment.model_dump(mode="json") == json.loads(GOLDEN.read_text())
    assert LaunchAssessment.model_validate_json(assessment.model_dump_json()) == assessment
    assert not assessment.lowest_hour_verified
    assert assessment.audit == []


def test_slice_to_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cape: Launch,
    forecast: ForecastResponse,
) -> None:
    catalog = load_rules()
    at = cape.net - timedelta(hours=24)
    path = save_slices(tmp_path / "archive", [cape], {"cape": forecast}, catalog, at)
    assert path is not None
    assessed = assess_launches([cape], {"cape": forecast}, catalog, at, root=tmp_path)
    expected = ledger_row(assessed[0])
    written = LedgerRow.model_validate_json((tmp_path / f"ledger/{at:%Y-%m}.jsonl").read_text())
    assert written == expected
    assert set(written.model_dump()) == LEDGER_KEYS
    assert written.official_go_pct == 95
    assert written.official_concerns == ["Cumulus Cloud Rule", "Unknown concern"]
    assert written.unmapped_concerns == ["Unknown concern"]
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "data").exists()
    assert slice_to_ledger(path, catalog) == [written]


def test_tier_c_reference_rules_and_context(cape: Launch, forecast: ForecastResponse) -> None:
    location = cape.pad.location.model_copy(update={"id": 26})
    launch = cape.model_copy(
        update={
            "pad": cape.pad.model_copy(update={"location": location}),
            "rocket_name": "Unpublished",
        }
    )
    assessment = assess_launch(
        launch,
        forecast.series[:1],
        load_rules(),
        AssessmentRun(NOW, {"ecmwf": NOW}, climatology=Climatology((10, 20, 30), (1, 2, 3))),
    )
    assert assessment.tier == "C"
    assert assessment.rules
    assert all(rule.reference_only for rule in assessment.rules)
    assert assessment.context.convective_fraction_t0 is not None
    assert assessment.context.upper_wind_percentile_t0 is not None
    assert assessment.context.shear_percentile_t0 is not None
    assert assessment.union_risk_t0 == {"ecmwf": 0, "gfs": None}
    assert all(rule.by_model["gfs"].risk_fraction is None for rule in assessment.rules)
    assert all(rule.member_values_by_hour["gfs"] is None for rule in assessment.rules)


def test_missing_evidence_preserves_rule_denominators(
    cape: Launch, forecast: ForecastResponse
) -> None:
    launch = cape.model_copy(update={"rocket_name": "Falcon 9"})
    ecmwf = forecast.series[0]
    values = {name: array.copy() for name, array in ecmwf.values.items()}
    values["wind_speed_10m"][:] = 30
    values["wind_speed_100m"][:] = 30
    values["wind_speed_10m"][0, :] = np.nan
    result = assess_launch(launch, [replace(ecmwf, values=values)], load_rules(), run(forecast))
    wind = next(rule for rule in result.rules if rule.rule_id == "liftoff_wind")
    assert wind.by_model["ecmwf"].evaluable_members == 50
    assert wind.by_model["ecmwf"].members == 51
    assert wind.by_model["ecmwf"].risk_fraction == 1
    assert wind.member_violated_by_hour["ecmwf"] is not None
    assert wind.member_violated_by_hour["ecmwf"][0][0] is None
    assert "NaN" not in result.model_dump_json()
    assert result.context.upper_wind_percentile_t0 is None


def test_material_hour_reaches_ledger(cape: Launch, forecast: ForecastResponse) -> None:
    launch = cape.model_copy(
        update={
            "rocket_name": "Falcon 9",
            "window_start": NOW + timedelta(hours=6),
            "window_end": NOW + timedelta(hours=8),
        }
    )
    wind = np.zeros((51, len(forecast.series[0].hours)), dtype=np.float32)
    wind[:, 15] = 30
    wind[:7, 16] = 30
    series = replace(
        forecast.series[0],
        values={
            "wind_speed_10m": wind,
            "wind_speed_100m": wind,
        },
    )
    result = assess_launch(launch, [series], load_rules(), run(forecast))
    row = ledger_row(result)
    assert row.union == (7 / 51, None)
    assert row.lowest_hour == NOW + timedelta(hours=8)
    assert row.lowest_hour_union == 0
    assert result.lowest_union_hour is not None
    assert result.lowest_union_hour.members_below_t0 == 7


def test_reference_site_preserves_published_vehicle_rule(
    cape: Launch,
    forecast: ForecastResponse,
) -> None:
    location = cape.pad.location.model_copy(update={"id": 26})
    launch = cape.model_copy(
        update={
            "pad": cape.pad.model_copy(update={"location": location}),
            "rocket_name": "Falcon 9",
        }
    )
    result = assess_launch(launch, forecast.series[:1], load_rules(), run(forecast))
    vehicle = next(rule for rule in result.rules if rule.rule_id == "liftoff_wind")
    assert not vehicle.reference_only
    assert all(rule.reference_only for rule in result.rules if rule.rule_id != "liftoff_wind")


@pytest.mark.parametrize("invalid", ["window", "shape", "cache"])
def test_validation_failure_skips_only_affected_launch(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    cape: Launch,
    forecast: ForecastResponse,
    invalid: str,
) -> None:
    bad = cape.model_copy(update={"id": "invalid"})
    forecasts = {"cape": forecast}
    if invalid == "window":
        bad = bad.model_copy(update={"window_end": cape.window_start - timedelta(hours=1)})
    else:
        location = cape.pad.location.model_copy(update={"id": 26})
        bad = bad.model_copy(update={"pad": cape.pad.model_copy(update={"location": location})})
        if invalid == "shape":
            broken = replace(forecast.series[0], values={"cape": np.zeros((1, 1), np.float32)})
            forecasts["location-26"] = replace(forecast, series=[broken])
        else:
            path = tmp_path / "data/weather/location-26.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}")
    result = assess_launches([bad, cape], forecasts, load_rules(), NOW, root=tmp_path)
    assert [item.launch.id for item in result] == [cape.id]
    assert "Skipping assessment for launch invalid" in caplog.text
    assert not (tmp_path / "site/public/data/launches/invalid.json").exists()


def test_assess_command_cached_forecast_and_refresh_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cape: Launch,
    forecast: ForecastResponse,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scrubcast.cli.FIXTURES", FIXTURES)
    path = tmp_path / "data/weather/cape.json"
    path.parent.mkdir(parents=True)
    (tmp_path / "data/schedule.json").write_text(
        Schedule(generated_at=NOW, launches=[cape]).model_dump_json()
    )
    path.write_text(SavedForecast.from_response(forecast).model_dump_json())
    main(["assess", "--fixtures"])
    main(["assess", "--fixtures"])
    ledger = tmp_path / "ledger/2026-11.jsonl"
    assert len(ledger.read_text().splitlines()) == 1
    assess_launches([cape], {"cape": forecast}, load_rules(), NOW + timedelta(hours=6))
    assert len(ledger.read_text().splitlines()) == 1
    output = tmp_path / f"site/public/data/launches/{cape.id}.json"
    assert LaunchAssessment.model_validate_json(output.read_text()).refresh_deferred
    refreshed = replace(forecast, fetched_at=NOW + timedelta(hours=6))
    assess_launches([cape], {"cape": refreshed}, load_rules(), NOW + timedelta(hours=6))
    assert len(ledger.read_text().splitlines()) == 2


def test_collect_writes_assessment_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scrubcast.cli.FIXTURES", FIXTURES)
    main(["collect", "--fixtures"])
    path = tmp_path / "ledger/2026-11.jsonl"
    rows = [LedgerRow.model_validate_json(line) for line in path.read_text().splitlines()]
    assert rows
    assert all(set(row.model_dump()) == LEDGER_KEYS for row in rows)
    for row in rows:
        assessment = LaunchAssessment.model_validate_json(
            (tmp_path / f"site/public/data/launches/{row.launch_id}.json").read_text()
        )
        assert ledger_row(assessment) == row
