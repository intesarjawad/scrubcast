"""Open-Meteo ensemble requests with measured upstream cost metadata."""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from scrubcast.models.weather import EnsembleModel, parse_ensemble
from scrubcast.sources.errors import SourceError
from scrubcast.sources.weather_source import ForecastResponse

if TYPE_CHECKING:
    from collections.abc import Sequence

    from scrubcast.models.rules import Coordinates

OPEN_METEO_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
_MODEL_NAMES: dict[EnsembleModel, str] = {"ecmwf": "ecmwf_ifs025", "gfs": "gfs_seamless"}


class _Metadata(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    generationtime_ms: float = Field(ge=0)


class _CostHeaders(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    cost_units: float = Field(alias="x-ratelimit-cost", ge=0)
    remaining_units: float = Field(alias="x-ratelimit-remaining", ge=0)


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


class OpenMeteoSource:
    """Use an injected synchronous client so the caller owns transport and lifetime."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def forecast(
        self,
        point: Coordinates,
        models: Sequence[EnsembleModel],
        variables: Sequence[str],
        days: int,
    ) -> ForecastResponse:
        """Request UTC hours in SI wind units and preserve upstream accounting."""
        if not models or not variables or days < 1:
            message = "Forecast requests require models, variables and positive days"
            raise ValueError(message)
        url = httpx.URL(
            OPEN_METEO_URL,
            params={
                "latitude": point.latitude,
                "longitude": point.longitude,
                "models": ",".join(_MODEL_NAMES[model] for model in models),
                "forecast_days": days,
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
            payload = _payload(response)
            metadata = _Metadata.model_validate(payload)
            costs = _CostHeaders.model_validate(dict(response.headers))
            fetched_at = _fetched_at(response)
            series = parse_ensemble(payload, single_model=models[0], url=str(response.url))
        except httpx.HTTPStatusError as error:
            raise SourceError(
                str(response.url),
                response.status_code,
                str(error),
                retry_after=response.headers.get("Retry-After"),
            ) from error
        except SourceError as error:
            raise SourceError(
                str(response.url),
                response.status_code,
                error.reason,
                retry_after=response.headers.get("Retry-After"),
            ) from error
        except (ValueError, KeyError) as error:
            raise SourceError(
                str(response.url),
                response.status_code,
                str(error),
                retry_after=response.headers.get("Retry-After"),
            ) from error
        return ForecastResponse(
            series=series,
            cost_units=costs.cost_units,
            remaining_units=costs.remaining_units,
            fetched_at=fetched_at,
            generationtime_ms=metadata.generationtime_ms,
        )
