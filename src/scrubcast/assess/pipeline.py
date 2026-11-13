"""Per-launch assessment I/O with validation failures isolated to their launch."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from scrubcast.assess.launch import AssessmentRun, assess_launch
from scrubcast.assess.ledger import append_ledger, ledger_row
from scrubcast.forecast_cache import SavedForecast
from scrubcast.weather import FRESHNESS, covers

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from scrubcast.models.assessment import LaunchAssessment
    from scrubcast.models.launch import Launch
    from scrubcast.rules.loader import RuleCatalog
    from scrubcast.sources.weather_source import ForecastResponse

logger = logging.getLogger(__name__)


def assess_launches(
    launches: Sequence[Launch],
    forecasts: Mapping[str, ForecastResponse],
    catalog: RuleCatalog,
    now: datetime,
    *,
    root: Path = Path(),
) -> list[LaunchAssessment]:
    """Publish successful launch assessments and append refreshed audit evidence."""
    assessments = assess_cached(launches, forecasts, catalog, now, root=root)
    for assessment in assessments:
        append_ledger(root / "ledger", ledger_row(assessment))
    return assessments


def assess_cached(
    launches: Sequence[Launch],
    forecasts: Mapping[str, ForecastResponse],
    catalog: RuleCatalog,
    now: datetime,
    *,
    root: Path = Path(),
) -> list[LaunchAssessment]:
    """Publish assessments from supplied or cached forecasts without audit writes."""
    assessments: list[LaunchAssessment] = []
    for launch in launches:
        try:
            response = _forecast(launch, forecasts, catalog, root)
            assessment = assess_launch(
                launch,
                response.series,
                catalog,
                AssessmentRun(
                    now,
                    {series.model: response.fetched_at for series in response.series},
                    refresh_deferred=now - response.fetched_at >= FRESHNESS,
                ),
            )
        except ValueError as error:
            logger.warning("Skipping assessment for launch %s: %s", launch.id, error)
            continue
        directory = root / "site/public/data/launches"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{launch.id}.json"
        path.write_text(assessment.model_dump_json(indent=2) + "\n")
        assessments.append(assessment)
    return assessments


def _forecast(
    launch: Launch,
    forecasts: Mapping[str, ForecastResponse],
    catalog: RuleCatalog,
    root: Path,
) -> ForecastResponse:
    point = catalog.site_for(launch.pad).forecast_point
    if point is None:
        msg = "no forecast point"
        raise ValueError(msg)
    response = forecasts.get(point.point_id)
    if response is None:
        path = root / "data/weather" / f"{point.point_id}.json"
        if not path.exists():
            msg = f"no forecast available for {point.point_id}"
            raise ValueError(msg)
        response = SavedForecast.model_validate_json(path.read_text()).response()
    if not covers(point, response.series[0].grid_point):
        msg = f"the {point.point_id} forecast is for another position; run `scrubcast weather`"
        raise ValueError(msg)
    return response
