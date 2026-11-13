"""Watch Launch Library documentation and the 2.3.0 root for a version change."""

import re
import subprocess
import sys
from importlib.metadata import version
from typing import TYPE_CHECKING

import httpx
from pydantic import TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Mapping

LLAPI_URL = "https://thespacedevs.com/llapi"
API_ROOT = "https://ll.thespacedevs.com/2.3.0/"
CURRENT_VERSION = (2, 3, 0)
VERSION_URL = re.compile(r"ll\.thespacedevs\.com/(\d+)\.(\d+)\.(\d+)/")
DEPRECATED_WORD = re.compile(r"\bdeprecated\b", re.IGNORECASE)
HTTP_TIMEOUT = httpx.Timeout(10, read=30)
REPOSITORY_URL = "https://github.com/intesarjawad/scrubcast"
HEADERS = {"User-Agent": f"scrubcast/{version('scrubcast')} (+{REPOSITORY_URL})"}
ISSUE_BODY = (
    "The Launch Library version watch found: {detail}\n\n"
    "The current port to the restructured API is described in docs/data.md under "
    '"Launch Library requests". Update the request paths, models and fixtures before '
    "the old version is removed.\n"
)


def documented_versions(documentation: str) -> list[tuple[int, int, int]]:
    """Return the API versions linked from the documentation page."""
    return [
        (int(match[0]), int(match[1]), int(match[2]))
        for match in VERSION_URL.findall(documentation)
    ]


def newer_version(documentation: str) -> str | None:
    """Return the highest documented API version when it is newer than the pinned one."""
    newest = max(documented_versions(documentation), default=None)
    if newest is None or newest <= CURRENT_VERSION:
        return None
    return ".".join(str(part) for part in newest)


def deprecation(headers: Mapping[str, str], body: str) -> str | None:
    """Report a deprecation header or a body that marks the pinned version deprecated."""
    lowered = {name.lower(): value for name, value in headers.items()}
    for name in ("deprecation", "sunset"):
        if value := lowered.get(name):
            return f"{name.title()}: {value}"
    if DEPRECATED_WORD.search(body):
        return "response body says deprecated"
    return None


def version_change(documentation: str, headers: Mapping[str, str], body: str) -> str | None:
    """Return one detail string when the documentation or response signals a change."""
    if newer := newer_version(documentation):
        return f"documented version {newer}"
    return deprecation(headers, body)


def _gh(*arguments: str) -> str:
    completed = subprocess.run(  # noqa: S603
        ["gh", *arguments],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def main() -> None:
    """Open one issue when Launch Library moves beyond the supported version."""
    with httpx.Client(timeout=HTTP_TIMEOUT, headers=HEADERS) as client:
        documentation = client.get(LLAPI_URL)
        documentation.raise_for_status()
        root = client.get(API_ROOT)
        root.raise_for_status()
    detail = version_change(documentation.text, root.headers, root.text)
    if detail is None:
        sys.stdout.write("Launch Library version unchanged\n")
        return
    title = f"Launch Library version change: {detail}"
    open_issues = TypeAdapter(list[dict[str, str]]).validate_json(
        _gh(
            "issue",
            "list",
            "--state",
            "open",
            "--search",
            title,
            "--limit",
            "100",
            "--json",
            "title",
        )
    )
    if any(issue["title"] == title for issue in open_issues):
        sys.stdout.write(f"Open issue already tracks {title}\n")
        return
    _gh("issue", "create", "--title", title, "--body", ISSUE_BODY.format(detail=detail))
    sys.stdout.write(f"Opened {title}\n")


if __name__ == "__main__":
    main()
