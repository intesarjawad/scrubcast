from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scrubcast.build.calendar import calendar, escape_text, fold_line
from scrubcast.build.contracts import LaunchSummary, WorstRule
from scrubcast.models.assessment import LaunchAssessment

GOLDEN = Path(__file__).parents[1] / "golden"
NOW = datetime(2026, 11, 5, 9, tzinfo=UTC)


def launch() -> LaunchSummary:
    assessment = LaunchAssessment.model_validate_json((GOLDEN / "assessment_cape.json").read_text())
    return LaunchSummary(
        **assessment.launch.model_dump(),
        tier=assessment.tier,
        assessment=True,
        worst_rule=WorstRule(label="Thick cloud 31%"),
        page_url="https://example.org/weather/launch/cape/",
    )


def test_calendar_golden() -> None:
    actual = calendar([launch()], NOW).encode()
    assert actual == (GOLDEN / "calendar.ics").read_bytes()
    assert actual.endswith(b"END:VCALENDAR\r\n")
    assert all(len(line) <= 75 for line in actual.split(b"\r\n"))


def test_calendar_instantaneous_window_and_utc() -> None:
    item = launch()
    item.window_start = item.window_end = item.net
    item.probability = 0
    result = calendar([item], NOW)
    assert "DTSTART:20261105T150000Z\r\n" in result
    assert "DTEND:20261105T170000Z\r\n" in result
    assert "DESCRIPTION:Official: 0% probability of GO" in result
    shifted = NOW.astimezone(datetime.fromisoformat("2026-11-05T03:00:00-06:00").tzinfo)
    assert calendar([item], shifted) == result


def test_calendar_horizon_order_and_missing_official() -> None:
    first = launch()
    first.probability = None
    second = first.model_copy(update={"id": "later", "net": NOW + timedelta(days=10)})
    past = first.model_copy(update={"id": "past", "net": NOW - timedelta(seconds=1)})
    beyond = first.model_copy(update={"id": "beyond", "net": second.net + timedelta(seconds=1)})
    result = calendar([beyond, second, past, first], NOW)
    assert result.count("BEGIN:VEVENT") == 2
    assert result.index(f"UID:{first.id}") < result.index("UID:later")
    assert "DESCRIPTION:Official forecast unavailable\\nhttps://example.org/" in result


@given(st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), max_size=250))
def test_calendar_unicode_escaping_round_trip(name: str) -> None:
    name += ",;\n发射\\é\r\n"
    item = launch().model_copy(update={"name": name})
    result = calendar([item], NOW)
    assert all(len(line.encode()) <= 75 for line in result.split("\r\n"))
    unfolded = result.replace("\r\n ", "")
    summary = next(
        line.removeprefix("SUMMARY:")
        for line in unfolded.split("\r\n")
        if line.startswith("SUMMARY:")
    )
    decoded: list[str] = []
    characters = iter(summary)
    for character in characters:
        if character == "\\":
            escaped = next(characters)
            decoded.append("\n" if escaped == "n" else escaped)
        else:
            decoded.append(character)
    assert "".join(decoded) == name.replace("\r\n", "\n") + " (Thick cloud 31%)"


@pytest.mark.parametrize("length", [74, 75, 76, 149, 150, 151])
def test_calendar_folding_boundary(length: int) -> None:
    value = "a" * length + "界"
    folded = fold_line(value)
    assert folded.replace("\r\n ", "") == value
    assert all(len(line.encode()) <= 75 for line in folded.split("\r\n"))


def test_calendar_text_escaping() -> None:
    assert escape_text("a\\b,c;d\r\ne\rf\ng") == "a\\\\b\\,c\\;d\\ne\\nf\\ng"
