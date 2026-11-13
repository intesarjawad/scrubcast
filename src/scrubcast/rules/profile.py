"""One member's hourly column and pure vertical-profile calculations."""

from dataclasses import dataclass, field
from math import isfinite, log
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from collections.abc import Mapping

    from scrubcast.models.weather import EnsembleSeries


type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class Profile:
    """Surface/source values and aligned levels, sorted above the model terrain.

    Missing variables remain absent; missing individual samples remain NaN.
    Heights are geopotential metres above sea level, including in context values.
    """

    values: Mapping[str, float] = field(default_factory=dict[str, float])
    z_m: FloatArray | None = None
    t_c: FloatArray | None = None
    cloud_pct: FloatArray | None = None
    grid_elevation_m: float = 0

    def __post_init__(self) -> None:
        if self.z_m is None:
            return
        order = np.argsort(self.z_m)
        order = order[self.z_m[order] >= self.grid_elevation_m]
        object.__setattr__(self, "z_m", self.z_m[order])
        if self.t_c is not None:
            object.__setattr__(self, "t_c", self.t_c[order])
        if self.cloud_pct is not None:
            object.__setattr__(self, "cloud_pct", self.cloud_pct[order])

    @classmethod
    def from_series(cls, series: EnsembleSeries, *, member: int, hour: int) -> Profile:
        """Extract one member/hour without filling unavailable weather fields."""
        values = {name: float(array[member, hour]) for name, array in series.values.items()}
        levels = [
            name.removeprefix("geopotential_height_")
            for name in values
            if name.startswith("geopotential_height_")
        ]

        def column(prefix: str) -> FloatArray | None:
            if not levels or not any(f"{prefix}_{level}" in values for level in levels):
                return None
            return np.array([values.get(f"{prefix}_{level}", np.nan) for level in levels])

        return cls(
            values=values,
            z_m=column("geopotential_height"),
            t_c=column("temperature"),
            cloud_pct=column("cloud_cover"),
            grid_elevation_m=series.grid_point.elevation,
        )


def wind_at_height_mps(v10: float, v100: float, z: float) -> float:
    """Extrapolate sustained wind with the bounded power law from the rule method."""
    if v10 < 0.5:
        return v100 * (z / 100) ** 0.14
    alpha = min(0.5, max(0.05, log(v100 / v10) / log(10))) if v100 > 0 else 0.05
    return v10 * (z / 10) ** alpha


def height_of_isotherm_m(profile: Profile, t_c: float) -> float | None:
    """Interpolate the first crossing from the ground without bridging missing levels."""
    heights, temperatures = profile.z_m, profile.t_c
    if heights is None or temperatures is None:
        return None
    for index, temperature in enumerate(temperatures):
        if temperature == t_c:
            return float(heights[index])
        if index == 0:
            continue
        previous = float(temperatures[index - 1])
        if isfinite(previous) and (previous - t_c) * (temperature - t_c) < 0:
            fraction = (t_c - previous) / (temperature - previous)
            return float(heights[index - 1] + fraction * (heights[index] - heights[index - 1]))
    return None


def cloudy_levels(profile: Profile, min_pct: float) -> BoolArray | None:
    """Mark qualifying cloud levels, retaining absence of a cloud column."""
    return None if profile.cloud_pct is None else profile.cloud_pct >= min_pct


def cloud_runs(mask: BoolArray) -> list[tuple[int, int]]:
    """Return inclusive endpoints of contiguous cloudy runs."""
    edges = np.diff(np.concatenate(([False], mask, [False])).astype(np.int8))
    return list(
        zip(
            np.flatnonzero(edges == 1).tolist(),
            (np.flatnonzero(edges == -1) - 1).tolist(),
            strict=True,
        )
    )
