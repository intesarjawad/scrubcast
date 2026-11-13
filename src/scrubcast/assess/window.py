"""Select forecast hours around a launch window without hiding missing coverage."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

ENSEMBLE_STEP = timedelta(hours=1)
WINDOW_PADDING = timedelta(minutes=30)


@dataclass(frozen=True)
class AssessmentWindow:
    """Chronological forecast hours and whether the complete window is available."""

    hours: tuple[datetime, ...]
    t0_index: int | None
    beyond_forecast_range: bool


def select_window(
    hours: Sequence[datetime],
    *,
    net: datetime,
    window_start: datetime,
    window_end: datetime,
) -> AssessmentWindow:
    """Select padded hourly samples; short windows use net plus or minus one hour.

    A missing required hour, including an internal gap, marks the board unavailable.
    Equidistant samples resolve to the earlier hour for a reproducible T-0 index.
    """
    duration = window_end - window_start
    if duration < timedelta():
        msg = "window_end must be at or after window_start"
        raise ValueError(msg)
    start, end = (
        (net - ENSEMBLE_STEP, net + ENSEMBLE_STEP)
        if duration < ENSEMBLE_STEP
        else (window_start - WINDOW_PADDING, window_end + WINDOW_PADDING)
    )
    first = start.replace(minute=0, second=0, microsecond=0)
    if first < start:
        first += ENSEMBLE_STEP
    required = tuple(
        first + offset * ENSEMBLE_STEP for offset in range((end - first) // ENSEMBLE_STEP + 1)
    )
    available = set(hours)
    selected = tuple(hour for hour in required if hour in available)
    t0_index = (
        min(range(len(selected)), key=lambda index: (abs(selected[index] - net), selected[index]))
        if selected
        else None
    )
    return AssessmentWindow(selected, t0_index, len(selected) != len(required))
