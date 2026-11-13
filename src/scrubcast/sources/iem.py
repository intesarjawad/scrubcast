"""Paced IEM METAR requests and unit-aware CSV decoding."""

import csv
from datetime import UTC, date, datetime
from io import StringIO
from time import monotonic, sleep
from typing import TYPE_CHECKING

import httpx

from scrubcast.models.observation import CloudLayer, Observation
from scrubcast.sources.errors import SourceError

if TYPE_CHECKING:
    from collections.abc import Callable

IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
IEM_MIN_INTERVAL_S = 10
KNOTS_TO_MPS = 0.514444
TRACE_PRECIPITATION_IN = 0.0001
_FIELDS = ("sknt", "gust", "p01i", "skyc1", "skyl1", "skyc2", "skyl2", "skyc3", "skyl3")


def _number(value: str) -> float | None:
    return None if value == "M" else float(value)


def parse_metars(text: str, *, url: str = IEM_URL) -> list[Observation]:
    """Convert knots to m/s without turning missing or trace readings into zero."""
    if "Too many requests" in text:
        raise SourceError(url, None, text.strip())
    try:
        reader = csv.DictReader(StringIO(text), strict=True)
        required = {"station", "valid", "lon", "lat", *_FIELDS}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise SourceError(url, None, "METAR CSV is missing required columns")
        result: list[Observation] = []
        for row in reader:
            wind, gust = _number(row["sknt"]), _number(row["gust"])
            precipitation = row["p01i"]
            result.append(
                Observation(
                    station=row["station"],
                    valid=datetime.strptime(row["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC),
                    latitude=float(row["lat"]),
                    longitude=float(row["lon"]),
                    wind_speed_mps=None if wind is None else wind * KNOTS_TO_MPS,
                    wind_gust_mps=None if gust is None else gust * KNOTS_TO_MPS,
                    precipitation_in=(
                        TRACE_PRECIPITATION_IN if precipitation == "T" else _number(precipitation)
                    ),
                    cloud_layers=tuple(
                        CloudLayer.model_validate(
                            {
                                # The archive pads two-letter codes: vertical visibility is "VV ".
                                "cover": None
                                if (cover := row[f"skyc{i}"].strip()) == "M"
                                else cover,
                                "base_ft": _number(row[f"skyl{i}"]),
                            }
                        )
                        for i in (1, 2, 3)
                    ),
                )
            )
    except (ValueError, KeyError, TypeError, csv.Error) as error:
        raise SourceError(url, None, str(error)) from error
    return result


class IEMSource:
    """Space requests by at least ten seconds, including failed attempts."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        clock: Callable[[], float] = monotonic,
        wait: Callable[[float], None] = sleep,
    ) -> None:
        self._client = client
        self._clock = clock
        self._wait = wait
        self._last_request: float | None = None

    def metars(self, station: str, year: int) -> list[Observation]:
        """Request one station's calendar year; raw caching belongs to the caller."""
        start, end = date(year, 1, 1), date(year + 1, 1, 1)
        params = [("station", station), *(("data", field) for field in _FIELDS)]
        for suffix, day in (("1", start), ("2", end)):
            params.extend(
                (f"{part}{suffix}", str(getattr(day, part))) for part in ("year", "month", "day")
            )
        params.extend(
            [
                ("tz", "Etc/UTC"),
                ("format", "onlycomma"),
                ("latlon", "yes"),
                ("missing", "M"),
                ("trace", "T"),
                ("report_type", "3"),
            ]
        )
        url = httpx.URL(IEM_URL, params=params)
        if self._last_request is not None:
            delay = IEM_MIN_INTERVAL_S - (self._clock() - self._last_request)
            if delay > 0:
                self._wait(delay)
        self._last_request = self._clock()
        try:
            response = self._client.get(url)
        except httpx.RequestError as error:
            raise SourceError(str(error.request.url), None, str(error)) from error
        try:
            response.raise_for_status()
            return parse_metars(response.text, url=str(response.url))
        except (httpx.HTTPStatusError, SourceError) as error:
            reason = error.reason if isinstance(error, SourceError) else str(error)
            raise SourceError(
                str(response.url),
                response.status_code,
                reason,
                retry_after=response.headers.get("Retry-After"),
            ) from error
