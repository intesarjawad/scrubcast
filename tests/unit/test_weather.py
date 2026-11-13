from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pytest
from pydantic import JsonValue, TypeAdapter

from scrubcast.models.weather import parse_ensemble
from scrubcast.sources.errors import SourceError

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _fixture(filename: str = "open_meteo_cape.json") -> dict[str, object]:
    return TypeAdapter(dict[str, object]).validate_json((FIXTURES / filename).read_text())


@pytest.mark.parametrize(
    ("filename", "counts", "point"),
    [
        ("open_meteo_cape.json", {"ecmwf": 51, "gfs": 31}, (28.5, -80.75, 5)),
        ("open_meteo_vandenberg.json", {"ecmwf": 51, "gfs": 31}, (34.75, -120.5, 144)),
        ("open_meteo_tierc_ecmwf_only.json", {"ecmwf": 51}, (30.5, 131, 17)),
    ],
)
def test_fixtures(filename: str, counts: dict[str, int], point: tuple[float, ...]) -> None:
    series = parse_ensemble(_fixture(filename))
    assert {item.model: item.members for item in series} == counts
    for item in series:
        assert len(item.hours) == 72
        assert item.hours[0] == datetime(2026, 11, 5, tzinfo=UTC)
        assert (
            item.grid_point.latitude,
            item.grid_point.longitude,
            item.grid_point.elevation,
        ) == point
        assert len(item.values) == (41 if item.model == "gfs" else 42)
        assert all(array.shape == (item.members, 72) for array in item.values.values())
        assert all(array.dtype == np.float32 for array in item.values.values())
        assert ("cloud_cover_high" in item.values) == (item.model == "ecmwf")
        with pytest.raises(FrozenInstanceError):
            item.__setattr__("members", 0)


@pytest.mark.parametrize("member_first", [True, False])
def test_key_order_and_member_order(*, member_first: bool) -> None:
    payload = _fixture()
    hourly = TypeAdapter(dict[str, list[JsonValue]]).validate_python(payload["hourly"])
    units = TypeAdapter(dict[str, str]).validate_python(payload["hourly_units"])
    if not member_first:

        def rename(key: str) -> str:
            if "_member" not in key:
                return key
            variable, rest = key.split("_member")
            member, suffix = rest.split("_", 1)
            return f"{variable}_{suffix}_member{member}"

        hourly = {rename(key): value for key, value in hourly.items()}
        units = {rename(key): value for key, value in units.items()}
    payload["hourly"] = dict(reversed(list(hourly.items())))
    payload["hourly_units"] = units
    series = {item.model: item for item in parse_ensemble(payload)}
    original = {item.model: item for item in parse_ensemble(_fixture())}
    for model, item in series.items():
        for variable, values in item.values.items():
            np.testing.assert_array_equal(values, original[model].values[variable])


def test_missing_single_value_is_nan() -> None:
    payload = _fixture()
    hourly = TypeAdapter(dict[str, list[JsonValue]]).validate_python(payload["hourly"])
    hourly["wind_speed_10m_member01_ecmwf_ifs025_ensemble"][2] = None
    payload["hourly"] = hourly
    values = parse_ensemble(payload)[0].values["wind_speed_10m"]
    assert np.isnan(values[1, 2])
    assert values[0, 0] == np.float32(2)
    assert np.isfinite(values[1, 1])


@pytest.mark.parametrize("member", ["", "_member01", "_member50"])
def test_partial_variable_raises(member: str) -> None:
    payload = _fixture()
    hourly = TypeAdapter(dict[str, list[JsonValue]]).validate_python(payload["hourly"])
    del hourly[f"wind_speed_10m{member}_ecmwf_ifs025_ensemble"]
    payload["hourly"] = hourly
    with pytest.raises(SourceError, match=r"wind_speed_10m.*members"):
        parse_ensemble(payload)


@pytest.mark.parametrize(
    ("variable", "unit"),
    [
        ("wind_speed_10m", "km/h"),
        ("wind_gusts_10m", "km/h"),
        ("precipitation", "inch"),
        ("temperature_850hPa", "°F"),
        ("geopotential_height_850hPa", "ft"),
        ("cloud_cover_high", "fraction"),
        ("relative_humidity_850hPa", "fraction"),
        ("wind_direction_500hPa", "rad"),
        ("cape", "invalid"),
    ],
)
def test_wrong_units_raise(variable: str, unit: str) -> None:
    payload = _fixture()
    hourly = TypeAdapter(dict[str, list[JsonValue]]).validate_python(payload["hourly"])
    units = TypeAdapter(dict[str, str]).validate_python(payload["hourly_units"])
    for member in range(51):
        member_suffix = f"_member{member:02d}" if member else ""
        key = f"{variable}{member_suffix}_ecmwf_ifs025_ensemble"
        hourly.setdefault(key, [1.0] * 72)
        units[key] = unit
    payload["hourly"] = hourly
    payload["hourly_units"] = units
    with pytest.raises(SourceError, match=f"{variable}.*{unit}"):
        parse_ensemble(payload)


@pytest.mark.parametrize("problem", ["length", "numeric", "unit", "timezone", "key"])
def test_invalid_response_raises(problem: str) -> None:
    payload = _fixture()
    hourly = TypeAdapter(dict[str, list[JsonValue]]).validate_python(payload["hourly"])
    key = "wind_speed_10m_ecmwf_ifs025_ensemble"
    if problem == "length":
        hourly[key].pop()
    elif problem == "numeric":
        hourly[key][0] = "invalid"
    elif problem == "unit":
        payload["hourly_units"] = {}
    elif problem == "timezone":
        payload["utc_offset_seconds"] = 3600
    else:
        hourly["unknown_model"] = [1.0] * 72
    payload["hourly"] = hourly
    with pytest.raises(SourceError):
        parse_ensemble(payload)


@pytest.mark.parametrize("model", ["ecmwf", "gfs"])
def test_single_model_identity(model: Literal["ecmwf", "gfs"]) -> None:
    payload = _fixture()
    suffix = "ecmwf_ifs025_ensemble" if model == "ecmwf" else "ncep_gefs_seamless"
    for field in ("hourly", "hourly_units"):
        mapping = TypeAdapter(dict[str, JsonValue]).validate_python(payload[field])
        payload[field] = {
            key.removesuffix(f"_{suffix}"): value
            for key, value in mapping.items()
            if key == "time" or key.endswith(f"_{suffix}")
        }
    series = parse_ensemble(payload, single_model=model)
    assert len(series) == 1
    assert series[0].model == model
    assert series[0].members == (51 if model == "ecmwf" else 31)


@pytest.mark.parametrize("control_missing", [True, False])
def test_control_determines_variable_availability(*, control_missing: bool) -> None:
    payload = _fixture("open_meteo_tierc_ecmwf_only.json")
    hourly = TypeAdapter(dict[str, list[JsonValue]]).validate_python(payload["hourly"])
    key = "wind_speed_10m" if control_missing else "wind_speed_10m_member01"
    hourly[key] = [None] * 72
    payload["hourly"] = hourly
    values = parse_ensemble(payload)[0].values
    assert ("wind_speed_10m" in values) != control_missing
    if not control_missing:
        assert np.isnan(values["wind_speed_10m"][1]).all()


def test_undefined_unit_requires_null_values() -> None:
    payload = _fixture()
    hourly = TypeAdapter(dict[str, list[JsonValue]]).validate_python(payload["hourly"])
    hourly["cloud_cover_high_ncep_gefs_seamless"][0] = 50.0
    payload["hourly"] = hourly
    with pytest.raises(SourceError, match=r"cloud_cover_high.*undefined"):
        parse_ensemble(payload)
