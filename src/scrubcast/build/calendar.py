"""RFC 5545 launch events with UTF-8-safe content-line folding."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from scrubcast.build.contracts import LaunchSummary

MAX_LINE_OCTETS = 75
FORECAST_HORIZON = timedelta(days=10)
INSTANTANEOUS_PADDING = timedelta(hours=1)


def escape_text(value: str) -> str:
    """Escape TEXT property delimiters and normalize source newlines."""
    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def fold_line(value: str) -> str:
    """Count the continuation space within each physical line's octet limit."""
    lines: list[str] = []
    current = ""
    octets = 0
    for character in value:
        width = len(character.encode("utf-8"))
        if octets + width > MAX_LINE_OCTETS:
            lines.append(current)
            current, octets = " ", 1
        current += character
        octets += width
    lines.append(current)
    return "\r\n".join(lines)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def calendar(launches: Sequence[LaunchSummary], now: datetime) -> str:
    """Render ten days of launch windows using the supplied publication time."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Scrubcast//Launch weather//EN"]
    for launch in sorted(launches, key=lambda item: (item.net, item.id)):
        if not now <= launch.net <= now + FORECAST_HORIZON:
            continue
        start, end = launch.window_start, launch.window_end
        if end <= start:
            start, end = launch.net - INSTANTANEOUS_PADDING, launch.net + INSTANTANEOUS_PADDING
        official = (
            f"Official: {launch.probability}% probability of GO"
            if launch.probability is not None
            else "Official forecast unavailable"
        )
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{escape_text(launch.id)}@scrubcast",
                f"DTSTAMP:{_timestamp(now)}",
                f"LAST-MODIFIED:{_timestamp(now)}",
                f"DTSTART:{_timestamp(start)}",
                f"DTEND:{_timestamp(end)}",
                f"SUMMARY:{escape_text(f'{launch.name} ({launch.worst_rule.label})')}",
                f"DESCRIPTION:{escape_text(f'{official}\n{launch.page_url}')}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_line(line) for line in lines) + "\r\n"
