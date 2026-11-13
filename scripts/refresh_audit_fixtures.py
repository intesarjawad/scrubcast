"""Recompute recorded audit documents, Markdown and badge bytes from the fixture ledger."""

from datetime import datetime, timedelta
from pathlib import Path

from scrubcast.audit.forecast_audit import ForecastLedger, audit_forecasts
from scrubcast.audit.report import render_validation
from scrubcast.build.badges import badges, render_badge
from scrubcast.build.contracts import Hindcast

ROOT = Path(__file__).resolve().parents[1]


def refresh(root: Path) -> None:
    """Keep every audit fixture and printed number on the production scoring path."""
    fixtures = root / "tests/fixtures"
    now = datetime.fromisoformat((fixtures / "RECORDED_AT").read_text().strip())
    source = fixtures / "hindcast/ledger.json"
    ledger = ForecastLedger.model_validate_json(source.read_bytes())
    for launch in ledger.launches:
        stations = {row.station for row in launch.observations}
        if launch.station is None and len(stations) == 1:
            launch.station = stations.pop()
    source.write_text(ledger.model_dump_json(indent=2) + "\n")
    full = audit_forecasts(ledger)
    (root / "tests/golden/validation.md").write_text(render_validation(full, now))
    for state in ("full", "small", "stale", "missing_eval"):
        audit = (
            audit_forecasts(ledger.model_copy(update={"launches": ledger.launches[:4]}))
            if state == "small"
            else full.model_copy(deep=True)
        )
        if state == "missing_eval":
            for evaluation in audit.evaluations:
                for metric in evaluation.rows:
                    metric.value = None
                    metric.sufficient = False
                evaluation.summary = f"{evaluation.title}: not estimated (n={evaluation.n})"
            audit.attempts.auc = None
        document = Hindcast(
            generated_at=now - timedelta(hours=49) if state == "stale" else now,
            lowest_hour_verified=audit.lowest_hour_verified,
            summary=[evaluation.summary for evaluation in audit.evaluations],
            forecast_audit=audit,
        )
        (fixtures / f"hindcast/{state}.json").write_text(document.model_dump_json(indent=2) + "\n")
        for name, badge in badges(document.model_dump(mode="json"), now).items():
            (root / f"tests/golden/badges/{name}-{state}.json").write_bytes(render_badge(badge))


if __name__ == "__main__":
    refresh(ROOT)
