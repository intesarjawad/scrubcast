"""Versioned public indexes and rule-chip metadata."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from scrubcast.audit.forecast_audit import ForecastAudit  # noqa: TC001
from scrubcast.models.assessment import AuditFooter
from scrubcast.models.launch import Launch
from scrubcast.models.rules import Confidence, Tier
from scrubcast.models.weather import EnsembleModel

__all__ = [
    "Confidence",
    "EnsembleModel",
    "Hindcast",
    "Latest",
    "LaunchSummary",
    "Past",
    "PastLaunch",
    "Tier",
    "WorstRule",
]


class WorstRule(BaseModel):
    """Display label and its evidence, absent for unavailable or clear forecasts."""

    label: str
    rule_id: str | None = None
    risk_fraction: float | None = None
    model: EnsembleModel | None = None
    confidence: Confidence | None = None


class LaunchSummary(Launch):
    """Schedule row with coverage and the available launch-page evidence."""

    tier: Tier
    assessment: bool
    worst_rule: WorstRule
    page_url: str


class PastLaunch(LaunchSummary):
    """Retained launch row carrying the audit footers kept for ninety days."""

    audit: list[AuditFooter] = Field(default_factory=list[AuditFooter])


class Latest(BaseModel):
    """Upcoming launches in the ten-day forecast horizon."""

    schema_version: Literal[1] = 1
    generated_at: AwareDatetime
    schedule_stale: bool
    members_total: int
    launches: list[LaunchSummary]


class Past(BaseModel):
    """Retained launch pages for the preceding ninety days."""

    schema_version: Literal[1] = 1
    generated_at: AwareDatetime
    launches: list[PastLaunch]


class Hindcast(BaseModel):
    """Published forward-audit summaries and the lowest-hour verification state."""

    schema_version: Literal[1] = 1
    generated_at: AwareDatetime
    lowest_hour_verified: bool = False
    summary: list[str] = Field(default_factory=list)
    forecast_audit: ForecastAudit | None = None
