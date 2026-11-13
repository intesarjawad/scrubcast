from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scrubcast.audit.forecast_audit import (
    ForecastLaunch,
    ForecastLedger,
    audit_forecasts,
    bucket_run,
    fair_crps,
)
from scrubcast.audit.report import render_validation
from scrubcast.cli import main

FIXTURES = Path(__file__).parents[1] / "fixtures"
GOLDEN = Path(__file__).parents[1] / "golden/validation.md"


def _fixture() -> ForecastLedger:
    return ForecastLedger.model_validate_json((FIXTURES / "hindcast/ledger.json").read_text())


def _with_launches(count: int) -> ForecastLedger:
    return _fixture().model_copy(
        update={"launches": _fixture().launches[:count]},
    )


def test_fixture_ledger_renders_the_golden_validation() -> None:
    now = datetime.fromisoformat((FIXTURES / "RECORDED_AT").read_text().strip())

    text = render_validation(audit_forecasts(_fixture()), now)

    assert text == GOLDEN.read_text()


def test_four_launches_print_insufficient_data_for_every_metric() -> None:
    audit = audit_forecasts(_with_launches(4))

    assert audit.n_launches == 4
    for evaluation in audit.evaluations:
        for row in evaluation.rows:
            assert row.n == 4
            assert row.display == "insufficient data (n=4)"
    assert audit.attempts.message == "insufficient data (attempts not launched n=0)"
    assert audit.lowest_hour.n == 4
    assert audit.lowest_hour.verified is False


def test_lowest_hour_requires_ten_paired_launches() -> None:
    ten = audit_forecasts(_with_launches(10)).lowest_hour
    nine = audit_forecasts(_with_launches(9)).lowest_hour

    assert ten.n == 10
    assert ten.interval is not None
    assert ten.interval[1] < 0
    assert ten.verified is True
    assert nine.n == 9
    assert nine.interval == ten.interval
    assert nine.verified is False


def test_bucket_selection_prefers_nearest_run_and_rejects_mismatched_net() -> None:
    net = datetime(2026, 1, 2, 12, tzinfo=UTC)
    launch = ForecastLaunch.model_validate(
        {
            "launch_id": "bucket",
            "net": net,
            "runs": [
                {"run_at": net - timedelta(hours=27), "net": net},
                {"run_at": net - timedelta(hours=22), "net": net},
                {"run_at": net - timedelta(hours=21), "net": net},
                {"run_at": net - timedelta(hours=24), "net": net + timedelta(minutes=31)},
            ],
        }
    )

    selected = bucket_run(launch, 24)

    assert selected is not None
    assert selected.run_at == net - timedelta(hours=22)
    assert bucket_run(launch, 72) is None


@pytest.mark.parametrize(
    ("members", "observed", "expected"),
    [
        ([9.0, 11.0], 10.0, 0.0),
        ([8.0, 12.0], 13.0, 1.0),
        ([], 10.0, None),
    ],
)
def test_fair_crps_is_computed_from_the_member_distribution(
    members: list[float], observed: float, expected: float | None
) -> None:
    assert fair_crps(members, observed) == expected


def test_audit_keeps_unknown_attempts_excluded_and_counted() -> None:
    ledger = _with_launches(12)
    launches = [
        launch.model_copy(update={"outcome": "unknown"}) if index == 0 else launch
        for index, launch in enumerate(ledger.launches)
    ]

    audit = audit_forecasts(ledger.model_copy(update={"launches": launches}))

    assert audit.attempts.unknown == 1
    assert audit.attempts.n == 11


def test_rescore_reproduces_the_fixture_ledger_rows(tmp_path: Path) -> None:
    asset = FIXTURES / "hindcast/release/slices-20261106T01.npz"

    main(["hindcast", "--rescore", str(asset), "--data-dir", str(tmp_path)])

    actual = (tmp_path / "ledger/rescored.jsonl").read_text()
    assert actual == (FIXTURES / "hindcast/rescored.jsonl").read_text()


@pytest.mark.parametrize("missing", ["archive", "archive/slices-20261106T01.npz"])
def test_rescore_without_slices_says_where_to_put_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["hindcast", "--rescore", str(tmp_path / missing), "--data-dir", str(tmp_path)])

    assert stopped.value.code == 1
    error = capsys.readouterr().err
    assert f"No archived slices found at {tmp_path / missing}." in error
    assert "docs/recipes.md" in error
