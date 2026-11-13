"""Paced weather collection with reusable forecasts and measured request accounting."""

import logging
from datetime import UTC, datetime, timedelta
from math import fsum
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from scrubcast.budget.ledger import BudgetRow, append_row, read_month
from scrubcast.budget.planner import (
    DAILY_COST_BUDGET,
    RUN_COST_BUDGET,
    CostRecord,
    ForecastCandidate,
    next_send_at,
    plan_requests,
)
from scrubcast.forecast_cache import SavedForecast
from scrubcast.models.rules import Tier
from scrubcast.models.weather import GridPoint
from scrubcast.rules.loader import distance_km
from scrubcast.sources.errors import SourceError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from scrubcast.models.launch import Launch
    from scrubcast.models.rules import ForecastPoint
    from scrubcast.models.weather import EnsembleModel
    from scrubcast.rules.loader import RuleCatalog
    from scrubcast.sources.weather_source import ForecastResponse, WeatherSource

logger = logging.getLogger(__name__)
FRESHNESS = timedelta(hours=5)
# Open-Meteo snaps to a nearby 0.25 degree cell, about 18 km off for the Cape point; a cell
# farther away than this was returned for other coordinates under the same point id.
MAX_CELL_DISTANCE_KM = 100
LEVELS = (1000, 925, 850, 700, 600, 500, 400, 300, 250, 200)
VARIABLES = (
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_speed_100m",
    "precipitation",
    "cape",
    "cloud_cover_high",
    *(
        f"{variable}_{level}hPa"
        for variable in ("temperature", "cloud_cover", "geopotential_height")
        for level in LEVELS
    ),
    *(f"wind_speed_{level}hPa" for level in (500, 300, 250, 200)),
    "wind_direction_500hPa",
    "wind_direction_250hPa",
)


def covers(point: ForecastPoint, cell: GridPoint) -> bool:
    """Whether a returned model cell can stand for a forecast point."""
    return distance_km(point, cell) <= MAX_CELL_DISTANCE_KM


def utc_now() -> datetime:
    """Read the real clock at each send, including time spent in network calls."""
    return datetime.now(UTC)


class WeatherCollector:
    """Own one run's I/O while the planner remains independent of clock and disk."""

    def __init__(
        self,
        source: WeatherSource,
        catalog: RuleCatalog,
        *,
        root: Path = Path(),
        clock: Callable[[], datetime] = utc_now,
        wait: Callable[[float], None] = sleep,
    ) -> None:
        self.source = source
        self.catalog = catalog
        self.data = root / "data"
        self.ledger = root / "ledger"
        self.clock = clock
        self.wait = wait

    def _candidates(
        self,
        launches: Sequence[Launch],
        now: datetime,
    ) -> tuple[list[ForecastCandidate], dict[str, ForecastResponse]]:
        points: dict[str, ForecastCandidate] = {}
        forecasts: dict[str, ForecastResponse] = {}
        for launch in launches:
            if not now <= launch.net <= now + timedelta(days=10):
                continue
            site = self.catalog.site_for(launch.pad)
            point = site.forecast_point
            if point is None:
                msg = f"No forecast point for {launch.id}"
                raise ValueError(msg)
            previous = points.get(point.point_id)
            if previous is not None and previous.next_launch <= launch.net:
                continue
            path = self.data / "weather" / f"{point.point_id}.json"
            cached = SavedForecast.model_validate_json(path.read_text()) if path.exists() else None
            if cached is not None and not covers(point, cached.series[0].grid_point):
                logger.warning("%s: cached forecast is for another position; refetching", path)
                cached = None
            if cached is not None:
                forecasts[point.point_id] = cached.response()
            points[point.point_id] = ForecastCandidate(
                point,
                site.tier,
                launch.net,
                cached.fetched_at if cached else None,
            )
        return list(points.values()), forecasts

    def _cell_aliases(self, candidates: Sequence[ForecastCandidate]) -> dict[str, str]:
        path = self.data / "cells.json"
        cells = (
            TypeAdapter(dict[str, GridPoint]).validate_json(path.read_bytes())
            if path.exists()
            else {}
        )
        canonical: dict[tuple[float, float], str] = {}
        aliases: dict[str, str] = {}
        for candidate in sorted(candidates, key=lambda item: item.point.point_id):
            point_id = candidate.point.point_id
            if (
                candidate.tier != Tier.C
                or point_id not in cells
                or not covers(candidate.point, cells[point_id])
            ):
                continue
            cell = cells[point_id]
            owner = canonical.setdefault((cell.latitude, cell.longitude), point_id)
            if owner != point_id:
                aliases[point_id] = owner
        return aliases

    def _save_cell(self, point_id: str, response: ForecastResponse) -> None:
        path = self.data / "cells.json"
        adapter = TypeAdapter(dict[str, GridPoint])
        cells = adapter.validate_json(path.read_bytes()) if path.exists() else {}
        cells[point_id] = response.series[0].grid_point
        path.write_bytes(adapter.dump_json(cells, indent=2) + b"\n")

    def run(
        self, launches: Sequence[Launch], now: datetime, *, force: bool = False
    ) -> dict[str, ForecastResponse]:
        """Refresh stale eligible points and retain cached data on either deferral."""
        candidates, forecasts = self._candidates(launches, now)
        aliases = self._cell_aliases(candidates)
        candidates = [
            candidate
            for candidate in candidates
            if candidate.point.point_id not in aliases
            and (force or candidate.fetched_at is None or now - candidate.fetched_at >= FRESHNESS)
        ]
        rows = read_month(self.ledger, f"{now:%Y-%m}")
        previous_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        pacing_rows = [*read_month(self.ledger, previous_month), *rows]
        spent = fsum(row.cost_units for row in rows if row.sent_at.date() == now.date())
        plan = plan_requests(candidates, spent, now)
        selected = {request.point.point_id for request in plan}
        for candidate in candidates:
            if candidate.point.point_id not in selected:
                append_row(
                    self.ledger,
                    BudgetRow(
                        sent_at=now,
                        point_id=candidate.point.point_id,
                        status="deferred_budget",
                    ),
                )
        history = [
            CostRecord(row.sent_at, row.cost_units)
            for row in pacing_rows
            if row.sent_at <= self.clock()
        ]
        run_costs: list[float] = []
        budget_exhausted = False
        for request in plan:
            current = self.clock()
            send_at = next_send_at(history, request.cost_units, current)
            if send_at > current:
                self.wait((send_at - current).total_seconds())
            sent_at = self.clock()
            today = read_month(self.ledger, f"{sent_at:%Y-%m}")
            spent = fsum(row.cost_units for row in today if row.sent_at.date() == sent_at.date())
            if (
                budget_exhausted
                or fsum([*run_costs, request.cost_units]) > RUN_COST_BUDGET
                or fsum([spent, request.cost_units]) > DAILY_COST_BUDGET
            ):
                budget_exhausted = True
                append_row(
                    self.ledger,
                    BudgetRow(
                        sent_at=sent_at,
                        point_id=request.point.point_id,
                        status="deferred_budget",
                    ),
                )
                continue
            response = self._fetch(request.point, request.models, request.days, sent_at, forecasts)
            if response is None:
                # A rejected request may still consume the shared IP's minute allowance.
                history.append(CostRecord(sent_at, request.cost_units))
                continue
            mismatch = abs(response.cost_units - request.cost_units) > request.cost_units * 0.01
            append_row(
                self.ledger,
                BudgetRow(
                    sent_at=sent_at,
                    point_id=request.point.point_id,
                    status="fetched",
                    cost_units=response.cost_units,
                    remaining_units=response.remaining_units,
                    cost_mismatch=mismatch,
                ),
            )
            if mismatch:
                logger.warning(
                    "Cost mismatch for %s: expected %s, measured %s",
                    request.point.point_id,
                    request.cost_units,
                    response.cost_units,
                )
            run_costs.append(response.cost_units)
            history.append(CostRecord(sent_at, response.cost_units))
            path = self.data / "weather" / f"{request.point.point_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(SavedForecast.from_response(response).model_dump_json() + "\n")
            self._save_cell(request.point.point_id, response)
            forecasts[request.point.point_id] = response
        for alias, owner in aliases.items():
            if owner in forecasts:
                forecasts[alias] = forecasts[owner]
        return forecasts

    def _fetch(
        self,
        point: ForecastPoint,
        models: tuple[EnsembleModel, ...],
        days: int,
        sent_at: datetime,
        cached: Mapping[str, ForecastResponse],
    ) -> ForecastResponse | None:
        try:
            return self.source.forecast(point, models, VARIABLES, days)
        except SourceError as error:
            if error.status != 429:
                # One unreachable point must not stop the run; its launches keep the cache.
                previous = cached.get(point.point_id)
                kept = (
                    f"keeping the forecast fetched {previous.fetched_at:%Y-%m-%d %H:%M} UTC"
                    if previous
                    else "no cached forecast"
                )
                logger.warning("%s: refresh failed, %s. %s", point.point_id, kept, error)
                return None
            append_row(
                self.ledger,
                BudgetRow(
                    sent_at=sent_at,
                    point_id=point.point_id,
                    status="deferred_upstream_429",
                ),
            )
            logger.warning("%s: refresh deferred (rate limited upstream)", point.point_id)
            return None
