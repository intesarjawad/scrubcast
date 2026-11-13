"""Versioned rule data and resolved plot values used by launch assessments."""

import re
from datetime import date
from enum import StrEnum
from string import Formatter
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class Confidence(StrEnum):
    """Evidence strength of a model-based rule assessment."""

    DIRECT = "direct"
    MEDIUM = "medium"
    LOW = "low"


class Tier(StrEnum):
    """Site coverage of published launch weather criteria."""

    A = "A"
    B = "B"
    C = "C"


type SourceDate = date


type Comparator = Literal[">", ">=", "<="]
type Parameter = float | str


class Plot(BaseModel):
    """Parameter references shared by the verdict, threshold line and readout."""

    variable: str
    unit: str
    threshold_param: str
    comparator_param: str
    readout_phrase: str

    def validate_params(self, params: dict[str, Parameter]) -> None:
        """Reject dangling references and readouts that duplicate numeric parameters."""
        if re.search(r"\d", re.sub(r"\{[a-z_]+\}", "", self.readout_phrase)):
            msg = "readout_phrase contains a literal number"
            raise ValueError(msg)
        for _, name, spec, conversion in Formatter().parse(self.readout_phrase):
            if name is not None and (
                re.fullmatch(r"[a-z_]+", name) is None or name not in params or spec or conversion
            ):
                msg = f"Invalid readout placeholder: {name}"
                raise ValueError(msg)
        if self.threshold_param not in params or isinstance(params[self.threshold_param], str):
            msg = f"Missing numeric threshold parameter: {self.threshold_param}"
            raise ValueError(msg)
        if params.get(self.comparator_param) not in {">", ">=", "<="}:
            msg = f"Invalid comparator parameter: {self.comparator_param}"
            raise ValueError(msg)


class Rule(BaseModel):
    """Published criterion and its explicitly approximate model proxy."""

    rule_id: str
    title: str
    llccr: list[int]
    section: str
    text: str
    evaluation: Literal["proxy"]
    confidence: Confidence
    needs: list[str]
    proxy: dict[str, Parameter]
    origin: dict[str, Literal["scrub"]] = Field(default_factory=dict)
    plot: Plot
    approximation_note: str
    reference_only: bool = False

    @model_validator(mode="after")
    def validate_plot(self) -> Self:
        """Keep plot references and parameter provenance tied to this proxy."""
        self.plot.validate_params(self.proxy)
        if self.origin.keys() - self.proxy.keys():
            msg = f"Unknown origin parameter in {self.rule_id}"
            raise ValueError(msg)
        return self


class NotEvaluable(BaseModel):
    """Criterion omitted from verdicts because the required evidence is unavailable."""

    rule_id: str
    title: str
    llccr: list[int]
    reason: str


class RuleSet(BaseModel):
    """Dated source criteria loaded together before any launch is assessed."""

    rule_set_id: str
    version: str
    source_url: str
    source_date: SourceDate
    rules: list[Rule]
    not_evaluable: list[NotEvaluable]

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        """Reject ambiguous identifiers across evaluable and omitted criteria."""
        ids = [rule.rule_id for rule in [*self.rules, *self.not_evaluable]]
        if len(ids) != len(set(ids)):
            msg = f"Duplicate rule identifier in {self.rule_set_id}"
            raise ValueError(msg)
        return self


class VehicleConfig(BaseModel):
    """Published liftoff wind limit, including its measurement height and scope."""

    vehicle_id: str
    rocket_names: list[str]
    rule_id: Literal["liftoff_wind"]
    threshold_mps: float = Field(gt=0)
    reference_height_m: float = Field(gt=0)
    measure: Literal["sustained", "peak"]
    comparator: Comparator
    source_url: str
    source_note: str
    plot: Plot

    def parameters(self) -> dict[str, Parameter]:
        """Expose the same vehicle values used by wind evaluation and plotting."""
        return {
            "threshold_mps": self.threshold_mps,
            "reference_height_m": self.reference_height_m,
            "comparator": self.comparator,
        }

    @model_validator(mode="after")
    def validate_plot(self) -> Self:
        """Require wind readouts to resolve against the published vehicle values."""
        self.plot.validate_params(self.parameters())
        return self


class Coordinates(BaseModel):
    """Geographic degrees for a forecast request or a verified pad correction."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ForecastPoint(Coordinates):
    """Stable identity shared by pads using one forecast request."""

    point_id: str


class SiteConfig(BaseModel):
    """Site coverage independent of vehicle, with optional pad coordinate corrections."""

    site_id: str
    location_ids: list[int]
    tier: Tier
    forecast_point: ForecastPoint | None
    metar_station: str | None
    rule_sets: list[str]
    reference_only: bool
    confidence: Confidence | None = None
    coordinate_overrides: dict[int, Coordinates] = Field(default_factory=dict[int, Coordinates])


class Threshold(BaseModel):
    """Resolved comparison in the plotted variable's units."""

    value: float
    unit: str
    comparator: Comparator


class ResolvedPlot(BaseModel):
    """Display-ready plot metadata without unresolved parameter names."""

    variable: str
    unit: str
    readout_phrase: str
    origin: Literal["source", "scrub"]


class RuleSelection(BaseModel):
    """Site criteria and the vehicle wind rule available for a launch."""

    site: SiteConfig
    rules: list[Rule]
    vehicle: VehicleConfig | None
    not_evaluable: list[NotEvaluable]


class ConcernMatch(BaseModel):
    """Original official spelling retained even when no known rule matches."""

    name: str
    rule_id: str | None
