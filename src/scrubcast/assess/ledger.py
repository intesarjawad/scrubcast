"""Ledger projection and replay from archived forecast slices."""

from typing import TYPE_CHECKING

from scrubcast.archive.slices import load_slices
from scrubcast.assess.launch import AssessmentRun, assess_launch
from scrubcast.models.assessment import LedgerRow
from scrubcast.models.launch import Launch
from scrubcast.models.weather import EnsembleSeries

if TYPE_CHECKING:
    from pathlib import Path

    from scrubcast.models.assessment import LaunchAssessment
    from scrubcast.rules.loader import RuleCatalog


def ledger_row(assessment: LaunchAssessment) -> LedgerRow:
    """Project the launch-page assessment into the compact audit contract."""
    versions = {rule.rule_set_version for rule in assessment.rules}
    if len(versions) != 1:
        msg = f"Ledger requires one rule set version, got {sorted(versions)}"
        raise ValueError(msg)
    lowest = assessment.lowest_union_hour
    return LedgerRow(
        launch_id=assessment.launch.id,
        run_at=assessment.evaluated_at,
        fetched_at=assessment.fetched_at,
        net=assessment.launch.net,
        tier=assessment.tier,
        rule_set_version=versions.pop(),
        rules={
            rule.rule_id: (rule.by_model["ecmwf"].risk_fraction, rule.by_model["gfs"].risk_fraction)
            for rule in assessment.rules
        },
        union=(assessment.union_risk_t0["ecmwf"], assessment.union_risk_t0["gfs"]),
        lowest_hour=lowest.hour if lowest else None,
        lowest_hour_union=lowest.union_risk if lowest else None,
        window_end=assessment.launch.window_end,
        official_go_pct=assessment.official.probability_go_pct,
        official_concerns=assessment.official.concerns,
        unmapped_concerns=assessment.official.unmapped_concerns,
        launch=Launch(**assessment.launch.model_dump()),
    )


def append_ledger(directory: Path, row: LedgerRow) -> None:
    """Append once per launch, run and source refresh; cached forecasts add no row."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{row.run_at:%Y-%m}.jsonl"
    previous: LedgerRow | None = None
    if path.exists():
        for line in path.read_text().splitlines():
            candidate = LedgerRow.model_validate_json(line)
            if candidate.launch_id == row.launch_id:
                previous = candidate
    if previous is not None and (
        previous.run_at == row.run_at or previous.fetched_at == row.fetched_at
    ):
        return
    with path.open("a") as stream:
        stream.write(row.model_dump_json() + "\n")


def slice_to_ledger(path: Path, catalog: RuleCatalog) -> list[LedgerRow]:
    """Recompute audit rows using only the archive and the supplied rule catalog."""
    metadata, arrays = load_slices(path)
    rows: list[LedgerRow] = []
    for saved in metadata.launches:
        series = [
            EnsembleSeries(
                model=model,
                members=item.members,
                hours=item.hours,
                grid_point=item.grid_point,
                values={
                    name: arrays[item.array_key][index]
                    for index, name in enumerate(item.variable_order)
                },
            )
            for model, item in saved.models.items()
        ]
        assessment = assess_launch(
            saved.launch,
            series,
            catalog,
            AssessmentRun(
                metadata.run_at, {model: item.fetched_at for model, item in saved.models.items()}
            ),
        )
        assessment.official.probability_go_pct = saved.launch.official_go_pct
        assessment.official.concerns = saved.launch.official_concerns
        assessment.official.unmapped_concerns = saved.launch.unmapped_concerns
        rows.append(ledger_row(assessment))
    return rows
