import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest
from pydantic import TypeAdapter

from scrubcast.archive.slices import load_slices, save_slices
from scrubcast.cli import Schedule, main
from scrubcast.models.launch import Launch
from scrubcast.models.weather import parse_ensemble
from scrubcast.rules.loader import load_rules
from scrubcast.sources.weather_source import ForecastResponse

if TYPE_CHECKING:
    from collections.abc import Mapping

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = datetime(2026, 11, 5, 9, tzinfo=UTC)


@pytest.fixture
def cape_launch() -> Launch:
    launches = TypeAdapter(list[Launch]).validate_python(
        json.loads((FIXTURES / "ll2_upcoming.json").read_text())["results"],
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
def forecasts() -> dict[str, ForecastResponse]:
    return {
        "cape": ForecastResponse(
            series=parse_ensemble(json.loads((FIXTURES / "open_meteo_cape.json").read_text())),
            fetched_at=NOW - timedelta(minutes=4),
            cost_units=344.4,
            remaining_units=255.6,
            generationtime_ms=1,
        )
    }


def test_round_trip_and_complete_sidecar(
    tmp_path: Path,
    cape_launch: Launch,
    forecasts: dict[str, ForecastResponse],
) -> None:
    path = save_slices(tmp_path, [cape_launch], forecasts, load_rules(), NOW)
    assert path is not None
    assert path == tmp_path / "slices-20261105T09.npz"
    assert path.stat().st_size < 100_000
    metadata, arrays = load_slices(path)
    assert metadata.run_at == NOW
    assert metadata.rule_set_version
    saved = metadata.launches[0]
    assert saved.launch.id == cape_launch.id
    assert saved.launch.net == cape_launch.net
    assert saved.launch.window_start == cape_launch.window_start
    assert saved.launch.window_end == cape_launch.window_end
    assert saved.launch.tier == "A"
    assert saved.launch.official_go_pct == 95
    assert saved.launch.official_concerns == ["Cumulus Cloud Rule", "Unknown concern"]
    assert saved.launch.unmapped_concerns == ["Unknown concern"]
    assert saved.point_id == "cape"
    assert set(saved.models) == {"ecmwf", "gfs"}
    for original in forecasts["cape"].series:
        model = saved.models[original.model]
        assert model.fetched_at == forecasts["cape"].fetched_at
        assert model.grid_point == original.grid_point
        assert model.members == original.members
        assert model.hours == [datetime(2026, 11, 5, hour, tzinfo=UTC) for hour in (15, 16, 17)]
        assert model.variable_order == list(original.values)
        assert len(model.variable_order) == (42 if original.model == "ecmwf" else 41)
        expected = np.stack([values[:, 15:18] for values in original.values.values()])
        np.testing.assert_array_equal(arrays[model.array_key], expected)
        assert arrays[model.array_key].dtype == np.float32
    assert json.loads(path.with_suffix(".json").read_text()) == metadata.model_dump(mode="json")


@pytest.mark.parametrize("hours", [-1, 97])
def test_outside_horizon_writes_nothing(
    tmp_path: Path,
    cape_launch: Launch,
    forecasts: dict[str, ForecastResponse],
    hours: int,
) -> None:
    launch = cape_launch.model_copy(update={"net": NOW + timedelta(hours=hours)})
    assert save_slices(tmp_path, [launch], forecasts, load_rules(), NOW) is None
    assert not list(tmp_path.iterdir())


def test_absent_forecast_fails_loudly(tmp_path: Path, cape_launch: Launch) -> None:
    with pytest.raises(ValueError, match="cape"):
        save_slices(tmp_path, [cape_launch], {}, load_rules(), NOW)


def test_load_rejects_wrong_array_shape(
    tmp_path: Path,
    cape_launch: Launch,
    forecasts: dict[str, ForecastResponse],
) -> None:
    path = save_slices(tmp_path, [cape_launch], forecasts, load_rules(), NOW)
    assert path is not None
    metadata, arrays = load_slices(path)
    key = metadata.launches[0].models["ecmwf"].array_key
    arrays[key] = arrays[key][:, :, :1]
    np.savez_compressed(path, allow_pickle=False, **arrays)
    with pytest.raises(ValueError, match="shape"):
        load_slices(path)


@pytest.mark.parametrize("with_assessment", [False, True])
def test_collect_command_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forecasts: dict[str, ForecastResponse],
    *,
    with_assessment: bool,
) -> None:
    events: list[str] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scrubcast.cli.FIXTURES", FIXTURES)

    def weather(schedule: Schedule, now: datetime) -> Mapping[str, ForecastResponse]:
        assert (tmp_path / "data/schedule.json").exists()
        assert schedule.launches
        assert now == datetime.fromisoformat((FIXTURES / "RECORDED_AT").read_text().strip())
        events.append("weather")
        return {"cape": forecasts["cape"], "vandenberg": forecasts["cape"]}

    def assess(
        schedule: Schedule,
        saved: Mapping[str, ForecastResponse],
        now: datetime,
    ) -> None:
        assert list((tmp_path / "archive").glob("*.npz"))
        assert schedule.launches
        assert saved
        assert now == datetime.fromisoformat((FIXTURES / "RECORDED_AT").read_text().strip())
        events.append("assess")

    main(
        ["collect", "--fixtures"],
        weather_collector=weather,
        assessor=assess if with_assessment else None,
    )
    assert events == (["weather", "assess"] if with_assessment else ["weather"])
    path = next((tmp_path / "archive").glob("*.npz"))
    metadata, _ = load_slices(path)
    assert metadata.launches


def test_collect_default_weather_integration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scrubcast.cli.FIXTURES", FIXTURES)
    main(["collect", "--fixtures"])
    assert (tmp_path / "data/schedule.json").exists()
    assert (tmp_path / "data/weather/cape.json").exists()
    assert list((tmp_path / "archive").glob("*.npz"))
    assert (tmp_path / "ledger/budget-2026-11.jsonl").exists()


@pytest.mark.parametrize("hours", [0, 96])
def test_horizon_includes_boundaries(
    tmp_path: Path,
    cape_launch: Launch,
    forecasts: dict[str, ForecastResponse],
    hours: int,
) -> None:
    launch = cape_launch.model_copy(update={"net": NOW + timedelta(hours=hours)})
    assert save_slices(tmp_path, [launch], forecasts, load_rules(), NOW) is not None


@pytest.mark.parametrize("location_id", [143, 26])
def test_non_tier_a_writes_nothing(
    tmp_path: Path,
    cape_launch: Launch,
    location_id: int,
) -> None:
    location = cape_launch.pad.location.model_copy(update={"id": location_id})
    pad = cape_launch.pad.model_copy(update={"location": location})
    launch = cape_launch.model_copy(update={"pad": pad})
    assert save_slices(tmp_path, [launch], {}, load_rules(), NOW) is None
    assert not list(tmp_path.iterdir())


def test_multiple_launches_and_nan_round_trip(
    tmp_path: Path,
    cape_launch: Launch,
    forecasts: dict[str, ForecastResponse],
) -> None:
    second = cape_launch.model_copy(
        update={"id": "second-launch", "probability": None, "weather_concerns": None}
    )
    series = forecasts["cape"].series[0]
    series.values["wind_speed_10m"][1, 16] = np.nan
    path = save_slices(tmp_path, [cape_launch, second], forecasts, load_rules(), NOW)
    assert path is not None
    metadata, arrays = load_slices(path)
    assert len(metadata.launches) == 2
    assert len(arrays) == 4
    assert metadata.launches[1].launch.official_go_pct is None
    assert metadata.launches[1].launch.official_concerns == []
    for launch in metadata.launches:
        model = launch.models["ecmwf"]
        variable_index = model.variable_order.index("wind_speed_10m")
        assert np.isnan(arrays[model.array_key][variable_index, 1, 1])
