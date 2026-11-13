"""Check that GitHub Pages serves a fresh build and the ledger's current hindcast."""

import argparse
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import BaseModel, ValidationError

from scrubcast.build.contracts import Hindcast, Latest

MAX_AGE = timedelta(hours=2)
HTTP_TIMEOUT = httpx.Timeout(10, read=30)
REDEPLOY = (
    "Next: start a deploy with `gh workflow run refresh.yml` (it also runs every hour at "
    "minute 17), wait for it to finish, then rerun this check."
)


class DeployError(Exception):
    """A failed check, worded with its next step."""


def _fetch[T: BaseModel](client: httpx.Client, url: str, contract: type[T]) -> T:
    try:
        response = client.get(url)
    except httpx.HTTPError as error:
        message = f"Could not fetch {url}: {error}. Next: check the URL, then rerun."
        raise DeployError(message) from error
    if not response.is_success:
        message = f"{url} returned HTTP {response.status_code}. {REDEPLOY}"
        raise DeployError(message)
    try:
        return contract.model_validate_json(response.content)
    except ValidationError as error:
        message = f"{url} does not match the published contract: {error}. {REDEPLOY}"
        raise DeployError(message) from error


def _ledger_hindcast() -> Hindcast:
    """Fetch the ledger branch first so the comparison never uses a stale local copy."""
    fetched = subprocess.run(
        ["git", "fetch", "--quiet", "origin", "ledger"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if fetched.returncode:
        message = (
            f"`git fetch origin ledger` failed: {fetched.stderr.strip()}. "
            "Next: run this from a clone whose origin has the ledger branch."
        )
        raise DeployError(message)
    shown = subprocess.run(
        ["git", "show", "FETCH_HEAD:hindcast.json"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode:
        message = (
            "The ledger branch has no hindcast.json yet. Next: run "
            "`gh workflow run audit.yml`, wait for its ledger commit, then rerun this check."
        )
        raise DeployError(message)
    try:
        return Hindcast.model_validate_json(shown.stdout)
    except ValidationError as error:
        message = f"hindcast.json on the ledger branch is invalid: {error}. Next: rerun the audit."
        raise DeployError(message) from error


def freshness(latest: Latest, now: datetime) -> str:
    """Accept a build no more than two hours old; a future stamp means a wrong clock."""
    stamp = latest.generated_at.isoformat()
    age = now - latest.generated_at
    if age < timedelta(0):
        message = (
            f"latest.json was generated at {stamp}, after this machine's time "
            f"{now.isoformat()}. Next: correct this machine's clock, then rerun this check."
        )
        raise DeployError(message)
    if age > MAX_AGE:
        message = (
            f"latest.json was generated at {stamp}, {age.total_seconds() / 3600:.1f} h ago; "
            f"the limit is {MAX_AGE.total_seconds() / 3600:.0f} h. {REDEPLOY}"
        )
        raise DeployError(message)
    return f"latest.json is {age.total_seconds() / 60:.0f} min old (generated at {stamp})"


def same_hindcast(published: Hindcast, ledger: Hindcast) -> str:
    """Compare parsed documents, since the build re-serialises the ledger file."""
    if published != ledger:
        message = (
            f"Pages serves the hindcast generated at {published.generated_at.isoformat()}; "
            f"the ledger has the one generated at {ledger.generated_at.isoformat()}. "
            f"{REDEPLOY}"
        )
        raise DeployError(message)
    return f"hindcast.json matches the ledger (generated at {ledger.generated_at.isoformat()})"


def main(argv: list[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> None:
    """Print one line per passing check and exit 1 with every failure and its next step."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pages_url", help="the deployed site, including its base path")
    args = parser.parse_args(argv)
    if not args.pages_url.startswith(("https://", "http://")):
        parser.error(f"{args.pages_url} is not a URL. Next: pass the full Pages URL.")
    base = args.pages_url.rstrip("/")
    passed: list[str] = []
    failed: list[str] = []
    with httpx.Client(transport=transport, timeout=HTTP_TIMEOUT) as client:
        checks = (
            lambda: freshness(
                _fetch(client, f"{base}/data/latest.json", Latest), datetime.now(UTC)
            ),
            lambda: same_hindcast(
                _fetch(client, f"{base}/data/hindcast.json", Hindcast), _ledger_hindcast()
            ),
        )
        for check in checks:
            try:
                passed.append(check())
            except DeployError as problem:
                failed.append(str(problem))
    sys.stdout.write("".join(f"ok: {line}\n" for line in passed))
    if failed:
        sys.exit("\n".join(failed))


if __name__ == "__main__":
    main()
