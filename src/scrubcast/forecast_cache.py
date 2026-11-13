"""JSON forecast cache preserving source metadata and missing member values."""

import numpy as np
from pydantic import AwareDatetime, BaseModel, ConfigDict

from scrubcast.models.weather import EnsembleModel, EnsembleSeries, GridPoint
from scrubcast.sources.weather_source import ForecastResponse


class SavedSeries(BaseModel):
    """JSON representation using null for missing member values."""

    model: EnsembleModel
    members: int
    hours: list[AwareDatetime]
    values: dict[str, list[list[float | None]]]
    grid_point: GridPoint


class SavedForecast(BaseModel):
    """Source metadata and arrays sufficient for offline collection and replay."""

    model_config = ConfigDict(ser_json_inf_nan="null")

    fetched_at: AwareDatetime
    generationtime_ms: float
    cost_units: float
    remaining_units: float
    series: list[SavedSeries]

    @classmethod
    def from_response(cls, response: ForecastResponse) -> SavedForecast:
        """Encode arrays without filling missing weather with zero."""
        return cls(
            fetched_at=response.fetched_at,
            generationtime_ms=response.generationtime_ms,
            cost_units=response.cost_units,
            remaining_units=response.remaining_units,
            series=[
                SavedSeries(
                    model=item.model,
                    members=item.members,
                    hours=item.hours,
                    grid_point=item.grid_point,
                    values={name: values.tolist() for name, values in item.values.items()},
                )
                for item in response.series
            ],
        )

    def response(self) -> ForecastResponse:
        """Restore float32 member arrays for archive consumers."""
        return ForecastResponse(
            fetched_at=self.fetched_at,
            generationtime_ms=self.generationtime_ms,
            cost_units=self.cost_units,
            remaining_units=self.remaining_units,
            series=[
                EnsembleSeries(
                    model=item.model,
                    members=item.members,
                    hours=item.hours,
                    grid_point=item.grid_point,
                    values={
                        name: np.asarray(values, dtype=np.float32)
                        for name, values in item.values.items()
                    },
                )
                for item in self.series
            ],
        )
