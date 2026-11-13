from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from math import nan

import numpy as np
import pytest

from scrubcast.models.rules import Parameter, Rule
from scrubcast.rules.loader import load_rules
from scrubcast.rules.profile import Profile
from scrubcast.rules.proxies import (
    LIFTOFF_WIND_NEEDS,
    ProxyResult,
    anvil,
    compare,
    convective,
    cumulus,
    disturbed_weather,
    flight_through_precip,
    liftoff_wind,
    shear_per_km,
    thick_cloud,
    upper_wind_mps,
)

type Proxy = Callable[[Profile, Mapping[str, Parameter]], ProxyResult]
PROXIES: dict[str, Proxy] = {
    "liftoff_wind": liftoff_wind,
    "thick_cloud": thick_cloud,
    "cumulus": cumulus,
    "anvil": anvil,
    "disturbed_weather": disturbed_weather,
    "flight_through_precip": flight_through_precip,
}


@pytest.fixture
def rules() -> dict[str, Rule]:
    return {rule.rule_id: rule for rule in load_rules().rule_sets["llcc-nasa-std-4010a"].rules}


def parameters(rule_id: str, rules: dict[str, Rule]) -> dict[str, Parameter]:
    if rule_id == "liftoff_wind":
        vehicle = load_rules().vehicles["falcon9"]
        return {**vehicle.parameters(), "measure": vehicle.measure}
    return rules[rule_id].proxy


def storm_profile() -> Profile:
    return Profile(
        values={
            "wind_speed_10m": 20,
            "wind_speed_100m": 25,
            "wind_gusts_10m": 30,
            "cape": 1500,
            "precipitation": 3,
            "cloud_cover_high": 80,
        },
        z_m=np.array([0, 1500, 3000]),
        t_c=np.array([10, 0, -10]),
        cloud_pct=np.array([80, 80, 80]),
    )


@pytest.mark.parametrize(
    ("rule_id", "storm_value", "clear_value"),
    [
        ("liftoff_wind", 23.348505285, 2.334850529),
        ("thick_cloud", 3000, 0),
        ("cumulus", 1500, 1500),
        ("anvil", 1500, 1500),
        ("disturbed_weather", 3, 3),
        ("flight_through_precip", 3, 0),
    ],
)
def test_proxy_goldens(
    rule_id: str, storm_value: float, clear_value: float, rules: dict[str, Rule]
) -> None:
    proxy, params = PROXIES[rule_id], parameters(rule_id, rules)
    storm = storm_profile()
    if rule_id == "liftoff_wind":
        clear = replace(storm, values={"wind_speed_10m": 2, "wind_speed_100m": 2.5})
    elif rule_id == "flight_through_precip":
        clear = replace(storm, values={"precipitation": 0})
    else:
        clear = replace(
            storm, cloud_pct=np.array([0, 0, 0]), values={**storm.values, "cloud_cover_high": 0}
        )
    violated = proxy(storm, params)
    assert violated.verdict == "violated"
    assert violated.value == pytest.approx(storm_value)
    result = proxy(clear, params)
    assert result.verdict == "clear"
    assert result.value == pytest.approx(clear_value)
    assert proxy(Profile(), params) == ProxyResult("not_evaluable", None)


@pytest.mark.parametrize(
    ("rule_id", "boundary"),
    [
        ("cumulus", 0.254),
        ("anvil", 2.54),
        ("disturbed_weather", 2.54),
        ("flight_through_precip", 0.254),
    ],
)
def test_precipitation_strict_boundaries(
    rule_id: str, boundary: float, rules: dict[str, Rule]
) -> None:
    for precipitation, verdict in [(boundary, "clear"), (boundary + 1e-6, "violated")]:
        profile = storm_profile()
        profile = replace(profile, values={**profile.values, "precipitation": precipitation})
        assert PROXIES[rule_id](profile, rules[rule_id].proxy).verdict == verdict


def test_falcon_wind_strict_boundary(rules: dict[str, Rule]) -> None:
    params = parameters("liftoff_wind", rules)
    v10 = 13.41 / (49.4 / 10) ** 0.05
    profile = Profile(values={"wind_speed_10m": v10, "wind_speed_100m": v10})
    assert liftoff_wind(profile, params) == ProxyResult("clear", 13.41)
    profile = replace(profile, values={"wind_speed_10m": v10 + 0.01, "wind_speed_100m": v10})
    assert liftoff_wind(profile, params).verdict == "violated"


def test_peak_wind_uses_larger_of_gust_and_sustained(rules: dict[str, Rule]) -> None:
    params = {**parameters("liftoff_wind", rules), "measure": "peak"}
    profile = Profile(values={"wind_speed_10m": 1, "wind_speed_100m": 1, "wind_gusts_10m": 20})
    assert liftoff_wind(profile, params) == ProxyResult("violated", 20)
    assert liftoff_wind(storm_profile(), params).value == 30
    assert liftoff_wind(
        replace(profile, values={"wind_speed_10m": 20, "wind_speed_100m": 25, "wind_gusts_10m": 1}),
        params,
    ).value == pytest.approx(23.348505285)
    assert (
        liftoff_wind(Profile(values={"wind_speed_10m": 1, "wind_speed_100m": 1}), params).verdict
        == "not_evaluable"
    )


class DeclaredValues(Mapping[str, float]):
    def __init__(self, values: Mapping[str, float]) -> None:
        self._values = values

    def __getitem__(self, key: str) -> float:
        assert key in self._values, f"Undeclared input read: {key}"
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


class DeclaredProfile(Profile):
    allowed_columns: frozenset[str] | None = None

    def __getattribute__(self, name: str) -> object:
        if name in {"z_m", "t_c", "cloud_pct"} and self.allowed_columns is not None:
            assert name in self.allowed_columns, f"Undeclared column read: {name}"
        return super().__getattribute__(name)


@pytest.mark.parametrize("rule_id", PROXIES)
def test_proxies_use_only_declared_needs(rule_id: str, rules: dict[str, Rule]) -> None:
    needs = LIFTOFF_WIND_NEEDS if rule_id == "liftoff_wind" else rules[rule_id].needs
    source = storm_profile()
    profile = DeclaredProfile(
        values=DeclaredValues({key: value for key, value in source.values.items() if key in needs}),
        z_m=source.z_m if "geopotential_height_levels" in needs else None,
        t_c=source.t_c if "temperature_levels" in needs else None,
        cloud_pct=source.cloud_pct if "cloud_cover_levels" in needs else None,
    )
    object.__setattr__(
        profile,
        "allowed_columns",
        frozenset(
            field
            for need, field in {
                "geopotential_height_levels": "z_m",
                "temperature_levels": "t_c",
                "cloud_cover_levels": "cloud_pct",
            }.items()
            if need in needs
        ),
    )
    assert PROXIES[rule_id](profile, parameters(rule_id, rules)).verdict == "violated"


@pytest.mark.parametrize("rule_id", PROXIES)
def test_missing_and_nonfinite_needs_are_not_evaluable(
    rule_id: str, rules: dict[str, Rule]
) -> None:
    needs = LIFTOFF_WIND_NEEDS if rule_id == "liftoff_wind" else rules[rule_id].needs
    source = storm_profile()
    for need in needs:
        field = {
            "geopotential_height_levels": "z_m",
            "temperature_levels": "t_c",
            "cloud_cover_levels": "cloud_pct",
        }.get(need)
        if field is None:
            missing = replace(
                source, values={key: value for key, value in source.values.items() if key != need}
            )
            nonfinite = replace(source, values={**source.values, need: nan})
        elif field == "z_m":
            missing = replace(source, z_m=None)
            nonfinite = replace(source, z_m=np.array([nan, nan, nan]))
        elif field == "t_c":
            missing = replace(source, t_c=None)
            nonfinite = replace(source, t_c=np.array([10, nan, -10]))
        else:
            missing = replace(source, cloud_pct=None)
            nonfinite = replace(source, cloud_pct=np.array([80, nan, 80]))
        assert PROXIES[rule_id](missing, parameters(rule_id, rules)).verdict == "not_evaluable", (
            need
        )
        assert PROXIES[rule_id](nonfinite, parameters(rule_id, rules)).verdict == "not_evaluable", (
            need
        )


def test_thick_cloud_uses_deepest_qualifying_run(rules: dict[str, Rule]) -> None:
    profile = Profile(
        z_m=np.array([0, 2000, 3000, 4000, 5400, 7000, 10000]),
        t_c=np.array([20, 10, 5, 0, -20, -30, -40]),
        cloud_pct=np.array([50, 50, 0, 50, 50, 0, 50]),
    )
    assert thick_cloud(profile, rules["thick_cloud"].proxy) == ProxyResult("violated", 1400)


@pytest.mark.parametrize(
    ("rule_id", "temperature", "verdict"),
    [
        ("cumulus", -5, "violated"),
        ("disturbed_weather", 0, "clear"),
        ("disturbed_weather", -0.001, "violated"),
    ],
)
def test_cloud_temperature_boundaries(
    rule_id: str, temperature: float, verdict: str, rules: dict[str, Rule]
) -> None:
    profile = replace(
        storm_profile(), z_m=None, t_c=np.array([temperature]), cloud_pct=np.array([30])
    )
    assert PROXIES[rule_id](profile, rules[rule_id].proxy).verdict == verdict


@pytest.mark.parametrize(
    ("rule_id", "key", "value"),
    [
        ("thick_cloud", "thickness_min_m", 4000),
        ("cumulus", "cape_min_jkg", 2000),
        ("anvil", "cape_min_jkg", 2000),
        ("disturbed_weather", "precip_min_mmh", 4),
        ("flight_through_precip", "precip_min_mmh", 4),
        ("liftoff_wind", "threshold_mps", 40),
    ],
)
def test_parameters_control_verdict(
    rule_id: str, key: str, value: float, rules: dict[str, Rule]
) -> None:
    params = {**parameters(rule_id, rules), key: value}
    assert PROXIES[rule_id](storm_profile(), params).verdict == "clear"


@pytest.mark.parametrize(("comparator", "expected"), [(">", False), (">=", True), ("<=", True)])
def test_comparison_boundaries(comparator: str, *, expected: bool) -> None:
    assert compare(5, 5, comparator) is expected


def test_context_functions_and_vector_shear() -> None:
    profile = Profile(
        values={
            "cape": 1000,
            "precipitation": 0.255,
            "wind_speed_300hPa": 20,
            "wind_speed_250hPa": 30,
            "wind_speed_200hPa": 25,
            "wind_speed_500hPa": 10,
            "wind_direction_250hPa": 90,
            "wind_direction_500hPa": 270,
            "geopotential_height_250hPa": 10000,
            "geopotential_height_500hPa": 5000,
        }
    )
    assert convective(profile) is True
    assert convective(replace(profile, values={**profile.values, "precipitation": 0.254})) is False
    assert upper_wind_mps(profile) == 30
    assert shear_per_km(profile) == pytest.approx(8)
    assert (
        shear_per_km(
            replace(profile, values={**profile.values, "geopotential_height_250hPa": 5000})
        )
        is None
    )
    assert convective(Profile()) is None
    assert upper_wind_mps(Profile()) is None
    assert shear_per_km(Profile()) is None
