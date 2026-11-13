import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from scrubcast.cli import main

ROOT = Path(__file__).parents[2]


def test_every_readme_paragraph_saying_free_says_non_commercial() -> None:
    paragraphs = re.split(r"\n\s*\n", (ROOT / "README.md").read_text(encoding="utf-8"))
    for paragraph in paragraphs:
        if re.search(r"\bfree\b", paragraph, re.IGNORECASE):
            assert "non-commercial" in paragraph, paragraph


def test_recipes_name_only_real_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    listed = re.search(r"\{([a-z,]+)\}", capsys.readouterr().out)
    assert listed is not None
    recipes = (ROOT / "docs/recipes.md").read_text(encoding="utf-8")
    named = set(re.findall(r"\bscrubcast ([a-z]+)\b", recipes))
    assert named
    assert named <= set(listed.group(1).split(","))


def test_readme_member_count_matches_the_fixture_build() -> None:
    latest = json.loads((ROOT / "tests/fixtures/demo/latest.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"against {latest['members_total']} ensemble forecasts" in readme


def test_readme_caption_names_the_fixture_night() -> None:
    storm = ROOT / "tests/fixtures/worst_case/storm-night.json"
    launch = json.loads(storm.read_text(encoding="utf-8"))["launch"]
    start = datetime.fromisoformat(launch["window_start"])
    end = datetime.fromisoformat(launch["window_end"])
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "not a launch" in launch["name"]
    assert (
        "Fixture night, not a launch: the recorded Cape Canaveral ensemble for "
        f"{start:%Y-%m-%d %H:%M} to {end:%H:%M} UTC." in readme
    )
