import json
import operator
import re
import shutil
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from scrubcast.models.launch import Launch, Location, Pad
from scrubcast.models.rules import Plot, RuleSet, Tier
from scrubcast.rules.loader import RULES_ROOT, format_param, load_rules, resolve_plot, site_for

FIXTURES = Path(__file__).parents[1] / "fixtures"


def fixture_launches() -> list[Launch]:
    launches: list[Launch] = []
    for path in sorted(FIXTURES.glob("ll2*.json")):
        launches.extend(
            TypeAdapter(list[Launch]).validate_python(json.loads(path.read_text())["results"])
        )
    return launches


@pytest.fixture
def rules_copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(RULES_ROOT, tmp_path / "rules"))


def test_all_rule_files_validate_and_plots_resolve() -> None:
    catalog = load_rules()
    assert len(catalog.rule_sets) == 1
    assert set(catalog.vehicles) == {"falcon9", "falcon-heavy"}
    assert set(catalog.sites) == {"cape", "vandenberg", "starbase", "wallops", "generic"}
    for rule_set in catalog.rule_sets.values():
        assert RuleSet.model_validate_json(rule_set.model_dump_json()) == rule_set
        for rule in rule_set.rules:
            threshold, plot = resolve_plot(rule.plot, rule.proxy, rule.origin)
            assert threshold.value == rule.proxy[rule.plot.threshold_param]
            assert threshold.comparator == rule.proxy[rule.plot.comparator_param]
            assert "{" not in plot.readout_phrase
            assert re.search(r"\d", re.sub(r"\{[a-z_]+\}", "", rule.plot.readout_phrase)) is None
            assert plot.origin == (
                "scrub" if rule.plot.threshold_param in rule.origin else "source"
            )
    for vehicle in catalog.vehicles.values():
        threshold, plot = resolve_plot(vehicle.plot, vehicle.parameters())
        assert threshold.value == vehicle.threshold_mps
        assert plot.readout_phrase == "exceed 13.4 m/s (49.4 m above the pad)"
        assert plot.origin == "source"


def test_florida_pads_share_cape_for_every_vehicle() -> None:
    catalog = load_rules()
    launches = [launch for launch in fixture_launches() if launch.pad.location.id in {12, 27}]
    assert launches
    for launch in launches:
        site = site_for(launch.pad)
        assert site.tier == Tier.A
        assert site.forecast_point is not None
        assert site.forecast_point.point_id == "cape"
    pad = launches[0].pad
    falcon = catalog.rules_for(pad, "Falcon 9")
    assert falcon.vehicle is not None
    assert falcon.vehicle.vehicle_id == "falcon9"
    vulcan = catalog.rules_for(pad, "Vulcan")
    assert vulcan.site.tier == Tier.A
    assert vulcan.vehicle is None
    assert all(not rule.reference_only for rule in vulcan.rules)
    assert (
        next(rule for rule in vulcan.not_evaluable if rule.rule_id == "liftoff_wind").reason
        == "no published limit"
    )


def test_starbase_is_reference_only_without_starship_wind_limit() -> None:
    launch = next(launch for launch in fixture_launches() if launch.pad.location.id == 143)
    selection = load_rules().rules_for(launch.pad, "Starship")
    assert selection.site.tier == Tier.B
    assert selection.vehicle is None
    assert selection.rules
    assert all(rule.reference_only for rule in selection.rules)


def test_tanegashima_falls_back_to_low_confidence_reference_rules() -> None:
    launch = next(launch for launch in fixture_launches() if launch.pad.location.id == 26)
    selection = load_rules().rules_for(launch.pad, launch.rocket_name)
    assert selection.site.tier == Tier.C
    assert selection.site.forecast_point is not None
    assert selection.site.forecast_point.latitude == launch.pad.latitude
    assert selection.site.forecast_point.longitude == launch.pad.longitude
    assert all(rule.reference_only and rule.confidence == "low" for rule in selection.rules)


@pytest.mark.parametrize(("offset", "valid"), [(0, True), (0.01, True), (0.05, False)])
def test_coordinate_override_distance(rules_copy: Path, offset: float, *, valid: bool) -> None:
    path = rules_copy / "sites/cape.json"
    data = json.loads(path.read_text())
    data["coordinate_overrides"] = {"1": {"latitude": offset, "longitude": 0}}
    path.write_text(json.dumps(data))
    pad = Pad(
        id=1,
        name="Pad",
        latitude=0,
        longitude=0,
        location=Location(id=12, name="Cape", timezone_name="UTC"),
    )
    catalog = load_rules(rules_copy)
    if valid:
        assert catalog.site_for(pad).site_id == "cape"
    else:
        with pytest.raises(ValueError, match=r"pad 1.*less than 5 km"):
            catalog.site_for(pad)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("threshold_param", "missing", "threshold parameter"),
        ("comparator_param", "missing", "comparator parameter"),
        ("readout_phrase", "above 1400 m", "literal number"),
        ("readout_phrase", "above {missing} m", "placeholder"),
        ("readout_phrase", "above {thickness_min_m:.1f} m", "literal number"),
        ("readout_phrase", "above {thickness_min_m.real} m", "placeholder"),
        ("readout_phrase", "above {thickness_min_m", "before end of string"),
    ],
)
def test_loader_rejects_invalid_plot(
    rules_copy: Path, field: str, value: str, message: str
) -> None:
    path = rules_copy / "llcc/nasa-std-4010a.json"
    data = json.loads(path.read_text())
    data["rules"][0]["plot"][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValidationError, match=message):
        load_rules(rules_copy)


def test_thickness_edit_changes_shared_comparison_and_readout(rules_copy: Path) -> None:
    before = load_rules(rules_copy).rule_sets["llcc-nasa-std-4010a"].rules[0]
    path = rules_copy / "llcc/nasa-std-4010a.json"
    data = json.loads(path.read_text())
    data["rules"][0]["proxy"]["thickness_min_m"] = 1800
    path.write_text(json.dumps(data))
    after = load_rules(rules_copy).rule_sets["llcc-nasa-std-4010a"].rules[0]
    resolved_before = resolve_plot(before.plot, before.proxy, before.origin)
    resolved_after = resolve_plot(after.plot, after.proxy, after.origin)
    comparisons = {">": operator.gt, ">=": operator.ge, "<=": operator.le}
    assert [
        comparisons[threshold.comparator](1600, threshold.value)
        for threshold, _ in [resolved_before, resolved_after]
    ] == [True, False]
    assert resolved_before[0].value == 1400
    assert resolved_after[0].value == 1800
    assert (
        resolved_before[1].readout_phrase
        == "have a cloud layer 1,400 m or thicker between 0 and -20 °C"
    )
    assert (
        resolved_after[1].readout_phrase
        == "have a cloud layer 1,800 m or thicker between 0 and -20 °C"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (13.41, "13.4"),
        (1400, "1,400"),
        (0.254, "0.254"),
        (-20, "-20"),
        (0, "0"),
        (999.9, "1,000"),
        (1234567, "1,230,000"),
    ],
)
def test_parameter_formatting(value: float, expected: str) -> None:
    assert format_param(value) == expected


def test_plot_can_be_resolved_directly() -> None:
    plot = Plot(
        variable="wind",
        unit="m/s",
        threshold_param="limit",
        comparator_param="comparator",
        readout_phrase="exceed {limit} m/s",
    )
    threshold, readout = resolve_plot(plot, {"limit": 13.41, "comparator": ">"})
    assert threshold.value == 13.41
    assert readout.readout_phrase == "exceed 13.4 m/s"
