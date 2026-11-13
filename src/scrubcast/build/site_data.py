"""Publish schema-backed indexes beside the per-launch assessment files."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from pydantic import BaseModel, JsonValue, TypeAdapter

from scrubcast.build.badges import write_badges
from scrubcast.build.calendar import FORECAST_HORIZON, calendar
from scrubcast.build.contracts import (
    Hindcast,
    Latest,
    LaunchSummary,
    Past,
    PastLaunch,
    WorstRule,
)
from scrubcast.build.past import PAST_RETENTION, LedgerEvidence, past_summaries, read_ledger
from scrubcast.models.assessment import AuditFooter, LaunchAssessment
from scrubcast.models.rules import Confidence, Tier

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from scrubcast.models.launch import Launch
    from scrubcast.models.weather import EnsembleModel
    from scrubcast.rules.loader import RuleCatalog

CHIP_MIN_RISK = 0.05


@dataclass(frozen=True)
class Publication:
    """Destination, schedule freshness and fixture evidence supplied by the build command."""

    root: Path = Path()
    site_url: str = "/"
    schedule_stale: bool = False
    fixture_ledger: Path | None = None


def worst_rule(assessment: LaunchAssessment) -> WorstRule:
    """Select published direct or medium rules before low-confidence evidence."""
    if assessment.tier == Tier.C:
        return WorstRule(label="No published rules")
    reference = " (LLCC reference)" if assessment.tier == Tier.B else ""
    candidates = [
        rule for rule in assessment.rules if assessment.tier == Tier.B or not rule.reference_only
    ]
    for confidence in ((Confidence.DIRECT, Confidence.MEDIUM), (Confidence.LOW,)):
        risks: list[tuple[float, str, EnsembleModel]] = []
        for rule in candidates:
            if rule.confidence not in confidence:
                continue
            for model in ("ecmwf", "gfs"):
                evidence = rule.by_model.get(model)
                if evidence is None:
                    continue
                risk = evidence.risk_fraction
                if evidence.evaluable_members and risk is not None and risk >= CHIP_MIN_RISK:
                    risks.append((risk, rule.rule_id, model))
        if risks:
            risk, rule_id, model = min(risks, key=lambda item: (-item[0], item[1]))
            rule = next(rule for rule in candidates if rule.rule_id == rule_id)
            suffix = " (low confidence)" if rule.confidence == Confidence.LOW else ""
            suffix += reference
            return WorstRule(
                label=f"{rule.title} {risk:.0%} ({model.upper()}){suffix}",
                rule_id=rule_id,
                risk_fraction=risk,
                model=model,
                confidence=rule.confidence,
            )
    unavailable = not candidates or any(
        not any(
            risk.risk_fraction is not None and risk.evaluable_members
            for risk in rule.by_model.values()
        )
        for rule in candidates
    )
    label = "Forecast unavailable" if unavailable else "No rule above 5%"
    return WorstRule(label=label + reference)


def _summary(
    launch: Launch,
    assessment: LaunchAssessment | None,
    catalog: RuleCatalog,
    site_url: str,
) -> LaunchSummary:
    tier = catalog.site_for(launch.pad).tier
    return LaunchSummary(
        **launch.model_dump(),
        tier=tier,
        assessment=assessment is not None,
        worst_rule=(
            worst_rule(assessment)
            if assessment is not None
            else WorstRule(label="No published rules" if tier == Tier.C else "Forecast unavailable")
        ),
        page_url=f"{site_url.rstrip('/')}/launch/{quote(launch.id, safe='')}/",
    )


def _write(path: Path, model: BaseModel) -> None:
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _retained_pages(pages: Path, now: datetime) -> dict[str, LaunchAssessment]:
    retained: dict[str, LaunchAssessment] = {}
    for path in sorted(pages.glob("*.json")):
        saved = LaunchAssessment.model_validate_json(path.read_text())
        if now - PAST_RETENTION <= saved.launch.net < now:
            retained[saved.launch.id] = saved
        elif saved.launch.net < now - PAST_RETENTION:
            path.unlink()
    return retained


def _audit_footers(
    evidence: LedgerEvidence,
    legacy: dict[str, list[AuditFooter]],
    launch_id: str,
) -> list[AuditFooter]:
    saved = evidence.footers.get(launch_id, [])
    known = {footer.attempt_id for footer in saved}
    footers = [
        *saved,
        *(item for item in legacy.get(launch_id, []) if item.attempt_id not in known),
    ]
    return sorted(footers, key=lambda footer: footer.attempt_net, reverse=True)


def _known_summaries(
    directory: Path,
    retained: dict[str, LaunchAssessment],
    catalog: RuleCatalog,
    site_url: str,
) -> dict[str, LaunchSummary]:
    known: dict[str, LaunchSummary] = {}
    previous = directory / "past.json"
    if previous.exists():
        for summary in Past.model_validate_json(previous.read_text()).launches:
            known[summary.id] = summary
    for item in retained.values():
        known[item.launch.id] = _summary(item.launch, item, catalog, site_url)
    return known


def _past_index(
    evidence: LedgerEvidence,
    legacy: dict[str, list[AuditFooter]],
    now: datetime,
    known: dict[str, LaunchSummary],
    site_url: str,
) -> list[PastLaunch]:
    start = now - PAST_RETENTION

    def recent(launch_id: str) -> list[AuditFooter]:
        return [
            footer
            for footer in _audit_footers(evidence, legacy, launch_id)
            if start <= footer.attempt_net <= now
        ]

    past = {
        summary.id: summary.model_copy(update={"audit": recent(summary.id)})
        for summary in past_summaries(evidence, now, site_url, known)
    }
    for launch_id, summary in known.items():
        if launch_id not in past and start <= summary.net < now:
            # A row from the previous past.json keeps its footers when the ledger lacks them.
            published = summary.audit if isinstance(summary, PastLaunch) else []
            audit = recent(launch_id) or [
                footer for footer in published if start <= footer.attempt_net <= now
            ]
            data = summary.model_dump(exclude={"audit"})
            data["assessment"] = False
            past[launch_id] = PastLaunch(**data, audit=audit)
    return sorted(past.values(), key=lambda summary: summary.net, reverse=True)


def write_site_data(
    launches: Sequence[Launch],
    assessments: Sequence[LaunchAssessment],
    catalog: RuleCatalog,
    now: datetime,
    *,
    publication: Publication | None = None,
) -> Latest:
    """Write public files and retain past launch pages for ninety days."""
    publication = publication or Publication()
    directory = publication.root / "site/public/data"
    pages = directory / "launches"
    pages.mkdir(parents=True, exist_ok=True)
    by_id = {assessment.launch.id: assessment for assessment in assessments}
    retained = _retained_pages(pages, now)
    roots = [publication.root]
    if publication.fixture_ledger is not None and publication.fixture_ledger.exists():
        roots.insert(0, publication.fixture_ledger)
    evidence = read_ledger(roots, catalog)
    footers_path = publication.root / "ledger/audit-footers.json"
    legacy = (
        TypeAdapter(dict[str, list[AuditFooter]]).validate_json(footers_path.read_text())
        if footers_path.exists()
        else {}
    )
    hindcast_path = publication.root / "ledger/hindcast.json"
    verified = False
    if hindcast_path.exists():
        hindcast = TypeAdapter(dict[str, JsonValue]).validate_json(hindcast_path.read_text())
        verified = TypeAdapter(bool).validate_python(hindcast.get("lowest_hour_verified", False))
        (directory / "hindcast.json").write_text(
            json.dumps(hindcast, indent=2) + "\n", encoding="utf-8"
        )
        write_badges(directory / "badges", hindcast, now)
    else:
        empty = Hindcast(generated_at=now)
        _write(directory / "hindcast.json", empty)
        write_badges(directory / "badges", empty.model_dump(mode="json"), now)
    for assessment in assessments:
        audit = _audit_footers(evidence, legacy, assessment.launch.id)
        published = assessment.model_copy(update={"lowest_hour_verified": verified, "audit": audit})
        _write(pages / f"{assessment.launch.id}.json", published)
        if now - PAST_RETENTION <= assessment.launch.net < now:
            retained[assessment.launch.id] = published
    upcoming = sorted(
        (launch for launch in launches if now <= launch.net <= now + FORECAST_HORIZON),
        key=lambda launch: (launch.net, launch.id),
    )
    members_total = sum(
        max(
            (
                rule.by_model[model].members
                for item in assessments
                for rule in item.rules
                if model in rule.by_model
            ),
            default=0,
        )
        for model in ("ecmwf", "gfs")
    )
    latest = Latest(
        generated_at=now,
        schedule_stale=publication.schedule_stale,
        members_total=members_total,
        launches=[
            _summary(launch, by_id.get(launch.id), catalog, publication.site_url)
            for launch in upcoming
        ],
    )
    known = _known_summaries(directory, retained, catalog, publication.site_url)
    past = Past(
        generated_at=now,
        launches=_past_index(evidence, legacy, now, known, publication.site_url),
    )
    _write(directory / "latest.json", latest)
    _write(directory / "past.json", past)
    (directory / "calendar.ics").write_bytes(calendar(latest.launches, now).encode("utf-8"))
    return latest
