from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from pydantic import TypeAdapter, ValidationError

from scrubcast.models.observation import CloudLayer, Observation
from scrubcast.sources.errors import SourceError
from scrubcast.sources.historical import parse_historical, parse_previous_runs
from scrubcast.sources.iem import parse_metars

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_observation_validation() -> None:
    observation = Observation(
        station="XMR",
        valid=datetime(2025, 10, 1, tzinfo=UTC),
        latitude=28.4677,
        longitude=-80.5668,
        wind_speed_mps=None,
        wind_gust_mps=None,
        precipitation_in=None,
        cloud_layers=(CloudLayer(cover=None, base_ft=None),),
    )
    assert observation.wind_speed_mps is None
    assert observation.precipitation_in is None
    for field, value in (
        ("wind_speed_mps", -1),
        ("wind_gust_mps", float("nan")),
        ("precipitation_in", -1),
        ("latitude", 91),
        ("longitude", -181),
        ("valid", "2025-10-01T00:00:00"),
    ):
        data = observation.model_dump()
        data[field] = value
        with pytest.raises(ValidationError):
            Observation.model_validate(data)
    with pytest.raises(ValidationError, match="frozen"):
        observation.__setattr__("station", "TTS")


def test_metars_missing_is_not_zero() -> None:
    # Synthetic row: every measurement is M, while the station and UTC valid time remain known.
    text = (
        "station,valid,lon,lat,sknt,gust,p01i,skyc1,skyl1,skyc2,skyl2,skyc3,skyl3\n"
        "XMR,2025-10-01 00:55,-80.5668,28.4677,M,M,M,M,M,M,M,M,M\n"
    )
    observation = parse_metars(text)[0]
    assert observation.wind_speed_mps is None
    assert observation.wind_gust_mps is None
    assert observation.precipitation_in is None
    assert all(layer.cover is None and layer.base_ft is None for layer in observation.cloud_layers)


def test_metars_accepts_a_padded_cover_code() -> None:
    text = (
        "station,valid,lon,lat,sknt,gust,p01i,skyc1,skyl1,skyc2,skyl2,skyc3,skyl3\n"
        "XMR,2016-01-08 11:55,-80.5668,28.4677,4,M,M,VV ,200,M,M,M,M\n"
    )
    layer = parse_metars(text)[0].cloud_layers[0]
    assert layer.cover == "VV"
    assert layer.base_ft == 200


@pytest.mark.parametrize(
    "row",
    [
        "XMR,2025-10-01 00:55,-80.5668,28.4677,-1,M,M,M,M,M,M,M,M",
        "XMR,invalid,-80.5668,28.4677,10,M,M,M,M,M,M,M,M",
        "XMR,2025-10-01 00:55,-80.5668,28.4677,10",
    ],
)
def test_metars_rejects_bad_rows(row: str) -> None:
    header = (FIXTURES / "iem_xmr_2025-10.csv").read_text().splitlines()[0]
    with pytest.raises(SourceError):
        parse_metars(f"{header}\n{row}\n")


def _history_payload() -> dict[str, object]:
    # Synthetic UTC row: a 5 m/s wind, followed by a missing hour.
    return {
        "latitude": 28.5,
        "longitude": -80.75,
        "elevation": 5,
        "utc_offset_seconds": 0,
        "hourly_units": {"wind_speed_10m": "m/s", "precipitation": "mm"},
        "hourly": {
            "time": ["2025-10-01T00:00", "2025-10-01T01:00"],
            "wind_speed_10m": [5, None],
            "precipitation": [None, None],
        },
    }


def test_historical_single_model_and_missing_values() -> None:
    series = parse_historical(_history_payload(), single_model="gfs")[0]
    assert series.model == "gfs"
    assert series.values["wind_speed_10m"].shape == (1, 2)
    assert series.values["wind_speed_10m"][0, 0] == 5
    assert np.isnan(series.values["wind_speed_10m"][0, 1])
    assert "precipitation" not in series.values
    assert series.hours[0] == datetime(2025, 10, 1, tzinfo=UTC)


@pytest.mark.parametrize("previous", [False, True])
@pytest.mark.parametrize("unit", ["km/h", "missing"])
def test_historical_units_are_validated(*, previous: bool, unit: str) -> None:
    payload = _history_payload()
    if previous:
        payload["hourly"] = {
            "time": ["2025-10-01T00:00"],
            **{
                f"{variable}_previous_day{lead}": [5]
                for variable in ("wind_speed_10m", "wind_speed_100m", "precipitation")
                for lead in (1, 2, 3)
            },
        }
        payload["hourly_units"] = {
            f"{variable}_previous_day{lead}": (
                unit
                if variable == "wind_speed_10m"
                else "mm"
                if variable == "precipitation"
                else "m/s"
            )
            for variable in ("wind_speed_10m", "wind_speed_100m", "precipitation")
            for lead in (1, 2, 3)
        }
        with pytest.raises(SourceError, match="wind_speed_10m"):
            parse_previous_runs(payload)
    else:
        payload["hourly_units"] = {"wind_speed_10m": unit, "precipitation": "mm"}
        with pytest.raises(SourceError, match="wind_speed_10m"):
            parse_historical(payload)


def test_historical_rejects_misaligned_hours() -> None:
    payload = _history_payload()
    payload["hourly"] = {"time": ["2025-10-01T00:00"], "wind_speed_10m": [5, 6]}
    with pytest.raises(SourceError, match="expected 1 hourly values"):
        parse_historical(payload)


def test_previous_runs_single_model() -> None:
    payload = TypeAdapter(dict[str, object]).validate_json(
        (FIXTURES / "previous_runs_cape_2025-10.json").read_bytes()
    )
    # GFS valid 2025-10-01 00:00: day1 7.47, day2 3.91, day3 4.69 m/s.
    hourly = TypeAdapter(dict[str, object]).validate_python(payload["hourly"])
    units = TypeAdapter(dict[str, str]).validate_python(payload["hourly_units"])
    payload["hourly"] = {
        key.removesuffix("_gfs_seamless"): value
        for key, value in hourly.items()
        if key == "time" or key.endswith("_gfs_seamless")
    }
    payload["hourly_units"] = {
        key.removesuffix("_gfs_seamless"): value
        for key, value in units.items()
        if key.endswith("_gfs_seamless")
    }
    series = parse_previous_runs(payload, single_model="gfs")
    assert len(series) == 1
    assert series[0].model == "gfs"
    assert [
        series[0].leads[lead].values["wind_speed_10m"][0, 0] for lead in (1, 2, 3)
    ] == pytest.approx([7.47, 3.91, 4.69])
    assert series[0].leads[3].hours[0] == datetime(2025, 10, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "bad_key", ["wind_speed_10m_previous_day4", "temperature_500hPa_previous_day1"]
)
def test_previous_runs_rejects_unsupported_keys(bad_key: str) -> None:
    payload = _history_payload()
    payload["hourly"] = {"time": ["2025-10-01T00:00"], bad_key: [5]}
    with pytest.raises(SourceError, match="Unsupported Previous Runs variable"):
        parse_previous_runs(payload)


def test_previous_runs_rejects_incomplete_leads() -> None:
    payload = _history_payload()
    payload["hourly"] = {
        "time": ["2025-10-01T00:00"],
        "wind_speed_10m_previous_day1": [5],
    }
    with pytest.raises(SourceError, match="missing Previous Runs variables"):
        parse_previous_runs(payload)
