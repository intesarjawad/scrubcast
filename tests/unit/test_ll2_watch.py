import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from scrubcast.sources.ll2_watch import HEADERS, deprecation, version_change

FIXTURES = Path(__file__).parents[1] / "fixtures/ll2_watch"


class Case(BaseModel):
    documentation: str
    headers: dict[str, str]
    body: str
    expected: str | None


@pytest.mark.parametrize("name", ["no-change", "newer-version", "deprecation-header"])
def test_version_change_fixtures(name: str) -> None:
    case = Case.model_validate_json((FIXTURES / f"{name}.json").read_text())

    assert version_change(case.documentation, case.headers, case.body) == case.expected


def test_deprecated_word_in_body() -> None:
    assert deprecation({}, "This endpoint is deprecated") == "response body says deprecated"


def test_user_agent_names_the_project_and_its_repository() -> None:
    assert re.fullmatch(
        r"scrubcast/\d+\.\d+\.\d+ \(\+https://github\.com/intesarjawad/scrubcast\)",
        HEADERS["User-Agent"],
    )
