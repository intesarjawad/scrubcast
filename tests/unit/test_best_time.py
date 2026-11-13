from datetime import UTC, datetime, timedelta

import pytest

from scrubcast.assess.best_time import LowestUnionHour, lowest_union_hour
from scrubcast.rules.engine import HourAssessment

BASE = datetime(2026, 11, 5, tzinfo=UTC)
HOURS = [BASE + timedelta(hours=hour) for hour in range(5)]


def assessment(members: int, violating: int) -> HourAssessment:
    return HourAssessment(members=members, rules={}, union_violating_members=violating)


@pytest.mark.parametrize(
    ("members", "difference", "kept"),
    [(50, 5, True), (50, 4, False), (51, 5, False), (51, 6, True), (40, 4, False), (40, 5, True)],
)
def test_exact_integer_materiality_boundaries(members: int, difference: int, *, kept: bool) -> None:
    result = lowest_union_hour(
        HOURS[:2],
        [assessment(members, 10), assessment(members, 10 - difference)],
        t0_index=0,
        window_start=HOURS[0],
        window_end=HOURS[1],
    )
    if kept:
        assert result == LowestUnionHour(HOURS[1], (10 - difference) / members, difference)
    else:
        assert result is None


def test_earliest_tied_minimum_inside_window() -> None:
    result = lowest_union_hour(
        list(reversed(HOURS)),
        [assessment(51, count) for count in [0, 2, 2, 10, 0]],
        t0_index=3,
        window_start=HOURS[1],
        window_end=HOURS[3],
    )
    assert result == LowestUnionHour(HOURS[2], 2 / 51, 8)


@pytest.mark.parametrize("duration", [timedelta(), timedelta(minutes=59)])
def test_instantaneous_windows_have_no_lowest_hour(duration: timedelta) -> None:
    assert (
        lowest_union_hour(
            HOURS[:2],
            [assessment(51, 30), assessment(51, 0)],
            t0_index=0,
            window_start=HOURS[0],
            window_end=HOURS[0] + duration,
        )
        is None
    )


@pytest.mark.parametrize("ecmwf", [None, [], [assessment(0, 0), assessment(0, 0)]])
def test_missing_ecmwf_or_members_has_no_lowest_hour(ecmwf: list[HourAssessment] | None) -> None:
    assert (
        lowest_union_hour(HOURS[:2], ecmwf, t0_index=0, window_start=HOURS[0], window_end=HOURS[1])
        is None
    )


def test_different_member_counts_rejected() -> None:
    with pytest.raises(ValueError, match="member count"):
        lowest_union_hour(
            HOURS[:2],
            [assessment(51, 10), assessment(40, 0)],
            t0_index=0,
            window_start=HOURS[0],
            window_end=HOURS[1],
        )


def test_misaligned_hours_rejected() -> None:
    with pytest.raises(ValueError, match="align"):
        lowest_union_hour(
            HOURS,
            [assessment(51, 10)],
            t0_index=0,
            window_start=HOURS[0],
            window_end=HOURS[1],
        )
