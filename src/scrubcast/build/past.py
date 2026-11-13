"""Retained launch summaries rebuilt from the committed audit ledger."""

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote

from scrubcast.audit.forecast_audit import (
    attempt_footers,
    load_outcome_records,
    read_ledger_records,
)
from scrubcast.audit.outcomes import select_attempts
from scrubcast.build.contracts import PastLaunch, WorstRule
from scrubcast.models.launch import Launch
from scrubcast.models.rules import Tier

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime
    from pathlib import Path

    from scrubcast.audit.outcomes import Attempt, AttemptOutcome
    from scrubcast.build.contracts import LaunchSummary
    from scrubcast.models.assessment import AuditFooter, LedgerRow
    from scrubcast.rules.loader import RuleCatalog

PAST_RETENTION = timedelta(days=90)


@dataclass(frozen=True)
class LedgerEvidence:
    """Committed rows with their ready-made audit footers."""

    rows: list[LedgerRow]
    footers: dict[str, list[AuditFooter]]


def read_ledger(roots: Sequence[Path], catalog: RuleCatalog | None) -> LedgerEvidence:
    """Read ledger roots or bare fixture directories, letting later roots win outcomes."""
    rows: list[LedgerRow] = []
    outcomes: dict[str, AttemptOutcome] = {}
    for root in roots:
        directory = root / "ledger"
        directory = directory if directory.is_dir() else root
        rows.extend(read_ledger_records(directory))
        outcomes.update(load_outcome_records(directory))
    return LedgerEvidence(
        rows=rows,
        footers=attempt_footers(rows, outcomes, catalog),
    )


def _worst_rule(footers: Sequence[AuditFooter], tier: Tier) -> WorstRule:
    if tier == Tier.C:
        return WorstRule(label="No published rules")
    rules = [rule for footer in footers for rule in footer.scrubcast_24h]
    if not rules:
        return WorstRule(label="No rule above zero")
    top = max(rules, key=lambda rule: (rule.risk_fraction, rule.rule_id))
    return WorstRule(
        label=f"{top.title} {top.risk_fraction:.0%}",
        rule_id=top.rule_id,
        risk_fraction=top.risk_fraction,
    )


def _header(row: LedgerRow, known: Mapping[str, LaunchSummary]) -> Launch | None:
    if row.launch is not None:
        return row.launch
    previous = known.get(row.launch_id)
    return Launch.model_validate(previous.model_dump()) if previous is not None else None


def past_summaries(
    evidence: LedgerEvidence,
    now: datetime,
    site_url: str,
    known: Mapping[str, LaunchSummary],
) -> list[PastLaunch]:
    """Keep every attempt still inside the retention window, newest first."""
    start = now - PAST_RETENTION
    attempts: dict[str, Attempt] = {}
    for attempt in select_attempts(evidence.rows):
        if start <= attempt.attempt_net <= now:
            previous = attempts.get(attempt.forecast.launch_id)
            if previous is None or attempt.attempt_net > previous.attempt_net:
                attempts[attempt.forecast.launch_id] = attempt
    summaries: list[PastLaunch] = []
    for launch_id, attempt in attempts.items():
        row = attempt.forecast
        launch = _header(row, known)
        if launch is None:
            continue
        audit = [
            footer
            for footer in evidence.footers.get(launch_id, [])
            if start <= footer.attempt_net <= now
        ]
        concerns = ", ".join(row.official_concerns)
        launch = launch.model_copy(
            update={
                "probability": row.official_go_pct,
                "weather_concerns": concerns or None,
            }
        )
        summaries.append(
            PastLaunch(
                **launch.model_dump(),
                tier=row.tier,
                assessment=False,
                worst_rule=_worst_rule(audit, row.tier),
                page_url=f"{site_url.rstrip('/')}/launch/{quote(launch_id, safe='')}/",
                audit=audit,
            )
        )
    return sorted(summaries, key=lambda summary: summary.net, reverse=True)
