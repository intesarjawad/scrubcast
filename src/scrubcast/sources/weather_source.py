"""Forecast source contract shared by collection and request accounting."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from scrubcast.models.rules import Coordinates
    from scrubcast.models.weather import EnsembleModel, EnsembleSeries


@dataclass(frozen=True)
class ForecastResponse:
    """Validated series and upstream metadata for freshness and budget records."""

    series: list[EnsembleSeries]
    cost_units: float
    remaining_units: float
    fetched_at: datetime
    generationtime_ms: float


class WeatherSource(Protocol):
    """Provide ensemble forecasts without exposing provider request details."""

    def forecast(
        self,
        point: Coordinates,
        models: Sequence[EnsembleModel],
        variables: Sequence[str],
        days: int,
    ) -> ForecastResponse:
        """Fetch hourly series and the measured request cost for one point."""
        ...
