from math import nan
from pathlib import Path

import pytest
from pydantic import JsonValue, TypeAdapter

from scrubcast.assess.climatology import Climatology, percentile
from scrubcast.rules.profile import Profile

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.mark.parametrize("model", ["ecmwf_ifs025", "gfs_seamless"])
def test_historical_fixture_percentiles_reproducible(model: str) -> None:
    payload = TypeAdapter(dict[str, object]).validate_json(
        (FIXTURES / "historical_cape_2025-10.json").read_text()
    )
    hourly = TypeAdapter(dict[str, list[JsonValue]]).validate_python(payload["hourly"])
    values = TypeAdapter(dict[str, list[float | None]]).validate_python(
        {
            key.removesuffix(f"_{model}"): value
            for key, value in hourly.items()
            if key.endswith(f"_{model}")
        }
    )
    profiles = [
        Profile(
            values={
                name: sample if (sample := samples[hour]) is not None else nan
                for name, samples in values.items()
            }
        )
        for hour in range(len(hourly["time"]))
    ]
    climatology = Climatology.from_profiles(profiles)
    assert climatology == Climatology.from_profiles(reversed(profiles))
    assert len(climatology.upper_wind_mps) == 744
    assert len(climatology.shear_per_km) == 744
    for samples in (climatology.upper_wind_mps, climatology.shear_per_km):
        rank = percentile(20, samples)
        assert rank is not None
        assert 0 <= rank <= 100
        assert rank == percentile(20, tuple(reversed(samples)))


@pytest.mark.parametrize(
    ("value", "samples", "expected"),
    [
        (2, [1, 2, 2, 4], 75),
        (0, [1, 2], 0),
        (4, [1, 2, 4], 100),
        (2, [1, nan, 3], 50),
        (2, [], None),
        (2, [nan], None),
        (None, [1, 2], None),
        (nan, [1, 2], None),
    ],
)
def test_percentile_rank(value: float | None, samples: list[float], expected: float | None) -> None:
    assert percentile(value, samples) == expected


def test_missing_context_is_not_filled() -> None:
    assert Climatology.from_profiles([Profile()]) == Climatology((), ())
