"""Recorded weather and observation fixtures parse into the documented shapes."""

import importlib
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.mark.parametrize(
    ("filename", "members"),
    [
        ("open_meteo_cape.json", {"ecmwf": 51, "gfs": 31}),
        ("open_meteo_vandenberg.json", {"ecmwf": 51, "gfs": 31}),
        ("open_meteo_tierc_ecmwf_only.json", {"ecmwf": 51}),
    ],
)
def test_fixture_ensemble_models(filename: str, members: dict[str, int]) -> None:
    module = importlib.import_module("scrubcast.sources.open_meteo")
    series = module.parse_ensemble(json.loads((FIXTURES / filename).read_text()))
    assert {item.model: item.members for item in series} == members
    for item in series:
        assert len(item.hours) == 72
        assert all(values.shape == (item.members, 72) for values in item.values.values())
        if item.model == "gfs":
            assert "cloud_cover_high" not in item.values


def test_fixture_historical_models() -> None:
    module = importlib.import_module("scrubcast.sources.historical")
    series = module.parse_historical(
        json.loads((FIXTURES / "historical_cape_2025-10.json").read_text()),
    )
    assert {item.model for item in series} == {"ecmwf", "gfs"}
    assert all(len(item.hours) == 744 for item in series)


def test_fixture_previous_runs_models() -> None:
    module = importlib.import_module("scrubcast.sources.historical")
    series = module.parse_previous_runs(
        json.loads((FIXTURES / "previous_runs_cape_2025-10.json").read_text()),
    )
    assert {item.model for item in series} == {"ecmwf", "gfs"}
    assert all(set(item.leads) == {1, 2, 3} for item in series)


def test_fixture_observation_models() -> None:
    module = importlib.import_module("scrubcast.sources.iem")
    observations = module.parse_metars((FIXTURES / "iem_xmr_2025-10.csv").read_text())
    assert observations
    assert all(item.station == "XMR" for item in observations)
    assert any(item.wind_speed_mps is not None for item in observations)
