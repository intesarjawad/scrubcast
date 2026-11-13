import re
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from scrubcast.cli import main

SUBCOMMANDS = (
    "schedule",
    "weather",
    "assess",
    "build",
    "audit",
    "backfill",
    "hindcast",
    "next",
    "collect",
)


def test_installed_cli_help() -> None:
    result = subprocess.run(
        ["/usr/bin/env", "scrubcast", "--help"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    assert "usage: scrubcast" in result.stdout
    assert "--help" in result.stdout
    assert result.stderr == ""


def test_help_lists_exactly_the_published_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])

    assert stopped.value.code == 0
    listed = re.search(r"\{([a-z,]+)\}", capsys.readouterr().out)
    assert listed is not None
    assert sorted(listed.group(1).split(",")) == sorted(SUBCOMMANDS)


@pytest.mark.parametrize("subcommand", SUBCOMMANDS)
def test_subcommand_help_describes_its_own_usage(
    subcommand: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main([subcommand, "--help"])

    assert stopped.value.code == 0
    output = capsys.readouterr()
    assert f"usage: scrubcast {subcommand}" in output.out
    assert output.err == ""


@pytest.mark.parametrize(
    "arguments",
    [
        ["launch"],
        ["audit", "--unknown"],
        ["next", "--count", "x"],
        ["next", "--count", "0"],
        ["backfill", "--start", "2026-13-01"],
    ],
)
def test_invalid_arguments_exit_with_usage_error(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(arguments)

    assert stopped.value.code == 2
    assert "usage: scrubcast" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["weather", "assess"])
def test_missing_schedule_names_the_prerequisite(
    command: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as stopped:
        main([command])
    assert stopped.value.code == 1
    assert capsys.readouterr().err == (
        "No schedule found. Run `scrubcast schedule` or `scrubcast build` first.\n"
    )
