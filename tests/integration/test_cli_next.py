from pathlib import Path

import pytest

from scrubcast.cli import main

ROOT = Path(__file__).parents[2]
GOLDEN = ROOT / "tests/golden"


@pytest.mark.parametrize("columns", [60, 80, 120])
def test_next_fixtures_matches_golden(
    columns: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("scrubcast.cli.FIXTURES", ROOT / "tests/fixtures")
    monkeypatch.setenv("COLUMNS", str(columns))
    monkeypatch.setenv("NO_COLOR", "1")
    main(["next", "--fixtures"])
    captured = capsys.readouterr()
    assert captured.out == (GOLDEN / f"board-{columns}.txt").read_text()
    assert all(len(line) <= columns for line in captured.out.splitlines())
    assert captured.err == ""
