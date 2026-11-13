import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from scrubcast import messages
from scrubcast.build.contracts import Latest
from scrubcast.terminal.board import BoardOptions, render_board, run_next

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests/fixtures/demo/latest.json"


def _latest() -> Latest:
    return Latest.model_validate_json(FIXTURE.read_text())


def test_messages_name_a_state_and_a_next_action() -> None:
    for message in (
        messages.NETWORK_FAILURE,
        messages.NOT_PUBLISHED,
        messages.UNREADABLE_FILE,
        messages.OLD_DATA,
        messages.UNSUPPORTED_SCHEMA,
        messages.INVALID_DATA,
        messages.STALE,
        messages.NO_LAUNCHES,
    ):
        assert message.what.strip()
        assert message.next.strip()


def test_render_board_uses_pad_local_and_utc_times() -> None:
    text = render_board(_latest(), columns=80)
    assert "Members: 82" in text
    assert "NET 2026-11-06 16:46 PST (2026-11-07 00:46 UTC)" in text
    assert "Official: not published" in text
    assert "Worst rule: No rule above 5%" in text


def test_render_board_wraps_to_columns() -> None:
    latest = _latest()
    launch = latest.launches[0].model_copy(deep=True)
    launch.name = "Falcon 9 Block 5 | A very long mission name that must wrap"
    launch.pad.name = "Space Launch Complex 4E with an unusually long pad name"
    latest.launches = [launch]
    for columns in (60, 80, 120):
        text = render_board(latest, columns=columns)
        assert all(len(line) <= columns for line in text.splitlines())


def test_render_board_falls_back_to_utc_for_unknown_zone() -> None:
    latest = _latest()
    launch = latest.launches[0].model_copy(deep=True)
    launch.pad.location.timezone_name = "Not/AZone"
    latest.launches = [launch]
    text = render_board(latest, columns=80)
    assert "NET 2026-11-07 00:46 UTC (2026-11-07 00:46 UTC)" in text


def test_render_board_limits_count_and_sorts() -> None:
    latest = _latest()
    first = latest.launches[0].model_copy(deep=True)
    first.id = "a"
    first.name = "First"
    first.net = first.net.replace(day=8)
    second = first.model_copy(deep=True)
    second.id = "b"
    second.name = "Second"
    second.net = first.net.replace(day=7)
    latest.launches = [first, second]
    text = render_board(latest, columns=80, count=1)
    assert "1. Second" in text
    assert "First" not in text


def test_run_next_network_failure(capsys: pytest.CaptureFixture[str]) -> None:
    def fail(_request: httpx.Request) -> httpx.Response:
        msg = "offline"
        raise httpx.ConnectError(msg)

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        code = run_next(BoardOptions(data_url="https://example.org/latest.json"), client=client)
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == (
        messages.NETWORK_FAILURE.render(url="https://example.org/latest.json", reason="offline")
        + "\n"
    )


def test_run_next_names_the_http_status(capsys: pytest.CaptureFixture[str]) -> None:
    def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(unavailable)) as client:
        code = run_next(BoardOptions(data_url="https://example.org/latest.json"), client=client)
    assert code == 1
    assert capsys.readouterr().err.startswith(
        "Could not reach https://example.org/latest.json: HTTP 503 Service Unavailable."
    )


def test_run_next_explains_an_undeployed_site(capsys: pytest.CaptureFixture[str]) -> None:
    def missing(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(missing)) as client:
        code = run_next(BoardOptions(data_url="https://example.org/latest.json"), client=client)
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == (
        messages.NOT_PUBLISHED.render(url="https://example.org/latest.json") + "\n"
    )
    assert "`scrubcast build`" in captured.err
    assert "--data-url site/public/data/latest.json" in captured.err


def test_run_next_reads_a_local_build(capsys: pytest.CaptureFixture[str]) -> None:
    for data_url in (str(FIXTURE), FIXTURE.as_uri()):
        code = run_next(
            BoardOptions(data_url=data_url),
            columns=80,
            now=_latest().generated_at,
        )
        assert code == 0
        assert capsys.readouterr().out == render_board(_latest(), columns=80)


def test_run_next_missing_local_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "latest.json"
    code = run_next(BoardOptions(data_url=str(path)))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.startswith(f"Could not read {path}: ")
    assert "`scrubcast build`" in captured.err


def test_run_next_warns_when_data_is_old(capsys: pytest.CaptureFixture[str]) -> None:
    built = _latest().generated_at
    code = run_next(BoardOptions(data_url=str(FIXTURE)), columns=80, now=built + timedelta(hours=4))
    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    assert lines[0] == messages.OLD_DATA.render(hours=4, built=f"{built:%Y-%m-%d %H:%M}")
    assert lines[1] == "Scrubcast launch weather"
    code = run_next(BoardOptions(data_url=str(FIXTURE)), columns=80, now=built + timedelta(hours=3))
    assert code == 0
    assert capsys.readouterr().out.splitlines()[0] == "Scrubcast launch weather"


def test_run_next_unsupported_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "latest.json"
    path.write_text(json.dumps({"schema_version": 2}))
    code = run_next(BoardOptions(fixtures=True, fixture_path=path))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == messages.UNSUPPORTED_SCHEMA.render(version=2, supported=1) + "\n"


def test_run_next_stale_warning_before_board(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.loads(FIXTURE.read_text())
    payload["schedule_stale"] = True
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(payload))
    code = run_next(BoardOptions(fixtures=True, fixture_path=path), columns=80)
    captured = capsys.readouterr()
    assert code == 0
    lines = captured.out.splitlines()
    assert lines[0] == messages.STALE.render(
        launch_url="https://ll.thespacedevs.com/2.4.0/launches/54d471e8-695c-4fa7-a3cf-dbd8b389e8ae/"
    )
    assert lines[1] == "Scrubcast launch weather"


def test_run_next_no_launches(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = json.loads(FIXTURE.read_text())
    payload["launches"] = []
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(payload))
    code = run_next(BoardOptions(fixtures=True, fixture_path=path), columns=80)
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == messages.NO_LAUNCHES.render() + "\n"
