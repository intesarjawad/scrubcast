import json
import runpy
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from scrubcast.build.contracts import Hindcast, Latest

ROOT = Path(__file__).parents[2]
SCRIPT = runpy.run_path(str(ROOT / "scripts/check-deploy.py"))
PAGES = "https://example.github.io/scrubcast"
GIT = ("git", "-c", "user.name=Test", "-c", "user.email=test@example.com")
NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)
REDEPLOY = "Next: start a deploy with `gh workflow run refresh.yml`"


def _latest(generated_at: datetime) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "generated_at": generated_at.isoformat(),
            "schedule_stale": False,
            "members_total": 82,
            "launches": [],
        }
    )


def _hindcast(generated_at: str, *, summary: list[str] | None = None) -> str:
    return json.dumps({"schema_version": 1, "generated_at": generated_at, "summary": summary or []})


def _clone_with_ledger(tmp_path: Path, files: dict[str, str]) -> Path:
    """Make a clone whose origin has a ledger branch holding the given files."""
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run([*GIT, "init", "-q", "-b", "ledger"], cwd=origin, check=True)  # noqa: S603
    for name, text in files.items():
        (origin / name).write_text(text)
    subprocess.run([*GIT, "add", "-A"], cwd=origin, check=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        [*GIT, "commit", "-q", "--allow-empty", "--no-verify", "-m", "ledger: start"],
        cwd=origin,
        check=True,
    )
    clone = tmp_path / "clone"
    subprocess.run([*GIT, "clone", "-q", str(origin), str(clone)], check=True)  # noqa: S603
    return clone


def _run(
    pages: dict[str, tuple[int, str]],
    clone: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> SystemExit | None:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body = pages.get(request.url.path, (404, "Not Found"))
        return httpx.Response(status, text=body)

    monkeypatch.chdir(clone)
    try:
        SCRIPT["main"]([PAGES], transport=httpx.MockTransport(handler))
    except SystemExit as raised:
        return raised
    return None


def _pages(latest: str, hindcast: str) -> dict[str, tuple[int, str]]:
    return {
        "/scrubcast/data/latest.json": (200, latest),
        "/scrubcast/data/hindcast.json": (200, hindcast),
    }


def test_fresh_build_with_the_ledger_hindcast_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hindcast = _hindcast("2026-11-09T05:52:00+00:00")
    clone = _clone_with_ledger(tmp_path, {"hindcast.json": hindcast})
    generated = datetime.now(UTC) - timedelta(minutes=20)
    assert _run(_pages(_latest(generated), hindcast), clone, monkeypatch) is None
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("ok: latest.json is 20 min old")
    assert (
        lines[1] == "ok: hindcast.json matches the ledger (generated at 2026-11-09T05:52:00+00:00)"
    )


def test_reformatted_copy_of_the_ledger_hindcast_still_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _hindcast("2026-11-09T05:52:00Z", summary=["n=3"])
    published = json.dumps(json.loads(ledger), indent=2)
    clone = _clone_with_ledger(tmp_path, {"hindcast.json": ledger})
    latest = _latest(datetime.now(UTC))
    assert _run(_pages(latest, published), clone, monkeypatch) is None


def test_stale_mismatched_and_missing_are_all_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = _clone_with_ledger(
        tmp_path, {"hindcast.json": _hindcast("2026-11-09T05:52:00+00:00", summary=["n=4"])}
    )
    stale = _latest(datetime.now(UTC) - timedelta(hours=3))
    published = _hindcast("2026-11-08T05:51:00+00:00", summary=["n=3"])
    raised = _run(_pages(stale, published), clone, monkeypatch)
    assert raised is not None
    stale_line, mismatch_line = str(raised.code).splitlines()
    assert "h ago; the limit is 2 h." in stale_line
    assert REDEPLOY in stale_line
    assert mismatch_line == (
        "Pages serves the hindcast generated at 2026-11-08T05:51:00+00:00; the ledger has the "
        "one generated at 2026-11-09T05:52:00+00:00. Next: start a deploy with "
        "`gh workflow run refresh.yml` (it also runs every hour at minute 17), wait for it to "
        "finish, then rerun this check."
    )


def test_same_stamp_with_different_contents_is_a_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stamp = "2026-11-09T05:52:00+00:00"
    clone = _clone_with_ledger(tmp_path, {"hindcast.json": _hindcast(stamp, summary=["n=4"])})
    pages = _pages(_latest(datetime.now(UTC)), _hindcast(stamp, summary=["n=3"]))
    raised = _run(pages, clone, monkeypatch)
    assert raised is not None
    assert str(raised.code).startswith(f"Pages serves the hindcast generated at {stamp};")


def test_missing_published_files_name_the_status_and_the_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = _clone_with_ledger(tmp_path, {"hindcast.json": _hindcast("2026-11-09T05:52:00Z")})
    raised = _run({}, clone, monkeypatch)
    assert raised is not None
    lines = str(raised.code).splitlines()
    assert lines[0].startswith(f"{PAGES}/data/latest.json returned HTTP 404. {REDEPLOY}")
    assert lines[1].startswith(f"{PAGES}/data/hindcast.json returned HTTP 404. {REDEPLOY}")


def test_a_ledger_without_hindcast_points_to_the_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = _clone_with_ledger(tmp_path, {})
    pages = _pages(_latest(datetime.now(UTC)), _hindcast("2026-11-09T05:52:00Z"))
    raised = _run(pages, clone, monkeypatch)
    assert raised is not None
    assert str(raised.code) == (
        "The ledger branch has no hindcast.json yet. Next: run `gh workflow run audit.yml`, "
        "wait for its ledger commit, then rerun this check."
    )


def test_a_clone_without_the_ledger_branch_says_where_to_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run([*GIT, "init", "-q", str(tmp_path)], check=True)  # noqa: S603
    pages = _pages(_latest(datetime.now(UTC)), _hindcast("2026-11-09T05:52:00Z"))
    raised = _run(pages, tmp_path, monkeypatch)
    assert raised is not None
    assert str(raised.code).startswith("`git fetch origin ledger` failed: ")
    assert str(raised.code).endswith(
        "Next: run this from a clone whose origin has the ledger branch."
    )


def test_a_page_that_breaks_the_contract_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hindcast = _hindcast("2026-11-09T05:52:00Z")
    clone = _clone_with_ledger(tmp_path, {"hindcast.json": hindcast})
    raised = _run(_pages("<!doctype html>", hindcast), clone, monkeypatch)
    assert raised is not None
    assert str(raised.code).startswith(
        f"{PAGES}/data/latest.json does not match the published contract:"
    )


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(0), "latest.json is 0 min old"),
        (timedelta(hours=2), "latest.json is 120 min old"),
    ],
)
def test_freshness_accepts_up_to_two_hours(age: timedelta, expected: str) -> None:
    latest = Latest.model_validate_json(_latest(NOW - age))
    assert SCRIPT["freshness"](latest, NOW).startswith(expected)


def test_freshness_rejects_one_second_past_two_hours() -> None:
    latest = Latest.model_validate_json(_latest(NOW - timedelta(hours=2, seconds=1)))
    with pytest.raises(SCRIPT["DeployError"], match=r"2\.0 h ago; the limit is 2 h"):
        SCRIPT["freshness"](latest, NOW)


def test_future_dated_build_points_to_the_clock() -> None:
    latest = Latest.model_validate_json(_latest(NOW + timedelta(seconds=1)))
    with pytest.raises(SCRIPT["DeployError"]) as raised:
        SCRIPT["freshness"](latest, NOW)
    assert str(raised.value) == (
        "latest.json was generated at 2026-11-09T12:00:01+00:00, after this machine's time "
        "2026-11-09T12:00:00+00:00. Next: correct this machine's clock, then rerun this check."
    )


def test_same_hindcast_compares_parsed_values() -> None:
    ledger = Hindcast.model_validate_json(_hindcast("2026-11-09T05:52:00Z"))
    published = Hindcast.model_validate_json(_hindcast("2026-11-09T05:52:00+00:00"))
    assert SCRIPT["same_hindcast"](published, ledger).startswith("hindcast.json matches")


@pytest.mark.parametrize("argv", [[], ["example.github.io"], [PAGES, "extra"]])
def test_arguments_need_exactly_one_url(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        SCRIPT["main"](argv)
    assert raised.value.code == 2


def test_an_unreachable_site_names_the_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        message = "Connection refused"
        raise httpx.ConnectError(message, request=request)

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as raised:
        SCRIPT["main"]([PAGES], transport=httpx.MockTransport(refuse))
    assert str(raised.value.code).splitlines()[0] == (
        f"Could not fetch {PAGES}/data/latest.json: Connection refused. "
        "Next: check the URL, then rerun."
    )
