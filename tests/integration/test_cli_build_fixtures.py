from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx
    import pytest

from scrubcast.build.contracts import Hindcast, Latest, Past
from scrubcast.cli import fixture_response, main
from scrubcast.models.assessment import LaunchAssessment

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_build_fixtures_and_cached_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scrubcast.cli.FIXTURES", FIXTURES)
    main(["build", "--fixtures", "--site-url", "https://example.org/weather/"])
    directory = tmp_path / "site/public/data"
    latest = Latest.model_validate_json((directory / "latest.json").read_text())
    assert latest.launches
    assert latest.members_total == 82
    assert (
        latest.generated_at.isoformat().replace("+00:00", "Z")
        == (FIXTURES / "RECORDED_AT").read_text().strip()
    )
    assert not latest.schedule_stale
    Past.model_validate_json((directory / "past.json").read_text())
    Hindcast.model_validate_json((directory / "hindcast.json").read_text())
    pages = list((directory / "launches").glob("*.json"))
    assert pages
    for path in pages:
        assessment = LaunchAssessment.model_validate_json(path.read_text())
        assert path.stem == assessment.launch.id
    for launch in latest.launches:
        assert (directory / f"launches/{launch.id}.json").exists() == launch.assessment
    ledger = tmp_path / "ledger"
    assert list(ledger.glob("20??-??.jsonl"))
    # Removing assessment rows catches accidental first-time writes from cached weather.
    for path in ledger.glob("20??-??.jsonl"):
        path.unlink()
    before = {path.name: path.read_bytes() for path in ledger.iterdir()}
    calls: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.host != "ensemble-api.open-meteo.com"
        return fixture_response(request)

    monkeypatch.setattr("scrubcast.cli.fixture_response", transport)
    main(["build", "--fixtures", "--no-weather"])
    assert calls
    assert before == {path.name: path.read_bytes() for path in ledger.iterdir()}
    refreshed = Latest.model_validate_json((directory / "latest.json").read_text())
    assert [launch.assessment for launch in refreshed.launches] == [
        launch.assessment for launch in latest.launches
    ]


def test_build_uses_the_pages_url_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scrubcast.cli.FIXTURES", FIXTURES)
    monkeypatch.setenv("SITE_URL", "https://scrubcast.intesarjawad.com/")
    main(["build", "--fixtures"])
    latest = Latest.model_validate_json((tmp_path / "site/public/data/latest.json").read_text())
    assert latest.launches
    assert all(
        launch.page_url.startswith("https://scrubcast.intesarjawad.com/launch/")
        for launch in latest.launches
    )


def test_build_fixtures_writes_past_pages_without_a_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scrubcast.cli.FIXTURES", FIXTURES)
    assert not (tmp_path / "data").exists()

    main(["build", "--fixtures"])

    past = Past.model_validate_json((tmp_path / "site/public/data/past.json").read_text())
    assert [launch.id for launch in past.launches] == ["fixture-past"]
    assert not past.launches[0].assessment
    assert [
        (rule.rule_id, rule.risk_fraction) for rule in past.launches[0].audit[0].scrubcast_24h
    ] == [
        ("thick_cloud", 0.4),
        ("cumulus", 0.1),
    ]


def test_build_no_weather_without_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scrubcast.cli.FIXTURES", FIXTURES)
    calls: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.host != "ensemble-api.open-meteo.com"
        return fixture_response(request)

    monkeypatch.setattr("scrubcast.cli.fixture_response", transport)
    main(["build", "--fixtures", "--no-weather"])
    latest = Latest.model_validate_json((tmp_path / "site/public/data/latest.json").read_text())
    assert latest.launches
    assert all(not launch.assessment for launch in latest.launches)
    assert not (tmp_path / "ledger").exists()
    assert calls
