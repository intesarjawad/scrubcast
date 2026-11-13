from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic import JsonValue, TypeAdapter

from scrubcast.models.launch import Launch, LaunchDetailed
from scrubcast.models.rules import Coordinates
from scrubcast.sources.errors import SourceError
from scrubcast.sources.historical import HistoricalSource
from scrubcast.sources.iem import IEM_MIN_INTERVAL_S, IEMSource
from scrubcast.sources.launch_library import (
    LL2_BASE_URL,
    LL2_REQUESTS_PER_HOUR,
    RequestCounter,
    fetch_previous,
    fetch_upcoming,
)
from scrubcast.sources.open_meteo import OpenMeteoSource

if TYPE_CHECKING:
    from scrubcast.models.weather import EnsembleModel
    from scrubcast.sources.weather_source import WeatherSource

FIXTURES = Path(__file__).parents[1] / "fixtures"
SINCE = datetime(2025, 10, 1, tzinfo=UTC)


def _rows(filename: str = "ll2_upcoming.json") -> list[dict[str, JsonValue]]:
    data = TypeAdapter(dict[str, JsonValue]).validate_json((FIXTURES / filename).read_text())
    return TypeAdapter(list[dict[str, JsonValue]]).validate_python(data["results"])


def test_ll2_upcoming_200() -> None:
    rows = _rows()

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/2.3.0/launches/upcoming/"
        assert dict(request.url.params) == {"format": "json", "limit": "100", "mode": "normal"}
        return httpx.Response(200, json={"next": None, "results": rows})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        launches = fetch_upcoming(client)

    assert launches == [Launch.model_validate(row) for row in rows]


def test_ll2_upcoming_reads_one_page() -> None:
    rows = _rows()
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json={"next": f"{LL2_BASE_URL}upcoming/?offset=100", "results": rows}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        launches = fetch_upcoming(client)

    assert len(requests) == 1
    assert launches == [Launch.model_validate(row) for row in rows]


def test_ll2_upcoming_single_launch_is_one_request() -> None:
    rows = _rows()[:1]
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.params["id"] == "54d471e8-695c-4fa7-a3cf-dbd8b389e8ae"
        return httpx.Response(200, json={"next": None, "results": rows})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        launches = fetch_upcoming(client, "54d471e8-695c-4fa7-a3cf-dbd8b389e8ae")

    assert len(requests) == 1
    assert launches == [Launch.model_validate(row) for row in rows]


@pytest.mark.parametrize("mode", ["normal", "detailed"])
def test_ll2_previous_paging(mode: str) -> None:
    rows = _rows("ll2_previous_detailed.json")
    requests: list[httpx.Request] = []
    next_url = f"{LL2_BASE_URL}previous/?offset=100&mode={mode}"

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            assert request.url.params["net__gte"] == SINCE.isoformat()
            assert request.url.params["location__ids"] == "12,27"
            assert request.url.params["mode"] == mode
            assert request.url.params["limit"] == "100"
            return httpx.Response(200, json={"next": next_url, "results": rows[:1]})
        assert str(request.url) == next_url
        return httpx.Response(200, json={"next": None, "results": rows[1:]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        if mode == "normal":
            launches = fetch_previous(client, SINCE, [12, 27], "normal")
            assert all(type(launch) is Launch for launch in launches)
        else:
            launches = fetch_previous(client, SINCE, [12, 27], "detailed")
            assert all(isinstance(launch, LaunchDetailed) for launch in launches)
    assert [launch.id for launch in launches] == [row["id"] for row in rows]
    assert len(requests) == 2


@pytest.mark.parametrize("detailed", [False, True])
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", {"abbrev": "New Status"}, "New Status"),
        ("net", "invalid timestamp", "invalid timestamp"),
        ("probability", 101, "less than or equal to 100"),
    ],
)
def test_ll2_validation_error_skips_only_bad_launch(
    caplog: pytest.LogCaptureFixture,
    field: str,
    value: JsonValue,
    message: str,
    *,
    detailed: bool,
) -> None:
    rows = _rows("ll2_previous_detailed.json" if detailed else "ll2_upcoming.json")[:3]
    rows[0]["net_precision"] = None
    rows[1][field] = value
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if not detailed:
            return httpx.Response(200, json={"next": None, "results": rows})
        if len(requests) == 1:
            return httpx.Response(200, json={"next": "?offset=400", "results": rows[:2]})
        assert request.url.params["offset"] == "400"
        return httpx.Response(200, json={"next": None, "results": rows[2:]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        launches = fetch_previous(client, SINCE) if detailed else fetch_upcoming(client)
    assert [launch.id for launch in launches] == [rows[0]["id"], rows[2]["id"]]
    assert launches[0].net_precision is None
    assert len(requests) == (2 if detailed else 1)
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "WARNING"
    assert str(rows[1]["id"]) in caplog.text
    assert message in caplog.text


@pytest.mark.parametrize("row", [{"id": "broken"}, {}])
def test_ll2_missing_fields_skips_launch(
    row: dict[str, JsonValue], caplog: pytest.LogCaptureFixture
) -> None:
    rows = _rows()[:1]

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"next": None, "results": [row, *rows]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        launches = fetch_upcoming(client)

    assert [launch.id for launch in launches] == [rows[0]["id"]]
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "WARNING"
    assert str(row.get("id")) in caplog.text
    assert "Field required" in caplog.text


@pytest.mark.parametrize("retry_after", ["300", "Wed, 05 Nov 2026 18:00:00 GMT", None])
def test_ll2_429_does_not_retry_in_run(retry_after: str | None) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        headers = {} if retry_after is None else {"Retry-After": retry_after}
        return httpx.Response(429, headers=headers)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(SourceError) as caught:
            fetch_upcoming(client)
        assert caught.value.status == 429
        assert caught.value.retry_after == retry_after
        assert "upcoming/" in caught.value.url
        with pytest.raises(SourceError) as deferred:
            fetch_previous(client, SINCE)
        assert deferred.value.retry_after == retry_after
    assert len(requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"{}",
        b'{"next": null, "results": [null]}',
    ],
)
def test_ll2_malformed_response_has_url(body: bytes) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(SourceError, match=r"https://ll\.thespacedevs\.com/") as caught,
    ):
        fetch_upcoming(client)
    assert caught.value.status == 200


def test_ll2_counter_shared_across_endpoints_and_rolling_hour() -> None:
    now = [0.0]
    counter = RequestCounter(clock=lambda: now[0])
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"next": None, "results": []})

    with httpx.Client(
        transport=httpx.MockTransport(respond),
        event_hooks={"request": [counter]},
    ) as client:
        fetch_upcoming(client)
        now[0] = 1.0
        for _ in range(LL2_REQUESTS_PER_HOUR - 1):
            fetch_previous(client, SINCE)
        now[0] = 3599.0
        with pytest.raises(SourceError, match="budget exhausted"):
            fetch_upcoming(client)
        assert len(requests) == LL2_REQUESTS_PER_HOUR
        now[0] = 3600.0
        fetch_upcoming(client)
        with pytest.raises(SourceError, match="budget exhausted"):
            fetch_previous(client, SINCE)
        now[0] = 3601.0
        fetch_previous(client, SINCE)
    assert len(requests) == LL2_REQUESTS_PER_HOUR + 2


def test_ll2_automatic_counter_and_independent_clients() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"next": None, "results": []})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        for _ in range(LL2_REQUESTS_PER_HOUR):
            fetch_upcoming(client)
        with pytest.raises(SourceError, match="budget exhausted"):
            fetch_previous(client, SINCE)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert fetch_upcoming(client) == []


@pytest.mark.parametrize("status", [403, 500])
def test_ll2_http_failure(status: int) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(SourceError) as caught,
    ):
        fetch_upcoming(client)
    assert caught.value.status == status


def test_ll2_network_failure() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        message = "connection failed"
        raise httpx.ConnectError(message, request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(SourceError, match="connection failed") as caught,
    ):
        fetch_upcoming(client)
    assert caught.value.status is None


@pytest.mark.parametrize(
    "next_url",
    [
        "https://example.org/",
        str(
            httpx.URL(
                f"{LL2_BASE_URL}previous/",
                params={
                    "format": "json",
                    "limit": 100,
                    "mode": "detailed",
                    "net__gte": SINCE.isoformat(),
                },
            )
        ),
    ],
)
def test_ll2_rejects_invalid_paging(next_url: str) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"next": next_url, "results": []})

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(SourceError, match="pagination URL"),
    ):
        fetch_previous(client, SINCE)
    assert len(requests) == 1


OPEN_METEO_POINT = Coordinates(latitude=28.5618, longitude=-80.577)


def _open_meteo_headers(filename: str = "open_meteo_cape") -> dict[str, str]:
    recording = (FIXTURES / "headers" / f"{filename}.txt").read_text()
    lines = recording.replace(r"\r\n", "\n").splitlines()
    return dict(line.split(": ", 1) for line in lines if ": " in line)


@pytest.mark.parametrize(
    ("filename", "models", "cost", "remaining", "members"),
    [
        ("open_meteo_cape", ["ecmwf", "gfs"], 344.4, 255.6, [51, 31]),
        ("open_meteo_vandenberg", ["ecmwf", "gfs"], 344.4, 0.0, [51, 31]),
        ("open_meteo_tierc_ecmwf_only", ["ecmwf"], 214.2, 385.8, [51]),
    ],
)
def test_open_meteo_recorded_response(
    filename: str,
    models: list[EnsembleModel],
    cost: float,
    remaining: float,
    members: list[int],
) -> None:
    headers = _open_meteo_headers(filename)

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=(FIXTURES / f"{filename}.json").read_bytes(), headers=headers
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source: WeatherSource = OpenMeteoSource(client)
        result = source.forecast(OPEN_METEO_POINT, models, ["wind_speed_10m"], 10)
    assert [series.members for series in result.series] == members
    assert result.cost_units == cost
    assert result.remaining_units == remaining
    assert result.fetched_at.tzinfo == UTC
    assert result.fetched_at.strftime("%a, %d %b %Y %H:%M:%S GMT") == headers["Date"]
    assert result.generationtime_ms > 0
    assert result.series[0].grid_point.latitude != OPEN_METEO_POINT.latitude


def test_open_meteo_golden_query() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == (
            "https://ensemble-api.open-meteo.com/v1/ensemble?"
            "latitude=28.5618&longitude=-80.577&models=ecmwf_ifs025%2Cgfs_seamless"
            "&forecast_days=10&timezone=UTC&wind_speed_unit=ms"
            "&hourly=precipitation%2Cwind_speed_10m"
        )
        return httpx.Response(
            200,
            content=(FIXTURES / "open_meteo_cape.json").read_bytes(),
            headers=_open_meteo_headers(),
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        OpenMeteoSource(client).forecast(
            OPEN_METEO_POINT, ["ecmwf", "gfs"], ["wind_speed_10m", "precipitation"], 10
        )


def test_open_meteo_rejects_wrong_wind_units() -> None:
    payload = (FIXTURES / "open_meteo_cape.json").read_text().replace('"m/s"', '"km/h"')

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers=_open_meteo_headers())

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(SourceError, match=r"wind_speed_10m.*km/h") as caught,
    ):
        OpenMeteoSource(client).forecast(OPEN_METEO_POINT, ["ecmwf", "gfs"], ["wind_speed_10m"], 10)
    assert caught.value.status == 200
    assert "wind_speed_unit=ms" in caught.value.url


@pytest.mark.parametrize("status", [200, 400, 429])
def test_open_meteo_error_reason(status: int) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            json={"error": True, "reason": "Request limit exceeded"},
            headers={"Retry-After": "60"},
        )

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(SourceError, match="Request limit exceeded") as caught,
    ):
        OpenMeteoSource(client).forecast(OPEN_METEO_POINT, ["ecmwf"], ["wind_speed_10m"], 10)
    assert caught.value.status == status
    assert caught.value.retry_after == "60"
    assert len(requests) == 1


@pytest.mark.parametrize("body", [b"not json", b"{}", b"[]"])
def test_open_meteo_malformed_response(body: bytes) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(SourceError) as caught,
    ):
        OpenMeteoSource(client).forecast(OPEN_METEO_POINT, ["ecmwf"], ["wind_speed_10m"], 10)
    assert caught.value.url.startswith("https://ensemble-api.open-meteo.com/")
    assert caught.value.status == 200


@pytest.mark.parametrize("header", ["X-RateLimit-Cost", "X-RateLimit-Remaining"])
@pytest.mark.parametrize("value", [None, "invalid", "nan", "-1"])
def test_open_meteo_invalid_cost_headers(header: str, value: str | None) -> None:
    headers = _open_meteo_headers()
    if value is None:
        del headers[header]
    else:
        headers[header] = value

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=(FIXTURES / "open_meteo_cape.json").read_bytes(), headers=headers
        )

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(SourceError, match=header.lower()),
    ):
        OpenMeteoSource(client).forecast(OPEN_METEO_POINT, ["ecmwf", "gfs"], ["wind_speed_10m"], 10)


def test_open_meteo_network_failure() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        message = "connection failed"
        raise httpx.ConnectError(message, request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(SourceError, match="connection failed") as caught,
    ):
        OpenMeteoSource(client).forecast(OPEN_METEO_POINT, ["ecmwf"], ["wind_speed_10m"], 10)
    assert caught.value.status is None


@pytest.mark.parametrize("status", [403, 429, 500])
@pytest.mark.parametrize("body", [b"unavailable", b"{}"])
def test_open_meteo_http_failure(status: int, body: bytes) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, content=body, headers={"Retry-After": "60"})

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(SourceError) as caught,
    ):
        OpenMeteoSource(client).forecast(OPEN_METEO_POINT, ["ecmwf"], ["wind_speed_10m"], 10)
    assert caught.value.status == status
    assert caught.value.retry_after == "60"
    assert len(requests) == 1


@pytest.mark.parametrize("date", [None, "invalid", "Thu, 05 Nov 2026 08:56:31 -0000"])
def test_open_meteo_invalid_fetch_date(date: str | None) -> None:
    headers = _open_meteo_headers()
    if date is None:
        del headers["Date"]
    else:
        headers["Date"] = date

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=(FIXTURES / "open_meteo_cape.json").read_bytes(), headers=headers
        )

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(SourceError) as caught,
    ):
        OpenMeteoSource(client).forecast(OPEN_METEO_POINT, ["ecmwf", "gfs"], ["wind_speed_10m"], 10)
    assert caught.value.status == 200


@pytest.mark.parametrize("previous", [False, True])
def test_historical_recorded_response_and_query(*, previous: bool) -> None:
    filename = "previous_runs_cape_2025-10" if previous else "historical_cape_2025-10"
    host = (
        "previous-runs-api.open-meteo.com" if previous else "historical-forecast-api.open-meteo.com"
    )

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == host
        assert request.url.path == "/v1/forecast"
        params = request.url.params
        assert params["models"] == ("ecmwf_ifs025" if previous else "ecmwf_ifs025,gfs_seamless")
        assert params["latitude"] == "28.5618"
        assert params["longitude"] == "-80.577"
        assert params["wind_speed_unit"] == "ms"
        assert params["timezone"] == "UTC"
        assert params["start_date"] == "2025-10-01"
        assert params["end_date"] == "2025-10-31"
        if previous:
            assert set(params["hourly"].split(",")) == {
                f"{variable}_previous_day{lead}"
                for variable in ("wind_speed_10m", "wind_speed_100m", "precipitation")
                for lead in (1, 2, 3)
            }
        else:
            assert params["hourly"] == "precipitation,wind_speed_10m"
        return httpx.Response(
            200,
            content=(FIXTURES / f"{filename}.json").read_bytes(),
            headers=_open_meteo_headers(filename),
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = HistoricalSource(client)
        start, end = date(2025, 10, 1), date(2025, 10, 31)
        if previous:
            series = source.previous_runs(OPEN_METEO_POINT, "ecmwf", start, end)
            assert {item.model for item in series} == {"ecmwf", "gfs"}
            assert all(set(item.leads) == {1, 2, 3} for item in series)
            # ECMWF, valid 2025-10-01 00:00: the three recorded forecasts are 4.48, 4.11, 3.11 m/s.
            assert [
                series[0].leads[lead].values["wind_speed_10m"][0, 0] for lead in (1, 2, 3)
            ] == pytest.approx([4.48, 4.11, 3.11])
            assert all(len(item.leads[1].hours) == 744 for item in series)
        else:
            result = source.forecast(
                OPEN_METEO_POINT, ["ecmwf", "gfs"], ["wind_speed_10m", "precipitation"], start, end
            )
            assert result.cost_units == 18.599998
            assert result.remaining_units == 576.4143
            assert result.fetched_at == datetime(2026, 11, 5, 9, 2, 57, tzinfo=UTC)
            assert {item.model for item in result.series} == {"ecmwf", "gfs"}
            assert all(item.members == 1 and len(item.hours) == 744 for item in result.series)
            # ECMWF, valid 2025-10-01 00:00: recorded wind 4.58 m/s and precipitation 0.1 mm.
            assert result.series[0].values["wind_speed_10m"][0, 0] == pytest.approx(4.58)
            assert result.series[0].values["precipitation"][0, 0] == pytest.approx(0.1)


@pytest.mark.parametrize("previous", [False, True])
@pytest.mark.parametrize("status", [200, 400, 429, 500])
@pytest.mark.parametrize("body", [b"not json", b"{}", b'{"error":true,"reason":"limit exceeded"}'])
def test_historical_failure_has_context(*, previous: bool, status: int, body: bytes) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, content=body, headers={"Retry-After": "60"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = HistoricalSource(client)
        if previous:
            with pytest.raises(SourceError) as caught:
                source.previous_runs(
                    OPEN_METEO_POINT, "ecmwf", date(2025, 10, 1), date(2025, 10, 31)
                )
        else:
            with pytest.raises(SourceError) as caught:
                source.forecast(
                    OPEN_METEO_POINT,
                    ["ecmwf"],
                    ["wind_speed_10m"],
                    date(2025, 10, 1),
                    date(2025, 10, 31),
                )
    assert caught.value.status == status
    assert caught.value.url == str(requests[0].url)
    assert len(requests) == 1
    assert caught.value.retry_after == "60"


def test_iem_recorded_response_and_query() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "mesonet.agron.iastate.edu"
        assert request.url.path == "/cgi-bin/request/asos.py"
        assert request.url.params.get_list("data") == [
            "sknt",
            "gust",
            "p01i",
            "skyc1",
            "skyl1",
            "skyc2",
            "skyl2",
            "skyc3",
            "skyl3",
        ]
        assert {key: value for key, value in request.url.params.items() if key != "data"} == {
            "station": "XMR",
            "year1": "2025",
            "month1": "1",
            "day1": "1",
            "year2": "2026",
            "month2": "1",
            "day2": "1",
            "tz": "Etc/UTC",
            "format": "onlycomma",
            "latlon": "yes",
            "missing": "M",
            "trace": "T",
            "report_type": "3",
        }
        return httpx.Response(200, content=(FIXTURES / "iem_xmr_2025-10.csv").read_bytes())

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        observations = IEMSource(client).metars("XMR", 2025)
    first = observations[0]
    # XMR 2025-10-01 01:55: 10 knots * 0.514444 = 5.14444 m/s; gust 17 = 8.745548.
    assert first.station == "XMR"
    assert first.valid == datetime(2025, 10, 1, 1, 55, tzinfo=UTC)
    assert first.wind_speed_mps == pytest.approx(5.14444)
    assert first.wind_gust_mps == pytest.approx(8.745548)
    assert first.precipitation_in == 0
    assert first.cloud_layers[0].cover == "FEW"
    assert first.cloud_layers[0].base_ft == 2200
    # XMR 2025-10-01 07:55 reports T precipitation and M gust; 03:55 also reports M gust.
    assert observations[6].precipitation_in == 0.0001
    assert observations[6].wind_gust_mps is None
    assert observations[2].wind_gust_mps is None
    assert first.cloud_layers[1].base_ft is None


@pytest.mark.parametrize("status", [200, 429, 500])
@pytest.mark.parametrize("body", [b"Too many requests from your IP address, slow down", b"not csv"])
def test_iem_failure_no_retry(status: int, body: bytes) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, content=body, headers={"Retry-After": "60"})

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(SourceError) as caught,
    ):
        IEMSource(client).metars("XMR", 2025)
    assert caught.value.status == status
    assert caught.value.retry_after == "60"
    assert caught.value.url == str(requests[0].url)
    assert len(requests) == 1


def test_iem_pacing_includes_failed_requests() -> None:
    now = [0.0]
    requests: list[float] = []
    waits: list[float] = []

    def wait(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    def respond(_request: httpx.Request) -> httpx.Response:
        requests.append(now[0])
        return httpx.Response(200, text="Too many requests from your IP address, slow down")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = IEMSource(client, clock=lambda: now[0], wait=wait)
        for year in (2024, 2025):
            with pytest.raises(SourceError, match="Too many requests"):
                source.metars("XMR", year)
        now[0] = 25
        with pytest.raises(SourceError):
            source.metars("TTS", 2025)
    assert IEM_MIN_INTERVAL_S == 10
    assert requests == [0, 10, 25]
    assert waits == [10]


@pytest.mark.parametrize("endpoint", ["historical", "previous_runs", "iem"])
def test_historical_iem_network_failure(endpoint: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        message = "connection failed"
        raise httpx.ConnectError(message, request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        if endpoint == "iem":
            with pytest.raises(SourceError, match="connection failed") as caught:
                IEMSource(client).metars("XMR", 2025)
        elif endpoint == "previous_runs":
            with pytest.raises(SourceError, match="connection failed") as caught:
                HistoricalSource(client).previous_runs(
                    OPEN_METEO_POINT, "gfs", date(2025, 10, 1), date(2025, 10, 31)
                )
        else:
            with pytest.raises(SourceError, match="connection failed") as caught:
                HistoricalSource(client).forecast(
                    OPEN_METEO_POINT,
                    ["ecmwf"],
                    ["wind_speed_10m"],
                    date(2025, 10, 1),
                    date(2025, 10, 31),
                )
    assert caught.value.status is None
