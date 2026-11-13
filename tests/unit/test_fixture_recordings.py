import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"
LEVELS = (1000, 925, 850, 700, 600, 500, 400, 300, 250, 200)
VARIABLES = (
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_speed_100m",
    "precipitation",
    "cape",
    "cloud_cover_high",
    *(
        f"{name}_{level}hPa"
        for name in ("temperature", "cloud_cover", "geopotential_height")
        for level in LEVELS
    ),
    *(f"wind_speed_{level}hPa" for level in (500, 300, 250, 200)),
    *(f"wind_direction_{level}hPa" for level in (500, 250)),
)


def test_fixture_recorded_at() -> None:
    lines = (FIXTURES / "RECORDED_AT").read_text().splitlines()
    assert len(lines) == 1
    now = datetime.fromisoformat(lines[0])
    assert now.utcoffset() == UTC.utcoffset(now)
    requests = [json.loads(line) for line in (FIXTURES / "requests.jsonl").read_text().splitlines()]
    upcoming = next(row for row in requests if row["file"] == "ll2_upcoming.json")
    assert upcoming["requested_at"] == lines[0]


@pytest.mark.parametrize(
    ("filename", "count"),
    [
        ("ll2_upcoming.json", 12),
        ("ll2_2.4.0_upcoming.json", 12),
        ("ll2_previous_detailed.json", 20),
        ("ll2_2.4.0_previous_detailed.json", 20),
        ("ll2_previous_florida.json", 100),
    ],
)
def test_fixture_launch_counts(filename: str, count: int) -> None:
    rows = json.loads((FIXTURES / filename).read_text())["results"]
    assert len(rows) == count
    assert len({row["id"] for row in rows}) == count
    for row in rows:
        assert row["rocket"]["configuration"]["name"]
        assert row["status"]["abbrev"]
        assert "probability" in row
        assert "weather_concerns" in row
        assert datetime.fromisoformat(row["net"]).tzinfo is not None


def test_fixture_launch_selection() -> None:
    response = json.loads((FIXTURES / "ll2_upcoming.json").read_text())
    rows = response["results"]
    locations = {row["pad"]["location"]["id"] for row in rows}
    assert locations & {12, 27}
    assert 11 in locations
    assert 143 in locations
    assert locations - {12, 27, 11, 143, 21}
    assert any(
        row["mission"] is not None
        and row["mission"]["orbit"] is not None
        and row["mission"]["orbit"]["abbrev"] == "Sub"
        for row in rows
    )
    assert any(row["net_precision"]["abbrev"] == "M" for row in rows)
    florida = json.loads((FIXTURES / "ll2_previous_florida.json").read_text())["results"]
    assert {row["pad"]["location"]["id"] for row in florida} <= {12, 27}
    assert any(row["probability"] is not None and row["weather_concerns"] for row in florida)


def test_fixture_upcoming_2_4_0_selection() -> None:
    rows = json.loads((FIXTURES / "ll2_2.4.0_upcoming.json").read_text())["results"]
    assert {row["pad"]["location"]["id"] for row in rows} >= {12, 11, 143}
    assert any(
        row["mission"] is not None
        and row["mission"]["orbit"] is not None
        and row["mission"]["orbit"]["abbrev"] == "Sub"
        for row in rows
    )
    assert any(row["net_precision"]["abbrev"] == "M" for row in rows)


def test_fixture_previous_versions_and_scrub_evidence() -> None:
    old = json.loads((FIXTURES / "ll2_previous_detailed.json").read_text())["results"]
    new = json.loads((FIXTURES / "ll2_2.4.0_previous_detailed.json").read_text())["results"]
    assert [row["id"] for row in old] == [row["id"] for row in new]
    for rows in (old, new):
        comments = [update["comment"] for row in rows for update in row["updates"]]
        assert "Launch delayed due to launch site weather, new date TBD." in comments
        assert "Scrubbed for the day due to TEL arm hydraulics issue." in comments
    assert all("holdreason" not in row for row in new)


@pytest.mark.parametrize(
    ("filename", "suffixes"),
    [
        ("open_meteo_cape.json", {"ecmwf_ifs025_ensemble": 51, "ncep_gefs_seamless": 31}),
        ("open_meteo_vandenberg.json", {"ecmwf_ifs025_ensemble": 51, "ncep_gefs_seamless": 31}),
        ("open_meteo_tierc_ecmwf_only.json", {"": 51}),
    ],
)
def test_fixture_ensemble_wire_shape(filename: str, suffixes: dict[str, int]) -> None:
    response = json.loads((FIXTURES / filename).read_text())
    hourly = response["hourly"]
    units = response["hourly_units"]
    assert len(VARIABLES) == 42
    assert len(hourly["time"]) == 72
    expected = {"time"}
    for suffix, members in suffixes.items():
        for variable in VARIABLES:
            base = f"{variable}_{suffix}" if suffix else variable
            for member in range(members):
                member_name = f"{variable}_member{member:02d}" if member else variable
                key = f"{member_name}_{suffix}" if suffix else member_name
                expected.add(key)
                assert len(hourly[key]) == 72
                if variable.startswith(("wind_speed", "wind_gusts")):
                    assert units[key] == "m/s"
            if variable == "cloud_cover_high" and suffix == "ncep_gefs_seamless":
                assert all(value is None for value in hourly[base])
    assert set(hourly) == expected
    now = datetime.fromisoformat((FIXTURES / "RECORDED_AT").read_text().strip())
    assert hourly["time"][0].startswith(now.date().isoformat())


@pytest.mark.parametrize(
    "filename",
    [
        "open_meteo_cape.json",
        "open_meteo_vandenberg.json",
        "open_meteo_tierc_ecmwf_only.json",
        "historical_cape_2025-10.json",
        "previous_runs_cape_2025-10.json",
    ],
)
def test_fixture_response_headers(filename: str) -> None:
    headers = (FIXTURES / "headers" / f"{Path(filename).stem}.txt").read_text().lower()
    assert "200" in headers.splitlines()[0]
    assert "date:" in headers
    assert "x-ratelimit-cost:" in headers
    assert "x-ratelimit-remaining:" in headers
    assert json.loads((FIXTURES / filename).read_text())["hourly"]["time"]


def test_fixture_historical_wire_shape() -> None:
    response = json.loads((FIXTURES / "historical_cape_2025-10.json").read_text())
    hourly = response["hourly"]
    assert len(hourly["time"]) == 744
    assert hourly["time"][0] == "2025-10-01T00:00"
    assert hourly["time"][-1] == "2025-10-31T23:00"
    for variable in VARIABLES:
        for model in ("ecmwf_ifs025", "gfs_seamless"):
            assert len(hourly[f"{variable}_{model}"]) == 744


def test_fixture_previous_runs_wire_shape() -> None:
    response = json.loads((FIXTURES / "previous_runs_cape_2025-10.json").read_text())
    hourly = response["hourly"]
    assert len(hourly["time"]) == 744
    for model in ("ecmwf_ifs025", "gfs_seamless"):
        for variable in ("wind_speed_10m", "wind_speed_100m", "precipitation"):
            for day in (1, 2, 3):
                key = f"{variable}_previous_day{day}_{model}"
                assert len(hourly[key]) == 744
                assert any(value is not None for value in hourly[key])


def test_fixture_metar_wire_shape() -> None:
    with (FIXTURES / "iem_xmr_2025-10.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows
    assert {row["station"] for row in rows} == {"XMR"}
    assert all(row["valid"].startswith("2025-10-") for row in rows)
    assert any(row["sknt"] != "M" for row in rows)
    assert all(key in rows[0] for key in ("gust", "p01i", "skyc1", "skyl1", "skyc3", "skyl3"))


def test_fixture_checksums() -> None:
    for line in (FIXTURES / "SHA256SUMS").read_text().splitlines():
        checksum, filename = line.split("  ", maxsplit=1)
        assert hashlib.sha256((FIXTURES / filename).read_bytes()).hexdigest() == checksum
