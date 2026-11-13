"""Paged LL2 requests with a client-scoped anonymous request budget."""

import logging
from collections import deque
from time import monotonic
from typing import TYPE_CHECKING, Literal

import httpx
from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from scrubcast.models.launch import Launch, LaunchDetailed
from scrubcast.sources.errors import SourceError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

LL2_BASE_URL = "https://ll.thespacedevs.com/2.3.0/launches/"
LL2_REQUESTS_PER_HOUR = 15  # Anonymous LL2 limit.
ROLLING_HOUR_SECONDS = 3600
PAGE_LIMIT = 100
logger = logging.getLogger(__name__)


class RequestCounter:
    """Install as a request hook; reuse its client throughout a run to share the budget."""

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._requests: deque[float] = deque()
        self.rate_limited = False
        self.retry_after: str | None = None

    def __call__(self, request: httpx.Request) -> None:
        """Refuse requests before transport when the rolling budget is exhausted."""
        if request.url.host != "ll.thespacedevs.com":
            return
        now = self._clock()
        while self._requests and self._requests[0] <= now - ROLLING_HOUR_SECONDS:
            self._requests.popleft()
        if self.rate_limited:
            raise SourceError(
                str(request.url),
                429,
                "LL2 already rate limited this run",
                retry_after=self.retry_after,
            )
        if len(self._requests) >= LL2_REQUESTS_PER_HOUR:
            raise SourceError(str(request.url), None, "LL2 rolling-hour request budget exhausted")
        self._requests.append(now)


class _Page(BaseModel):
    model_config = ConfigDict(strict=True)

    next: str | None
    results: list[dict[str, JsonValue]]


def _counter(client: httpx.Client) -> RequestCounter:
    for hook in client.event_hooks["request"]:
        if isinstance(hook, RequestCounter):
            return hook
    counter = RequestCounter()
    client.event_hooks["request"].append(counter)
    return counter


def _parse_launches[LaunchModel: Launch](
    rows: list[dict[str, JsonValue]],
    model: type[LaunchModel],
) -> list[LaunchModel]:
    launches: list[LaunchModel] = []
    for row in rows:
        try:
            launches.append(model.model_validate(row))
        except ValidationError as error:
            logger.warning(
                "Skipping LL2 launch %s with validation error: %s",
                row.get("id"),
                error,
            )
    return launches


def _fetch[LaunchModel: Launch](
    client: httpx.Client,
    url: httpx.URL,
    model: type[LaunchModel],
    *,
    follow_pages: bool = True,
) -> list[LaunchModel]:
    counter = _counter(client)
    launches: list[LaunchModel] = []
    visited: set[httpx.URL] = set()
    while True:
        if url in visited or not str(url).startswith(LL2_BASE_URL):
            raise SourceError(str(url), None, "Invalid or repeated LL2 pagination URL")
        visited.add(url)
        try:
            response = client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            response = error.response
            if response.status_code == 429:
                counter.rate_limited = True
                counter.retry_after = response.headers.get("Retry-After")
            raise SourceError(
                str(error.request.url),
                response.status_code,
                str(error),
                retry_after=response.headers.get("Retry-After"),
            ) from error
        except httpx.RequestError as error:
            raise SourceError(str(error.request.url), None, str(error)) from error
        try:
            page = _Page.model_validate_json(response.content)
            launches.extend(_parse_launches(page.results, model))
        except ValidationError as error:
            raise SourceError(str(response.url), response.status_code, str(error)) from error
        if page.next is None or not follow_pages:
            return launches
        url = response.url.join(page.next)


def fetch_upcoming(client: httpx.Client, launch_id: str | None = None) -> list[Launch]:
    """Fetch the first page of upcoming normal-mode launches, ordered by NET.

    The list runs years ahead (478 rows on 2026-11-05) and the first 100 reach well past
    the ten-day forecast horizon, so further pages would only spend the anonymous hourly
    budget. Schedule filtering is left to the caller. A launch id narrows the list to one row.
    """
    params: dict[str, str | int] = {"format": "json", "limit": PAGE_LIMIT, "mode": "normal"}
    if launch_id is not None:
        params["id"] = launch_id
    return _fetch(
        client,
        httpx.URL(f"{LL2_BASE_URL}upcoming/", params=params),
        Launch,
        follow_pages=False,
    )


def fetch_previous(
    client: httpx.Client,
    since: datetime,
    location_ids: Sequence[int] = (),
    mode: Literal["normal", "detailed"] = "detailed",
) -> list[Launch] | list[LaunchDetailed]:
    """Fetch previous launches since an aware timestamp, optionally limited to sites."""
    if since.utcoffset() is None:
        message = "since must include a UTC offset"
        raise ValueError(message)
    params: dict[str, str | int] = {
        "format": "json",
        "limit": PAGE_LIMIT,
        "mode": mode,
        "net__gte": since.isoformat(),
    }
    if location_ids:
        params["location__ids"] = ",".join(str(location_id) for location_id in location_ids)
    url = httpx.URL(f"{LL2_BASE_URL}previous/", params=params)
    if mode == "detailed":
        return _fetch(client, url, LaunchDetailed)
    return _fetch(client, url, Launch)


def fetch_audit_launches(client: httpx.Client, since: datetime) -> list[LaunchDetailed]:
    """Fetch one detailed page of launches flown since a timestamp and one of upcoming ones.

    Two requests keep a nightly audit inside the anonymous budget; a slipped or held launch
    is in the upcoming page.
    """
    if since.utcoffset() is None:
        message = "since must include a UTC offset"
        raise ValueError(message)
    params: dict[str, str | int] = {"format": "json", "limit": PAGE_LIMIT, "mode": "detailed"}
    urls = (
        httpx.URL(f"{LL2_BASE_URL}previous/", params={**params, "net__gte": since.isoformat()}),
        httpx.URL(f"{LL2_BASE_URL}upcoming/", params=params),
    )
    return [
        launch for url in urls for launch in _fetch(client, url, LaunchDetailed, follow_pages=False)
    ]
