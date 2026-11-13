"""Station-specific METAR inputs for the forward forecast audit."""

from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from scrubcast.models.observation import Observation
from scrubcast.sources.iem import IEMSource

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path

    import httpx

    from scrubcast.models.assessment import LedgerRow
    from scrubcast.rules.loader import RuleCatalog

CLIMATE_YEARS = range(2016, 2026)
STORED_OBSERVATIONS = TypeAdapter(dict[str, list[Observation]])


def station_for(row: LedgerRow, catalog: RuleCatalog) -> str | None:
    """Resolve the pad's configured station, using IEM's three-character US identifiers."""
    if row.launch is None:
        return None
    station = catalog.site_for(row.launch.pad).metar_station
    return station.removeprefix("K") if station else None


def read_observations(path: Path) -> dict[str, list[Observation]]:
    """Read cached station series without substituting another station for a missing one."""
    return STORED_OBSERVATIONS.validate_json(path.read_bytes()) if path.exists() else {}


def fetch_observations(
    client: httpx.Client,
    root: Path,
    rows: Sequence[LedgerRow],
    catalog: RuleCatalog,
    now: datetime,
) -> None:
    """Refresh verifying METAR and fill absent ten-year station baselines from public IEM."""
    required: dict[str, set[int]] = {}
    for row in rows:
        station = station_for(row, catalog)
        if station and row.net <= now:
            required.setdefault(station, set()).add(row.net.year)
    if not required:
        return
    directory = root / "data/iem"
    directory.mkdir(parents=True, exist_ok=True)
    climate = read_observations(directory / "climatology.json")
    observed = read_observations(directory / "observations.json")
    source = IEMSource(client)
    for station, years in sorted(required.items()):
        cached_climate = climate.get(station, [])
        missing_climate = set(CLIMATE_YEARS) - {row.valid.year for row in cached_climate}
        samples: dict[int, list[Observation]] = {}
        for year in sorted(years | missing_climate):
            path = directory / f"{station}-{year}.json"
            if path.exists() and year < now.year:
                samples[year] = TypeAdapter(list[Observation]).validate_json(path.read_bytes())
            else:
                samples[year] = [
                    row for row in source.metars(station, year) if row.station == station
                ]
                path.write_text(
                    TypeAdapter(list[Observation]).dump_json(samples[year]).decode() + "\n"
                )
        climate[station] = sorted(
            [row for row in cached_climate if row.valid.year not in missing_climate]
            + [row for year in sorted(missing_climate) for row in samples[year]],
            key=lambda row: row.valid,
        )
        observed[station] = sorted(
            [row for row in observed.get(station, []) if row.valid.year not in years]
            + [row for year in sorted(years) for row in samples[year] if row.valid <= now],
            key=lambda row: row.valid,
        )
    for name, stored in (("climatology", climate), ("observations", observed)):
        (directory / f"{name}.json").write_text(
            STORED_OBSERVATIONS.dump_json(stored).decode() + "\n"
        )
