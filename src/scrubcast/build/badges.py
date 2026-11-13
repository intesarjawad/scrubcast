"""Small JSON badges for the three forward-audit summaries."""

from datetime import timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

from scrubcast.audit.forecast_audit import ForecastAudit

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from pathlib import Path

STALE_AFTER = timedelta(hours=48)
MAX_MESSAGE = 60
BADGE_FILES = ("wind", "precipitation", "attempts")
BADGE_LABELS = {
    "wind": "Scrubcast wind",
    "precipitation": "Scrubcast precipitation",
    "attempts": "Scrubcast attempts",
}
type BadgeColor = Literal["blue", "yellow", "lightgrey"]


class Badge(BaseModel):
    """A shields.io endpoint payload; the sample size and value stay out of the published bytes."""

    model_config = ConfigDict(extra="forbid")

    # shields.io rejects a payload without `schemaVersion` or with keys it does not define.
    schema_version: Literal[1] = Field(default=1, serialization_alias="schemaVersion")
    label: str
    message: str = Field(max_length=MAX_MESSAGE)
    color: BadgeColor
    n: int = Field(ge=0, exclude=True)
    value: float | None = Field(default=None, exclude=True)


def _short(value: float, *, percent: bool = True) -> str:
    return f"{value * 100:.1f}%" if percent else f"{value:.2f}"


def _metric_badge(
    audit: ForecastAudit,
    *,
    key: Literal["wind", "precipitation", "attempts"],
    stale: bool,
) -> Badge:
    if key == "attempts":
        attempts = audit.attempts
        n = attempts.n
        value = attempts.auc
        if attempts.message is not None:
            message = f"insufficient data (n={n})"
            color: BadgeColor = "lightgrey"
        elif value is None:
            message = f"not evaluated (n={n})"
            color = "lightgrey"
        else:
            message = f"attempt AUC {_short(value, percent=False)} (n={n})"
            color = "blue"
    else:
        evaluation_key = "observation" if key == "precipitation" else key
        evaluation = next(item for item in audit.evaluations if item.key == evaluation_key)
        row = next(
            (
                item
                for item in evaluation.rows
                if item.label.endswith("CRPS skill" if key == "wind" else "Brier skill")
            ),
            None,
        )
        n = row.n if row is not None else evaluation.n
        value = row.value if row is not None else None
        if row is None or value is None:
            message = f"not evaluated (n={n})"
            color = "lightgrey"
        elif not row.sufficient:
            message = f"insufficient data (n={n})"
            color = "lightgrey"
        else:
            model = f"{row.label.split()[0]} " if key == "wind" and row else ""
            message = f"{model}{key} skill {_short(value)} (n={n})"
            color = "blue"
    if stale:
        return Badge(label=BADGE_LABELS[key], message=message, color="yellow", n=n, value=value)
    return Badge(label=BADGE_LABELS[key], message=message, color=color, n=n, value=value)


def _no_audit() -> dict[str, Badge]:
    return {
        key: Badge(
            label=BADGE_LABELS[key],
            message="no audit yet (n=0)",
            color="lightgrey",
            n=0,
        )
        for key in BADGE_FILES
    }


def badges(data: Mapping[str, object] | None, now: datetime) -> dict[str, Badge]:
    """Read a published hindcast document; absent or empty data is an explicit state."""
    if data is None or data.get("forecast_audit") is None:
        return _no_audit()
    try:
        audit = ForecastAudit.model_validate(data["forecast_audit"])
    except ValueError:
        return _no_audit()
    generated_at = TypeAdapter(AwareDatetime).validate_python(data["generated_at"])
    stale = (now - generated_at) > STALE_AFTER
    return {key: _metric_badge(audit, key=key, stale=stale) for key in BADGE_FILES}


def render_badge(badge: Badge) -> bytes:
    """Keep the published bytes stable across runs and platforms."""
    return (badge.model_dump_json(indent=2, by_alias=True) + "\n").encode()


def write_badges(directory: Path, data: Mapping[str, object] | None, now: datetime) -> None:
    """Write one JSON endpoint per summary badge."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, badge in badges(data, now).items():
        (directory / f"{name}.json").write_bytes(render_badge(badge))
