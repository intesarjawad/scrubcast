import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from scrubcast.budget.report import main

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).parents[2]


def test_budget_report_matches_fixture_month_golden() -> None:
    result = subprocess.run(
        [
            "/usr/bin/env",
            "python",
            "scripts/budget-report.py",
            "--month",
            "2026-11",
            "--ledger",
            "tests/fixtures/budget",
            "--actions-file",
            "tests/fixtures/budget/actions.json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert result.stdout == (ROOT / "tests/golden/budget-report.txt").read_text()
    assert result.stderr == ""


def test_budget_report_main_prints_the_golden_in_process(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "budget-report",
            "--month",
            "2026-11",
            "--ledger",
            "tests/fixtures/budget",
            "--actions-file",
            "tests/fixtures/budget/actions.json",
        ],
    )
    main()
    captured = capsys.readouterr()
    assert captured.out == (ROOT / "tests/golden/budget-report.txt").read_text()
    assert captured.err == ""
