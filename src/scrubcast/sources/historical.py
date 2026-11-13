"""Deterministic history and forecasts issued one to three days before valid time."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Literal

import httpx
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from scrubcast.models.weather import EnsembleModel, EnsembleSeries, GridPoint
from scrubcast.sources.errors import SourceError
from scrubcast.sources.weather_source import ForecastResponse

if TYPE_CHECKING:
    from collections.abc import Sequence

    from scrubcast.models.rules import Coordinates

HISTORICAL_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_VARIABLES = ("wind_speed_10m", "wind_speed_100m", "precipitation")

_MODEL_NAMES: dict[EnsembleModel, str] = {"ecmwf": "ecmwf_ifs025", "gfs": "gfs_seamless"}


class _HistoricalResponse(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    elevation: float
    utc_offset_seconds: Literal[0]
    hourly_units: dict[str, str]
    hourly: dict[str, list[JsonValue]]


class _Metadata(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    generationtime_ms: float = Field(ge=0)


class _CostHeaders(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    cost_units: float = Field(alias="x-ratelimit-cost", ge=0)
    remaining_units: float = Field(alias="x-ratelimit-remaining", ge=0)


def _expected_unit(variable: str) -> str:
    for prefix, unit in (
        ("wind_speed_", "m/s"),
        ("wind_gusts_", "m/s"),
        ("wind_direction_", "°"),
        ("temperature_", "°C"),
        ("geopotential_height_", "m"),
        ("cloud_cover", "%"),
        ("relative_humidity_", "%"),
        ("precipitation", "mm"),
        ("cape", "J/kg"),
    ):
        if variable.startswith(prefix):
            return unit
    message = f"Unknown historical variable: {variable}"
    raise ValueError(message)


def _payload(response: httpx.Response) -> dict[str, JsonValue]:
    try:
        payload = TypeAdapter(dict[str, JsonValue]).validate_json(response.content)
    except ValueError:
        response.raise_for_status()
        raise
    if payload.get("error") is True:
        raise SourceError(str(response.url), response.status_code, str(payload.get("reason")))
    response.raise_for_status()
    return payload


def _fetched_at(response: httpx.Response) -> datetime:
    fetched_at = parsedate_to_datetime(response.headers["date"])
    if fetched_at.utcoffset() is None:
        message = "HTTP Date must include a UTC offset"
        raise ValueError(message)
    return fetched_at.astimezone(UTC)


@dataclass(frozen=True)
class PreviousRunsSeries:
    """One model's deterministic forecasts indexed by days before valid time."""

    model: EnsembleModel
    leads: dict[int, EnsembleSeries]


def parse_historical(
    payload: object, *, single_model: EnsembleModel = "ecmwf", url: str = HISTORICAL_URL
) -> list[EnsembleSeries]:
    """Keep the member-by-hour contract with a single deterministic member.

    Individual nulls become NaN; entirely null variables remain absent, just as
    they do for ensemble forecasts. Valid times are UTC, not issue times.
    """
    try:
        return _historical_series(payload, single_model)
    except ValueError as error:
        raise SourceError(url, None, str(error)) from error


def _historical_series(payload: object, single_model: EnsembleModel) -> list[EnsembleSeries]:
    response = _HistoricalResponse.model_validate(payload)
    times = TypeAdapter(list[datetime]).validate_python(response.hourly.get("time"))
    hours = [
        hour.replace(tzinfo=UTC) if hour.tzinfo is None else hour.astimezone(UTC) for hour in times
    ]
    raw = {key: values for key, values in response.hourly.items() if key != "time"}
    values = TypeAdapter(dict[str, list[float | None]]).validate_python(raw)
    groups: dict[EnsembleModel, dict[str, list[float | None]]] = {}
    for key, row in values.items():
        model = single_model
        variable = key
        for name, suffix in _MODEL_NAMES.items():
            if key.endswith(f"_{suffix}"):
                model, variable = name, key.removesuffix(f"_{suffix}")
                break
        expected = _expected_unit(variable)
        unit = response.hourly_units.get(key)
        if unit != expected and not (unit == "undefined" and all(v is None for v in row)):
            message = f"{key}: unit {unit!r}; expected {expected!r}"
            raise ValueError(message)
        if len(row) != len(hours):
            message = f"{key}: expected {len(hours)} hourly values, got {len(row)}"
            raise ValueError(message)
        variables = groups.setdefault(model, {})
        if variable in variables:
            message = f"{key}: duplicate variable {variable}"
            raise ValueError(message)
        variables[variable] = row
    if not hours or not groups:
        message = "Historical response contains no hours or weather variables"
        raise ValueError(message)
    point = GridPoint(response.latitude, response.longitude, response.elevation)
    return [
        EnsembleSeries(
            model,
            1,
            hours,
            {
                variable: np.asarray([row], dtype=np.float32)
                for variable, row in variables.items()
                if any(value is not None for value in row)
            },
            point,
        )
        for model, variables in groups.items()
    ]


def _validate_previous_keys(response: _HistoricalResponse, single_model: EnsembleModel) -> None:
    groups: dict[EnsembleModel, set[str]] = {}
    expected = {
        f"{variable}_previous_day{lead}"
        for variable in PREVIOUS_RUNS_VARIABLES
        for lead in (1, 2, 3)
    }
    for key in response.hourly:
        if key == "time":
            continue
        variable, model = key, single_model
        for name, suffix in _MODEL_NAMES.items():
            if key.endswith(f"_{suffix}"):
                variable, model = key.removesuffix(f"_{suffix}"), name
                break
        if variable not in expected:
            message = f"Unsupported Previous Runs variable: {key}"
            raise ValueError(message)
        groups.setdefault(model, set()).add(variable)
    for model, keys in groups.items():
        if keys != expected:
            message = f"{model}: missing Previous Runs variables: {sorted(expected - keys)}"
            raise ValueError(message)


def parse_previous_runs(
    payload: object, *, single_model: EnsembleModel = "ecmwf", url: str = PREVIOUS_RUNS_URL
) -> list[PreviousRunsSeries]:
    """Split previous_day1..3 into independent deterministic series per model."""
    try:
        response = _HistoricalResponse.model_validate(payload)
        _validate_previous_keys(response, single_model)
        groups: dict[EnsembleModel, dict[int, EnsembleSeries]] = {}
        for lead in (1, 2, 3):
            suffix = f"_previous_day{lead}"
            hourly = {"time": response.hourly["time"]}
            units: dict[str, str] = {}
            for key, row in response.hourly.items():
                if key == "time":
                    continue
                variable = key
                for model_suffix in _MODEL_NAMES.values():
                    variable = variable.removesuffix(f"_{model_suffix}")
                if variable not in {f"{name}{suffix}" for name in PREVIOUS_RUNS_VARIABLES}:
                    continue
                renamed = key.replace(suffix, "")
                hourly[renamed] = row
                units[renamed] = response.hourly_units[key]
            data = response.model_dump()
            data.update(hourly=hourly, hourly_units=units)
            for series in parse_historical(data, single_model=single_model, url=url):
                groups.setdefault(series.model, {})[lead] = series
        return [PreviousRunsSeries(model, leads) for model, leads in groups.items()]
    except (ValueError, KeyError) as error:
        raise SourceError(url, None, str(error)) from error


class HistoricalSource:
    """Use explicit models and dates with an injected synchronous HTTP client."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def forecast(
        self,
        point: Coordinates,
        models: Sequence[EnsembleModel],
        variables: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> ForecastResponse:
        """Fetch deterministic history for one point and calendar-month interval."""
        response = self._request(
            HISTORICAL_URL, point, models, variables, dates=(start_date, end_date)
        )
        try:
            payload = _payload(response)
            metadata = _Metadata.model_validate(payload)
            costs = _CostHeaders.model_validate(dict(response.headers))
            return ForecastResponse(
                series=parse_historical(payload, single_model=models[0], url=str(response.url)),
                cost_units=costs.cost_units,
                remaining_units=costs.remaining_units,
                fetched_at=_fetched_at(response),
                generationtime_ms=metadata.generationtime_ms,
            )
        except (ValueError, KeyError, SourceError) as error:
            reason = error.reason if isinstance(error, SourceError) else str(error)
            raise SourceError(
                str(response.url),
                response.status_code,
                reason,
                retry_after=response.headers.get("Retry-After"),
            ) from error

    def previous_runs(
        self,
        point: Coordinates,
        model: EnsembleModel,
        start_date: date,
        end_date: date,
    ) -> list[PreviousRunsSeries]:
        """Fetch one model-month, retaining each lead's original valid hours."""
        variables = [
            f"{variable}_previous_day{lead}"
            for variable in PREVIOUS_RUNS_VARIABLES
            for lead in (1, 2, 3)
        ]
        response = self._request(
            PREVIOUS_RUNS_URL, point, [model], variables, dates=(start_date, end_date)
        )
        try:
            return parse_previous_runs(
                _payload(response), single_model=model, url=str(response.url)
            )
        except (ValueError, KeyError, SourceError) as error:
            reason = error.reason if isinstance(error, SourceError) else str(error)
            raise SourceError(
                str(response.url),
                response.status_code,
                reason,
                retry_after=response.headers.get("Retry-After"),
            ) from error

    def _request(
        self,
        endpoint: str,
        point: Coordinates,
        models: Sequence[EnsembleModel],
        variables: Sequence[str],
        *,
        dates: tuple[date, date],
    ) -> httpx.Response:
        start_date, end_date = dates
        if not models or not variables or start_date > end_date:
            message = "Historical requests require models, variables and ordered dates"
            raise ValueError(message)
        url = httpx.URL(
            endpoint,
            params={
                "latitude": point.latitude,
                "longitude": point.longitude,
                "models": ",".join(_MODEL_NAMES[model] for model in models),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "timezone": "UTC",
                "wind_speed_unit": "ms",
                "hourly": ",".join(sorted(variables)),
            },
        )
        try:
            response = self._client.get(url)
        except httpx.RequestError as error:
            raise SourceError(str(error.request.url), None, str(error)) from error
        try:
            _payload(response)
        except (httpx.HTTPStatusError, ValueError, SourceError) as error:
            reason = error.reason if isinstance(error, SourceError) else str(error)
            raise SourceError(
                str(response.url),
                response.status_code,
                reason,
                retry_after=response.headers.get("Retry-After"),
            ) from error
        return response
