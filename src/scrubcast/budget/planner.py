"""Pure point selection and pacing under the ensemble cost limits."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import fsum, isfinite
from typing import TYPE_CHECKING

from scrubcast.budget.cost import request_cost
from scrubcast.models.rules import Tier

if TYPE_CHECKING:
    from collections.abc import Sequence

    from scrubcast.models.rules import ForecastPoint
    from scrubcast.models.weather import EnsembleModel

# A quarter of the daily allowance stays in reserve; the rest is split over four runs.
DAILY_COST_BUDGET = 7500
RUN_COST_BUDGET = 1875
MINUTE_COST_LIMIT = 600
_MINUTE_WINDOW = timedelta(seconds=60)
_FORECAST_DAYS = 10
_FORECAST_VARIABLES = 42
_ECMWF_MEMBERS = 51
_GFS_MEMBERS = 31


def _require_aware(value: datetime) -> None:
    if value.utcoffset() is None:
        message = "Budget timestamps must include a UTC offset"
        raise ValueError(message)


@dataclass(frozen=True)
class CostRecord:
    """A send timestamp and its measured X-RateLimit-Cost, in units."""

    sent_at: datetime
    cost_units: float

    def __post_init__(self) -> None:
        _require_aware(self.sent_at)
        if not isfinite(self.cost_units) or self.cost_units < 0:
            message = "Recorded cost must be finite and nonnegative"
            raise ValueError(message)


@dataclass(frozen=True)
class ForecastCandidate:
    """One deduplicated point with its nearest launch and previous file timestamp."""

    point: ForecastPoint
    tier: Tier
    next_launch: datetime
    fetched_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware(self.next_launch)
        if self.fetched_at is not None:
            _require_aware(self.fetched_at)


@dataclass(frozen=True)
class PlannedRequest:
    """A selected request; omitted candidates remain deferred for this run."""

    point: ForecastPoint
    models: tuple[EnsembleModel, ...]
    days: int
    cost_units: float
    send_at: datetime


def next_send_at(history: Sequence[CostRecord], cost: float, now: datetime) -> datetime:
    """Find the earliest send in a trailing (t - 60 seconds, t] cost window.

    Pass actual send times and measured costs after responses. A precomputed
    schedule must be paced again when actual timing or costs differ.
    """
    _require_aware(now)
    if not isfinite(cost) or not 0 <= cost <= MINUTE_COST_LIMIT:
        message = "Request cost must be finite and between 0 and 600 units"
        raise ValueError(message)
    if any(entry.sent_at > now for entry in history):
        message = "Send history must not contain future timestamps"
        raise ValueError(message)
    active = sorted(
        (entry for entry in history if entry.sent_at > now - _MINUTE_WINDOW),
        key=lambda entry: entry.sent_at,
    )
    send_at = now
    while fsum([cost, *(entry.cost_units for entry in active)]) > MINUTE_COST_LIMIT:
        send_at = active[0].sent_at + _MINUTE_WINDOW
        active = [entry for entry in active if entry.sent_at > send_at - _MINUTE_WINDOW]
    return send_at


def _priority(candidate: ForecastCandidate) -> tuple[Tier, datetime, datetime, str]:
    return (
        candidate.tier,
        candidate.fetched_at or datetime.min.replace(tzinfo=UTC),
        candidate.next_launch,
        candidate.point.point_id,
    )


def plan_requests(
    points: Sequence[ForecastCandidate], spent_today: float, now: datetime
) -> list[PlannedRequest]:
    """Schedule eligible points inside the ten-day horizon in tier order.

    Missing files sort before existing files, then oldest files and nearest
    launches win within a tier. Callers deduplicate points before planning and
    derive budget deferrals from the eligible point IDs absent from the result.
    """
    _require_aware(now)
    if not isfinite(spent_today) or spent_today < 0:
        message = "spent_today must be finite and nonnegative"
        raise ValueError(message)
    if len({candidate.point.point_id for candidate in points}) != len(points):
        message = "Forecast candidates must have unique point_id values"
        raise ValueError(message)
    horizon = now + timedelta(days=_FORECAST_DAYS)
    eligible = sorted(
        (candidate for candidate in points if now <= candidate.next_launch <= horizon),
        key=_priority,
    )
    plan: list[PlannedRequest] = []
    history: list[CostRecord] = []
    send_at = now
    for candidate in eligible:
        models: tuple[EnsembleModel, ...] = (
            ("ecmwf",) if candidate.tier == Tier.C else ("ecmwf", "gfs")
        )
        members = _ECMWF_MEMBERS + (_GFS_MEMBERS if candidate.tier != Tier.C else 0)
        cost = request_cost(_FORECAST_VARIABLES, members, _FORECAST_DAYS)
        costs = [entry.cost_units for entry in history]
        if (
            fsum([*costs, cost]) > RUN_COST_BUDGET
            or fsum([spent_today, *costs, cost]) > DAILY_COST_BUDGET
        ):
            # Cheaper lower tiers cannot bypass a higher tier that no longer fits.
            break
        send_at = next_send_at(history, cost, send_at)
        plan.append(PlannedRequest(candidate.point, models, _FORECAST_DAYS, cost, send_at))
        history.append(CostRecord(send_at, cost))
    return plan
