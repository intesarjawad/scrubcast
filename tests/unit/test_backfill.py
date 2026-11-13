import gzip
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pytest
from pydantic import JsonValue, TypeAdapter

from scrubcast.audit.backfill import (
    SliceCompleteError,
    SnapshotOptions,
    SnapshotTransport,
    StationInputs,
    build_evidence,
    climatology_median,
    nearest_observation,
)
from scrubcast.budget.ledger import BudgetRow, append_row
from scrubcast.models.launch import Launch
from scrubcast.models.observation import Observation
from scrubcast.models.weather import EnsembleSeries, GridPoint
from scrubcast.rules.loader import load_rules


@dataclass
class Clock:
    now: datetime = datetime(2026, 11, 5, tzinfo=UTC)

    def read(self) -> datetime:
        return self.now

    def wait(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def observation(valid: datetime, wind: float = 2) -> Observation:
    return Observation(
        station="XMR",
        valid=valid,
        latitude=28,
        longitude=-80,
        wind_speed_mps=wind,
        wind_gust_mps=None,
        precipitation_in=None,
        cloud_layers=(),
    )


def test_observation_tolerance_and_circular_climatology() -> None:
    net = datetime(2025, 1, 1, tzinfo=UTC)
    early = observation(net - timedelta(minutes=30))
    late = observation(net + timedelta(minutes=30))
    assert nearest_observation([late, early], net) == early
    assert nearest_observation([observation(net + timedelta(minutes=31))], net) is None
    assert nearest_observation([], net) is None
    climate = [
        observation(datetime(2024, 12, 31, 23, tzinfo=UTC), 4),
        observation(datetime(2024, 1, 16, 1, tzinfo=UTC), 8),
        observation(datetime(2024, 1, 17, tzinfo=UTC), 100),
        observation(datetime(2024, 1, 1, 2, tzinfo=UTC), 100),
    ]
    assert climatology_median(climate, net) == 6
    assert climatology_median([], net) is None


def test_request_limit_resume_and_corrupt_snapshot(tmp_path: Path) -> None:
    clock = Clock()
    calls: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200, content=b"recorded", headers={"date": "Thu, 05 Nov 2026 00:00:00 GMT"}
        )

    options = SnapshotOptions(request_limit=1, clock=clock.read, wait=clock.wait)
    with httpx.Client(
        transport=SnapshotTransport(tmp_path, httpx.MockTransport(upstream), options)
    ) as client:
        assert client.get("https://ll.thespacedevs.com/one").content == b"recorded"
        with pytest.raises(SliceCompleteError):
            client.get("https://ll.thespacedevs.com/two")
    with httpx.Client(
        transport=SnapshotTransport(tmp_path, httpx.MockTransport(upstream), options)
    ) as client:
        assert client.get("https://ll.thespacedevs.com/one").content == b"recorded"
        client.get("https://ll.thespacedevs.com/two")
    assert len(calls) == 2
    for asset in tmp_path.glob("*.gz"):
        asset.write_bytes(gzip.compress(b"changed"))
    with (
        httpx.Client(
            transport=SnapshotTransport(tmp_path, httpx.MockTransport(upstream), options)
        ) as client,
        pytest.raises(ValueError, match="integrity"),
    ):
        client.get("https://ll.thespacedevs.com/one")
    assert len(calls) == 2


def test_ll2_limit_survives_restart(tmp_path: Path) -> None:
    clock = Clock()
    sent: list[datetime] = []

    def upstream(_request: httpx.Request) -> httpx.Response:
        sent.append(clock.read())
        return httpx.Response(200, content=b"{}")

    options = SnapshotOptions(request_limit=15, clock=clock.read, wait=clock.wait)
    with httpx.Client(
        transport=SnapshotTransport(tmp_path, httpx.MockTransport(upstream), options)
    ) as client:
        for page in range(15):
            client.get(f"https://ll.thespacedevs.com/{page}")
    with httpx.Client(
        transport=SnapshotTransport(tmp_path, httpx.MockTransport(upstream), options)
    ) as client:
        client.get("https://ll.thespacedevs.com/16")
    assert sent[15] - sent[0] == timedelta(hours=1)
    assert all(
        sum(time - timedelta(hours=1) < other <= time for other in sent) <= 15 for time in sent
    )


def test_weather_measured_cost_paces_next_request_and_daily_limit(tmp_path: Path) -> None:
    clock = Clock()
    sent: list[datetime] = []

    def upstream(_request: httpx.Request) -> httpx.Response:
        sent.append(clock.read())
        return httpx.Response(200, content=b"{}", headers={"x-ratelimit-cost": "599.5"})

    options = SnapshotOptions(
        request_limit=3, clock=clock.read, wait=clock.wait, budget_directory=tmp_path / "ledger"
    )
    url = "https://previous-runs-api.open-meteo.com/v1/forecast"
    params = {
        "start_date": "2025-10-01",
        "end_date": "2025-10-31",
        "hourly": ",".join(["wind"] * 9),
        "models": "gfs",
    }
    with httpx.Client(
        transport=SnapshotTransport(tmp_path / "snapshots", httpx.MockTransport(upstream), options)
    ) as client:
        client.get(url, params=params)
        client.get(url, params={**params, "models": "ecmwf"})
    assert sent[1] - sent[0] == timedelta(minutes=1)
    append_row(
        tmp_path / "ledger",
        BudgetRow(sent_at=clock.read(), point_id="cape", status="fetched", cost_units=7400),
    )
    with (
        httpx.Client(
            transport=SnapshotTransport(
                tmp_path / "snapshots", httpx.MockTransport(upstream), options
            )
        ) as client,
        pytest.raises(SliceCompleteError),
    ):
        client.get(url, params={**params, "models": "third"})
    assert len(sent) == 2


def test_offline_missing_snapshot_never_reaches_transport(tmp_path: Path) -> None:
    def refuse(_request: httpx.Request) -> httpx.Response:
        message = "Network access is forbidden"
        raise AssertionError(message)

    options = SnapshotOptions(offline=True)
    with (
        httpx.Client(
            transport=SnapshotTransport(tmp_path, httpx.MockTransport(refuse), options)
        ) as client,
        pytest.raises(ValueError, match="Snapshot missing"),
    ):
        client.get("https://ll.thespacedevs.com/missing")


def test_lookalike_host_is_not_billed_as_weather(tmp_path: Path) -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{}")

    options = SnapshotOptions(budget_directory=tmp_path / "ledger")
    with httpx.Client(
        transport=SnapshotTransport(tmp_path / "snapshots", httpx.MockTransport(upstream), options)
    ) as client:
        assert client.get("https://evilopen-meteo.com/v1/forecast").status_code == 200


def test_failed_requests_still_consume_the_slice(tmp_path: Path) -> None:
    clock = Clock()
    options = SnapshotOptions(request_limit=1, clock=clock.read, wait=clock.wait)
    with httpx.Client(
        transport=SnapshotTransport(
            tmp_path, httpx.MockTransport(lambda _: httpx.Response(429)), options
        )
    ) as client:
        assert client.get("https://ll.thespacedevs.com/one").status_code == 429
        with pytest.raises(SliceCompleteError):
            client.get("https://ll.thespacedevs.com/two")
    assert not list(tmp_path.glob("*.gz"))


def test_shared_weather_cost_also_paces_backfill(tmp_path: Path) -> None:
    clock = Clock()
    append_row(
        tmp_path / "ledger",
        BudgetRow(sent_at=clock.read(), point_id="cape", status="fetched", cost_units=600),
    )
    sent: list[datetime] = []

    def upstream(_request: httpx.Request) -> httpx.Response:
        sent.append(clock.read())
        return httpx.Response(200, content=b"{}")

    options = SnapshotOptions(
        clock=clock.read, wait=clock.wait, budget_directory=tmp_path / "ledger"
    )
    with httpx.Client(
        transport=SnapshotTransport(tmp_path / "snapshots", httpx.MockTransport(upstream), options)
    ) as client:
        client.get(
            "https://previous-runs-api.open-meteo.com/forecast",
            params={
                "start_date": "2025-10-01",
                "end_date": "2025-10-31",
                "hourly": "wind",
                "models": "gfs",
            },
        )
    assert sent == [datetime(2026, 11, 5, 0, 1, tzinfo=UTC)]


def test_compressed_response_replays_decoded_bytes(tmp_path: Path) -> None:
    clock = Clock()
    options = SnapshotOptions(clock=clock.read, wait=clock.wait)
    upstream = httpx.MockTransport(
        lambda _: httpx.Response(
            200, content=gzip.compress(b'{"results":[]}'), headers={"content-encoding": "gzip"}
        )
    )
    with httpx.Client(transport=SnapshotTransport(tmp_path, upstream, options)) as client:
        assert client.get("https://ll.thespacedevs.com/compressed").content == b'{"results":[]}'
    with httpx.Client(
        transport=SnapshotTransport(tmp_path, upstream, SnapshotOptions(offline=True))
    ) as client:
        assert client.get("https://ll.thespacedevs.com/compressed").content == b'{"results":[]}'


def test_nearest_hour_and_window_keep_unevaluable_wind() -> None:
    payload = TypeAdapter(dict[str, JsonValue]).validate_json(
        Path("tests/fixtures/ll2_previous_florida.json").read_bytes()
    )
    launches = TypeAdapter(list[Launch]).validate_python(payload["results"])
    net = datetime(2025, 10, 1, 0, 30, tzinfo=UTC)
    launch = launches[0].model_copy(
        update={
            "net": net,
            "window_start": net.replace(minute=0),
            "window_end": net.replace(hour=2, minute=0),
            "rocket_name": "Falcon 9",
        }
    )
    hours = [net.replace(hour=hour, minute=0) for hour in range(3)]
    series = EnsembleSeries(
        "ecmwf",
        1,
        hours,
        {
            "wind_speed_10m": np.array([[2, 20, 2]], dtype=np.float32),
            "precipitation": np.array([[0, 0.4, 0]], dtype=np.float32),
        },
        GridPoint(28.5, -80.75, 5),
    )
    row = build_evidence(launch, series, StationInputs([], []), load_rules())
    assert row.wind_mps == 2
    assert row.verdicts["liftoff_wind"] is None
    assert row.verdicts["flight_through_precip"] is False
    assert row.window_verdicts["flight_through_precip"] is True
    assert row.observation_present is False
    assert row.observed_wind_mps is None
