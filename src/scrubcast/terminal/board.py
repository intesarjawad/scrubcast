"""Plain-text board of the next launches from the published index."""

import shutil
import sys
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import JsonValue, TypeAdapter, ValidationError

from scrubcast import messages
from scrubcast.build.contracts import Latest, LaunchSummary

if TYPE_CHECKING:
    from collections.abc import Sequence

PUBLISHED_DATA_URL = "https://scrubcast.intesarjawad.com/data/latest.json"
SUPPORTED_SCHEMA_VERSION = 1
DEFAULT_COUNT = 8
DEFAULT_FIXTURE = Path("tests/fixtures/demo/latest.json")
HTTP_TIMEOUT = httpx.Timeout(10, read=60)
# The site rebuilds hourly; three missed rebuilds mean the refresh has stopped.
MAX_DATA_AGE = timedelta(hours=3)


@dataclass(frozen=True)
class BoardOptions:
    """Where the board reads its index and how many launches it shows."""

    data_url: str = PUBLISHED_DATA_URL
    fixtures: bool = False
    count: int = DEFAULT_COUNT
    fixture_path: Path | None = None


class BoardError(Exception):
    """A user-facing failure with the message and exit code the CLI prints."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


def _utc_clock(moment: datetime) -> str:
    return f"{moment.astimezone(UTC):%Y-%m-%d %H:%M}"


def _utc_stamp(moment: datetime) -> str:
    return f"{_utc_clock(moment)} UTC"


def _local_stamp(moment: datetime, zone: str) -> str:
    try:
        local = moment.astimezone(ZoneInfo(zone))
    except ValueError, ZoneInfoNotFoundError:
        return _utc_stamp(moment)
    return f"{local:%Y-%m-%d %H:%M %Z}"


def _official(launch: LaunchSummary) -> str:
    if launch.probability is None:
        return "not published"
    return f"{launch.probability}% probability of GO"


def _wrap(text: str, columns: int, *, indent: str = "") -> list[str]:
    if len(indent) >= columns:
        indent = ""
    width = max(1, columns - len(indent))
    parts = textwrap.wrap(
        text,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [""]
    return [indent + part for part in parts]


def _launch_url(latest: Latest) -> str:
    if latest.launches:
        return f"https://ll.thespacedevs.com/2.4.0/launches/{latest.launches[0].id}/"
    return "https://thespacedevs.com/llapi"


def _fetch(client: httpx.Client, url: str) -> str:
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        status = error.response
        if status.status_code == HTTPStatus.NOT_FOUND:
            msg = messages.NOT_PUBLISHED.render(url=url)
            raise BoardError(msg) from error
        reason = f"HTTP {status.status_code} {status.reason_phrase}"
        msg = messages.NETWORK_FAILURE.render(url=url, reason=reason)
        raise BoardError(msg) from error
    except httpx.HTTPError as error:
        msg = messages.NETWORK_FAILURE.render(url=url, reason=str(error) or type(error).__name__)
        raise BoardError(msg) from error
    return response.text


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        msg = messages.UNREADABLE_FILE.render(path=path, reason=error.strerror or error)
        raise BoardError(msg) from error


def _local_path(data_url: str) -> Path | None:
    """Return the file a --data-url names, or None for a web address."""
    url = httpx.URL(data_url)
    if url.scheme == "file":
        return Path(url.path)
    return None if url.scheme in {"http", "https"} else Path(data_url)


def load_latest(options: BoardOptions, client: httpx.Client | None = None) -> Latest:
    """Read and validate the published index, rejecting unknown schema versions."""
    if options.fixtures:
        text = _read(options.fixture_path or DEFAULT_FIXTURE)
    elif (path := _local_path(options.data_url)) is not None:
        text = _read(path)
    elif client is None:
        with httpx.Client(timeout=HTTP_TIMEOUT) as owned:
            text = _fetch(owned, options.data_url)
    else:
        text = _fetch(client, options.data_url)
    try:
        payload = TypeAdapter(dict[str, JsonValue]).validate_json(text)
    except ValidationError as error:
        msg = messages.INVALID_DATA.render()
        raise BoardError(msg) from error
    version = payload.get("schema_version", SUPPORTED_SCHEMA_VERSION)
    if version != SUPPORTED_SCHEMA_VERSION:
        msg = messages.UNSUPPORTED_SCHEMA.render(
            version=version,
            supported=SUPPORTED_SCHEMA_VERSION,
        )
        raise BoardError(msg)
    try:
        return Latest.model_validate(payload)
    except ValidationError as error:
        msg = messages.INVALID_DATA.render()
        raise BoardError(msg) from error


def render_board(latest: Latest, *, columns: int, count: int = DEFAULT_COUNT) -> str:
    """Render the next launches in reading order, wrapped to the terminal width."""
    lines = ["Scrubcast launch weather"]
    lines.extend(
        _wrap(
            f"Generated {_utc_stamp(latest.generated_at)}. Members: {latest.members_total}.",
            columns,
        )
    )
    lines.append("")
    launches: Sequence[LaunchSummary] = sorted(
        latest.launches,
        key=lambda launch: (launch.net, launch.id),
    )[: max(0, count)]
    for index, launch in enumerate(launches, start=1):
        zone = launch.pad.location.timezone_name
        lines.extend(_wrap(f"{index}. {launch.name}", columns))
        lines.extend(
            _wrap(
                f"{launch.pad.name}, {launch.pad.location.name}",
                columns,
                indent="   ",
            )
        )
        lines.extend(
            _wrap(
                f"NET {_local_stamp(launch.net, zone)} ({_utc_stamp(launch.net)})",
                columns,
                indent="   ",
            )
        )
        lines.extend(
            _wrap(
                f"Window {_local_stamp(launch.window_start, zone)} to "
                f"{_local_stamp(launch.window_end, zone)}",
                columns,
                indent="   ",
            )
        )
        lines.extend(
            _wrap(
                f"({_utc_clock(launch.window_start)} to {_utc_clock(launch.window_end)} UTC)",
                columns,
                indent="          ",
            )
        )
        lines.extend(_wrap(f"Official: {_official(launch)}", columns, indent="   "))
        lines.extend(_wrap(f"Worst rule: {launch.worst_rule.label}", columns, indent="   "))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_next(
    options: BoardOptions | None = None,
    *,
    columns: int | None = None,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> int:
    """Print the board and return the process exit code.

    The output is plain text, so NO_COLOR needs no branch. Recorded fixtures are old by
    design, so only live or local data is checked for age.
    """
    options = options or BoardOptions()
    width = columns if columns is not None else shutil.get_terminal_size().columns
    try:
        latest = load_latest(options, client)
    except BoardError as error:
        sys.stderr.write(f"{error.message}\n")
        return error.exit_code
    age = (now or datetime.now(UTC)) - latest.generated_at
    if not options.fixtures and age > MAX_DATA_AGE:
        built = f"{latest.generated_at.astimezone(UTC):%Y-%m-%d %H:%M}"
        hours = age // timedelta(hours=1)
        sys.stdout.write(f"{messages.OLD_DATA.render(hours=hours, built=built)}\n")
    if latest.schedule_stale:
        sys.stdout.write(f"{messages.STALE.render(launch_url=_launch_url(latest))}\n")
    if not latest.launches:
        sys.stdout.write(f"{messages.NO_LAUNCHES.render()}\n")
        return 0
    sys.stdout.write(render_board(latest, columns=width, count=options.count))
    return 0
