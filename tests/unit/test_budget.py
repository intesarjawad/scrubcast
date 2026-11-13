from datetime import UTC, datetime, timedelta
from email.parser import Parser
from math import fsum
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scrubcast.budget.cost import request_cost
from scrubcast.budget.planner import (
    DAILY_COST_BUDGET,
    MINUTE_COST_LIMIT,
    RUN_COST_BUDGET,
    CostRecord,
    ForecastCandidate,
    next_send_at,
    plan_requests,
)
from scrubcast.models.rules import ForecastPoint, Tier

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)
HEADERS = Path(__file__).parents[1] / "fixtures/headers"


def _candidate(
    point_id: str,
    tier: Tier = Tier.A,
    *,
    fetched_at: datetime | None = None,
    next_launch: datetime = NOW + timedelta(days=1),
) -> ForecastCandidate:
    return ForecastCandidate(
        point=ForecastPoint(point_id=point_id, latitude=28.5618, longitude=-80.577),
        tier=tier,
        next_launch=next_launch,
        fetched_at=fetched_at,
    )


@pytest.mark.parametrize(
    ("n_vars", "members", "days", "expected"),
    [(3, 133, 1, 39.9), (47, 82, 10, 385.4), (1, 51, 94, 34.24), (42, 82, 10, 344.4)],
)
def test_request_cost(n_vars: int, members: int, days: int, expected: float) -> None:
    assert request_cost(n_vars, members, days) == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize(
    ("filename", "n_vars", "members", "days"),
    [
        ("cost-three-models.txt", 3, 133, 1),
        ("cost-47-variables.txt", 47, 82, 10),
        ("cost-history.txt", 1, 51, 94),
        ("cost-production.txt", 42, 82, 10),
    ],
)
def test_measured_cost(filename: str, n_vars: int, members: int, days: int) -> None:
    headers = Parser().parsestr((HEADERS / filename).read_text())
    assert request_cost(n_vars, members, days) == pytest.approx(
        float(headers["X-RateLimit-Cost"]), abs=0.01
    )


@pytest.mark.parametrize(("n_vars", "members", "days"), [(0, 51, 1), (1, -1, 1), (1, 51, 0)])
def test_request_cost_rejects_nonpositive_inputs(n_vars: int, members: int, days: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        request_cost(n_vars, members, days)


@given(
    n_vars=st.integers(1, 100),
    members=st.integers(1, 200),
    days=st.integers(1, 94),
)
def test_cost_scaling(n_vars: int, members: int, days: int) -> None:
    base = request_cost(n_vars, members, 1)
    assert request_cost(n_vars, members, days) == pytest.approx(base * max(1, days / 14))
    assert request_cost(n_vars * 2, members, days) == 2 * request_cost(n_vars, members, days)


def test_plan_models_costs_and_pacing() -> None:
    points = [_candidate("c", Tier.C), _candidate("b", Tier.B), _candidate("a")]
    plan = plan_requests(points, spent_today=0, now=NOW)
    assert [item.point.point_id for item in plan] == ["a", "b", "c"]
    assert [item.models for item in plan] == [("ecmwf", "gfs"), ("ecmwf", "gfs"), ("ecmwf",)]
    assert [item.cost_units for item in plan] == [344.4, 344.4, 214.2]
    assert [item.days for item in plan] == [10, 10, 10]
    assert [item.send_at for item in plan] == [
        NOW,
        NOW + timedelta(seconds=60),
        NOW + timedelta(seconds=60),
    ]
    assert [item.point.point_id for item in points] == ["c", "b", "a"]


def test_tier_c_oldest_first_then_nearest_launch() -> None:
    points = [
        _candidate("recent", Tier.C, fetched_at=NOW - timedelta(hours=1)),
        _candidate("old-far", Tier.C, fetched_at=NOW - timedelta(days=1)),
        _candidate("old-near", Tier.C, fetched_at=NOW - timedelta(days=1), next_launch=NOW),
        _candidate("missing", Tier.C),
    ]
    plan = plan_requests(points, spent_today=0, now=NOW)
    assert [item.point.point_id for item in plan] == ["missing", "old-near", "old-far", "recent"]


def test_plan_forecast_horizon() -> None:
    points = [
        _candidate("past", next_launch=NOW - timedelta(microseconds=1)),
        _candidate("now", next_launch=NOW),
        _candidate("last", next_launch=NOW + timedelta(days=10)),
        _candidate("later", next_launch=NOW + timedelta(days=10, microseconds=1)),
    ]
    assert [item.point.point_id for item in plan_requests(points, 0, NOW)] == ["now", "last"]


@pytest.mark.parametrize("spent_today", [7500, 8000])
def test_exhausted_daily_budget(spent_today: float) -> None:
    assert plan_requests([_candidate("a")], spent_today, NOW) == []


def test_exact_daily_remainder_can_be_spent() -> None:
    plan = plan_requests([_candidate("a")], DAILY_COST_BUDGET - 344.4, NOW)
    assert len(plan) == 1


def test_lower_tier_cannot_bypass_deferred_tier_a() -> None:
    assert (
        plan_requests([_candidate("c", Tier.C), _candidate("a")], DAILY_COST_BUDGET - 300, NOW)
        == []
    )


def test_run_budget_does_not_depend_on_input_order() -> None:
    points = [_candidate(f"c-{index}", Tier.C) for index in range(10)] + [
        _candidate(f"a-{index}") for index in range(6)
    ]
    plan = plan_requests(points, 0, NOW)
    assert len(plan) == 5
    assert all(item.point.point_id.startswith("a-") for item in plan)
    assert plan == plan_requests(list(reversed(points)), 0, NOW)


def test_pacing_uses_actual_cost_not_prediction() -> None:
    history = [CostRecord(sent_at=NOW, cost_units=400)]
    assert next_send_at(history, 214.2, NOW) == NOW + timedelta(seconds=60)


def test_pacing_expires_all_events_at_boundary() -> None:
    history = [CostRecord(NOW, 300), CostRecord(NOW, 300)]
    assert next_send_at(history, 0.1, NOW + timedelta(seconds=59, microseconds=999999)) == (
        NOW + timedelta(seconds=60)
    )
    assert next_send_at(history, 600, NOW + timedelta(seconds=60)) == (NOW + timedelta(seconds=60))


def test_pacing_waits_for_sufficient_expiry_with_unsorted_history() -> None:
    history = [CostRecord(NOW - timedelta(seconds=10), 300), CostRecord(NOW, 100)]
    assert next_send_at(list(reversed(history)), 500, NOW) == NOW + timedelta(seconds=50)
    assert next_send_at(history, 501, NOW) == NOW + timedelta(seconds=60)
    assert next_send_at(history, 200, NOW) == NOW
    assert next_send_at([], 600, NOW) == NOW


@pytest.mark.parametrize("cost", [-1, float("nan"), float("inf"), 600.01])
def test_pacing_rejects_invalid_cost(cost: float) -> None:
    with pytest.raises(ValueError, match="cost"):
        next_send_at([], cost, NOW)


@pytest.mark.parametrize("spent_today", [-1, float("nan"), float("inf")])
def test_plan_rejects_invalid_spend(spent_today: float) -> None:
    with pytest.raises(ValueError, match="spent_today"):
        plan_requests([], spent_today, NOW)


def test_pacing_rejects_future_history() -> None:
    with pytest.raises(ValueError, match="future"):
        next_send_at([CostRecord(NOW + timedelta(seconds=1), 1)], 1, NOW)


@pytest.mark.parametrize("cost", [-1, float("nan"), float("inf")])
def test_history_rejects_invalid_cost(cost: float) -> None:
    with pytest.raises(ValueError, match="cost"):
        CostRecord(NOW, cost)


def test_budget_requires_aware_times() -> None:
    naive = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="offset"):
        next_send_at([], 1, naive)
    with pytest.raises(ValueError, match="offset"):
        CostRecord(naive, 1)
    with pytest.raises(ValueError, match="offset"):
        _candidate("naive", next_launch=naive)
    with pytest.raises(ValueError, match="offset"):
        _candidate("naive", fetched_at=naive)
    with pytest.raises(ValueError, match="offset"):
        plan_requests([], 0, naive)


def test_plan_rejects_duplicate_point_ids() -> None:
    with pytest.raises(ValueError, match="point_id"):
        plan_requests([_candidate("cape"), _candidate("cape")], 0, NOW)


@given(
    tiers=st.lists(st.sampled_from(list(Tier)), max_size=60),
    spent_today=st.floats(min_value=0, max_value=10000, allow_nan=False, allow_infinity=False),
)
def test_plan_respects_budgets_pacing_and_tier_priority(
    tiers: list[Tier], spent_today: float
) -> None:
    points = [_candidate(str(index), tier) for index, tier in enumerate(tiers)]
    plan = plan_requests(points, spent_today, NOW)
    costs = [item.cost_units for item in plan]
    assert fsum(costs) <= RUN_COST_BUDGET
    if spent_today <= DAILY_COST_BUDGET:
        assert fsum([spent_today, *costs]) <= DAILY_COST_BUDGET
    else:
        assert not plan
    selected = {item.point.point_id for item in plan}
    if any(point.tier == Tier.C and point.point.point_id in selected for point in points):
        assert all(point.point.point_id in selected for point in points if point.tier == Tier.A)
    for item in plan:
        assert item.send_at >= NOW
        assert (
            fsum(
                other.cost_units
                for other in plan
                if item.send_at - timedelta(seconds=60) < other.send_at <= item.send_at
            )
            <= MINUTE_COST_LIMIT
        )


@given(costs=st.lists(st.integers(min_value=1, max_value=60000), max_size=60))
def test_pacing_arbitrary_costs(costs: list[int]) -> None:
    history: list[CostRecord] = []
    previous = NOW
    for hundredths in costs:
        cost = hundredths / 100
        send_at = next_send_at(history, cost, previous)
        assert send_at >= previous
        recent = [entry for entry in history if entry.sent_at > send_at - timedelta(seconds=60)]
        assert fsum([cost, *(entry.cost_units for entry in recent)]) <= MINUTE_COST_LIMIT
        if send_at > previous:
            earlier = send_at - timedelta(microseconds=1)
            assert (
                fsum(
                    [
                        cost,
                        *(
                            entry.cost_units
                            for entry in history
                            if entry.sent_at > earlier - timedelta(seconds=60)
                        ),
                    ]
                )
                > MINUTE_COST_LIMIT
            )
        history.append(CostRecord(send_at, cost))
        previous = send_at
