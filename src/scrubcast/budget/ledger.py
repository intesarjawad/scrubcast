"""Append-only monthly request accounting shared by collection and reporting."""

from typing import TYPE_CHECKING, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from pathlib import Path


class BudgetRow(BaseModel):
    """One request outcome; deferrals without a response carry no measured spend."""

    model_config = ConfigDict(allow_inf_nan=False)

    sent_at: AwareDatetime
    point_id: str
    status: Literal["fetched", "deferred_budget", "deferred_upstream_429"]
    cost_units: float = Field(default=0, ge=0)
    remaining_units: float | None = Field(default=None, ge=0)
    cost_mismatch: bool = False


def read_month(directory: Path, month: str) -> list[BudgetRow]:
    """Read validated rows, returning an empty month before its first request."""
    path = directory / f"budget-{month}.jsonl"
    if not path.exists():
        return []
    return [BudgetRow.model_validate_json(line) for line in path.read_text().splitlines()]


def append_row(directory: Path, row: BudgetRow) -> None:
    """Persist a response before another request can consume its allowance."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"budget-{row.sent_at:%Y-%m}.jsonl").open("a") as stream:
        stream.write(row.model_dump_json() + "\n")
