import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import numpy as np
from pydantic import TypeAdapter

from scrubcast.budget.ledger import BudgetRow, append_row, read_month
from scrubcast.cli import Schedule, main
from scrubcast.forecast_cache import SavedForecast
from scrubcast.models.rules import Coordinates
from scrubcast.models.weather import GridPoint
from scrubcast.rules.loader import load_rules
from scrubcast.sources.open_meteo import OpenMeteoSource
from scrubcast.weather import VARIABLES, WeatherCollector

if TYPE_CHECKING:
    import pytest

    from scrubcast.models.launch import Launch

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = datetime(2026, 11, 5, 9, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW
        self.waits: list[float] = []

    def read(self) -> datetime:
        return self.now

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += timedelta(seconds=seconds)


def launches() -> list[Launch]:
    schedule = Schedule.model_validate_json(
        (Path(__file__).parents[1] / "golden/schedule.json").read_text(),
    )
    return [
        launch.model_copy(update={"net": NOW + timedelta(days=1)})
        for launch in schedule.launches
        if launch.pad.location.id in {12, 11}
    ]


def response(request: httpx.Request) -> httpx.Response:
    name = "cape" if request.url.params["latitude"].startswith("28") else "vandenberg"
    return httpx.Response(
        200,
        content=(FIXTURES / f"open_meteo_{name}.json").read_bytes(),
        headers={
            "Date": "Thu, 05 Nov 2026 09:00:00 GMT",
            "X-RateLimit-Cost": "344.4",
            "X-RateLimit-Remaining": "255.6",
        },
    )


def test_weather_cli_paces_persists_and_reuses(tmp_path: Path) -> None:
    clock = Clock()
    sends: list[datetime] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sends.append(clock.read())
        assert len(request.url.params["hourly"].split(",")) == 42
        return response(request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        collector = WeatherCollector(
            OpenMeteoSource(client), load_rules(), root=tmp_path, clock=clock.read, wait=clock.wait
        )
        forecasts = collector.run(launches(), NOW)
        assert set(forecasts) == {"cape", "vandenberg"}
        assert sends == [NOW, NOW + timedelta(minutes=1)]
        assert clock.waits == [60]
        paths = sorted((tmp_path / "data/weather").glob("*.json"))
        assert len(paths) == 2
        before = {path: path.read_bytes() for path in paths}
        cached = collector.run(launches(), clock.read())
        assert len(sends) == 2
        assert {path: path.read_bytes() for path in paths} == before
        for key, forecast in cached.items():
            for original, saved in zip(forecasts[key].series, forecast.series, strict=True):
                for variable, values in original.values.items():
                    np.testing.assert_array_equal(values, saved.values[variable])
        collector.run(launches(), clock.read(), force=True)
        assert len(sends) == 4
    rows = read_month(tmp_path / "ledger", "2026-11")
    assert len(rows) == 4
    assert all(row.cost_units == 344.4 and row.remaining_units == 255.6 for row in rows)
    assert all(not row.cost_mismatch for row in rows)


def test_weather_cli_upstream_429_preserves_cache_and_never_retries(tmp_path: Path) -> None:
    clock = Clock()
    calls: list[httpx.Request] = []
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        WeatherCollector(
            OpenMeteoSource(client), load_rules(), root=tmp_path, clock=clock.read, wait=clock.wait
        ).run(launches(), NOW)
    paths = list((tmp_path / "data/weather").glob("*.json"))
    before = {path: path.read_bytes() for path in paths}

    def limited(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            429, json={"error": True, "reason": "Rate limited"}, headers={"Retry-After": "60"}
        )

    with httpx.Client(transport=httpx.MockTransport(limited)) as client:
        saved = WeatherCollector(
            OpenMeteoSource(client), load_rules(), root=tmp_path, clock=clock.read, wait=clock.wait
        ).run(launches(), NOW, force=True)
    assert len(calls) == 2
    assert set(saved) == {"cape", "vandenberg"}
    assert {path: path.read_bytes() for path in paths} == before
    assert [row.status for row in read_month(tmp_path / "ledger", "2026-11")][-2:] == [
        "deferred_upstream_429",
        "deferred_upstream_429",
    ]


def test_weather_cli_budget_deferral_and_mismatch(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    append_row(
        tmp_path / "ledger",
        BudgetRow(
            sent_at=NOW - timedelta(hours=1),
            point_id="previous",
            status="fetched",
            cost_units=7000,
        ),
    )
    clock = Clock()
    calls: list[httpx.Request] = []

    def measured(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        result = response(request)
        result.headers["X-RateLimit-Cost"] = "350"
        return result

    with httpx.Client(transport=httpx.MockTransport(measured)) as client:
        forecasts = WeatherCollector(
            OpenMeteoSource(client), load_rules(), root=tmp_path, clock=clock.read, wait=clock.wait
        ).run(launches(), NOW)
    assert len(calls) == 1
    assert len(forecasts) == 1
    rows = read_month(tmp_path / "ledger", "2026-11")
    assert sum(row.status == "deferred_budget" for row in rows) == 1
    assert rows[-1].cost_units == 350
    assert rows[-1].cost_mismatch
    assert "Cost mismatch" in caplog.text


def test_weather_cli_command_and_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scrubcast.cli.FIXTURES", FIXTURES)
    (tmp_path / "data").mkdir()
    (tmp_path / "data/schedule.json").write_text(
        Schedule(generated_at=NOW, launches=launches()[:1]).model_dump_json(),
    )
    main(["weather", "--fixtures"])
    path = next((tmp_path / "data/weather").glob("*.json"))
    saved = SavedForecast.model_validate_json(path.read_text())
    assert saved.series
    main(["weather", "--fixtures"])
    assert len(read_month(tmp_path / "ledger", "2026-11")) == 1
    main(["weather", "--fixtures", "--force"])
    assert len(read_month(tmp_path / "ledger", "2026-11")) == 2


def test_weather_cli_measured_cost_reduces_remaining_daily_budget(tmp_path: Path) -> None:
    append_row(
        tmp_path / "ledger",
        BudgetRow(
            sent_at=NOW - timedelta(hours=1),
            point_id="previous",
            status="fetched",
            cost_units=6800,
        ),
    )
    clock = Clock()
    sends: list[datetime] = []

    def expensive(request: httpx.Request) -> httpx.Response:
        sends.append(clock.read())
        result = response(request)
        result.headers["X-RateLimit-Cost"] = "400"
        return result

    with httpx.Client(transport=httpx.MockTransport(expensive)) as client:
        WeatherCollector(
            OpenMeteoSource(client), load_rules(), root=tmp_path, clock=clock.read, wait=clock.wait
        ).run(launches(), NOW)
    assert len(sends) == 1
    rows = read_month(tmp_path / "ledger", "2026-11")
    assert rows[-1].status == "deferred_budget"
    assert sum(row.cost_units for row in rows) == 7200


def test_weather_cli_paces_across_month_boundary(tmp_path: Path) -> None:
    clock = Clock()
    clock.now = datetime(2026, 12, 1, tzinfo=UTC)
    append_row(
        tmp_path / "ledger",
        BudgetRow(
            sent_at=clock.now - timedelta(seconds=10),
            point_id="previous",
            status="fetched",
            cost_units=344.4,
        ),
    )
    selected = [
        launch.model_copy(update={"net": clock.now + timedelta(days=1)})
        for launch in launches()[:1]
    ]
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        WeatherCollector(
            OpenMeteoSource(client), load_rules(), root=tmp_path, clock=clock.read, wait=clock.wait
        ).run(selected, clock.read())
    assert clock.waits == [50]
    rows = read_month(tmp_path / "ledger", "2026-12")
    assert len(rows) == 1
    assert rows[0].sent_at == datetime(2026, 12, 1, 0, 0, 50, tzinfo=UTC)


def test_weather_cli_tier_c_deduplicates_returned_cells(tmp_path: Path) -> None:
    clock = Clock()
    # Two locations at the recorded Tanegashima request point share its returned cell.
    selected = [_tier_c_launch(location_id, 30.400938, 130.97564) for location_id in (9001, 9002)]
    calls: list[httpx.Request] = []

    def single_model(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.params["models"] == "ecmwf_ifs025"
        return httpx.Response(
            200,
            content=(FIXTURES / "open_meteo_tierc_ecmwf_only.json").read_bytes(),
            headers={
                "Date": "Thu, 05 Nov 2026 09:00:00 GMT",
                "X-RateLimit-Cost": "214.2",
                "X-RateLimit-Remaining": "385.8",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(single_model)) as client:
        collector = WeatherCollector(
            OpenMeteoSource(client), load_rules(), root=tmp_path, clock=clock.read, wait=clock.wait
        )
        collector.run(selected, NOW)
        assert len(calls) == 2
        assert (tmp_path / "data/cells.json").exists()
        saved = collector.run(selected, NOW, force=True)
        assert len(calls) == 3
        assert saved["location-9001"] is saved["location-9002"]


def _tier_c_launch(location_id: int, latitude: float, longitude: float) -> Launch:
    launch = launches()[0]
    location = launch.pad.location.model_copy(update={"id": location_id})
    pad = launch.pad.model_copy(
        update={"latitude": latitude, "longitude": longitude, "location": location}
    )
    return launch.model_copy(update={"id": f"generic-{location_id}", "pad": pad})


def _snapped(request: httpx.Request) -> httpx.Response:
    """Answer at the 0.25 degree cell nearest the requested point, as the API does."""
    payload = json.loads((FIXTURES / "open_meteo_tierc_ecmwf_only.json").read_text())
    payload["latitude"] = round(float(request.url.params["latitude"]) * 4) / 4
    payload["longitude"] = round(float(request.url.params["longitude"]) * 4) / 4
    return httpx.Response(
        200,
        json=payload,
        headers={
            "Date": "Thu, 05 Nov 2026 09:00:00 GMT",
            "X-RateLimit-Cost": "214.2",
            "X-RateLimit-Remaining": "385.8",
        },
    )


def test_weather_cli_ignores_cells_and_files_learned_at_other_coordinates(
    tmp_path: Path,
) -> None:
    # One LL2 location can move between pads hundreds of kilometres apart (sea platforms),
    # so a cell or file saved for its earlier pad must not stand in for the current one.
    sea = _tier_c_launch(3, 33.216667, 126.366667)
    inland = _tier_c_launch(17, 40.960556, 100.298333)
    elsewhere = GridPoint(latitude=30.5, longitude=131.0, elevation=17.0)
    (tmp_path / "data/weather").mkdir(parents=True)
    (tmp_path / "data/cells.json").write_text(
        TypeAdapter(dict[str, GridPoint])
        .dump_json({"location-3": elsewhere, "location-17": elsewhere})
        .decode()
    )
    with httpx.Client(transport=httpx.MockTransport(_snapped)) as client:
        recorded = OpenMeteoSource(client).forecast(
            Coordinates(latitude=elsewhere.latitude, longitude=elsewhere.longitude),
            ("ecmwf",),
            VARIABLES,
            10,
        )
    stale = SavedForecast.from_response(replace(recorded, fetched_at=NOW - timedelta(hours=1)))
    for point_id in ("location-3", "location-17"):
        (tmp_path / f"data/weather/{point_id}.json").write_text(stale.model_dump_json())
    clock = Clock()
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _snapped(request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        forecasts = WeatherCollector(
            OpenMeteoSource(client), load_rules(), root=tmp_path, clock=clock.read, wait=clock.wait
        ).run([sea, inland], NOW)

    assert len(calls) == 2
    cells = {
        point_id: (forecast.series[0].grid_point.latitude, forecast.series[0].grid_point.longitude)
        for point_id, forecast in forecasts.items()
    }
    assert cells == {"location-3": (33.25, 126.25), "location-17": (41.0, 100.25)}


def test_weather_cli_source_failure_keeps_cache_and_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    clock = Clock()
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        WeatherCollector(
            OpenMeteoSource(client), load_rules(), root=tmp_path, clock=clock.read, wait=clock.wait
        ).run(launches(), NOW)
    paths = sorted((tmp_path / "data/weather").glob("*.json"))
    before = {path: path.read_bytes() for path in paths}
    calls: list[httpx.Request] = []

    def unreachable(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.params["latitude"].startswith("28"):
            message = "Connection refused"
            raise httpx.ConnectError(message, request=request)
        return httpx.Response(502, text="Bad Gateway")

    with httpx.Client(transport=httpx.MockTransport(unreachable)) as client:
        saved = WeatherCollector(
            OpenMeteoSource(client), load_rules(), root=tmp_path, clock=clock.read, wait=clock.wait
        ).run(launches(), clock.read(), force=True)

    assert len(calls) == 2
    assert set(saved) == {"cape", "vandenberg"}
    assert {path: path.read_bytes() for path in paths} == before
    assert "cape: refresh failed, keeping the forecast fetched 2026-11-05 09:00 UTC" in caplog.text
    assert "Connection refused" in caplog.text
    assert "vandenberg: refresh failed" in caplog.text
