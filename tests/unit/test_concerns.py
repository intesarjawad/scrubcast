import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from scrubcast.models.launch import Launch, parse_concerns
from scrubcast.rules.concerns import normalise_concern
from scrubcast.rules.loader import load_rules

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_every_fixture_concern_maps() -> None:
    catalog = load_rules()
    names: set[str] = set()
    for path in sorted(FIXTURES.glob("ll2*.json")):
        launches = TypeAdapter(list[Launch]).validate_python(
            json.loads(path.read_text())["results"]
        )
        for launch in launches:
            names.update(parse_concerns(launch.weather_concerns))
    assert names
    unmapped = sorted(name for name in names if catalog.normalise_concern(name).rule_id is None)
    assert not unmapped, f"Unmapped official concerns: {unmapped}"


@pytest.mark.parametrize(
    ("name", "rule_id"),
    [
        ("  cUmUlUs ClOuD RuLe  ", "cumulus"),
        ("Anvil Rules", "anvil"),
        ("Surface Electric Field Rule", "surface_electric_fields"),
        ("Ascent Corridor Recovery", "booster_recovery"),
        ("Lightning Rule", "lightning"),
        ("Unknown Official Concern ", None),
    ],
)
def test_normalisation_preserves_official_text(name: str, rule_id: str | None) -> None:
    match = normalise_concern(name)
    assert match.name == name
    assert match.rule_id == rule_id
