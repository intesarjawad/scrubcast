import importlib.util
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

import httpx

if TYPE_CHECKING:
    import pytest

    from scrubcast.models.assessment import LedgerRow

from scrubcast.assess.ledger import slice_to_ledger
from scrubcast.audit.forecast_audit import audit_forecasts, load_forecast_ledger
from scrubcast.audit.observations import read_observations
from scrubcast.build.contracts import Hindcast
from scrubcast.cli import main
from scrubcast.rules.loader import load_rules

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests/fixtures/hindcast/release"


def _restore_collector_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[LedgerRow]:
    archive = FIXTURES / "slices-20261106T01.npz"
    rows = slice_to_ledger(archive, load_rules())
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "2026-11.jsonl").write_text("".join(row.model_dump_json() + "\n" for row in rows))
    module_spec = importlib.util.spec_from_file_location(
        "restore_archives", ROOT / "scripts/restore-archives.py"
    )
    assert module_spec is not None
    assert module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    downloads: list[list[str]] = []

    def download(command: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        assert check
        assert command[:6] == [
            "gh",
            "release",
            "download",
            "archive-2026-11",
            "--repo",
            "owner/weather-data",
        ]
        downloads.append(command)
        destination = Path(command[command.index("--dir") + 1])
        for index, arg in enumerate(command):
            if arg == "--pattern":
                shutil.copyfile(FIXTURES / command[index + 1], destination / command[index + 1])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", download)
    module.restore(tmp_path, "owner/weather-data")
    assert len(downloads) == 1
    module.restore(tmp_path, "owner/weather-data")
    assert len(downloads) == 1
    return rows


def test_collector_ledger_restored_slices_and_current_metar_produce_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = _restore_collector_files(tmp_path, monkeypatch)
    monkeypatch.setattr("scrubcast.sources.iem.IEM_MIN_INTERVAL_S", 0)
    net = rows[0].net
    requests: list[httpx.Request] = []

    def metar(_transport: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "mesonet.agron.iastate.edu"
        assert request.url.params["station"] == "VBG"
        requests.append(request)
        at = net.replace(year=int(request.url.params["year1"]))
        header = "station,valid,lon,lat,sknt,gust,p01i,skyc1,skyl1,skyc2,skyl2,skyc3,skyl3\n"
        return httpx.Response(
            200, text=header + f"VBG,{at:%Y-%m-%d %H:%M},-120.6,34.7,10,M,0.00,CLR,M,M,M,M,M\n"
        )

    now = net + timedelta(days=1)

    monkeypatch.setattr("scrubcast.cli.datetime", Mock(wraps=datetime, now=Mock(return_value=now)))
    main(["backfill", "--fixtures", "--request-limit", "30", "--data-dir", str(tmp_path)])
    monkeypatch.setattr("scrubcast.cli.record_outcomes", Mock(return_value=0))
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", metar)
    main(["audit", "--data-dir", str(tmp_path)])
    assert {request.url.params["year1"] for request in requests} == {
        str(year) for year in range(2016, 2027)
    }
    requests.clear()
    main(["audit", "--data-dir", str(tmp_path)])
    assert [request.url.params["year1"] for request in requests] == ["2026"]
    main(["hindcast", "--offline", "--data-dir", str(tmp_path)])
    loaded = load_forecast_ledger(tmp_path, load_rules())
    assert loaded.launches[0].station == "VBG"
    assert loaded.launches[0].observations[0].valid.year == 2026
    assert loaded.launches[0].runs[0].wind_members.keys() == {"ecmwf", "gfs"}
    assert {row.valid.year for row in loaded.climatology} == set(range(2016, 2026))
    audit = audit_forecasts(loaded)
    assert audit.evaluations[0].n == 1
    assert audit.evaluations[1].n == 1
    assert set(read_observations(tmp_path / "data/iem/observations.json")) == {"VBG"}
    published = Hindcast.model_validate_json((tmp_path / "ledger/hindcast.json").read_bytes())
    assert published.forecast_audit == audit
