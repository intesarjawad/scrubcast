from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic import AwareDatetime, BaseModel

from scrubcast import cli
from scrubcast.audit.outcomes import AttemptOutcome
from scrubcast.models.assessment import LedgerRow
from scrubcast.models.launch import LaunchDetailed, LaunchStatus
from scrubcast.sources.errors import SourceError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

FIXTURES = Path(__file__).parents[1] / "fixtures"


class Scenario(BaseModel):
    ledger: list[LedgerRow]
    launches: list[LaunchDetailed]
    now: AwareDatetime


def _scenario(name: str) -> Scenario:
    return Scenario.model_validate_json((FIXTURES / f"outcomes/{name}.json").read_text())


def _write_ledger(root: Path, rows: Sequence[LedgerRow]) -> None:
    (root / "ledger").mkdir()
    (root / "ledger/2026-11.jsonl").write_text(
        "".join(row.model_dump_json() + "\n" for row in rows)
    )


def _page(launches: Sequence[LaunchDetailed], next_url: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={"next": next_url, "results": [launch.model_dump(mode="json") for launch in launches]},
    )


def _source(
    previous: Sequence[LaunchDetailed],
    upcoming: Sequence[LaunchDetailed],
    requests: list[httpx.Request],
) -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _page(previous if "/previous/" in request.url.path else upcoming)

    return respond


def _saved(root: Path) -> list[AttemptOutcome]:
    return [
        AttemptOutcome.model_validate_json(line)
        for line in (root / "ledger/outcomes.jsonl").read_text().splitlines()
    ]


def test_outcomes_come_from_one_previous_and_one_upcoming_request(tmp_path: Path) -> None:
    case = _scenario("launched_later")
    _write_ledger(tmp_path, case.ledger)
    requests: list[httpx.Request] = []

    transport = httpx.MockTransport(_source(case.launches, [], requests))
    with httpx.Client(transport=transport) as client:
        count = cli.record_outcomes(client, tmp_path, case.now)

    assert count == 1
    previous, upcoming = requests
    assert previous.url.path.endswith("/launches/previous/")
    assert upcoming.url.path.endswith("/launches/upcoming/")
    assert previous.url.params["net__gte"] == (case.ledger[0].net - timedelta(days=1)).isoformat()
    for request in requests:
        assert request.url.params["mode"] == "detailed"
        assert request.url.params["limit"] == "100"
        assert "location__ids" not in request.url.params
    (saved,) = _saved(tmp_path)
    assert saved.outcome == "launched_later"
    assert saved.net_now == case.launches[0].net
    assert saved.audited_at == case.now


def test_slipped_launch_is_found_in_the_upcoming_page(tmp_path: Path) -> None:
    case = _scenario("new_t0")
    _write_ledger(tmp_path, case.ledger)

    transport = httpx.MockTransport(_source([], case.launches, []))
    with httpx.Client(transport=transport) as client:
        cli.record_outcomes(client, tmp_path, case.now)

    assert [saved.outcome for saved in _saved(tmp_path)] == ["new_t0_pending"]


def test_launch_in_neither_page_is_recorded_as_unknown(tmp_path: Path) -> None:
    case = _scenario("launched")
    _write_ledger(tmp_path, case.ledger)

    with httpx.Client(transport=httpx.MockTransport(_source([], [], []))) as client:
        cli.record_outcomes(client, tmp_path, case.now)

    (saved,) = _saved(tmp_path)
    assert saved.outcome == "unknown"
    assert saved.status_now is None


def test_only_the_first_page_of_each_list_is_requested(tmp_path: Path) -> None:
    case = _scenario("launched")
    _write_ledger(tmp_path, case.ledger)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _page(case.launches, str(request.url.copy_add_param("offset", "100")))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        cli.record_outcomes(client, tmp_path, case.now)

    assert len(requests) == 2
    assert [saved.outcome for saved in _saved(tmp_path)] == ["launched"]


def test_oldest_open_attempt_sets_the_previous_request_start(tmp_path: Path) -> None:
    case = _scenario("two_attempts")
    _write_ledger(tmp_path, case.ledger)
    requests: list[httpx.Request] = []

    transport = httpx.MockTransport(_source(case.launches, [], requests))
    with httpx.Client(transport=transport) as client:
        count = cli.record_outcomes(client, tmp_path, case.now)

    oldest = min(row.net for row in case.ledger)
    assert count == len(_saved(tmp_path)) == 2
    assert requests[0].url.params["net__gte"] == (oldest - timedelta(days=1)).isoformat()


@pytest.mark.parametrize(
    "elapsed", [timedelta(hours=6) - timedelta(seconds=1), timedelta(days=7, hours=6)]
)
def test_no_request_is_sent_when_no_attempt_is_open(tmp_path: Path, elapsed: timedelta) -> None:
    case = _scenario("launched")
    _write_ledger(tmp_path, case.ledger)
    row = case.ledger[0]
    now = max(row.net, row.window_end) + timedelta(hours=1) + elapsed
    requests: list[httpx.Request] = []

    with httpx.Client(transport=httpx.MockTransport(_source([], [], requests))) as client:
        count = cli.record_outcomes(client, tmp_path, now)

    assert count == 0
    assert requests == []
    assert not (tmp_path / "ledger/outcomes.jsonl").exists()


def test_frozen_outcomes_survive_a_later_audit(tmp_path: Path) -> None:
    case = _scenario("launched")
    _write_ledger(tmp_path, case.ledger)
    frozen = AttemptOutcome(
        attempt_id="earlier-launch@2026-01-01T00:00:00Z",
        attempt_net=datetime(2026, 1, 1, tzinfo=UTC),
        outcome="hold",
        net_now=None,
        status_now=LaunchStatus.HOLD,
        note=None,
        audited_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    (tmp_path / "ledger/outcomes.jsonl").write_text(frozen.model_dump_json() + "\n")

    with httpx.Client(transport=httpx.MockTransport(_source(case.launches, [], []))) as client:
        cli.record_outcomes(client, tmp_path, case.now)

    assert [saved.outcome for saved in _saved(tmp_path)] == ["hold", "launched"]
    assert _saved(tmp_path)[0] == frozen


def test_source_failure_keeps_the_saved_outcomes(tmp_path: Path) -> None:
    case = _scenario("launched")
    _write_ledger(tmp_path, case.ledger)
    path = tmp_path / "ledger/outcomes.jsonl"
    path.write_text("saved\n")
    transport = httpx.MockTransport(lambda _: httpx.Response(503))

    with httpx.Client(transport=transport) as client, pytest.raises(SourceError):
        cli.record_outcomes(client, tmp_path, case.now)

    assert path.read_text() == "saved\n"


def _open_attempt(tmp_path: Path) -> LaunchDetailed:
    case = _scenario("launched")
    net = datetime.now(UTC) - timedelta(days=1)
    row = LedgerRow.model_validate(
        case.ledger[0].model_dump()
        | {
            "run_at": net - timedelta(hours=24),
            "net": net,
            "window_end": net + timedelta(hours=2),
        }
    )
    _write_ledger(tmp_path, [row])
    return case.launches[0].model_copy(update={"net": net})


def test_audit_command_reports_the_audited_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    launch = _open_attempt(tmp_path)
    transport = httpx.MockTransport(_source([launch], [], []))
    monkeypatch.setattr(httpx, "Client", partial(httpx.Client, transport=transport))

    cli.main(["audit", "--data-dir", str(tmp_path)])

    assert capsys.readouterr().out == (
        f"Audited attempts n=1; outcomes: {tmp_path / 'ledger/outcomes.jsonl'}\n"
    )
    assert [saved.outcome for saved in _saved(tmp_path)] == ["launched"]


def test_audit_command_without_a_ledger_sends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    requests: list[httpx.Request] = []
    transport = httpx.MockTransport(_source([], [], requests))
    monkeypatch.setattr(httpx, "Client", partial(httpx.Client, transport=transport))

    cli.main(["audit", "--data-dir", str(tmp_path)])

    assert requests == []
    assert capsys.readouterr().out.startswith("Audited attempts n=0;")


def test_audit_command_exits_with_the_source_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _open_attempt(tmp_path)
    transport = httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "60"}))
    monkeypatch.setattr(httpx, "Client", partial(httpx.Client, transport=transport))

    with pytest.raises(SystemExit) as stopped:
        cli.main(["audit", "--data-dir", str(tmp_path)])

    assert stopped.value.code == 1
    assert "429" in capsys.readouterr().err
    assert not (tmp_path / "ledger/outcomes.jsonl").exists()
