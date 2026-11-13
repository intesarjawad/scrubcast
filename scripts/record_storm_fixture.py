"""Assess the recorded Cape Canaveral ensemble over its cloudiest four hours.

The ensemble response in tests/fixtures/open_meteo_cape.json is real model output. No
launch was scheduled in this window, so the launch is named as a fixture and must never
be shown as one: it exists so the launch page can be checked on a night the members
disagree.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import TypeAdapter

from scrubcast.assess.launch import AssessmentRun, assess_launch
from scrubcast.models.launch import Launch
from scrubcast.models.weather import parse_ensemble
from scrubcast.rules.loader import load_rules

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
DESTINATION = FIXTURES / "worst_case/storm-night.json"
CAPE_LOCATION = 12
WINDOW_START = datetime(2026, 11, 5, 0, tzinfo=UTC)
WINDOW = timedelta(hours=4)
EVALUATED_AT = datetime(2026, 11, 5, 9, tzinfo=UTC)


def main() -> None:
    """Write the storm-night assessment fixture."""
    series = parse_ensemble(json.loads((FIXTURES / "open_meteo_cape.json").read_text()))
    launches = TypeAdapter(list[Launch]).validate_python(
        json.loads((FIXTURES / "ll2_upcoming.json").read_text())["results"]
    )
    cape = next(launch for launch in launches if launch.pad.location.id == CAPE_LOCATION)
    fixture = cape.model_copy(
        update={
            "id": "fixture-cape-storm-night",
            "name": "Fixture night | Cape ensemble, not a launch",
            "net": WINDOW_START,
            "window_start": WINDOW_START,
            "window_end": WINDOW_START + WINDOW,
            "probability": None,
            "weather_concerns": None,
        }
    )
    run = AssessmentRun(EVALUATED_AT, {s.model: EVALUATED_AT for s in series})
    assessment = assess_launch(fixture, series, load_rules(), run)
    DESTINATION.write_text(json.dumps(assessment.model_dump(mode="json"), indent=2) + "\n")


if __name__ == "__main__":
    main()
