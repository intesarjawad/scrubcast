"""Restore the exact raw slice files referenced by the forward collector ledger."""

import os
import subprocess
from datetime import timedelta
from pathlib import Path

from scrubcast.archive.slices import ARCHIVE_HORIZON
from scrubcast.audit.forecast_audit import read_forward_ledger


def restore(root: Path, repository: str) -> None:
    """Download each ledger run and sidecar from its monthly archive release."""
    directory = root / "archive"
    directory.mkdir(parents=True, exist_ok=True)
    months: dict[str, set[str]] = {}
    for row in read_forward_ledger(root):
        if row.tier != "A" or not timedelta() <= row.net - row.run_at <= ARCHIVE_HORIZON:
            continue
        name = f"slices-{row.run_at:%Y%m%dT%H}"
        for suffix in ("npz", "json"):
            asset = f"{name}.{suffix}"
            if not (directory / asset).exists():
                months.setdefault(f"archive-{row.run_at:%Y-%m}", set()).add(asset)
    for tag, assets in sorted(months.items()):
        command = ["gh", "release", "download", tag, "--repo", repository, "--dir", str(directory)]
        for asset in sorted(assets):
            command.extend(["--pattern", asset])
        subprocess.run(command, check=True)  # noqa: S603


if __name__ == "__main__":
    restore(Path(), os.environ["ARCHIVE_REPO"])
