import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from scrubcast.models.weather import EnsembleSeries, GridPoint
from scrubcast.rules.profile import (
    Profile,
    cloud_runs,
    cloudy_levels,
    height_of_isotherm_m,
    wind_at_height_mps,
)


def test_wind_reference_height() -> None:
    assert wind_at_height_mps(5, 7, 49.4) == pytest.approx(6.3146, abs=1e-3)


@pytest.mark.parametrize(("v10", "v100", "alpha"), [(5, 5, 0.05), (1, 100, 0.5)])
def test_wind_exponent_clamped(v10: float, v100: float, alpha: float) -> None:
    assert wind_at_height_mps(v10, v100, 40) == pytest.approx(v10 * 4**alpha)


def test_calm_wind_fallback_and_zero_upper_wind() -> None:
    assert wind_at_height_mps(0.49, 7, 40) == pytest.approx(7 * 0.4**0.14)
    assert wind_at_height_mps(0, 0, 40) == 0
    assert wind_at_height_mps(5, 0, 40) == pytest.approx(5 * 4**0.05)
    assert wind_at_height_mps(0.5, 7, 40) == pytest.approx(0.5 * 4**0.5)


@pytest.mark.parametrize(("temperature", "height"), [(0, 3000), (-10, 4500), (-30, None)])
def test_isotherm_endpoints(temperature: float, height: float | None) -> None:
    profile = Profile(z_m=np.array([0, 1500, 3000, 4500]), t_c=np.array([20, 10, 0, -10]))
    assert height_of_isotherm_m(profile, temperature) == height


def test_first_isotherm_crossing_and_interpolation() -> None:
    profile = Profile(z_m=np.array([0, 1000, 2000, 3000]), t_c=np.array([10, -10, 10, -10]))
    assert height_of_isotherm_m(profile, 0) == 500
    assert height_of_isotherm_m(profile, 10) == 0
    assert height_of_isotherm_m(Profile(), 0) is None


@given(st.floats(min_value=-9, max_value=19), st.floats(min_value=-9, max_value=19))
def test_isotherm_height_monotone(first: float, second: float) -> None:
    profile = Profile(z_m=np.array([0, 1500, 3000, 4500]), t_c=np.array([20, 10, 0, -10]))
    lower_temperature, higher_temperature = sorted((first, second))
    lower_height = height_of_isotherm_m(profile, lower_temperature)
    higher_height = height_of_isotherm_m(profile, higher_temperature)
    assert lower_height is not None
    assert higher_height is not None
    assert lower_height >= higher_height


def test_levels_sort_and_drop_below_grid_elevation() -> None:
    profile = Profile(
        z_m=np.array([1500, 0, 500]),
        t_c=np.array([-10, 20, 10]),
        cloud_pct=np.array([80, 10, 50]),
        grid_elevation_m=500,
    )
    np.testing.assert_array_equal(profile.z_m, [500, 1500])
    np.testing.assert_array_equal(profile.t_c, [10, -10])
    np.testing.assert_array_equal(profile.cloud_pct, [50, 80])


def test_cloud_mask_and_runs() -> None:
    profile = Profile(cloud_pct=np.array([49, 50, 70, 0, 50]))
    mask = cloudy_levels(profile, 50)
    assert mask is not None
    assert cloud_runs(mask) == [(1, 2), (4, 4)]
    assert cloud_runs(np.array([], dtype=np.bool_)) == []
    assert cloudy_levels(Profile(), 50) is None


def test_profile_from_series_preserves_missing_cloud_and_member_hour() -> None:
    values = {
        "wind_speed_10m": np.array([[1, 2], [3, 4]], dtype=np.float32),
        "geopotential_height_1000hPa": np.full((2, 2), 100, dtype=np.float32),
        "temperature_1000hPa": np.full((2, 2), 20, dtype=np.float32),
        "geopotential_height_850hPa": np.full((2, 2), 1500, dtype=np.float32),
        "temperature_850hPa": np.full((2, 2), -5, dtype=np.float32),
    }
    series = EnsembleSeries("ecmwf", 2, [], values, GridPoint(0, 0, 500))
    profile = Profile.from_series(series, member=1, hour=1)
    assert profile.values["wind_speed_10m"] == 4
    np.testing.assert_array_equal(profile.z_m, [1500])
    np.testing.assert_array_equal(profile.t_c, [-5])
    assert profile.cloud_pct is None


def test_isotherm_does_not_interpolate_across_missing_temperature() -> None:
    profile = Profile(z_m=np.array([0, 1000, 2000]), t_c=np.array([10, math.nan, -10]))
    assert height_of_isotherm_m(profile, 0) is None
