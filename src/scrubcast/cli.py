import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from pydantic import AwareDatetime, BaseModel, JsonValue, TypeAdapter

from scrubcast.archive.slices import save_slices
from scrubcast.assess.ledger import slice_to_ledger
from scrubcast.assess.pipeline import assess_cached, assess_launches
from scrubcast.audit.backfill import (
    START_DATE,
    SliceCompleteError,
    SnapshotOptions,
    SnapshotTransport,
    backfill_lock,
    run_backfill,
)
from scrubcast.audit.backfill import (
    render_validation as render_backfill_validation,
)
from scrubcast.audit.forecast_audit import (
    audit_forecasts,
    launch_footers,
    load_forecast_ledger,
    load_outcomes,
    read_forward_ledger,
)
from scrubcast.audit.observations import fetch_observations
from scrubcast.audit.outcomes import SOURCE_LOOKBACK, audit_attempts, open_attempts
from scrubcast.audit.report import render_validation as render_audit_validation
from scrubcast.build.badges import write_badges
from scrubcast.build.contracts import Hindcast
from scrubcast.build.site_data import Publication, write_site_data
from scrubcast.models.launch import Launch, LaunchStatus
from scrubcast.rules.loader import load_rules
from scrubcast.sources.errors import SourceError
from scrubcast.sources.launch_library import fetch_audit_launches, fetch_upcoming
from scrubcast.sources.open_meteo import OpenMeteoSource
from scrubcast.terminal.board import (
    DEFAULT_COUNT,
    PUBLISHED_DATA_URL,
    BoardOptions,
    run_next,
)
from scrubcast.weather import WeatherCollector as PacedWeatherCollector

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from scrubcast.rules.loader import RuleCatalog
    from scrubcast.sources.weather_source import ForecastResponse

NET_PRECISION_DAY_OR_FINER = frozenset({"SEC", "MIN", "HR", "AM", "PM", "DAY"})
UPCOMING_STATUSES = frozenset(
    {LaunchStatus.GO, LaunchStatus.TBC, LaunchStatus.TBD, LaunchStatus.HOLD},
)
_PACKAGED_FIXTURES = Path(str(files("scrubcast").joinpath("resources/fixtures")))
FIXTURES = (
    _PACKAGED_FIXTURES
    if _PACKAGED_FIXTURES.is_dir()
    else Path(__file__).resolve().parents[2] / "tests/fixtures"
)
logger = logging.getLogger(__name__)


@dataclass
class _FixtureClock:
    now: datetime

    def read(self) -> datetime:
        return self.now

    def wait(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Schedule(BaseModel):
    """Saved launches and source freshness; generated_at is the last successful fetch."""

    generated_at: AwareDatetime
    schedule_stale: bool = False
    launches: list[Launch]


type WeatherCollector = Callable[[Schedule, datetime], Mapping[str, ForecastResponse]]
type Assessor = Callable[[Schedule, Mapping[str, ForecastResponse], datetime], None]

# Launch paging and month-long historical queries often answer slower than httpx's five seconds.
HTTP_TIMEOUT = httpx.Timeout(10, read=60)


def collect(
    client: httpx.Client,
    now: datetime,
    catalog: RuleCatalog,
    weather: WeatherCollector,
    assess: Assessor | None = None,
) -> Path | None:
    """Refresh the schedule and weather, archive replay inputs, then assess launches."""
    schedule = write_schedule(client, now, Path("data/schedule.json"))
    forecasts = weather(schedule, now)
    available = [
        launch
        for launch in schedule.launches
        if (point := catalog.site_for(launch.pad).forecast_point) is not None
        and point.point_id in forecasts
    ]
    path = save_slices(Path("archive"), available, forecasts, catalog, now)
    if assess is not None:
        assess(schedule, forecasts, now)
    else:
        assess_launches(schedule.launches, forecasts, catalog, now)
    return path


def record_outcomes(client: httpx.Client, root: Path, now: datetime) -> int:
    """Save outcomes of attempts inside their audit interval and return how many were open."""
    rows = read_forward_ledger(root)
    attempts = open_attempts(rows, now)
    if not attempts:
        return 0
    since = min(attempt.attempt_net for attempt in attempts) - SOURCE_LOOKBACK
    outcomes = audit_attempts(
        rows,
        fetch_audit_launches(client, since),
        now,
        previous=load_outcomes(root).values(),
    )
    (root / "ledger/outcomes.jsonl").write_text(
        "".join(outcome.model_dump_json() + "\n" for outcome in outcomes)
    )
    return len(attempts)


def filter_schedule(launches: Sequence[Launch]) -> list[Launch]:
    """Keep upcoming orbital launches with a NET known to at least the day."""
    scheduled: list[Launch] = []
    for launch in launches:
        if launch.status not in UPCOMING_STATUSES:
            logger.info("Excluding launch %s: status %r is not upcoming", launch.id, launch.status)
            continue
        if (
            launch.mission is not None
            and launch.mission.orbit is not None
            and launch.mission.orbit.abbrev == "Sub"
        ):
            logger.info("Excluding launch %s: suborbital mission (Sub)", launch.id)
            continue
        if launch.net_precision not in NET_PRECISION_DAY_OR_FINER:
            logger.info(
                "Excluding launch %s: NET precision %r is coarser than a day or unknown",
                launch.id,
                launch.net_precision,
            )
            continue
        scheduled.append(launch)
    return scheduled


def write_schedule(client: httpx.Client, now: datetime, path: Path) -> Schedule:
    """Fetch and save the schedule, preserving the last good launches on source failure."""
    try:
        launches = fetch_upcoming(client)
    except SourceError as error:
        logger.warning("%s", error)
        if not path.exists():
            raise
        schedule = Schedule.model_validate_json(path.read_text()).model_copy(
            update={"schedule_stale": True},
        )
    else:
        schedule = Schedule(generated_at=now, launches=filter_schedule(launches))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(schedule.model_dump_json(indent=2) + "\n")
    return schedule


def fixture_response(_request: httpx.Request) -> httpx.Response:
    """Serve recorded schedule and weather responses without network access."""
    if _request.url.host == "ensemble-api.open-meteo.com":
        latitude = float(_request.url.params["latitude"])
        name = "cape" if latitude > 25 and latitude < 30 else "vandenberg"
        if _request.url.params["models"] == "ecmwf_ifs025":
            name = "tierc_ecmwf_only"
        headers = dict(
            line.split(": ", 1)
            for line in (FIXTURES / f"headers/open_meteo_{name}.txt").read_text().splitlines()
            if ": " in line
        )
        return httpx.Response(
            200, content=(FIXTURES / f"open_meteo_{name}.json").read_bytes(), headers=headers
        )
    response = TypeAdapter(dict[str, JsonValue]).validate_json(
        (FIXTURES / "ll2_upcoming.json").read_text(),
    )
    # The recorded selection is complete for offline runs, regardless of source pagination.
    response["next"] = None
    return httpx.Response(200, json=response)


def _positive_int(value: str) -> int:
    if not value.isdecimal() or int(value) < 1:
        message = f"expected a whole number of 1 or more, got {value!r}"
        raise argparse.ArgumentTypeError(message)
    return int(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrubcast",
        description=(
            "Scrub through a launch window and see which weather rules the forecast models break, "
            "hour by hour."
        ),
    )
    subcommands = parser.add_subparsers(dest="command")
    schedule_parser = subcommands.add_parser("schedule", help="Save upcoming orbital launches")
    schedule_parser.add_argument("--fixtures", action="store_true", help="Use recorded source data")
    collect_parser = subcommands.add_parser("collect", help="Save schedule, weather and raw slices")
    collect_parser.add_argument("--fixtures", action="store_true", help="Use recorded source data")
    weather_parser = subcommands.add_parser("weather", help="Refresh scheduled forecast points")
    weather_parser.add_argument("--fixtures", action="store_true", help="Use recorded source data")
    weather_parser.add_argument("--force", action="store_true", help="Refresh files newer than 5 h")
    collect_parser.add_argument("--force", action="store_true", help="Refresh files newer than 5 h")
    assess_parser = subcommands.add_parser("assess", help="Assess cached launch forecasts")
    assess_parser.add_argument("--fixtures", action="store_true", help="Use the recorded clock")
    build_parser = subcommands.add_parser("build", help="Publish static launch data and calendar")
    build_parser.add_argument("--fixtures", action="store_true", help="Use recorded source data")
    build_parser.add_argument("--no-weather", action="store_true", help="Assess cached forecasts")
    build_parser.add_argument(
        "--site-url",
        default=os.environ.get("SITE_URL", "/"),
        help="Published site URL including base path (defaults to SITE_URL)",
    )
    next_parser = subcommands.add_parser(
        "next", help="Print the next launches as a plain-text board"
    )
    next_parser.add_argument("--fixtures", action="store_true", help="Use recorded published data")
    next_parser.add_argument(
        "--data-url",
        default=PUBLISHED_DATA_URL,
        help="latest.json URL, or the path of a local build such as site/public/data/latest.json",
    )
    next_parser.add_argument(
        "--count", type=_positive_int, default=DEFAULT_COUNT, help="Launches to print"
    )
    outcomes_parser = subcommands.add_parser("audit", help="Record launch attempt outcomes")
    outcomes_parser.add_argument("--data-dir", type=Path, default=Path())
    for command, summary in (
        ("backfill", "Check retrospective launch weather"),
        ("hindcast", "Rebuild the validation report and badges from saved data"),
    ):
        audit_parser = subcommands.add_parser(command, help=summary)
        audit_parser.add_argument("--start", type=date.fromisoformat)
        audit_parser.add_argument("--end", type=date.fromisoformat)
        audit_parser.add_argument("--data-dir", type=Path, default=Path())
        audit_parser.add_argument("--request-limit", type=int, default=5)
        audit_parser.add_argument("--offline", action="store_true")
        audit_parser.add_argument("--fixtures", action="store_true")
        if command == "hindcast":
            audit_parser.add_argument(
                "--rescore",
                type=Path,
                nargs="?",
                const=Path("archive"),
                help="Rebuild ledger rows from archived ensemble slices",
            )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    weather_collector: WeatherCollector | None = None,
    assessor: Assessor | None = None,
) -> None:
    """Parse arguments for the launch weather command line."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "next":
        _next_command(parser, args)
        return
    if args.command == "audit":
        _audit_command(parser, args)
    elif args.command == "hindcast":
        _hindcast_locked(parser, args)
    elif args.command == "backfill":
        _backfill_locked(parser, args)
    elif args.command in {"schedule", "weather", "collect", "assess", "build"}:
        _run_pipeline(parser, args, weather_collector, assessor)


def _run_pipeline(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    weather_collector: WeatherCollector | None,
    assessor: Assessor | None,
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    catalog = load_rules()
    now = _clock_time(fixtures=args.fixtures)
    transport = httpx.MockTransport(fixture_response) if args.fixtures else None
    with httpx.Client(transport=transport, timeout=HTTP_TIMEOUT) as client:
        try:
            collector = PacedWeatherCollector(
                OpenMeteoSource(client),
                catalog,
            )
            if args.fixtures:
                fixture_clock = _FixtureClock(now)
                collector.clock = fixture_clock.read
                collector.wait = fixture_clock.wait

            def default_weather(schedule: Schedule, at: datetime) -> Mapping[str, ForecastResponse]:
                return collector.run(schedule.launches, at, force=getattr(args, "force", False))

            active_weather = weather_collector or default_weather
            if args.command == "collect":
                collect(client, now, catalog, active_weather, assessor)
            elif args.command == "build":
                schedule = write_schedule(client, now, Path("data/schedule.json"))
                cached = {path: path.read_bytes() for path in Path("data/weather").glob("*.json")}
                forecasts: Mapping[str, ForecastResponse] = (
                    {} if args.no_weather else active_weather(schedule, now)
                )
                assess = (
                    assess_launches
                    if not args.no_weather
                    and any(
                        cached.get(path) != path.read_bytes()
                        for path in Path("data/weather").glob("*.json")
                    )
                    else assess_cached
                )
                assessments = assess(
                    schedule.launches,
                    forecasts,
                    catalog,
                    now,
                )
                write_site_data(
                    schedule.launches,
                    assessments,
                    catalog,
                    now,
                    publication=Publication(
                        schedule_stale=schedule.schedule_stale,
                        site_url=args.site_url,
                        fixture_ledger=FIXTURES / "past" if args.fixtures else None,
                    ),
                )
            elif args.command == "assess":
                schedule = Schedule.model_validate_json(Path("data/schedule.json").read_text())
                assess_launches(schedule.launches, {}, catalog, now)
            elif args.command == "weather":
                schedule = Schedule.model_validate_json(Path("data/schedule.json").read_text())
                active_weather(schedule, now)
            else:
                write_schedule(client, now, Path("data/schedule.json"))
        except FileNotFoundError as error:
            if error.filename != "data/schedule.json":
                raise
            parser.exit(
                1, "No schedule found. Run `scrubcast schedule` or `scrubcast build` first.\n"
            )
        except SourceError as error:
            parser.exit(1, f"{error}\n")


def _next_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    code = run_next(
        BoardOptions(
            data_url=args.data_url,
            fixtures=args.fixtures,
            count=args.count,
            fixture_path=FIXTURES / "demo/latest.json",
        )
    )
    if code:
        parser.exit(code)


def _audit_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        try:
            now = datetime.now(UTC)
            count = record_outcomes(client, args.data_dir, now)
            fetch_observations(
                client, args.data_dir, read_forward_ledger(args.data_dir), load_rules(), now
            )
        except SourceError as error:
            parser.exit(1, f"{error}\n")
    sys.stdout.write(
        f"Audited attempts n={count}; outcomes: {args.data_dir / 'ledger/outcomes.jsonl'}\n"
    )


def _backfill_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    selection_path = args.data_dir / "data/backfill/selection.json"
    saved = (
        TypeAdapter(dict[str, str]).validate_json(selection_path.read_text())
        if selection_path.exists()
        else {}
    )
    offline = args.offline or args.command == "hindcast"
    args.start = args.start or (
        date.fromisoformat(saved["start"])
        if offline and saved
        else date(2025, 10, 1)
        if args.fixtures
        else START_DATE
    )
    end = args.end or (
        date.fromisoformat(saved["end"])
        if offline and saved
        else date(2025, 10, 31)
        if args.fixtures
        else datetime.now(UTC).date()
    )
    if args.start < START_DATE or end < args.start or args.request_limit < 1:
        parser.error("Use ordered dates from 2024-02-03 and a positive request limit")
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    selection_path.write_text(
        json.dumps({"start": args.start.isoformat(), "end": end.isoformat()}) + "\n"
    )
    upstream = httpx.MockTransport(_backfill_fixture) if args.fixtures else httpx.HTTPTransport()
    fixture_clock = _FixtureClock(datetime.now(UTC))
    options = SnapshotOptions(
        request_limit=args.request_limit,
        offline=args.offline or args.command == "hindcast",
        budget_directory=args.data_dir / "ledger",
    )
    if args.fixtures:
        options = SnapshotOptions(
            request_limit=args.request_limit,
            offline=args.offline or args.command == "hindcast",
            clock=fixture_clock.read,
            wait=fixture_clock.wait,
            budget_directory=args.data_dir / "ledger",
        )
    transport = SnapshotTransport(
        args.data_dir / "data/backfill/snapshots",
        upstream,
        options,
    )
    with httpx.Client(transport=transport, timeout=HTTP_TIMEOUT) as client:
        try:
            count = run_backfill(client, load_rules(), args.data_dir, args.start, end)
        except SliceCompleteError:
            sys.stdout.write(
                f"Saved {transport.sent} requests. Repeat the same command to continue.\n"
            )
        except (SourceError, ValueError) as error:
            parser.exit(1, f"{error}\n")
        else:
            sys.stdout.write(
                f"Backfill n={count}; tables: {args.data_dir / 'ledger/backfill-tables.json'}\n"
            )


def _backfill_fixture(request: httpx.Request) -> httpx.Response:
    names = {
        "ll.thespacedevs.com": "ll2_previous_florida.json",
        "historical-forecast-api.open-meteo.com": "historical_cape_2025-10.json",
        "previous-runs-api.open-meteo.com": "previous_runs_cape_2025-10.json",
        "mesonet.agron.iastate.edu": "iem_xmr_2025-10.csv",
    }
    name = names[request.url.host]
    content = (FIXTURES / name).read_bytes()
    if name.startswith("ll2"):
        payload = TypeAdapter(dict[str, JsonValue]).validate_json(content)
        payload["next"] = None
        return httpx.Response(200, json=payload)
    # The recording covers XMR in October 2025 only.
    if name.endswith("csv") and (
        request.url.params["station"] != "XMR" or request.url.params["year1"] != "2025"
    ):
        content = content.split(b"\n", 1)[0] + b"\n"
    headers = dict(
        line.split(": ", 1)
        for line in (FIXTURES / "headers" / f"{Path(name).stem}.txt").read_text().splitlines()
        if ": " in line
    )
    return httpx.Response(200, content=content, headers=headers)


def _clock_time(*, fixtures: bool) -> datetime:
    return (
        datetime.fromisoformat((FIXTURES / "RECORDED_AT").read_text().strip())
        if fixtures
        else datetime.now(UTC)
    )


def _backfill_locked(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    try:
        with backfill_lock(args.data_dir):
            _backfill_command(parser, args)
    except ValueError as error:
        parser.exit(1, f"{error}\n")


def _hindcast_locked(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    try:
        with backfill_lock(args.data_dir):
            _hindcast_command(parser, args)
    except ValueError as error:
        parser.exit(1, f"{error}\n")


def _hindcast_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.rescore is not None:
        _rescore(args.data_dir, args.rescore)
    else:
        _backfill_command(parser, args)
    now = (
        datetime.fromisoformat((FIXTURES / "RECORDED_AT").read_text().strip())
        if args.fixtures
        else datetime.now(UTC)
    )
    ledger = load_forecast_ledger(args.data_dir, load_rules())
    audit = audit_forecasts(ledger)
    hindcast = Hindcast(
        generated_at=now,
        lowest_hour_verified=audit.lowest_hour_verified,
        summary=[evaluation.summary for evaluation in audit.evaluations],
        forecast_audit=audit,
    )
    ledger_directory = args.data_dir / "ledger"
    ledger_directory.mkdir(parents=True, exist_ok=True)
    (ledger_directory / "hindcast.json").write_text(hindcast.model_dump_json(indent=2) + "\n")
    report = render_audit_validation(audit, now)
    tables = ledger_directory / "backfill-tables.json"
    if tables.exists() and audit.n_launches:
        previous = render_backfill_validation(
            TypeAdapter(dict[str, JsonValue]).validate_json(tables.read_text())
        )
        report = f"{previous.rstrip()}\n\n{report}"
        (ledger_directory / "validation.md").write_text(report)
    elif not tables.exists():
        (ledger_directory / "validation.md").write_text(report)
    write_badges(
        args.data_dir / "site/public/data/badges",
        hindcast.model_dump(mode="json"),
        now,
    )
    (ledger_directory / "audit-footers.json").write_text(
        json.dumps(
            {
                launch_id: [footer.model_dump(mode="json") for footer in footers]
                for launch_id, footers in launch_footers(ledger).items()
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    sys.stdout.write(
        f"Hindcast n={audit.n_launches}; validation: {ledger_directory / 'validation.md'}\n"
    )


def _rescore(root: Path, path: Path) -> None:
    paths = sorted(path.glob("*.npz")) if path.is_dir() else [path] if path.exists() else []
    rows = [row for asset in paths for row in slice_to_ledger(asset, load_rules())]
    if not rows:
        message = (
            f"No archived slices found at {path}. Next: copy slices-*.npz and their .json "
            "sidecars there, as docs/recipes.md shows, or pass their directory to --rescore."
        )
        raise ValueError(message)
    directory = root / "ledger"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "rescored.jsonl").write_text("".join(row.model_dump_json() + "\n" for row in rows))
    sys.stdout.write(f"Rescored n={len(rows)}; ledger: {directory / 'rescored.jsonl'}\n")
