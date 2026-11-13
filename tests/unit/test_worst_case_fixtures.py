import json
from pathlib import Path

from scrubcast.build.contracts import Latest
from scrubcast.models.assessment import LaunchAssessment

FIXTURES = Path(__file__).parents[2] / "tests/fixtures/worst_case"

STATES = {
    "thirty-launches.json",
    "window-24h.json",
    "window-crosses-midnight.json",
    "missing-official-fields.json",
    "long-mission-name.json",
    "non-latin-name.json",
    "member-nan-hour.json",
    "ecmwf-missing.json",
    "refresh-deferred.json",
    "schedule-stale.json",
    "window-beyond-horizon.json",
    "unmapped-concern.json",
    "storm-night.json",
}


def test_every_documented_state_has_a_fixture() -> None:
    assert {path.name for path in FIXTURES.glob("*.json")} == STATES


def test_fixtures_parse_as_published_contracts() -> None:
    for path in sorted(FIXTURES.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "launches" in payload:
            Latest.model_validate(payload)
        else:
            LaunchAssessment.model_validate(payload)
