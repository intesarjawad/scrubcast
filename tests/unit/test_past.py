from datetime import UTC, datetime, timedelta
from pathlib import Path

from scrubcast.build.contracts import Past
from scrubcast.build.past import past_summaries, read_ledger
from scrubcast.build.site_data import Publication, write_site_data
from scrubcast.rules.loader import load_rules

NOW = datetime(2026, 11, 5, 8, 59, 17, tzinfo=UTC)
FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_past_summaries_come_from_the_committed_ledger() -> None:
    evidence = read_ledger([FIXTURES / "past"], load_rules())

    summaries = past_summaries(evidence, NOW, "https://example.org/", {})

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.id == "fixture-past"
    assert summary.name == "Falcon 9 Block 5 | Retained Fixture"
    assert summary.probability == 90
    assert summary.weather_concerns == "Cumulus Cloud Rule"
    assert not summary.assessment
    assert summary.page_url == "https://example.org/launch/fixture-past/"
    assert [footer.outcome for footer in summary.audit] == ["launched"]
    footer = summary.audit[0]
    assert [(rule.rule_id, rule.risk_fraction) for rule in footer.scrubcast_24h] == [
        ("thick_cloud", 0.4),
        ("cumulus", 0.1),
    ]
    assert footer.official_concerns == ["Cumulus Cloud Rule"]
    assert summary.worst_rule.label == "Thick cloud 40%"


def test_past_summaries_expire_ninety_days_after_t0() -> None:
    evidence = read_ledger([FIXTURES / "past"], load_rules())
    net = datetime(2026, 11, 3, 0, 46, tzinfo=UTC)

    assert past_summaries(evidence, net + timedelta(days=90), "/", {})
    assert not past_summaries(evidence, net + timedelta(days=90, seconds=1), "/", {})


def test_build_writes_past_pages_without_a_data_directory(tmp_path: Path) -> None:
    assert not (tmp_path / "data").exists()

    write_site_data(
        [],
        [],
        load_rules(),
        NOW,
        publication=Publication(root=tmp_path, fixture_ledger=FIXTURES / "past"),
    )

    past = Past.model_validate_json((tmp_path / "site/public/data/past.json").read_text())
    assert [launch.id for launch in past.launches] == ["fixture-past"]
    assert not past.launches[0].assessment
    assert past.launches[0].audit
    assert not (tmp_path / "data").exists()


def test_rebuild_keeps_a_published_past_row_missing_from_the_ledger(tmp_path: Path) -> None:
    # The first build saw the launch in a fixture ledger; the next build only has past.json.
    write_site_data(
        [],
        [],
        load_rules(),
        NOW,
        publication=Publication(root=tmp_path, fixture_ledger=FIXTURES / "past"),
    )
    write_site_data(
        [], [], load_rules(), NOW + timedelta(hours=1), publication=Publication(root=tmp_path)
    )

    past = Past.model_validate_json((tmp_path / "site/public/data/past.json").read_text())
    assert [launch.id for launch in past.launches] == ["fixture-past"]
    assert not past.launches[0].assessment
    assert [footer.outcome for footer in past.launches[0].audit] == ["launched"]
