"""Assessment and audit records shared by the CLI and published launch data."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from scrubcast.models.launch import Launch
from scrubcast.models.rules import Confidence, ResolvedPlot, Threshold, Tier
from scrubcast.models.weather import EnsembleModel

__all__ = [
    "AuditFooter",
    "Confidence",
    "Context",
    "EnsembleModel",
    "Launch",
    "LaunchAssessment",
    "LedgerRow",
    "ModelRisk",
    "Official",
    "ResolvedPlot",
    "RuleRisk",
    "Threshold",
    "Tier",
]


class ModelRisk(BaseModel):
    """T-0 rule risk with its evaluable and supplied member counts."""

    risk_fraction: float | None
    evaluable_members: int
    members: int


class RuleRisk(BaseModel):
    """Resolved criterion with hourly evidence and a separate T-0 summary."""

    rule_id: str
    title: str
    confidence: Confidence
    reference_only: bool
    approximation_note: str
    llccr: list[int]
    source_url: str
    rule_set_version: str
    by_model: dict[EnsembleModel, ModelRisk]
    hours: list[AwareDatetime]
    risk_by_hour: dict[EnsembleModel, list[float | None]]
    member_values_by_hour: dict[EnsembleModel, list[list[float | None]] | None]
    member_violated_by_hour: dict[EnsembleModel, list[list[Literal[0, 1] | None]] | None]
    threshold: Threshold | None
    plot: ResolvedPlot


class GridPoint(BaseModel):
    """Returned forecast cell in display units."""

    lat: float
    lon: float
    elevation_m: float


class LowestHour(BaseModel):
    """Material ECMWF improvement within the launch window."""

    hour: AwareDatetime
    union_risk: float
    members_below_t0: int


class OmittedRule(BaseModel):
    """Unavailable criterion and the reason it cannot be evaluated."""

    rule_id: str
    title: str
    reason: str


class Context(BaseModel):
    """Context values remain absent when weather or historical evidence is missing."""

    convective_fraction_t0: float | None
    upper_wind_percentile_t0: float | None
    shear_percentile_t0: float | None


class Official(BaseModel):
    """Official forecast kept separate from modelled member fractions."""

    probability_go_pct: int | None
    concerns: list[str]
    unmapped_concerns: list[str]
    source: Literal["Launch Library 2"] = "Launch Library 2"


class AuditRule(BaseModel):
    """Rule evidence from an attempt's 24-hour ledger row."""

    rule_id: str
    title: str
    risk_fraction: float


class AuditNote(BaseModel):
    """Dated launch outcome evidence."""

    created_on: AwareDatetime
    text: str


class AuditFooter(BaseModel):
    """Outcome of one audited launch attempt."""

    attempt_id: str
    attempt_net: AwareDatetime
    official_concerns: list[str]
    scrubcast_24h: list[AuditRule]
    outcome: Literal["launched", "launched_later", "new_t0_pending", "hold", "unknown"]
    net_now: AwareDatetime | None
    note: AuditNote | None


class LaunchAssessment(BaseModel):
    """Versioned launch-page assessment contract."""

    schema_version: Literal[1] = 1
    launch: Launch
    tier: Tier
    evaluated_at: AwareDatetime
    fetched_at: dict[EnsembleModel, AwareDatetime | None]
    refresh_deferred: bool
    grid_point: GridPoint
    t0_index: int
    rules: list[RuleRisk]
    union_risk_t0: dict[EnsembleModel, float | None]
    lowest_union_hour: LowestHour | None
    lowest_hour_verified: bool = False
    not_evaluable: list[OmittedRule]
    context: Context
    official: Official
    audit: list[AuditFooter] = Field(default_factory=list[AuditFooter])


class LedgerRow(BaseModel):
    """Append-only assessment record in ECMWF, GFS order with its page header."""

    model_config = ConfigDict(extra="forbid")

    launch_id: str
    run_at: AwareDatetime
    fetched_at: dict[EnsembleModel, AwareDatetime | None]
    net: AwareDatetime
    tier: Tier
    rule_set_version: str
    rules: dict[str, tuple[float | None, float | None]]
    union: tuple[float | None, float | None]
    lowest_hour: AwareDatetime | None
    lowest_hour_union: float | None
    window_end: AwareDatetime
    official_go_pct: int | None
    official_concerns: list[str]
    unmapped_concerns: list[str]
    launch: Launch | None = None
