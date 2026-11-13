"""Attempt outcomes from ledgered launch windows and structured schedule fields."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from scrubcast.models.assessment import AuditNote, LedgerRow
from scrubcast.models.launch import LaunchDetailed, LaunchStatus

if TYPE_CHECKING:
    from collections.abc import Iterable

type Outcome = Literal["launched", "launched_later", "new_t0_pending", "hold", "unknown"]

ATTEMPT_LEAD = timedelta(hours=24)
ATTEMPT_LEAD_TOLERANCE = timedelta(hours=3)
WINDOW_MARGIN = timedelta(hours=1)
AUDIT_DELAY = timedelta(hours=6)
REAUDIT_PERIOD = timedelta(days=7)
# A launch flown early in its attempt window carries a NET before the attempt's T-0.
SOURCE_LOOKBACK = timedelta(days=1)
NOTE_LOOKBACK = timedelta(hours=6)
NOTE_LOOKAHEAD = timedelta(hours=6)
NOTE_MAX_CHARACTERS = 80
LAUNCHED_STATUSES = frozenset(
    {
        LaunchStatus.SUCCESS,
        LaunchStatus.FAILURE,
        LaunchStatus.PARTIAL_FAILURE,
        LaunchStatus.IN_FLIGHT,
        LaunchStatus.PAYLOAD_DEPLOYED,
    }
)
PENDING_STATUSES = frozenset({LaunchStatus.GO, LaunchStatus.TBC, LaunchStatus.TBD})


@dataclass(frozen=True)
class Attempt:
    """A distinct scheduled T-0 with its selected 24-hour forecast evidence."""

    forecast: LedgerRow

    @property
    def attempt_net(self) -> datetime:
        """Use UTC so equivalent source offsets share one persisted identity."""
        return self.forecast.net.astimezone(UTC)

    @property
    def attempt_id(self) -> str:
        """Stable launch and scheduled T-0 key for repeated audits."""
        return f"{self.forecast.launch_id}@{self.attempt_net.isoformat().replace('+00:00', 'Z')}"

    @property
    def window_start(self) -> datetime:
        """Include the hour preceding the ledgered T-0."""
        return self.attempt_net - WINDOW_MARGIN

    @property
    def window_end(self) -> datetime:
        """Include the hour following the later of T-0 and the ledgered window end."""
        return max(self.attempt_net, self.forecast.window_end) + WINDOW_MARGIN


class AttemptOutcome(BaseModel):
    """One replaceable outcome record per attempt, frozen after its audit period."""

    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    attempt_net: AwareDatetime
    outcome: Outcome
    net_now: AwareDatetime | None
    status_now: LaunchStatus | None
    note: AuditNote | None
    audited_at: AwareDatetime


def select_attempts(ledger: Iterable[LedgerRow]) -> list[Attempt]:
    """Select the nearest 24-hour row per launch and T-0, preferring earlier runs."""
    selected: dict[tuple[str, datetime], LedgerRow] = {}
    for row in ledger:
        distance = abs(row.net - row.run_at - ATTEMPT_LEAD)
        if distance > ATTEMPT_LEAD_TOLERANCE:
            continue
        key = (row.launch_id, row.net)
        previous = selected.get(key)
        if previous is None or (distance, row.run_at) < (
            abs(previous.net - previous.run_at - ATTEMPT_LEAD),
            previous.run_at,
        ):
            selected[key] = row
    return [Attempt(row) for _, row in sorted(selected.items())]


def open_attempts(ledger: Iterable[LedgerRow], now: datetime) -> list[Attempt]:
    """Select attempts past their audit delay whose outcome is still replaceable."""
    return [
        attempt
        for attempt in select_attempts(ledger)
        if timedelta(0) <= now - (attempt.window_end + AUDIT_DELAY) < REAUDIT_PERIOD
    ]


def _outcome(attempt: Attempt, launch: LaunchDetailed | None) -> Outcome:
    if launch is None:
        return "unknown"
    if launch.status in LAUNCHED_STATUSES:
        if attempt.window_start <= launch.net <= attempt.window_end:
            return "launched"
        if launch.net > attempt.window_end:
            return "launched_later"
    if launch.status in PENDING_STATUSES and launch.net > attempt.window_end:
        return "new_t0_pending"
    if launch.status is LaunchStatus.HOLD:
        return "hold"
    return "unknown"


def _note(attempt: Attempt, launch: LaunchDetailed) -> AuditNote | None:
    start = attempt.attempt_net - NOTE_LOOKBACK
    end = attempt.window_end + NOTE_LOOKAHEAD
    update = max(
        (update for update in launch.updates if start <= update.created_on <= end),
        key=lambda update: update.created_on,
        default=None,
    )
    if update is None:
        return None
    return AuditNote(created_on=update.created_on, text=update.comment[:NOTE_MAX_CHARACTERS])


def classify_attempt(
    attempt: Attempt, launch: LaunchDetailed | None, now: datetime
) -> AttemptOutcome:
    """Classify a source snapshot; audit scheduling is applied by audit_attempts."""
    if now.utcoffset() is None:
        message = "now must include a UTC offset"
        raise ValueError(message)
    if launch is not None and launch.id != attempt.forecast.launch_id:
        message = "Current launch does not match the attempt's launch"
        raise ValueError(message)
    outcome = _outcome(attempt, launch)
    note = (
        _note(attempt, launch)
        if launch is not None and outcome in {"launched_later", "new_t0_pending", "hold"}
        else None
    )
    return AttemptOutcome(
        attempt_id=attempt.attempt_id,
        attempt_net=attempt.attempt_net,
        outcome=outcome,
        net_now=launch.net if launch is not None else None,
        status_now=launch.status if launch is not None else None,
        note=note,
        audited_at=now,
    )


def audit_attempts(
    ledger: Iterable[LedgerRow],
    launches: Iterable[LaunchDetailed],
    now: datetime,
    *,
    previous: Iterable[AttemptOutcome] = (),
) -> list[AttemptOutcome]:
    """Replace outcomes during their audit interval and retain frozen records."""
    if now.utcoffset() is None:
        message = "now must include a UTC offset"
        raise ValueError(message)
    current = {launch.id: launch for launch in launches}
    results = {result.attempt_id: result for result in previous}
    for attempt in open_attempts(ledger, now):
        results[attempt.attempt_id] = classify_attempt(
            attempt, current.get(attempt.forecast.launch_id), now
        )
    return sorted(results.values(), key=lambda result: (result.attempt_net, result.attempt_id))
