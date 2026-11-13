import json
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest

from scrubcast.rules.loader import load_rules

ROOT = Path(__file__).parents[2]
SCRIPT = runpy.run_path(str(ROOT / "scripts/gen-docs.py"))


def test_committed_page_matches_the_rule_files() -> None:
    result = subprocess.run(
        ["/usr/bin/env", "python", "scripts/gen-docs.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_every_rule_and_site_is_documented() -> None:
    catalog = load_rules()
    page = SCRIPT["render"](catalog)
    ids = [
        rule.rule_id
        for rule_set in catalog.rule_sets.values()
        for rule in [*rule_set.rules, *rule_set.not_evaluable]
    ]
    for identifier in [*ids, "liftoff_wind", *catalog.sites]:
        assert f"`{identifier}`" in page, identifier
    assert "| `cloud_cover_min_pct` | 50 | Scrubcast |" in page
    assert "| `thickness_min_m` | 1400 | Published rule |" in page
    assert "| Falcon 9 | `>` 13.41 m/s | 49.4 m | sustained |" in page


def test_a_changed_threshold_changes_the_page(tmp_path: Path) -> None:
    rules = shutil.copytree(ROOT / "rules", tmp_path / "rules")
    vehicle = rules / "vehicles/falcon9.json"
    document = json.loads(vehicle.read_text())
    document["threshold_mps"] = 12.5
    vehicle.write_text(json.dumps(document))
    page = SCRIPT["render"](load_rules(rules))
    assert "| Falcon 9 | `>` 12.5 m/s |" in page
    assert "exceed 12.5 m/s (49.4 m above the pad)" in page


def test_check_mode_names_the_command_when_the_page_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = tmp_path / "docs/rules.md"
    stale.parent.mkdir()
    stale.write_text("# Rules\n")
    monkeypatch.setitem(SCRIPT["main"].__globals__, "ROOT", tmp_path)
    monkeypatch.setitem(SCRIPT["main"].__globals__, "OUTPUT", stale)
    monkeypatch.setattr("sys.argv", ["gen-docs.py", "--check"])
    with pytest.raises(SystemExit) as raised:
        SCRIPT["main"]()
    assert str(raised.value) == (
        "docs/rules.md does not match the rule files. "
        "Run `uv run python scripts/gen-docs.py` and commit the result."
    )
    assert stale.read_text() == "# Rules\n"


def test_write_mode_regenerates_a_missing_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "rules.md"
    monkeypatch.setitem(SCRIPT["main"].__globals__, "OUTPUT", output)
    monkeypatch.setattr("sys.argv", ["gen-docs.py"])
    SCRIPT["main"]()
    assert output.read_text() == (ROOT / "docs/rules.md").read_text()
