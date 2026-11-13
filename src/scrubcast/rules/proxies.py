"""Pure launch-weather approximations and context from hourly member profiles."""

from dataclasses import dataclass
from math import cos, hypot, isfinite, radians, sin
from typing import TYPE_CHECKING, Literal

import numpy as np

from scrubcast.rules.profile import Profile, cloud_runs, wind_at_height_mps

if TYPE_CHECKING:
    from collections.abc import Mapping

    from scrubcast.models.rules import Parameter

# Vehicle configurations have no Rule.needs field; sustained wind needs both heights.
LIFTOFF_WIND_NEEDS = ("wind_speed_10m", "wind_speed_100m")
# Context definitions from the rule method; these do not produce rule verdicts.
CONVECTIVE_CAPE_MIN_JKG = 1000
CONVECTIVE_PRECIP_MIN_MMH = 0.254
METRES_PER_KM = 1000


@dataclass(frozen=True)
class ProxyResult:
    """A verdict and its plotted value; unavailable evidence has no verdict.

    The value remains available when only an ancillary gate is missing.
    """

    verdict: Literal["violated", "clear", "not_evaluable"]
    value: float | None


def _number(params: Mapping[str, Parameter], name: str) -> float:
    value = params[name]
    if isinstance(value, str):
        msg = f"Expected numeric proxy parameter: {name}"
        raise TypeError(msg)
    return value


def compare(value: float, threshold: Parameter, comparator: Parameter) -> bool:
    """Apply the same parameter comparison used by the plot threshold."""
    if isinstance(threshold, str):
        msg = "Expected numeric comparison threshold"
        raise TypeError(msg)
    match comparator:
        case ">":
            return value > threshold
        case ">=":
            return value >= threshold
        case "<=":
            return value <= threshold
        case _:
            msg = f"Unsupported proxy comparator: {comparator}"
            raise ValueError(msg)


def _inputs(profile: Profile, *names: str) -> tuple[float, ...] | None:
    values = tuple(profile.values.get(name, float("nan")) for name in names)
    return values if all(isfinite(value) for value in values) else None


def _result(value: float, *, violated: bool) -> ProxyResult:
    return ProxyResult("violated" if violated else "clear", value)


def liftoff_wind(profile: Profile, params: Mapping[str, Parameter]) -> ProxyResult:
    """Plot sustained wind at reference height, or the larger of it and the gust.

    Pass VehicleConfig.parameters() plus the vehicle's measure field as params.
    """
    inputs = _inputs(profile, *LIFTOFF_WIND_NEEDS)
    if inputs is None:
        return ProxyResult("not_evaluable", None)
    v10, v100 = inputs
    value = wind_at_height_mps(v10, v100, _number(params, "reference_height_m"))
    if params["measure"] == "peak":
        gust = _inputs(profile, "wind_gusts_10m")
        if gust is None:
            return ProxyResult("not_evaluable", None)
        value = max(value, gust[0])
    return _result(value, violated=compare(value, params["threshold_mps"], params["comparator"]))


def thick_cloud(profile: Profile, params: Mapping[str, Parameter]) -> ProxyResult:
    """Plot the deepest cloudy run with a level in the specified temperature band."""
    heights, temperatures, clouds = profile.z_m, profile.t_c, profile.cloud_pct
    if heights is None or temperatures is None or clouds is None:
        return ProxyResult("not_evaluable", None)
    if any(
        not column.size or not np.isfinite(column).all()
        for column in (heights, temperatures, clouds)
    ):
        return ProxyResult("not_evaluable", None)
    mask = clouds >= _number(params, "cloud_cover_min_pct")
    in_band = (temperatures >= _number(params, "t_min_c")) & (
        temperatures <= _number(params, "t_max_c")
    )
    value = max(
        (
            float(heights[top] - heights[bottom])
            for bottom, top in cloud_runs(mask)
            if in_band[bottom : top + 1].any()
        ),
        default=0.0,
    )
    return _result(
        value, violated=compare(value, params["thickness_min_m"], params["thickness_comparator"])
    )


def _cold_cloud(
    profile: Profile, params: Mapping[str, Parameter], *, inclusive: bool
) -> bool | None:
    temperatures, clouds = profile.t_c, profile.cloud_pct
    if temperatures is None or clouds is None or not temperatures.size or not clouds.size:
        return None
    if not np.isfinite(temperatures).all() or not np.isfinite(clouds).all():
        return None
    cold = (
        temperatures <= _number(params, "t_max_c")
        if inclusive
        else temperatures < _number(params, "t_max_c")
    )
    return bool(((clouds >= _number(params, "cloud_cover_min_pct")) & cold).any())


def cumulus(profile: Profile, params: Mapping[str, Parameter]) -> ProxyResult:
    """Plot CAPE, gated by precipitation and cloud reaching the cold-top limit."""
    cape_input = _inputs(profile, "cape")
    if cape_input is None:
        return ProxyResult("not_evaluable", None)
    cape = cape_input[0]
    precipitation_input = _inputs(profile, "precipitation")
    if precipitation_input is None:
        return ProxyResult("not_evaluable", cape)
    precipitation = precipitation_input[0]
    cloud = _cold_cloud(profile, params, inclusive=True)
    if cloud is None:
        return ProxyResult("not_evaluable", cape)
    return _result(
        cape,
        violated=cloud
        and compare(precipitation, params["precip_min_mmh"], params["precip_comparator"])
        and compare(cape, params["cape_min_jkg"], params["cape_comparator"]),
    )


def anvil(profile: Profile, params: Mapping[str, Parameter]) -> ProxyResult:
    """Plot CAPE, gated by moderate precipitation and a high-cloud shield."""
    cape_input = _inputs(profile, "cape")
    if cape_input is None:
        return ProxyResult("not_evaluable", None)
    cape = cape_input[0]
    inputs = _inputs(profile, "precipitation", "cloud_cover_high")
    if inputs is None:
        return ProxyResult("not_evaluable", cape)
    precipitation, high_cloud = inputs
    return _result(
        cape,
        violated=high_cloud >= _number(params, "cloud_cover_high_min_pct")
        and compare(precipitation, params["precip_min_mmh"], params["precip_comparator"])
        and compare(cape, params["cape_min_jkg"], params["cape_comparator"]),
    )


def disturbed_weather(profile: Profile, params: Mapping[str, Parameter]) -> ProxyResult:
    """Plot precipitation, gated by cloud strictly below freezing."""
    inputs = _inputs(profile, "precipitation")
    if inputs is None:
        return ProxyResult("not_evaluable", None)
    precipitation = inputs[0]
    cloud = _cold_cloud(profile, params, inclusive=False)
    if cloud is None:
        return ProxyResult("not_evaluable", precipitation)
    return _result(
        precipitation,
        violated=cloud
        and compare(precipitation, params["precip_min_mmh"], params["precip_comparator"]),
    )


def flight_through_precip(profile: Profile, params: Mapping[str, Parameter]) -> ProxyResult:
    """Plot precipitation using the published detection stand-in."""
    inputs = _inputs(profile, "precipitation")
    if inputs is None:
        return ProxyResult("not_evaluable", None)
    value = inputs[0]
    return _result(
        value, violated=compare(value, params["precip_min_mmh"], params["precip_comparator"])
    )


def convective(profile: Profile) -> bool | None:
    """Describe convection without turning context into a rule verdict."""
    inputs = _inputs(profile, "cape", "precipitation")
    if inputs is None:
        return None
    cape, precipitation = inputs
    return cape >= CONVECTIVE_CAPE_MIN_JKG and precipitation > CONVECTIVE_PRECIP_MIN_MMH


def upper_wind_mps(profile: Profile) -> float | None:
    """Return the maximum speed across the specified upper pressure levels."""
    inputs = _inputs(profile, "wind_speed_300hPa", "wind_speed_250hPa", "wind_speed_200hPa")
    return None if inputs is None else max(inputs)


def shear_per_km(profile: Profile) -> float | None:
    """Return vector wind shear in m/s per kilometre between the pressure levels."""
    inputs = _inputs(
        profile,
        "wind_speed_250hPa",
        "wind_direction_250hPa",
        "geopotential_height_250hPa",
        "wind_speed_500hPa",
        "wind_direction_500hPa",
        "geopotential_height_500hPa",
    )
    if inputs is None:
        return None
    speed250, direction250, z250, speed500, direction500, z500 = inputs
    depth_km = (z250 - z500) / METRES_PER_KM
    if depth_km <= 0:
        return None
    direction250, direction500 = radians(direction250), radians(direction500)
    return (
        hypot(
            speed250 * sin(direction250) - speed500 * sin(direction500),
            speed250 * cos(direction250) - speed500 * cos(direction500),
        )
        / depth_km
    )
