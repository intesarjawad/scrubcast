import runpy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = runpy.run_path(str(ROOT / "scripts/cold-start-cli.py"))


def test_runs_within_budget_pass() -> None:
    assert SCRIPT["over_budget"]({"cold": 20.0, "warm": 2.0}) == []


def test_each_run_over_budget_names_its_fix() -> None:
    cold, warm = SCRIPT["over_budget"]({"cold": 20.01, "warm": 2.5})
    assert cold.startswith("The cold run took 20.01 s; the budget is 20 s. Next: ")
    assert "optional `pipeline` extra" in cold
    assert warm.startswith("The warm run took 2.50 s; the budget is 2 s. Next: ")
    assert "PYTHONPROFILEIMPORTTIME=1" in warm


def test_cold_and_warm_share_one_new_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = tmp_path / "seen"
    record = f"import os; open({str(seen)!r}, 'a').write(os.environ['UV_CACHE_DIR'] + '\\n')"
    monkeypatch.setitem(SCRIPT["main"].__globals__, "COMMAND", (sys.executable, "-c", record))
    SCRIPT["main"]([])
    cold, warm = seen.read_text().splitlines()
    assert cold == warm
    assert not Path(cold).exists()
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in lines] == ["cold", "warm"]
    assert lines[0].endswith(" s (budget 20 s)")
    assert lines[1].endswith(" s (budget 2 s)")


def test_slow_runs_exit_with_every_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(SCRIPT["main"].__globals__, "COMMAND", (sys.executable, "-c", "pass"))
    monkeypatch.setitem(SCRIPT["main"].__globals__, "BUDGETS_S", {"cold": 0.0, "warm": 0.0})
    with pytest.raises(SystemExit) as raised:
        SCRIPT["main"]([])
    cold, warm = str(raised.value.code).splitlines()
    assert cold.startswith("The cold run took ")
    assert warm.startswith("The warm run took ")


def test_a_failing_command_stops_before_timing_the_warm_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = (sys.executable, "-c", "import sys; sys.exit('no such package')")
    monkeypatch.setitem(SCRIPT["main"].__globals__, "COMMAND", failing)
    with pytest.raises(SystemExit) as raised:
        SCRIPT["main"]([])
    assert str(raised.value.code).endswith(
        "exited 1: no such package\n"
        "Next: run the command by hand to see the full error, fix it, then rerun."
    )


def test_stray_arguments_are_rejected() -> None:
    with pytest.raises(SystemExit) as raised:
        SCRIPT["main"](["scrubcast"])
    assert raised.value.code == 2
