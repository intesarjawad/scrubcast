from pathlib import Path

import pytest

from scrubcast.build.contracts import Hindcast, Latest, Past
from scrubcast.models.assessment import LaunchAssessment

DATA = Path("site/public/data")


def _read(name: str) -> str:
    path = DATA / name
    if not path.exists():
        pytest.skip("site/public/data is produced by the fixture build")
    return path.read_text()


def test_built_indexes_match_contracts() -> None:
    assert Latest.model_validate_json(_read("latest.json")).schema_version == 1
    assert Past.model_validate_json(_read("past.json")).schema_version == 1
    assert Hindcast.model_validate_json(_read("hindcast.json")).schema_version == 1


def test_built_launch_pages_match_contracts() -> None:
    pages = sorted((DATA / "launches").glob("*.json"))
    if not pages:
        pytest.skip("site/public/data is produced by the fixture build")
    for path in pages:
        assert LaunchAssessment.model_validate_json(path.read_text()).launch.id == path.stem
