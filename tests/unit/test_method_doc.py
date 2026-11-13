import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).parents[2]
DOC = ROOT / "docs/method.md"

THREE_EVALUATIONS = (
    "retrospective proxy check",
    "retrospective deterministic surface forecast check",
    "forward audit of ledgered ensemble forecasts",
)

CITATIONS = (
    "https://standards.nasa.gov/sites/default/files/standards/NASA/A/0/NASA-STD-4010A-Approved.pdf",
    "https://www.nasa.gov/kennedy/about-kennedy/fact-sheets/",
    "https://open-meteo.com/",
    "https://thespacedevs.com/llapi",
    "https://mesonet.agron.iastate.edu/",
    "https://www.ecfr.gov/current/title-14/section-450.163",
)


def _documents() -> Iterator[dict[str, Any]]:
    for path in sorted((ROOT / "rules").rglob("*.json")):
        yield json.loads(path.read_text(encoding="utf-8"))


def _rule_ids(document: dict[str, Any]) -> Iterator[str]:
    for rule in document.get("rules", []):
        yield rule["rule_id"]
    for rule in document.get("not_evaluable", []):
        yield rule["rule_id"]
    if "vehicle_id" in document:
        yield document["rule_id"]


def _scrub_numbers(document: dict[str, Any]) -> Iterator[tuple[str, str, int | float]]:
    for rule in document.get("rules", []):
        proxy = rule.get("proxy", {})
        for parameter, origin in rule.get("origin", {}).items():
            if origin == "scrub":
                yield rule["rule_id"], parameter, proxy[parameter]


def _lines() -> list[str]:
    return DOC.read_text(encoding="utf-8").splitlines()


def test_every_rule_id_is_named() -> None:
    lines = _lines()
    for document in _documents():
        for rule_id in _rule_ids(document):
            assert any(f"`{rule_id}`" in line for line in lines), rule_id


def test_every_scrub_number_is_named_with_its_rule() -> None:
    lines = _lines()
    for document in _documents():
        for rule_id, parameter, value in _scrub_numbers(document):
            number = re.escape(str(value))
            assert any(
                f"`{rule_id}`" in line
                and f"`{parameter}`" in line
                and re.search(rf"(?<![\d.]){number}(?![\d.])", line)
                for line in lines
            ), (rule_id, parameter, value)


def test_all_three_evaluations_are_named() -> None:
    text = DOC.read_text(encoding="utf-8")
    for evaluation in THREE_EVALUATIONS:
        assert evaluation in text


def test_citations_link_their_sources() -> None:
    text = DOC.read_text(encoding="utf-8")
    for url in CITATIONS:
        assert f"]({url})" in text, url
