from datetime import UTC, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import AwareDatetime, BaseModel, JsonValue, TypeAdapter

from scrubcast.audit.outcomes import (
    AttemptOutcome,
    Outcome,
    audit_attempts,
    classify_attempt,
    select_attempts,
)
from scrubcast.models.assessment import AuditNote, LedgerRow
from scrubcast.models.launch import LaunchDetailed, LaunchStatus, LaunchUpdate

FIXTURES = Path(__file__).parents[1] / "fixtures"


class ExpectedOutcome(BaseModel):
    outcome: Outcome
    net_now: AwareDatetime | None
    note: AuditNote | None


class Scenario(BaseModel):
    ledger: list[LedgerRow]
    launches: list[LaunchDetailed]
    now: AwareDatetime
    expected: list[ExpectedOutcome]


def _scenario(name: str) -> Scenario:
    return Scenario.model_validate_json((FIXTURES / f"outcomes/{name}.json").read_text())


@pytest.fixture
def scenario() -> Scenario:
    return _scenario("launched_later")


@pytest.mark.parametrize(
    "name", ["launched", "launched_later", "new_t0", "hold", "unknown", "two_attempts"]
)
def test_outcome_fixtures(name: str) -> None:
    case = _scenario(name)

    results = audit_attempts(case.ledger, case.launches, case.now)

    assert [result.model_dump(include={"outcome", "net_now", "note"}) for result in results] == [
        expected.model_dump() for expected in case.expected
    ]
    assert len({result.attempt_id for result in results}) == len(case.expected)
    for result, row in zip(results, case.ledger, strict=True):
        assert result.attempt_net == row.net
        assert result.attempt_id == f"{row.launch_id}@{row.net.isoformat().replace('+00:00', 'Z')}"
        assert result.status_now == case.launches[0].status
        assert result.audited_at == case.now
        assert set(result.model_dump()) == {
            "attempt_id",
            "attempt_net",
            "outcome",
            "net_now",
            "status_now",
            "note",
            "audited_at",
        }
        assert AttemptOutcome.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("hours", [21, 24, 27])
def test_attempt_lead_interval_is_inclusive(scenario: Scenario, hours: int) -> None:
    row = scenario.ledger[0]
    row = row.model_copy(update={"run_at": row.net - timedelta(hours=hours)})

    assert select_attempts([row])[0].forecast == row


@pytest.mark.parametrize(
    "lead", [timedelta(hours=21, microseconds=-1), timedelta(hours=27, microseconds=1)]
)
def test_no_attempt_without_a_24_hour_row(scenario: Scenario, lead: timedelta) -> None:
    row = scenario.ledger[0]
    row = row.model_copy(update={"run_at": row.net - lead})

    assert select_attempts([row]) == []
    assert audit_attempts([row], scenario.launches, scenario.now) == []


def test_24_hour_selection_uses_nearest_row_then_earlier_run(scenario: Scenario) -> None:
    row = scenario.ledger[0]
    earlier = row.model_copy(update={"run_at": row.net - timedelta(hours=25)})
    later = row.model_copy(
        update={
            "run_at": row.net - timedelta(hours=23),
            "window_end": row.net + timedelta(hours=10),
        }
    )
    farther = row.model_copy(update={"run_at": row.net - timedelta(hours=26)})

    for rows in ([later, farther, earlier], [earlier, farther, later]):
        attempt = select_attempts(rows)[0]
        assert attempt.forecast == earlier
        assert attempt.window_start == row.net - timedelta(hours=1)
        assert attempt.window_end == earlier.window_end + timedelta(hours=1)
        assert select_attempts([*rows, row])[0].forecast == row


def test_attempt_keys_group_equal_instants_and_separate_launches(scenario: Scenario) -> None:
    row = scenario.ledger[0]
    offset = row.model_copy(update={"net": row.net.astimezone(timezone(timedelta(hours=2)))})
    other = row.model_copy(update={"launch_id": "other-launch"})

    attempts = select_attempts([row, offset, other])

    assert len(attempts) == 2
    assert len({attempt.attempt_id for attempt in attempts}) == 2
    assert all(attempt.attempt_id.endswith("Z") for attempt in attempts)
    assert select_attempts([other, offset, row]) == attempts


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (LaunchStatus.SUCCESS, ["unknown", "launched", "launched", "launched_later"]),
        (LaunchStatus.FAILURE, ["unknown", "launched", "launched", "launched_later"]),
        (LaunchStatus.PARTIAL_FAILURE, ["unknown", "launched", "launched", "launched_later"]),
        (LaunchStatus.IN_FLIGHT, ["unknown", "launched", "launched", "launched_later"]),
        (LaunchStatus.PAYLOAD_DEPLOYED, ["unknown", "launched", "launched", "launched_later"]),
        (LaunchStatus.GO, ["unknown", "unknown", "unknown", "new_t0_pending"]),
        (LaunchStatus.TBC, ["unknown", "unknown", "unknown", "new_t0_pending"]),
        (LaunchStatus.TBD, ["unknown", "unknown", "unknown", "new_t0_pending"]),
        (LaunchStatus.HOLD, ["hold", "hold", "hold", "hold"]),
    ],
)
def test_status_and_net_table(
    scenario: Scenario, status: LaunchStatus, expected: list[str]
) -> None:
    attempt = select_attempts(scenario.ledger)[0]
    times = [
        attempt.window_start - timedelta(microseconds=1),
        attempt.window_start,
        attempt.window_end,
        attempt.window_end + timedelta(minutes=1),
    ]

    for net, outcome in zip(times, expected, strict=True):
        current = scenario.launches[0].model_copy(update={"status": status, "net": net})
        result = classify_attempt(attempt, current, scenario.now)
        assert result.outcome == outcome
        assert result.net_now == net


@pytest.mark.parametrize("end_offset", [timedelta(hours=-2), timedelta(0)])
def test_window_end_cannot_precede_attempt_net(scenario: Scenario, end_offset: timedelta) -> None:
    row = scenario.ledger[0]
    row = row.model_copy(update={"window_end": row.net + end_offset})

    assert select_attempts([row])[0].window_end == row.net + timedelta(hours=1)


def test_missing_launch_is_unknown(scenario: Scenario) -> None:
    unrelated = scenario.launches[0].model_copy(update={"id": "unrelated"})

    result = audit_attempts(scenario.ledger, [unrelated], scenario.now)[0]

    assert result.outcome == "unknown"
    assert result.net_now is None
    assert result.status_now is None
    assert result.note is None


@pytest.mark.parametrize(
    ("offset", "shown"),
    [
        (timedelta(hours=-7), False),
        (timedelta(hours=-6, microseconds=-1), False),
        (timedelta(hours=-6), True),
        (timedelta(hours=1), True),
        (timedelta(hours=9), True),
        (timedelta(hours=9, microseconds=1), False),
    ],
)
def test_note_window_boundaries(scenario: Scenario, offset: timedelta, *, shown: bool) -> None:
    attempt = select_attempts(scenario.ledger)[0]
    update = LaunchUpdate(created_on=attempt.attempt_net + offset, comment="Delay note.")
    current = scenario.launches[0].model_copy(update={"updates": [update]})

    note = classify_attempt(attempt, current, scenario.now).note

    assert note == (AuditNote(created_on=update.created_on, text=update.comment) if shown else None)


def test_latest_eligible_note_is_verbatim_and_limited_to_80_characters(scenario: Scenario) -> None:
    attempt = select_attempts(scenario.ledger)[0]
    latest = LaunchUpdate(
        created_on=attempt.attempt_net + timedelta(hours=1), comment="  天候: " + "x" * 100
    )
    old = LaunchUpdate(created_on=attempt.attempt_net, comment="Older note.")
    outside = LaunchUpdate(
        created_on=attempt.window_end + timedelta(hours=6, seconds=1), comment="Unrelated note."
    )
    current = scenario.launches[0].model_copy(update={"updates": [outside, latest, old]})

    result = classify_attempt(attempt, current, scenario.now)

    assert result.note == AuditNote(created_on=latest.created_on, text=latest.comment[:80])
    assert result.note is not None
    assert len(result.note.text) == 80


@pytest.mark.parametrize("text", ["Weather scrub.", "Technical scrub.", "Liftoff."])
def test_notes_never_classify_causes(scenario: Scenario, text: str) -> None:
    current = scenario.launches[0].model_copy(
        update={"updates": [LaunchUpdate(created_on=scenario.ledger[0].net, comment=text)]}
    )

    result = audit_attempts(scenario.ledger, [current], scenario.now)[0]

    assert result.outcome == "launched_later"
    assert result.note is not None
    assert result.note.text == text


@pytest.mark.parametrize("name", ["launched", "launched_later", "new_t0", "hold", "unknown"])
def test_absent_updates_mean_no_note(name: str) -> None:
    case = _scenario(name)
    current = case.launches[0].model_copy(update={"updates": []})

    result = audit_attempts(case.ledger, [current], case.now)[0]

    assert result.note is None
    assert result.outcome == case.expected[0].outcome


@pytest.mark.parametrize("prefix", ["ll2", "ll2_2.4.0"], ids=["2.3.0", "2.4.0"])
@pytest.mark.parametrize("name", ["weather_delay", "technical_delay"])
def test_recorded_delay_notes_match_both_api_versions(prefix: str, name: str) -> None:
    # Attempt times are synthetic; these source snapshots contain no ledger history.
    case = _scenario(name)
    response = TypeAdapter(dict[str, JsonValue]).validate_json(
        (FIXTURES / f"{prefix}_previous_detailed.json").read_text()
    )
    launches = TypeAdapter(list[LaunchDetailed]).validate_python(response["results"])

    result = audit_attempts(case.ledger, launches, case.now)[0]

    assert (
        result.model_dump(include={"outcome", "net_now", "note"}) == case.expected[0].model_dump()
    )


def test_unused_reason_fields_have_no_effect(scenario: Scenario) -> None:
    source = scenario.launches[0].model_dump(mode="json")
    source.update(holdreason="Weather", failreason="Technical")
    current = LaunchDetailed.model_validate(source)

    assert audit_attempts(scenario.ledger, [current], scenario.now) == audit_attempts(
        scenario.ledger, scenario.launches, scenario.now
    )


def test_audit_starts_at_window_end_plus_six_hours(scenario: Scenario) -> None:
    attempt = select_attempts(scenario.ledger)[0]
    due = attempt.window_end + timedelta(hours=6)

    assert audit_attempts(scenario.ledger, scenario.launches, due - timedelta(microseconds=1)) == []
    result = audit_attempts(scenario.ledger, scenario.launches, due)
    assert len(result) == 1
    assert result[0].audited_at == due


def test_reaudit_replaces_one_row_until_seven_days_after_first_due(scenario: Scenario) -> None:
    attempt = select_attempts(scenario.ledger)[0]
    due = attempt.window_end + timedelta(hours=6)
    original = audit_attempts(scenario.ledger, [], due)
    freeze = due + timedelta(days=7)

    updated = audit_attempts(
        scenario.ledger, scenario.launches, freeze - timedelta(microseconds=1), previous=original
    )

    assert len(updated) == 1
    assert updated[0].attempt_id == original[0].attempt_id
    assert updated[0].outcome == "launched_later"
    assert audit_attempts(scenario.ledger, [], freeze, previous=updated) == updated
    assert (
        audit_attempts(scenario.ledger, [], freeze + timedelta(days=1), previous=updated) == updated
    )
    assert audit_attempts([], [], freeze, previous=updated) == updated


def test_expired_unaudited_attempt_is_not_reconstructed(scenario: Scenario) -> None:
    attempt = select_attempts(scenario.ledger)[0]
    freeze = attempt.window_end + timedelta(hours=6, days=7)

    assert audit_attempts(scenario.ledger, scenario.launches, freeze) == []


def test_classifier_rejects_a_different_launch(scenario: Scenario) -> None:
    attempt = select_attempts(scenario.ledger)[0]
    current = scenario.launches[0].model_copy(update={"id": "other"})

    with pytest.raises(ValueError, match="launch"):
        classify_attempt(attempt, current, scenario.now)


def test_audit_requires_an_aware_clock(scenario: Scenario) -> None:
    with pytest.raises(ValueError, match="offset"):
        audit_attempts(scenario.ledger, scenario.launches, scenario.now.replace(tzinfo=None))


def test_attempt_ids_are_in_utc(scenario: Scenario) -> None:
    attempt = select_attempts(scenario.ledger)[0]

    assert attempt.attempt_net.tzinfo == UTC
