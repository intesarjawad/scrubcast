"""Launch Library fields used by scheduling, weather assessment and outcome audits."""

from enum import StrEnum

from pydantic import AliasPath, AwareDatetime, BaseModel, ConfigDict, Field


class LaunchStatus(StrEnum):
    """Known LL2 status abbreviations, including completed launch outcomes."""

    GO = "Go"
    TBD = "TBD"
    SUCCESS = "Success"
    FAILURE = "Failure"
    HOLD = "Hold"
    IN_FLIGHT = "In Flight"
    PARTIAL_FAILURE = "Partial Failure"
    TBC = "TBC"
    PAYLOAD_DEPLOYED = "Payload Deployed"


class Location(BaseModel):
    """Launch site identity and IANA time zone for local launch times."""

    id: int
    name: str
    timezone_name: str


class Pad(BaseModel):
    """Launch pad position in geographic degrees and its parent site."""

    id: int
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location: Location


class Orbit(BaseModel):
    """Orbit abbreviation retained for the schedule's suborbital filter."""

    abbrev: str


class Mission(BaseModel):
    """Mission orbit, which LL2 may not yet identify."""

    orbit: Orbit | None


class Launch(BaseModel):
    """Consumed LL2 normal fields; probability is the official integer percent of GO."""

    # Accept saved model output as well as the nested source fields.
    model_config = ConfigDict(validate_by_name=True)

    id: str
    name: str
    slug: str
    status: LaunchStatus = Field(validation_alias=AliasPath("status", "abbrev"))
    net: AwareDatetime
    net_precision: str | None = Field(validation_alias=AliasPath("net_precision", "abbrev"))
    window_start: AwareDatetime
    window_end: AwareDatetime
    probability: int | None = Field(ge=0, le=100, strict=True)
    weather_concerns: str | None
    launch_service_provider_name: str = Field(
        validation_alias=AliasPath("launch_service_provider", "name"),
    )
    rocket_name: str = Field(validation_alias=AliasPath("rocket", "configuration", "name"))
    pad: Pad
    mission: Mission | None
    last_updated: AwareDatetime


class LaunchUpdate(BaseModel):
    """Dated source comment used as evidence when classifying an attempt's outcome."""

    created_on: AwareDatetime
    comment: str


class LaunchDetailed(Launch):
    """LL2 detailed fields, requiring audit evidence even when the update list is empty."""

    updates: list[LaunchUpdate]


def parse_concerns(text: str | None) -> list[str]:
    """Split official concern names, preserving spelling and order for rule mapping."""
    if text is None:
        return []
    concerns = (part.strip() for part in text.split(","))
    return [concern for concern in concerns if concern]
