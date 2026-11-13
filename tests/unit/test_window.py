from datetime import UTC, datetime, timedelta

import pytest

from scrubcast.assess.window import select_window

BASE = datetime(2026, 11, 5, tzinfo=UTC)
HOURS = [BASE + timedelta(hours=hour) for hour in range(8)]


@pytest.mark.parametrize(
    ("net_minutes", "start_minutes", "end_minutes", "expected", "t0_index"),
    [
        (120, 120, 120, [1, 2, 3], 1),
        (160, 160, 160, [2, 3], 1),
        (120, 0, 240, [0, 1, 2, 3, 4], 2),
        (120, 30, 270, [0, 1, 2, 3, 4, 5], 2),
        (150, 120, 150, [2, 3], 0),
        (120, 120, 180, [2, 3], 0),
    ],
)
def test_window_hours(
    net_minutes: int,
    start_minutes: int,
    end_minutes: int,
    expected: list[int],
    t0_index: int,
) -> None:
    window = select_window(
        list(reversed(HOURS)),
        net=BASE + timedelta(minutes=net_minutes),
        window_start=BASE + timedelta(minutes=start_minutes),
        window_end=BASE + timedelta(minutes=end_minutes),
    )
    assert window.hours == tuple(HOURS[hour] for hour in expected)
    assert window.t0_index == t0_index
    assert not window.beyond_forecast_range


@pytest.mark.parametrize("available", [HOURS[:3], HOURS[2:], [], [HOURS[1], HOURS[3]]])
def test_missing_required_hours_hide_board(available: list[datetime]) -> None:
    window = select_window(available, net=HOURS[2], window_start=HOURS[2], window_end=HOURS[2])
    assert window.beyond_forecast_range
    if not available:
        assert window.hours == ()
        assert window.t0_index is None


def test_reversed_window_rejected() -> None:
    with pytest.raises(ValueError, match="window_end"):
        select_window(HOURS, net=HOURS[2], window_start=HOURS[3], window_end=HOURS[2])
