"""Self-contained ensemble slices for replaying a collector run without its cache."""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

import numpy as np
import numpy.typing as npt
from pydantic import AwareDatetime, BaseModel, Field

from scrubcast.models import weather
from scrubcast.models.launch import Launch, parse_concerns

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from scrubcast.rules.loader import RuleCatalog
    from scrubcast.sources.weather_source import ForecastResponse

ARCHIVE_HORIZON = timedelta(hours=96)
WINDOW_PADDING = timedelta(hours=1)


class LaunchSummary(Launch):
    """Source launch snapshot with the coverage and official fields needed for replay."""

    tier: Literal["A"]
    official_go_pct: int | None = Field(ge=0, le=100)
    official_concerns: list[str]
    unmapped_concerns: list[str]


class ModelSlice(BaseModel):
    """Array axis order and source metadata for one launch and model."""

    array_key: str
    fetched_at: AwareDatetime
    grid_point: weather.GridPoint
    hours: list[AwareDatetime] = Field(min_length=1)
    variable_order: list[str] = Field(min_length=1)
    members: int = Field(gt=0)


type ModelSlices = dict[weather.EnsembleModel, ModelSlice]


class LaunchSlice(BaseModel):
    """Launch identity and per-model slices sharing one requested forecast point."""

    launch: LaunchSummary
    point_id: str
    models: ModelSlices


class SliceMetadata(BaseModel):
    """JSON sidecar sufficient to reconstruct inputs to a complete ledger row."""

    run_at: AwareDatetime
    rule_set_version: str = Field(min_length=1)
    launches: list[LaunchSlice] = Field(min_length=1)


def save_slices(
    directory: Path,
    launches: Sequence[Launch],
    forecasts: Mapping[str, ForecastResponse],
    catalog: RuleCatalog,
    run_at: datetime,
) -> Path | None:
    """Save Tier A windows within 96 hours; return no path when none qualify."""
    selected: list[LaunchSlice] = []
    arrays: dict[str, npt.NDArray[np.float32]] = {}
    versions: set[str] = set()
    for launch in launches:
        site = catalog.site_for(launch.pad)
        if site.tier != "A" or not timedelta() <= launch.net - run_at <= ARCHIVE_HORIZON:
            continue
        point = site.forecast_point
        if point is None:
            msg = f"No forecast point for launch {launch.id}"
            raise ValueError(msg)
        response = forecasts.get(point.point_id)
        if response is None or not response.series:
            msg = f"No forecast available for {point.point_id}"
            raise ValueError(msg)
        versions.update(catalog.rule_sets[name].version for name in site.rule_sets)
        concerns = parse_concerns(launch.weather_concerns)
        summary = LaunchSummary(
            **launch.model_dump(),
            tier="A",
            official_go_pct=launch.probability,
            official_concerns=concerns,
            unmapped_concerns=[
                name for name in concerns if catalog.normalise_concern(name).rule_id is None
            ],
        )
        models: ModelSlices = {}
        for series in response.series:
            indices = [
                index
                for index, hour in enumerate(series.hours)
                if (
                    launch.window_start - WINDOW_PADDING
                    <= hour
                    <= launch.window_end + WINDOW_PADDING
                )
            ]
            key = f"launch_{len(selected)}_{series.model}"
            metadata = ModelSlice(
                array_key=key,
                fetched_at=response.fetched_at,
                grid_point=series.grid_point,
                hours=[series.hours[index] for index in indices],
                variable_order=list(series.values),
                members=series.members,
            )
            arrays[key] = np.stack([values[:, indices] for values in series.values.values()])
            models[series.model] = metadata
        selected.append(LaunchSlice(launch=summary, point_id=point.point_id, models=models))
    if not selected:
        return None
    if len(versions) != 1:
        msg = f"Slice run requires one rule set version, got {sorted(versions)}"
        raise ValueError(msg)
    sidecar = SliceMetadata(run_at=run_at, rule_set_version=versions.pop(), launches=selected)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"slices-{run_at:%Y%m%dT%H}.npz"
    np.savez_compressed(path, allow_pickle=False, **arrays)
    path.with_suffix(".json").write_text(sidecar.model_dump_json(indent=2) + "\n")
    return path


def load_slices(path: Path) -> tuple[SliceMetadata, dict[str, npt.NDArray[np.float32]]]:
    """Load a sidecar and validate its float32 variable-by-member-by-hour arrays."""
    metadata = SliceMetadata.model_validate_json(path.with_suffix(".json").read_text())
    arrays: dict[str, npt.NDArray[np.float32]] = {}
    with np.load(path, allow_pickle=False) as saved:
        for launch in metadata.launches:
            for model in launch.models.values():
                array = saved[model.array_key]
                shape = (len(model.variable_order), model.members, len(model.hours))
                if array.dtype != np.float32 or array.shape != shape:
                    msg = (
                        f"{model.array_key}: expected float32 shape {shape}, "
                        f"got {array.dtype} {array.shape}"
                    )
                    raise ValueError(msg)
                arrays[model.array_key] = array
        if set(saved.files) != set(arrays):
            msg = "Archive arrays do not match the sidecar"
            raise ValueError(msg)
    return metadata, arrays
