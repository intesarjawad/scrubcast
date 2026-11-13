"""Station observations retain missing measurements and their physical units."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class CloudLayer(BaseModel):
    """A reported sky condition and optional base height above ground in feet."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    cover: Literal["CLR", "SKC", "FEW", "SCT", "BKN", "OVC", "VV"] | None
    base_ft: float | None = Field(ge=0)


class Observation(BaseModel):
    """One UTC METAR; precipitation stays in inches to preserve trace semantics."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    station: str = Field(min_length=1)
    valid: AwareDatetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    wind_speed_mps: float | None = Field(ge=0)
    wind_gust_mps: float | None = Field(ge=0)
    precipitation_in: float | None = Field(ge=0)
    cloud_layers: tuple[CloudLayer, ...]
