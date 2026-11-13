"""Terminal messages that name the state and the next action."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    """A user-facing state and the action that follows it."""

    what: str
    next: str

    def render(self, **values: object) -> str:
        """Fill placeholders in both parts and join them into one sentence."""
        return f"{self.what.format(**values)} {self.next.format(**values)}"


NETWORK_FAILURE = Message(
    what="Could not reach {url}: {reason}.",
    next=(
        "Check the connection and run `scrubcast next` again, or read a saved copy with "
        "`scrubcast next --data-url path/to/latest.json`."
    ),
)
NOT_PUBLISHED = Message(
    what="Nothing is published at {url} yet (HTTP 404), so the site has not been deployed there.",
    next=(
        "Build the data on this machine with `scrubcast build`, then run "
        "`scrubcast next --data-url site/public/data/latest.json`."
    ),
)
UNREADABLE_FILE = Message(
    what="Could not read {path}: {reason}.",
    next=(
        "Run `scrubcast build` to write site/public/data/latest.json, then "
        "`scrubcast next --data-url site/public/data/latest.json`."
    ),
)
OLD_DATA = Message(
    what="This launch data is {hours} h old (built {built} UTC).",
    next="The published site rebuilds hourly; run `scrubcast next` again later.",
)
UNSUPPORTED_SCHEMA = Message(
    what="This data uses schema version {version}; Scrubcast reads {supported}.",
    next="Update Scrubcast, then run `scrubcast next` again.",
)
INVALID_DATA = Message(
    what="The published launch data could not be read.",
    next="Run `scrubcast next` again; if it persists, report the problem.",
)
STALE = Message(
    what=(
        "Launch Library 2 did not answer the last refresh. The launch schedule may be out of date."
    ),
    next="Check the published launch record at {launch_url}.",
)
NO_LAUNCHES = Message(
    what="No orbital launches in the next 10 days.",
    next="Run `scrubcast next` after the next publication.",
)
