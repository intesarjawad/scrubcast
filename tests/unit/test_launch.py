from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import JsonValue, TypeAdapter, ValidationError

from scrubcast.models.launch import Launch, LaunchDetailed, LaunchStatus, parse_concerns

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _fixture_rows(filename: str) -> list[dict[str, JsonValue]]:
    response = TypeAdapter(dict[str, JsonValue]).validate_json((FIXTURES / filename).read_text())
    return TypeAdapter(list[dict[str, JsonValue]]).validate_python(response["results"])


@pytest.fixture(params=["ll2", "ll2_2.4.0"], ids=["2.3.0", "2.4.0"])
def ll2_prefix(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def upcoming_row(ll2_prefix: str) -> dict[str, JsonValue]:
    return _fixture_rows(f"{ll2_prefix}_upcoming.json")[0]


@pytest.mark.parametrize(
    ("filename", "model"),
    [
        ("ll2_upcoming.json", Launch),
        ("ll2_2.4.0_upcoming.json", Launch),
        ("ll2_previous_florida.json", Launch),
        ("ll2_previous_detailed.json", LaunchDetailed),
        ("ll2_2.4.0_previous_detailed.json", LaunchDetailed),
    ],
)
def test_every_fixture_launch_parses(filename: str, model: type[Launch]) -> None:
    rows = _fixture_rows(filename)

    launches = [model.model_validate(row) for row in rows]

    assert [launch.id for launch in launches] == [row["id"] for row in rows]
    assert all(launch.rocket_name for launch in launches)
    assert all(model.model_validate_json(launch.model_dump_json()) == launch for launch in launches)


def test_upcoming_fields(upcoming_row: dict[str, JsonValue]) -> None:
    launch = Launch.model_validate(upcoming_row)

    assert launch.id == "711de6bc-f755-475b-a12f-ec5240da3a11"
    assert launch.name == "Long March 2C | Unknown Payload"
    assert launch.slug == "long-march-2c-unknown-payload"
    assert launch.status is LaunchStatus.GO
    assert launch.net == datetime(2026, 11, 5, 16, tzinfo=UTC)
    assert launch.net_precision == "HR"
    assert launch.window_start == datetime(2026, 11, 5, 15, 52, tzinfo=UTC)
    assert launch.window_end == datetime(2026, 11, 5, 16, 16, tzinfo=UTC)
    assert launch.last_updated == datetime(2026, 10, 30, 13, 34, 13, tzinfo=UTC)
    assert launch.rocket_name == "Long March 2C"
    assert (
        launch.launch_service_provider_name == "China Aerospace Science and Technology Corporation"
    )
    assert launch.pad.id == 66
    assert launch.pad.name == "Launch Complex 3 (LC-3/LA-1)"
    assert launch.pad.latitude == pytest.approx(28.247059)
    assert launch.pad.longitude == pytest.approx(102.029008)
    assert launch.pad.location.id == 16
    assert launch.pad.location.name == "Xichang Satellite Launch Center, People's Republic of China"
    assert launch.pad.location.timezone_name == "Asia/Shanghai"
    assert launch.mission is not None
    assert launch.mission.orbit is not None
    assert launch.mission.orbit.abbrev == "N/A"
    assert launch.probability is None
    assert launch.weather_concerns is None


def test_detailed_fields_and_official_probability(ll2_prefix: str) -> None:
    rows = _fixture_rows(f"{ll2_prefix}_previous_detailed.json")
    row = next(row for row in rows if row["id"] == "94ec1605-bd9c-47fa-9f36-69148ee4e370")

    launch = LaunchDetailed.model_validate(row)

    assert launch.status is LaunchStatus.SUCCESS
    assert launch.probability == 95
    assert launch.weather_concerns == "Cumulus Cloud Rule"
    assert launch.rocket_name == "Falcon 9"
    assert launch.updates
    assert launch.updates[0].created_on == datetime(2025, 10, 29, 17, 42, tzinfo=UTC)
    assert launch.updates[0].comment == "Launch success."
    assert [update.comment for update in launch.updates] == [
        update["comment"]
        for update in TypeAdapter(list[dict[str, JsonValue]]).validate_python(row["updates"])
    ]
    assert all(update.created_on.utcoffset() == UTC.utcoffset(None) for update in launch.updates)


def test_detailed_without_holdreason(ll2_prefix: str) -> None:
    rows = _fixture_rows(f"{ll2_prefix}_previous_detailed.json")
    for row in rows:
        row.pop("holdreason", None)

    launches = [LaunchDetailed.model_validate(row) for row in rows]

    comments = {update.comment for launch in launches for update in launch.updates}
    assert "Launch delayed due to launch site weather, new date TBD." in comments
    assert "Scrubbed for the day due to TEL arm hydraulics issue." in comments


def test_detailed_requires_updates(upcoming_row: dict[str, JsonValue]) -> None:
    upcoming_row.pop("updates", None)

    with pytest.raises(ValidationError, match="updates"):
        LaunchDetailed.model_validate(upcoming_row)


def test_detailed_accepts_no_updates(upcoming_row: dict[str, JsonValue]) -> None:
    upcoming_row["updates"] = []

    assert LaunchDetailed.model_validate(upcoming_row).updates == []


@pytest.mark.parametrize(
    "update",
    [
        {"created_on": "2026-11-05T16:00:00", "comment": "Launch delayed."},
        {"created_on": "invalid", "comment": "Launch delayed."},
        {"created_on": "2026-11-05T16:00:00Z"},
        {"comment": "Launch delayed."},
    ],
)
def test_detailed_invalid_update(upcoming_row: dict[str, JsonValue], update: JsonValue) -> None:
    upcoming_row["updates"] = [update]

    with pytest.raises(ValidationError, match="updates"):
        LaunchDetailed.model_validate(upcoming_row)


@pytest.mark.parametrize(
    "abbrev",
    [
        "Go",
        "TBD",
        "Success",
        "Failure",
        "Hold",
        "In Flight",
        "Partial Failure",
        "TBC",
        "Payload Deployed",
    ],
)
def test_known_status(upcoming_row: dict[str, JsonValue], abbrev: str) -> None:
    upcoming_row["status"] = {"abbrev": abbrev}

    launch = Launch.model_validate(upcoming_row)

    assert isinstance(launch.status, LaunchStatus)
    assert launch.status.value == abbrev


def test_unknown_status_is_rejected(upcoming_row: dict[str, JsonValue]) -> None:
    upcoming_row["status"] = {"abbrev": "Unrecognized"}

    with pytest.raises(ValidationError, match=r"status\.abbrev"):
        Launch.model_validate(upcoming_row)


@pytest.mark.parametrize("mission", [None, {"orbit": None}])
def test_unknown_mission_or_orbit(upcoming_row: dict[str, JsonValue], mission: JsonValue) -> None:
    upcoming_row["mission"] = mission

    launch = Launch.model_validate(upcoming_row)

    assert launch.mission is None or launch.mission.orbit is None


def test_schedule_filter_inputs_are_preserved(ll2_prefix: str) -> None:
    launches = [Launch.model_validate(row) for row in _fixture_rows(f"{ll2_prefix}_upcoming.json")]

    assert any(launch.net_precision == "M" for launch in launches)
    assert any(
        launch.mission is not None
        and launch.mission.orbit is not None
        and launch.mission.orbit.abbrev == "Sub"
        for launch in launches
    )


@pytest.mark.parametrize("probability", [0, 100])
def test_probability_boundaries(upcoming_row: dict[str, JsonValue], probability: int) -> None:
    upcoming_row["probability"] = probability

    assert Launch.model_validate(upcoming_row).probability == probability


@pytest.mark.parametrize("probability", [-1, 101, 95.5, "95", True])
def test_invalid_probability(upcoming_row: dict[str, JsonValue], probability: JsonValue) -> None:
    upcoming_row["probability"] = probability

    with pytest.raises(ValidationError, match="probability"):
        Launch.model_validate(upcoming_row)


@pytest.mark.parametrize("field", ["net", "window_start", "window_end", "last_updated"])
@pytest.mark.parametrize("value", ["invalid", "2026-11-05T16:00:00"])
def test_invalid_timestamp(upcoming_row: dict[str, JsonValue], field: str, value: str) -> None:
    upcoming_row[field] = value

    with pytest.raises(ValidationError, match=field):
        Launch.model_validate(upcoming_row)


@pytest.mark.parametrize("field", ["id", "pad", "probability", "weather_concerns"])
def test_required_field(upcoming_row: dict[str, JsonValue], field: str) -> None:
    del upcoming_row[field]

    with pytest.raises(ValidationError, match=field):
        Launch.model_validate(upcoming_row)


@pytest.mark.parametrize(
    ("field", "value"),
    [("latitude", -90.1), ("latitude", 90.1), ("longitude", -180.1), ("longitude", 180.1)],
)
def test_invalid_pad_coordinate(
    upcoming_row: dict[str, JsonValue],
    field: str,
    value: float,
) -> None:
    pad = TypeAdapter(dict[str, JsonValue]).validate_python(upcoming_row["pad"])
    pad[field] = value
    upcoming_row["pad"] = pad

    with pytest.raises(ValidationError, match=rf"pad\.{field}"):
        Launch.model_validate(upcoming_row)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, []),
        ("", []),
        ("  , ,\t", []),
        (
            "Cumulus Cloud Rule, Thick Cloud Layers Rule",
            ["Cumulus Cloud Rule", "Thick Cloud Layers Rule"],
        ),
        ("  Anvil Rules , , Liftoff Winds, ", ["Anvil Rules", "Liftoff Winds"]),
        ("Unknown Concern, anvil rule", ["Unknown Concern", "anvil rule"]),
        ("Anvil Rule, Anvil Rule", ["Anvil Rule", "Anvil Rule"]),
    ],
)
def test_parse_concerns(text: str | None, expected: list[str]) -> None:
    assert parse_concerns(text) == expected
