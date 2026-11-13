import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter

from scrubcast.models.launch import Location, Pad
from scrubcast.models.weather import parse_ensemble
from scrubcast.rules.engine import assess_hour
from scrubcast.rules.loader import RULES_ROOT, load_rules
from scrubcast.rules.profile import Profile

if TYPE_CHECKING:
    from scrubcast.models.rules import RuleSelection

FIXTURES = Path(__file__).parents[1] / "fixtures"
GOLDEN = Path(__file__).parents[1] / "golden" / "hour_cape.json"


def selection(
    rocket: str = "Falcon 9", location: int = 12, root: Path = RULES_ROOT
) -> RuleSelection:
    pad = Pad(
        id=1,
        name="Pad",
        latitude=28.5,
        longitude=-80.75,
        location=Location(id=location, name="Site", timezone_name="UTC"),
    )
    return load_rules(root).rules_for(pad, rocket)


def profile(wind: float = 0, precipitation: float = 0, cloud: float = 0) -> Profile:
    return Profile(
        values={
            "wind_speed_10m": wind,
            "wind_speed_100m": wind,
            "cape": 1500,
            "precipitation": precipitation,
            "cloud_cover_high": cloud,
        },
        z_m=np.array([0, 1500, 3000]),
        t_c=np.array([10, 0, -10]),
        cloud_pct=np.array([cloud, cloud, cloud]),
    )


@pytest.fixture
def cape_profiles() -> list[Profile]:
    payload = TypeAdapter(dict[str, object]).validate_json(
        (FIXTURES / "open_meteo_cape.json").read_text()
    )
    series = parse_ensemble(payload)[0]
    return [Profile.from_series(series, member=member, hour=0) for member in range(series.members)]


def test_cape_hour_zero_golden(cape_profiles: list[Profile]) -> None:
    result = assess_hour(cape_profiles, selection())
    actual = {
        "members": result.members,
        "union_violating_members": result.union_violating_members,
        "union_risk_fraction": result.union_risk_fraction,
        "rules": {
            key: {
                "risk_fraction": rule.risk_fraction,
                "evaluable_members": rule.evaluable_members,
                "violating_members": rule.violating_members,
                "member_results": [asdict(member) for member in rule.member_results],
            }
            for key, rule in result.rules.items()
        },
        "not_evaluable": [rule.model_dump(mode="json") for rule in result.not_evaluable],
    }
    assert actual == json.loads(GOLDEN.read_text())


@given(
    st.lists(
        st.tuples(
            st.floats(min_value=0, max_value=30),
            st.floats(min_value=0, max_value=10),
            st.floats(min_value=0, max_value=100),
        ),
        min_size=1,
        max_size=30,
    )
)
def test_fully_evaluable_union_bounds(members: list[tuple[float, float, float]]) -> None:
    selected = selection()
    profiles = [profile(*member) for member in members]
    result = assess_hour(profiles, selected)
    union = result.union_risk_fraction
    assert union is not None
    assert 0 <= union <= 1
    for rule_id, rule in result.rules.items():
        assert rule.evaluable_members == len(profiles)
        assert rule.risk_fraction is not None
        assert 0 <= rule.risk_fraction <= 1
        eligible = rule_id == "liftoff_wind" or any(
            item.rule_id == rule_id and item.confidence in {"direct", "medium"}
            for item in selected.rules
        )
        if eligible:
            assert union >= rule.risk_fraction


@given(st.permutations(range(5)))
def test_member_order_invariance(order: list[int]) -> None:
    profiles = [profile(), profile(20), profile(precipitation=3, cloud=80), Profile(), profile(5)]
    expected = assess_hour(profiles, selection())
    result = assess_hour([profiles[index] for index in order], selection())
    assert result.union_risk_fraction == expected.union_risk_fraction
    assert result.union_violating_members == expected.union_violating_members
    assert result.members == expected.members
    for rule_id, rule in result.rules.items():
        original = expected.rules[rule_id]
        assert rule.risk_fraction == original.risk_fraction
        assert rule.evaluable_members == original.evaluable_members
        assert rule.member_results == tuple(original.member_results[index] for index in order)


def test_mixed_evaluability_preserves_both_denominators() -> None:
    result = assess_hour([profile(20), Profile()], selection())
    wind = result.rules["liftoff_wind"]
    assert wind.risk_fraction == 1
    assert wind.evaluable_members == 1
    assert [member.verdict for member in wind.member_results] == ["violated", "not_evaluable"]
    assert result.members == 2
    assert result.union_violating_members == 1
    assert result.union_risk_fraction == 0.5


@pytest.mark.parametrize("profiles", [[], [Profile()]])
def test_no_evaluable_members(profiles: list[Profile]) -> None:
    result = assess_hour(profiles, selection())
    assert result.union_risk_fraction == (0 if profiles else None)
    assert all(rule.risk_fraction is None for rule in result.rules.values())
    assert all(rule.evaluable_members == 0 for rule in result.rules.values())


def test_reference_only_rules_never_enter_union() -> None:
    result = assess_hour([profile(precipitation=3, cloud=80)], selection("Starship", 143))
    assert result.rules["thick_cloud"].risk_fraction == 1
    assert result.union_risk_fraction == 0
    assert any(
        rule.rule_id == "liftoff_wind" and rule.reason == "no published limit"
        for rule in result.not_evaluable
    )


def test_reference_site_still_uses_vehicle_wind() -> None:
    result = assess_hour([profile(20, 3, 80)], selection(location=143))
    assert result.rules["liftoff_wind"].risk_fraction == 1
    assert result.union_risk_fraction == 1


def test_low_confidence_and_correlated_rules() -> None:
    selected = selection("Unknown")
    assert assess_hour([profile(precipitation=1)], selected).union_risk_fraction == 0
    result = assess_hour([profile(precipitation=3, cloud=80), profile()], selected)
    assert result.rules["thick_cloud"].risk_fraction == 0.5
    assert result.rules["disturbed_weather"].risk_fraction == 0.5
    assert result.union_risk_fraction == 0.5


def test_unknown_proxy_fails_with_kind() -> None:
    selected = selection()
    selected.rules[0] = selected.rules[0].model_copy(
        update={"proxy": {**selected.rules[0].proxy, "kind": "unknown"}}
    )
    with pytest.raises(ValueError, match="unknown"):
        assess_hour([profile()], selected)


def test_vehicle_peak_measure_is_passed_to_proxy() -> None:
    selected = selection()
    assert selected.vehicle is not None
    selected.vehicle = selected.vehicle.model_copy(update={"measure": "peak"})
    result = assess_hour(
        [replace(profile(), values={**profile().values, "wind_gusts_10m": 20})], selected
    )
    assert result.rules["liftoff_wind"].risk_fraction == 1
    assert result.rules["liftoff_wind"].member_results[0].value == 20


@pytest.mark.parametrize(
    ("rule_id", "parameter", "replacement"),
    [
        ("thick_cloud", "cloud_cover_min_pct", 101),
        ("thick_cloud", "thickness_min_m", 10000),
        ("thick_cloud", "t_min_c", 1),
        ("thick_cloud", "t_max_c", -100),
        ("cumulus", "cape_min_jkg", 2000),
        ("cumulus", "precip_min_mmh", 10),
        ("cumulus", "cloud_cover_min_pct", 101),
        ("cumulus", "t_max_c", -100),
        ("anvil", "cape_min_jkg", 2000),
        ("anvil", "precip_min_mmh", 10),
        ("anvil", "cloud_cover_high_min_pct", 101),
        ("disturbed_weather", "precip_min_mmh", 10),
        ("disturbed_weather", "cloud_cover_min_pct", 101),
        ("disturbed_weather", "t_max_c", -100),
        ("flight_through_precip", "precip_min_mmh", 10),
        ("liftoff_wind", "threshold_mps", 100),
        ("liftoff_wind", "reference_height_m", 100),
    ],
)
def test_json_numeric_parameters_change_storm_golden(
    tmp_path: Path, rule_id: str, parameter: str, replacement: float
) -> None:
    root = Path(shutil.copytree(RULES_ROOT, tmp_path / "rules"))
    profiles = [profile(20, 3, 80)]
    expected = assess_hour(profiles, selection())
    assert all(rule.risk_fraction == 1 for rule in expected.rules.values())
    if rule_id == "liftoff_wind":
        path = root / "vehicles" / "falcon9.json"
        vehicle = load_rules(root).vehicles["falcon9"]
        path.write_text(
            vehicle.model_copy(update={parameter: float(replacement)}).model_dump_json()
        )
    else:
        rule_set = load_rules(root).rule_sets["llcc-nasa-std-4010a"]
        rule = next(rule for rule in rule_set.rules if rule.rule_id == rule_id)
        rule.proxy[parameter] = float(replacement)
        path = next((root / "llcc").glob("*.json"))
        path.write_text(rule_set.model_dump_json())
    changed = assess_hour(profiles, selection(root=root))
    assert changed.rules[rule_id] != expected.rules[rule_id]
