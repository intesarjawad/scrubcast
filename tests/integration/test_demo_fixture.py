import hashlib
import json
import runpy
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import httpx

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/demo"


def test_demo_fixture_provenance_and_selection() -> None:
    provenance = json.loads((FIXTURE / "provenance.json").read_text())
    assessment = json.loads((FIXTURE / "assessment.json").read_text())
    assert provenance["pipeline_version"]
    for filename, digest in provenance["sha256"].items():
        assert hashlib.sha256((FIXTURE / filename).read_bytes()).hexdigest() == digest
    pages = [
        json.loads((FIXTURE / response["body"]).read_text())
        for response in provenance["responses"]
        if response["body"].startswith("ll2-")
    ]
    rows = [row for page in pages for row in page["results"]]
    for response in provenance["responses"]:
        assert response["status"] == 200
        assert datetime.fromisoformat(response["retrieved_at"]).utcoffset() is not None
        assert response["url"].startswith("https://")
    assert len(rows) == pages[0]["count"]
    launch = assessment["launch"]
    raw = next(row for row in rows if row["id"] == launch["id"])
    for field in (
        "id",
        "name",
        "net",
        "window_start",
        "window_end",
        "probability",
        "weather_concerns",
    ):
        assert launch[field] == raw[field]
    for field in ("id", "name", "latitude", "longitude"):
        assert launch["pad"][field] == raw["pad"][field]
    for field in ("id", "name", "timezone_name"):
        assert launch["pad"]["location"][field] == raw["pad"]["location"][field]
    assert raw["rocket"]["configuration"]["name"].startswith("Falcon 9")
    assert assessment["tier"] == "A"
    assert assessment["official"]["probability_go_pct"] == raw["probability"]
    recorded_at = datetime.fromisoformat((FIXTURE / "RECORDED_AT").read_text().strip())
    assert recorded_at <= datetime.fromisoformat(raw["net"]) <= recorded_at + timedelta(days=10)
    if raw["probability"] is None or not raw["weather_concerns"]:
        assert provenance["limitations"]
        assert not any(row["probability"] is not None and row["weather_concerns"] for row in rows)
    else:
        assert raw["pad"]["location"]["id"] in {12, 27}
    if raw["weather_concerns"] and "Unknown concern" in raw["weather_concerns"]:
        assert any("verbatim" in note for note in provenance["limitations"])


def test_demo_fixture_precipitation_is_unmodified_hourly_source_evidence() -> None:
    raw = json.loads((FIXTURE / "weather.json").read_text())["hourly"]
    assessment = json.loads((FIXTURE / "assessment.json").read_text())
    rule = next(rule for rule in assessment["rules"] if rule["rule_id"] == "flight_through_precip")
    for model, suffix in (("ecmwf", "ecmwf_ifs025_ensemble"), ("gfs", "ncep_gefs_seamless")):
        for hour, timestamp in enumerate(rule["hours"]):
            index = raw["time"].index(timestamp[:16])
            expected_values: list[float | None] = []
            expected_verdicts: list[int | None] = []
            for member in range(rule["by_model"][model]["members"]):
                name = "precipitation" if member == 0 else f"precipitation_member{member:02d}"
                value = raw[f"{name}_{suffix}"][index]
                expected_values.append(value)
                expected_verdicts.append(
                    None if value is None else int(value > rule["threshold"]["value"])
                )
            assert rule["member_values_by_hour"][model][hour] == pytest.approx(
                expected_values, abs=1e-6
            )
            assert rule["member_violated_by_hour"][model][hour] == expected_verdicts
    repeated = all(
        row == rule["member_values_by_hour"]["ecmwf"][0]
        for row in rule["member_values_by_hour"]["ecmwf"]
    )
    if repeated:
        assert all(value == 0 for row in rule["member_values_by_hour"]["ecmwf"] for value in row)
        provenance = json.loads((FIXTURE / "provenance.json").read_text())
        assert "zero precipitation" in " ".join(provenance["limitations"])


def test_demo_fixture_replays_commands_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_network(_self: httpx.HTTPTransport, _request: httpx.Request) -> httpx.Response:
        pytest.fail("Demo replay attempted a live network request")

    monkeypatch.setattr("httpx.HTTPTransport.handle_request", reject_network)
    namespace = runpy.run_path(str(ROOT / "site/scripts/fixtures.py"))
    publish = namespace["publish"]
    monkeypatch.setitem(publish.__globals__, "ROOT", tmp_path)
    publish()
    expected = json.loads((FIXTURE / "assessment.json").read_text())
    built = tmp_path / f"site/public/data/launches/{expected['launch']['id']}.json"
    assert json.loads(built.read_text()) == expected
    assert json.loads((tmp_path / "site/public/data/latest.json").read_text()) == json.loads(
        (FIXTURE / "latest.json").read_text()
    )
