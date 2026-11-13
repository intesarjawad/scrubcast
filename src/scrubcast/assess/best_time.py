"""Choose a materially lower ECMWF member union within a launch window."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from scrubcast.rules.engine import HourAssessment

# Hourly interpolation makes smaller shifts too noisy to present as a useful choice.
LOWEST_HOUR_MIN_DROP_PCT = 10
LOWEST_HOUR_MIN_MEMBERS = 5
PERCENT_SCALE = 100


@dataclass(frozen=True)
class LowestUnionHour:
    """Material modelled improvement over T-0, without an observed-outcome claim."""

    hour: datetime
    union_risk: float
    members_below_t0: int


def lowest_union_hour(
    hours: Sequence[datetime],
    ecmwf_assessments: Sequence[HourAssessment] | None,
    *,
    t0_index: int,
    window_start: datetime,
    window_end: datetime,
) -> LowestUnionHour | None:
    """Return the earliest minimum only when both integer materiality gates pass.

    Assessments must be aligned to hours and share one ensemble member count.
    Only unpadded window hours are candidates; T-0 may be a padded sample.
    """
    if window_end - window_start < timedelta(hours=1) or not ecmwf_assessments:
        return None
    if len(hours) != len(ecmwf_assessments):
        msg = "ECMWF assessments must align with forecast hours"
        raise ValueError(msg)
    t0 = ecmwf_assessments[t0_index]
    if any(hour.members != t0.members for hour in ecmwf_assessments):
        msg = "ECMWF assessments must share one member count"
        raise ValueError(msg)
    if t0.members == 0:
        return None
    candidates = [
        (hour, assessment)
        for hour, assessment in zip(hours, ecmwf_assessments, strict=True)
        if window_start <= hour <= window_end
    ]
    if not candidates:
        return None
    hour, assessment = min(candidates, key=lambda item: (item[1].union_violating_members, item[0]))
    difference = t0.union_violating_members - assessment.union_violating_members
    if (
        difference < LOWEST_HOUR_MIN_MEMBERS
        or difference * PERCENT_SCALE < LOWEST_HOUR_MIN_DROP_PCT * t0.members
    ):
        return None
    return LowestUnionHour(hour, assessment.union_violating_members / t0.members, difference)
