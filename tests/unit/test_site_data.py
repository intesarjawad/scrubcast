import json
from datetime import timedelta
from pathlib import Path

import pytest

from scrubcast.build.contracts import Hindcast, Latest, Past
from scrubcast.build.schema import write_schemas
from scrubcast.build.site_data import Publication, worst_rule, write_site_data
from scrubcast.models.assessment import LaunchAssessment
from scrubcast.models.rules import Confidence, Tier
from scrubcast.rules.loader import load_rules

ROOT = Path(__file__).parents[2]


@pytest.fixture
def assessment() -> LaunchAssessment:
    return LaunchAssessment.model_validate_json(
        (ROOT / "tests/golden/assessment_cape.json").read_text()
    )


def test_worst_rule_priority_fallback_and_reference(assessment: LaunchAssessment) -> None:
    direct = assessment.rules[0].model_copy(deep=True)
    direct.confidence = Confidence.DIRECT
    direct.reference_only = False
    direct.by_model["ecmwf"].risk_fraction = 0.05
    direct.by_model["gfs"].risk_fraction = 0.9
    low = direct.model_copy(deep=True)
    low.rule_id = "low"
    low.confidence = Confidence.LOW
    low.by_model["ecmwf"].risk_fraction = 0.8
    low.by_model["gfs"].risk_fraction = 0.1
    reference = direct.model_copy(deep=True)
    reference.rule_id = "reference"
    reference.reference_only = True
    reference.by_model["ecmwf"].risk_fraction = 1
    assessment.tier = Tier.A
    assessment.rules = [low, reference, direct]
    chip = worst_rule(assessment)
    assert chip.rule_id == direct.rule_id
    assert chip.risk_fraction == 0.9
    assert chip.model == "gfs"
    assert chip.label.endswith("90% (GFS)")
    direct.by_model["ecmwf"].risk_fraction = None
    assert worst_rule(assessment).model == "gfs"
    direct.by_model["gfs"].risk_fraction = None
    assert worst_rule(assessment).label.endswith("80% (ECMWF) (low confidence)")
    assessment.tier = Tier.B
    assert worst_rule(assessment).label.endswith("100% (ECMWF) (LLCC reference)")
    assessment.tier = Tier.C
    assert worst_rule(assessment).label == "No published rules"


def test_worst_rule_clear_and_tied_order(assessment: LaunchAssessment) -> None:
    assessment.tier = Tier.A
    for rule in assessment.rules:
        rule.reference_only = False
        for risk in rule.by_model.values():
            risk.risk_fraction = 0.049
    assert worst_rule(assessment).label == "No rule above 5%"
    for rule in assessment.rules:
        rule.confidence = Confidence.MEDIUM
        rule.by_model["ecmwf"].risk_fraction = 0.5
    expected = worst_rule(assessment)
    assessment.rules.reverse()
    assert worst_rule(assessment) == expected


@pytest.mark.parametrize("model", ["ecmwf", "gfs"])
def test_worst_rule_names_either_ensemble(assessment: LaunchAssessment, model: str) -> None:
    for rule in assessment.rules:
        rule.reference_only = False
        for name, risk in rule.by_model.items():
            risk.risk_fraction = 1.0 if name == model else 0.0
    chip = worst_rule(assessment)
    assert chip.risk_fraction == 1.0
    assert chip.model == model
    assert model.upper() in chip.label


@pytest.mark.parametrize("missing", ["null", "no_members", "no_rules", "missing_rule", "no_models"])
def test_worst_rule_does_not_reassure_without_evidence(
    assessment: LaunchAssessment, missing: str
) -> None:
    for rule in assessment.rules:
        rule.reference_only = False
        for risk in rule.by_model.values():
            risk.risk_fraction = 0.0
            if missing == "null":
                risk.risk_fraction = None
            if missing == "no_members":
                risk.evaluable_members = 0
    if missing == "no_rules":
        assessment.rules = []
    if missing == "missing_rule":
        for risk in assessment.rules[0].by_model.values():
            risk.risk_fraction = None
    if missing == "no_models":
        for rule in assessment.rules:
            rule.by_model = {}
    chip = worst_rule(assessment)
    assert "unavailable" in chip.label.lower()
    assert chip.risk_fraction is None


def test_worst_rule_uses_a_single_available_ensemble(assessment: LaunchAssessment) -> None:
    for rule in assessment.rules:
        rule.reference_only = False
        rule.by_model.pop("ecmwf")
        rule.by_model["gfs"].risk_fraction = 1.0
    chip = worst_rule(assessment)
    assert chip.model == "gfs"
    assert chip.risk_fraction == 1.0


def test_site_data_publishes_missing_models_as_unavailable(
    tmp_path: Path, assessment: LaunchAssessment
) -> None:
    for rule in assessment.rules:
        rule.by_model = {}
    latest = write_site_data(
        [assessment.launch],
        [assessment],
        load_rules(),
        assessment.evaluated_at,
        publication=Publication(root=tmp_path),
    )
    assert latest.members_total == 0
    assert latest.launches[0].worst_rule.label == "Forecast unavailable"


def test_site_data_retains_and_expires_pages(tmp_path: Path, assessment: LaunchAssessment) -> None:
    now = assessment.evaluated_at
    catalog = load_rules()
    latest = write_site_data(
        [assessment.launch], [assessment], catalog, now, publication=Publication(root=tmp_path)
    )
    assert latest.members_total == 82
    assert latest.launches[0].assessment
    directory = tmp_path / "site/public/data"
    assert Latest.model_validate_json((directory / "latest.json").read_text()) == latest
    assert Past.model_validate_json((directory / "past.json").read_text()).launches == []
    assert not Hindcast.model_validate_json(
        (directory / "hindcast.json").read_text()
    ).lowest_hour_verified
    later = assessment.launch.net + timedelta(days=2)
    write_site_data([], [], catalog, later, publication=Publication(root=tmp_path))
    past = Past.model_validate_json((directory / "past.json").read_text())
    assert [launch.id for launch in past.launches] == [assessment.launch.id]
    assert not (tmp_path / "data").exists()
    write_site_data(
        [], [], catalog, later + timedelta(days=90), publication=Publication(root=tmp_path)
    )
    assert not list((directory / "launches").glob("*.json"))
    assert not Past.model_validate_json((directory / "past.json").read_text()).launches


def test_site_data_copies_hindcast_and_verification(
    tmp_path: Path, assessment: LaunchAssessment
) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    data = {
        "generated_at": assessment.evaluated_at.isoformat(),
        "lowest_hour_verified": True,
        "forecast_audit": {"n": 10},
    }
    source = ledger / "hindcast.json"
    source.write_text(json.dumps(data))
    original = source.read_bytes()
    latest = write_site_data(
        [assessment.launch],
        [assessment],
        load_rules(),
        assessment.evaluated_at,
        publication=Publication(
            root=tmp_path, schedule_stale=True, site_url="https://example.org/weather/"
        ),
    )
    assert latest.schedule_stale
    assert latest.launches[0].page_url.startswith("https://example.org/weather/launch/")
    directory = tmp_path / "site/public/data"
    assert json.loads((directory / "hindcast.json").read_text()) == data
    published = LaunchAssessment.model_validate_json(
        (directory / f"launches/{assessment.launch.id}.json").read_text()
    )
    assert published.lowest_hour_verified
    assert not assessment.lowest_hour_verified
    assert source.read_bytes() == original


def test_schema_exports_match_models(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_schemas(tmp_path)
    first = {path.name: path.read_bytes() for path in tmp_path.glob("*.json")}
    definitions = json.loads(capsys.readouterr().out)["$defs"]
    assert {"Latest", "Past", "LaunchAssessment", "RuleSet", "Hindcast"} <= definitions.keys()
    assert "launch_service_provider_name" in definitions["Launch"]["properties"]
    write_schemas(tmp_path)
    assert first == {path.name: path.read_bytes() for path in tmp_path.glob("*.json")}
    assert first == {path.name: path.read_bytes() for path in (ROOT / "schemas").glob("*.json")}


def test_clear_reference_chip_keeps_its_qualification(assessment: LaunchAssessment) -> None:
    assessment.tier = Tier.B
    for rule in assessment.rules:
        for risk in rule.by_model.values():
            risk.risk_fraction = 0.0
    assert worst_rule(assessment).label == "No rule above 5% (LLCC reference)"
