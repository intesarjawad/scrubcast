import gzip
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, JsonValue, TypeAdapter

from scrubcast.audit.backfill import Snapshot
from scrubcast.audit.proxy_check import Evidence
from scrubcast.cli import main
from scrubcast.models.observation import Observation

if TYPE_CHECKING:
    import pytest

GOLDEN = Path(__file__).resolve().parents[1] / "golden/backfill-tables.json"


class LedgerRecord(BaseModel):
    evidence: Evidence
    snapshots: list[Snapshot]


LedgerRecord.model_rebuild(_types_namespace={"Evidence": Evidence})


def test_backfill_tables_resume_and_offline_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[2])
    command = ["backfill", "--fixtures", "--data-dir", str(tmp_path), "--request-limit", "3"]
    main(command)
    assert "Saved 3 requests" in capsys.readouterr().out
    assert not (tmp_path / "ledger/backfill.jsonl").exists()
    for _ in range(4):
        main(command)
    assert "Backfill n=7" in capsys.readouterr().out
    ledger = tmp_path / "ledger"
    actual = TypeAdapter(JsonValue).validate_json((ledger / "backfill-tables.json").read_bytes())
    expected = TypeAdapter(JsonValue).validate_json(GOLDEN.read_bytes())
    assert actual == expected
    before = {
        name: (ledger / name).read_bytes()
        for name in ("backfill.jsonl", "backfill-tables.json", "validation.md")
    }

    def refuse(_self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        message = f"Offline replay attempted a network request: {request.url}"
        raise AssertionError(message)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    main(["hindcast", "--offline", "--data-dir", str(tmp_path)])
    assert "Backfill n=7" in capsys.readouterr().out
    assert before == {name: (ledger / name).read_bytes() for name in before}
    records = [
        LedgerRecord.model_validate_json(line)
        for line in (ledger / "backfill.jsonl").read_text().splitlines()
    ]
    assert len(records) == 56
    assert len({record.evidence.launch_id for record in records}) == 7
    for metadata in (tmp_path / "data/backfill/snapshots").glob("*.json"):
        if metadata.name == "requests.json":
            continue
        payload = Snapshot.model_validate_json(metadata.read_text())
        assert payload.recorded_at
        assert payload.url.startswith("https://")
        raw = gzip.decompress((metadata.parent / payload.asset).read_bytes())
        assert payload.sha256 == hashlib.sha256(raw).hexdigest()
    climate = TypeAdapter(dict[str, list[Observation]]).validate_json(
        (tmp_path / "data/iem/climatology.json").read_text()
    )
    assert set(climate) == {"XMR"}
    assert len(climate["XMR"]) == 685


def test_top_up_retains_earlier_launches_and_rebuilds_from_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[2])
    base = ["backfill", "--fixtures", "--data-dir", str(tmp_path), "--request-limit", "30"]
    main([*base, "--start", "2025-10-01", "--end", "2025-10-15"])
    assert "Backfill n=2" in capsys.readouterr().out
    first_assets = {
        path.name: path.read_bytes() for path in (tmp_path / "data/backfill/snapshots").glob("*.gz")
    }
    main([*base, "--start", "2025-10-16", "--end", "2025-10-31"])
    assert "Backfill n=7" in capsys.readouterr().out
    for name, content in first_assets.items():
        assert (tmp_path / "data/backfill/snapshots" / name).read_bytes() == content
    ledger = tmp_path / "ledger"
    assert TypeAdapter(JsonValue).validate_json(
        (ledger / "backfill-tables.json").read_bytes()
    ) == TypeAdapter(JsonValue).validate_json(GOLDEN.read_bytes())
    expected = (ledger / "validation.md").read_bytes()
    (ledger / "backfill.jsonl").write_text("corrupt ledger\n")
    (ledger / "validation.md").unlink()

    def refuse(_self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        message = f"Unexpected request: {request.url}"
        raise AssertionError(message)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    main(["hindcast", "--offline", "--data-dir", str(tmp_path)])
    assert (ledger / "validation.md").read_bytes() == expected
    assert len((ledger / "backfill.jsonl").read_text().splitlines()) == 56
