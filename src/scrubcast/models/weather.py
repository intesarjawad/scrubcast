"""Validated ensemble responses and member-by-hour weather arrays."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from scrubcast.sources.errors import SourceError

type EnsembleModel = Literal["ecmwf", "gfs"]

_MODEL_SUFFIXES: dict[str, EnsembleModel] = {
    "ecmwf_ifs025_ensemble": "ecmwf",
    "ncep_gefs_seamless": "gfs",
}
_MEMBER_COUNTS: dict[EnsembleModel, int] = {"ecmwf": 51, "gfs": 31}
_SOURCE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"


@dataclass(frozen=True)
class GridPoint:
    """Returned model cell coordinates in degrees and elevation in metres."""

    latitude: float
    longitude: float
    elevation: float


@dataclass(frozen=True)
class EnsembleSeries:
    """One model's member-by-hour arrays, with NaN for individual missing values."""

    model: EnsembleModel
    members: int
    hours: list[datetime]
    values: dict[str, npt.NDArray[np.float32]]
    grid_point: GridPoint


class _EnsembleResponse(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    elevation: float
    utc_offset_seconds: Literal[0]
    hourly_units: dict[str, str]
    hourly: dict[str, list[JsonValue]]


def _series_key(key: str, single_model: EnsembleModel) -> tuple[EnsembleModel, str, int]:
    member = 0
    match = re.search(r"_member(\d+)(?=_|$)", key)
    if match:
        member = int(match[1])
        key = key[: match.start()] + key[match.end() :]
        if member == 0:
            msg = f"Invalid control member key: {key}"
            raise ValueError(msg)
    for suffix, model in _MODEL_SUFFIXES.items():
        if key.endswith(f"_{suffix}"):
            return model, key.removesuffix(f"_{suffix}"), member
    return single_model, key, member


def _expected_unit(variable: str) -> str:
    for prefix, unit in (
        ("wind_speed_", "m/s"),
        ("wind_gusts_", "m/s"),
        ("wind_direction_", "°"),
        ("temperature_", "°C"),
        ("geopotential_height_", "m"),
        ("cloud_cover", "%"),
        ("relative_humidity_", "%"),
    ):
        if variable.startswith(prefix):
            return unit
    if variable == "precipitation":
        return "mm"
    if variable == "cape":
        return "J/kg"
    msg = f"Unknown ensemble variable: {variable}"
    raise ValueError(msg)


def _group_members(
    response: _EnsembleResponse, single_model: EnsembleModel, hours: int
) -> dict[EnsembleModel, dict[str, dict[int, list[float | None]]]]:
    groups: dict[EnsembleModel, dict[str, dict[int, list[float | None]]]] = {}
    raw_values = {key: value for key, value in response.hourly.items() if key != "time"}
    validated = TypeAdapter(dict[str, list[float | None]]).validate_python(raw_values)
    for key, values in validated.items():
        model, variable, member = _series_key(key, single_model)
        expected = _expected_unit(variable)
        unit = response.hourly_units.get(key)
        if unit != expected and not (unit == "undefined" and all(v is None for v in values)):
            msg = f"{key}: unit {unit!r}; expected {expected!r}"
            raise ValueError(msg)
        if len(values) != hours:
            msg = f"{key}: expected {hours} hourly values, got {len(values)}"
            raise ValueError(msg)
        members = groups.setdefault(model, {}).setdefault(variable, {})
        if member in members:
            msg = f"{key}: duplicate member {member}"
            raise ValueError(msg)
        members[member] = values
    if not groups:
        msg = "Ensemble response contains no weather variables"
        raise ValueError(msg)
    return groups


def _validate_members(
    model: EnsembleModel, variable: str, members: dict[int, list[float | None]]
) -> None:
    count = _MEMBER_COUNTS[model]
    if set(members) != set(range(count)):
        msg = f"{model} {variable}: expected members 0 through {count - 1}"
        raise ValueError(msg)


def parse_ensemble(
    payload: object, *, single_model: EnsembleModel = "ecmwf", url: str = _SOURCE_URL
) -> list[EnsembleSeries]:
    """Parse both suffixed key orders; unsuffixed requests default to ECMWF."""
    try:
        response = _EnsembleResponse.model_validate(payload)
        times = TypeAdapter(list[datetime]).validate_python(response.hourly.get("time"))
        hours = [
            hour.replace(tzinfo=UTC) if hour.tzinfo is None else hour.astimezone(UTC)
            for hour in times
        ]
        groups = _group_members(response, single_model, len(hours))
        point = GridPoint(response.latitude, response.longitude, response.elevation)
        result: list[EnsembleSeries] = []
        for model, variables in groups.items():
            count = _MEMBER_COUNTS[model]
            arrays: dict[str, npt.NDArray[np.float32]] = {}
            for variable, members in variables.items():
                _validate_members(model, variable, members)
                if all(value is None for value in members[0]):
                    continue
                arrays[variable] = np.asarray(
                    [members[index] for index in range(count)], dtype=np.float32
                )
            result.append(EnsembleSeries(model, count, hours, arrays, point))
    except ValueError as error:
        raise SourceError(url, None, str(error)) from error
    return result
