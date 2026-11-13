import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def _run(tmp_path: Path, **stats: int) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "stats.json"
    path.write_text(json.dumps(stats))
    return subprocess.run(  # noqa: S603
        ["/usr/bin/env", "python", "scripts/mutation-score.py", "--stats", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_score_at_the_floor_passes_and_skipped_mutants_are_excluded(tmp_path: Path) -> None:
    result = _run(tmp_path, killed=80, survived=15, total=110, skipped=10)
    assert result.returncode == 0
    assert result.stdout == "mutation score: 80 / 100 = 80.0%\n"


def test_score_below_the_floor_fails(tmp_path: Path) -> None:
    result = _run(tmp_path, killed=79, survived=21, total=100, skipped=0)
    assert result.returncode == 1
    assert result.stdout == "mutation score: 79 / 100 = 79.0%\n"
    assert "Below the 80% floor." in result.stderr


@pytest.mark.parametrize("total", [0, 5])
def test_no_tested_mutants_fails(tmp_path: Path, total: int) -> None:
    result = _run(tmp_path, killed=0, survived=0, total=total, skipped=5)
    assert result.returncode == 1
    assert "No mutants were tested" in result.stderr
