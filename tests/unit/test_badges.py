import json
from datetime import datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from scrubcast.build.badges import BADGE_FILES, badges, render_badge
from scrubcast.build.contracts import Hindcast

FIXTURES = Path(__file__).parents[1] / "fixtures/hindcast"
GOLDEN = Path(__file__).parents[1] / "golden/badges"
STATES = ("full", "missing_eval", "stale", "small")
# The keys shields.io's endpoint schema accepts that a badge here can use; it rejects any other key.
SHIELDS_KEYS = {"schemaVersion", "label", "message", "color"}


def _now() -> datetime:
    return datetime.fromisoformat(
        (Path(__file__).parents[1] / "fixtures/RECORDED_AT").read_text().strip()
    )


def _fixture(state: str) -> Hindcast:
    return Hindcast.model_validate_json((FIXTURES / f"{state}.json").read_text())


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("name", BADGE_FILES)
def test_badges_match_goldens(name: str, state: str) -> None:
    badge = badges(_fixture(state).model_dump(mode="json"), _now())[name]

    assert render_badge(badge) == (GOLDEN / f"{name}-{state}.json").read_bytes()


@pytest.mark.parametrize("state", STATES)
def test_published_bytes_are_a_shields_endpoint(state: str) -> None:
    for badge in badges(_fixture(state).model_dump(mode="json"), _now()).values():
        payload = json.loads(render_badge(badge))
        assert set(payload) == SHIELDS_KEYS
        assert payload["schemaVersion"] == 1


def test_absent_hindcast_is_an_explicit_state() -> None:
    output = badges(None, _now())

    assert set(output) == set(BADGE_FILES)
    assert all(badge.message == "no audit yet (n=0)" for badge in output.values())
    assert all(badge.color == "lightgrey" for badge in output.values())


def test_negative_wind_skill_keeps_the_informational_colour() -> None:
    data = _fixture("full")
    assert data.forecast_audit is not None
    skill = next(
        row for row in data.forecast_audit.evaluations[0].rows if row.label.endswith("CRPS skill")
    )
    skill.value = -0.4

    badge = badges(data.model_dump(mode="json"), _now())["wind"]

    assert badge.color == "blue"
    assert badge.message == "ECMWF wind skill -40.0% (n=12)"


@given(n=st.integers(min_value=0, max_value=1_000_000))
@settings(max_examples=50)
def test_messages_stay_short_and_name_the_same_sample(n: int) -> None:
    data = _fixture("missing_eval")
    assert data.forecast_audit is not None
    for evaluation in data.forecast_audit.evaluations:
        evaluation.n = n
        for row in evaluation.rows:
            row.n = n
            row.value = None
            row.sufficient = False
    data.forecast_audit.attempts.n = n
    data.forecast_audit.attempts.auc = None
    data.forecast_audit.attempts.message = None

    for badge in badges(data.model_dump(mode="json"), _now()).values():
        assert len(badge.message) <= 60
        assert f"n={n}" in badge.message
        assert badge.n == n
