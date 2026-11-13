import logging
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue, TypeAdapter

from scrubcast.cli import Schedule, filter_schedule, main, write_schedule
from scrubcast.models.launch import Launch, LaunchStatus, Mission, Orbit
from scrubcast.sources.errors import SourceError

FIXTURES = Path(__file__).parents[1] / "fixtures"
GOLDEN = Path(__file__).parents[1] / "golden/schedule.json"


@pytest.fixture
def launches() -> list[Launch]:
    response = TypeAdapter(dict[str, JsonValue]).validate_json(
        (FIXTURES / "ll2_upcoming.json").read_text(),
    )
    return TypeAdapter(list[Launch]).validate_python(response["results"])


@pytest.fixture
def now() -> datetime:
    return datetime.fromisoformat((FIXTURES / "RECORDED_AT").read_text().strip())


def test_schedule_golden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scrubcast.cli.FIXTURES", FIXTURES)
    caplog.set_level(logging.INFO)

    main(["schedule", "--fixtures"])

    output = tmp_path / "data/schedule.json"
    assert output.read_text() == GOLDEN.read_text()
    schedule = Schedule.model_validate_json(output.read_text())
    assert schedule.generated_at == datetime.fromisoformat(
        (FIXTURES / "RECORDED_AT").read_text().strip(),
    )
    assert schedule.schedule_stale is False
    assert "NET precision 'M'" in caplog.text
    assert "suborbital mission (Sub)" in caplog.text


@pytest.mark.parametrize("precision", ["SEC", "MIN", "HR", "AM", "PM", "DAY"])
def test_net_precision_allowlist(launches: list[Launch], precision: str) -> None:
    launch = launches[0].model_copy(update={"net_precision": precision})
    assert filter_schedule([launch]) == [launch]


@pytest.mark.parametrize("precision", ["M", "Q1", "Q2", "Q3", "Q4", "H1", "H2", "Y", "unknown"])
def test_net_precision_excludes_with_reason(
    launches: list[Launch],
    precision: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    launch = launches[0].model_copy(update={"net_precision": precision})
    caplog.set_level(logging.INFO)

    assert filter_schedule([launch]) == []
    assert launch.id in caplog.text
    assert f"NET precision {precision!r}" in caplog.text


def test_suborbital_excluded(launches: list[Launch], caplog: pytest.LogCaptureFixture) -> None:
    launch = launches[0].model_copy(update={"mission": Mission(orbit=Orbit(abbrev="Sub"))})
    caplog.set_level(logging.INFO)

    assert filter_schedule([launch]) == []
    assert launch.id in caplog.text
    assert "suborbital" in caplog.text


@pytest.mark.parametrize("mission", [None, Mission(orbit=None), Mission(orbit=Orbit(abbrev="N/A"))])
def test_suborbital_filter_keeps_unknown_orbit(
    launches: list[Launch], mission: Mission | None
) -> None:
    launch = launches[0].model_copy(update={"mission": mission})
    assert filter_schedule([launch]) == [launch]


@pytest.mark.parametrize("status", list(LaunchStatus))
def test_schedule_status_filter(launches: list[Launch], status: LaunchStatus) -> None:
    launch = launches[0].model_copy(update={"status": status})
    expected = (
        [launch]
        if status in {LaunchStatus.GO, LaunchStatus.TBC, LaunchStatus.TBD, LaunchStatus.HOLD}
        else []
    )
    assert filter_schedule([launch]) == expected


def test_schedule_fetches_and_writes(
    launches: list[Launch],
    now: datetime,
    tmp_path: Path,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/2.3.0/launches/upcoming/"
        return httpx.Response(
            200,
            json={"next": None, "results": [launch.model_dump(mode="json") for launch in launches]},
        )

    path = tmp_path / "data/schedule.json"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        schedule = write_schedule(client, now, path)

    assert Schedule.model_validate_json(path.read_text()) == schedule
    assert schedule.launches == filter_schedule(launches)
    assert schedule.generated_at == now
    assert schedule.schedule_stale is False


@pytest.mark.parametrize("status", [429, 503])
def test_schedule_source_failure_reuses_cache(
    launches: list[Launch],
    now: datetime,
    tmp_path: Path,
    status: int,
) -> None:
    path = tmp_path / "schedule.json"
    cached = Schedule(generated_at=now, launches=launches[:1])
    path.write_text(cached.model_dump_json())
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, headers={"Retry-After": "3600"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        schedule = write_schedule(client, now, path)

    assert len(requests) == 1
    assert schedule == cached.model_copy(update={"schedule_stale": True})
    assert Schedule.model_validate_json(path.read_text()) == schedule


def test_schedule_source_failure_without_cache(now: datetime, tmp_path: Path) -> None:
    path = tmp_path / "schedule.json"
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(429))) as client,
        pytest.raises(SourceError, match="429"),
    ):
        write_schedule(client, now, path)
    assert not path.exists()
