"""Failures at source boundaries, with context for cached-data fallbacks."""


class SourceError(Exception):
    """A failed source request; retry_after preserves the server's header verbatim."""

    def __init__(
        self,
        url: str,
        status: int | None,
        reason: str,
        *,
        retry_after: str | None = None,
    ) -> None:
        self.url = url
        self.status = status
        self.reason = reason
        self.retry_after = retry_after
        super().__init__(
            f"Source request failed at {url} (status {status}): {reason}. "
            "Next: check the connection and run the same `scrubcast` command again; "
            "files already saved under data/ are kept."
        )
