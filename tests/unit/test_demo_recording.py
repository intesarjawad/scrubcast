import json
import runpy
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scrubcast.models.assessment import LaunchAssessment, RuleRisk
from scrubcast.models.launch import Launch
from scrubcast.models.rules import Confidence

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests/fixtures"
SCRIPT = runpy.run_path(str(ROOT / "scripts/record_demo_fixture.py"))
FLORIDA_ID = "3b430f81-0ff1-4d85-8a1a-cef0de326198"
VANDENBERG_ID = "54d471e8-695c-4fa7-a3cf-dbd8b389e8ae"


def _launch(name: str, launch_id: str) -> Launch:
    rows = json.loads((FIXTURES / name).read_text())["results"]
    return Launch.model_validate(next(row for row in rows if row["id"] == launch_id))


def test_florida_falcon_9_with_official_fields_inside_the_horizon_qualifies() -> None:
    launch = _launch("ll2_previous_florida.json", FLORIDA_ID)
    assert SCRIPT["refusal"](launch, launch.net - timedelta(days=1)) is None
    assert SCRIPT["refusal"](launch, launch.net - timedelta(days=10)) is None


@pytest.mark.parametrize(
    ("update", "days_before", "reason"),
    [
        ({"rocket_name": "Falcon Heavy"}, 1, "is not a Falcon 9"),
        ({"probability": None}, 1, "has no official probability"),
        ({"weather_concerns": None}, 1, "has no official weather concerns"),
        ({"weather_concerns": ""}, 1, "has no official weather concerns"),
        ({}, 11, "outside the 10-day forecast horizon"),
        ({}, -1, "outside the 10-day forecast horizon"),
    ],
)
def test_other_launches_are_refused(
    update: dict[str, object], days_before: int, reason: str
) -> None:
    launch = _launch("ll2_previous_florida.json", FLORIDA_ID).model_copy(update=update)
    assert reason in SCRIPT["refusal"](launch, launch.net - timedelta(days=days_before))


def test_california_and_missing_launches_are_refused() -> None:
    launch = _launch("ll2_upcoming.json", VANDENBERG_ID)
    now = launch.net - timedelta(days=1)
    assert SCRIPT["refusal"](launch, now) == f"{launch.name} is not at a Florida pad"
    assert "not in the upcoming schedule" in SCRIPT["refusal"](None, now)


def _with_window(top_hours: Sequence[float | None]) -> LaunchAssessment:
    """Give one direct rule the highest T-0 share and a hand-written hourly series."""
    assessment = LaunchAssessment.model_validate_json(
        (FIXTURES / "demo/assessment.json").read_text()
    )
    rules: list[RuleRisk] = []
    for index, rule in enumerate(assessment.rules):
        ecmwf = rule.by_model["ecmwf"].model_copy(update={"risk_fraction": 0.9 if index else 0.0})
        hours = list(top_hours) if index else [0.0] * len(top_hours)
        rules.append(
            rule.model_copy(
                update={
                    "confidence": Confidence.DIRECT if index == 1 else Confidence.LOW,
                    "by_model": {**rule.by_model, "ecmwf": ecmwf},
                    "risk_by_hour": {**rule.risk_by_hour, "ecmwf": hours},
                }
            )
        )
    rules[0] = rules[0].model_copy(
        update={"confidence": Confidence.MEDIUM, "risk_by_hour": {"ecmwf": [0.0, 1.0]}}
    )
    return assessment.model_copy(update={"rules": rules})


def test_spread_uses_the_top_direct_or_medium_rule_across_the_window() -> None:
    # The low rules share the top T-0 value but are ignored; the medium rule has 0.
    assert SCRIPT["spread"](_with_window([0.1, None, 0.5, 0.3])) == pytest.approx(0.4)


def test_widest_keeps_the_recording_with_the_largest_spread(tmp_path: Path) -> None:
    narrow, wide = tmp_path / "narrow", tmp_path / "wide"
    for directory, hours in ((narrow, [0.2, 0.3]), (wide, [0.0, 0.6])):
        directory.mkdir()
        (directory / "assessment.json").write_text(_with_window(hours).model_dump_json())
    assert SCRIPT["widest"]([narrow, wide]) == wide
    assert SCRIPT["widest"]([wide, narrow]) == wide


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Needs a live recording: no upcoming Florida Falcon 9 in the recorded schedules has "
        "a probability and weather concerns, so scripts/record_demo_fixture.py must run "
        "while such a launch is inside the ten-day forecast horizon"
    ),
)
def test_demo_fixture_holds_a_florida_falcon_9_with_official_fields() -> None:
    demo = FIXTURES / "demo"
    provenance = json.loads((demo / "provenance.json").read_text())
    rows = [
        row
        for response in provenance["responses"]
        if response["body"].startswith("ll2-")
        for row in json.loads((demo / response["body"]).read_text())["results"]
    ]
    raw = next(row for row in rows if row["id"] == provenance["launch_id"])
    assert raw["rocket"]["configuration"]["name"].startswith("Falcon 9")
    assert raw["pad"]["location"]["id"] in {12, 27}
    assert raw["probability"] is not None
    assert raw["weather_concerns"]
    recorded_at = datetime.fromisoformat((demo / "RECORDED_AT").read_text().strip())
    assert recorded_at <= datetime.fromisoformat(raw["net"]) <= recorded_at + timedelta(days=10)
