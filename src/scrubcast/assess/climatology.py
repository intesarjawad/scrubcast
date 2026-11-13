"""Pure context distributions from historical deterministic forecast profiles."""

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

from scrubcast.rules.proxies import shear_per_km, upper_wind_mps

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from scrubcast.rules.profile import Profile


@dataclass(frozen=True)
class Climatology:
    """Finite upper-wind and shear samples for one point, model and history period."""

    upper_wind_mps: tuple[float, ...]
    shear_per_km: tuple[float, ...]

    @classmethod
    def from_profiles(cls, profiles: Iterable[Profile]) -> Climatology:
        """Build context samples from the caller's last 365 days at a single point."""
        upper_winds: list[float] = []
        shears: list[float] = []
        for profile in profiles:
            wind = upper_wind_mps(profile)
            shear = shear_per_km(profile)
            if wind is not None and isfinite(wind):
                upper_winds.append(wind)
            if shear is not None and isfinite(shear):
                shears.append(shear)
        return cls(tuple(sorted(upper_winds)), tuple(sorted(shears)))


def percentile(value: float | None, samples: Sequence[float]) -> float | None:
    """Return the percentage of finite historical samples at or below the value.

    Missing context or an empty finite distribution has no percentile. Equal
    samples count in full, so the maximum historical value ranks at 100.
    """
    if value is None or not isfinite(value):
        return None
    finite = [sample for sample in samples if isfinite(sample)]
    return 100 * sum(sample <= value for sample in finite) / len(finite) if finite else None
