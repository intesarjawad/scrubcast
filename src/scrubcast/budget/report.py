"""Summarise monthly request units, deferrals and collector Actions duration."""

import argparse
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from math import fsum
from pathlib import Path
from tempfile import TemporaryFile

from pydantic import AwareDatetime, BaseModel, Field, TypeAdapter

from scrubcast.budget.ledger import read_month
from scrubcast.budget.planner import DAILY_COST_BUDGET


class ActionRun(BaseModel):
    """Timestamps exported by gh run list for collect.yml."""

    started_at: AwareDatetime = Field(alias="startedAt")
    updated_at: AwareDatetime = Field(alias="updatedAt")


def main() -> None:
    """Print an offline-reproducible month report, querying Actions when requested."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", default=f"{datetime.now(UTC):%Y-%m}")
    parser.add_argument("--ledger", type=Path, default=Path("ledger"))
    parser.add_argument("--actions-file", type=Path)
    args = parser.parse_args()
    month = datetime.strptime(args.month, "%Y-%m").replace(tzinfo=UTC)
    rows = read_month(args.ledger, f"{month:%Y-%m}")
    lines: list[str] = []
    daily: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        daily[f"{row.sent_at:%Y-%m-%d}"].append(row.cost_units)
    lines.append(f"Budget {month:%Y-%m} (units; daily budget {DAILY_COST_BUDGET:,})")
    for day, costs in sorted(daily.items()):
        total = fsum(costs)
        flag = " OVER BUDGET" if total > DAILY_COST_BUDGET else ""
        lines.append(f"{day}: {total:,.2f} / {DAILY_COST_BUDGET:,}{flag}")
    lines.append(f"Deferred by budget: {sum(row.status == 'deferred_budget' for row in rows)}")
    lines.append(
        f"Deferred upstream 429: {sum(row.status == 'deferred_upstream_429' for row in rows)}"
    )
    if args.actions_file is not None:
        raw = args.actions_file.read_text()
    else:
        with TemporaryFile() as output, TemporaryFile() as errors:
            pid = os.posix_spawn(
                "/usr/bin/env",
                [
                    "/usr/bin/env",
                    "gh",
                    "run",
                    "list",
                    "-w",
                    "collect.yml",
                    "--created",
                    f">={month:%Y-%m}-01",
                    "--limit",
                    "1000",
                    "--json",
                    "startedAt,updatedAt",
                ],
                dict(os.environ),
                file_actions=[
                    (os.POSIX_SPAWN_DUP2, output.fileno(), 1),
                    (os.POSIX_SPAWN_DUP2, errors.fileno(), 2),
                ],
            )
            _, status = os.waitpid(pid, 0)
            if os.waitstatus_to_exitcode(status):
                errors.seek(0)
                parser.exit(1, f"Cannot read Actions duration: {errors.read().decode().strip()}\n")
            output.seek(0)
            raw = output.read().decode()
    runs = TypeAdapter(list[ActionRun]).validate_json(raw)
    minutes = fsum(
        (run.updated_at - run.started_at).total_seconds() / 60
        for run in runs
        if run.started_at.strftime("%Y-%m") == args.month
    )
    lines.append(f"Actions minutes (elapsed): {minutes:.2f}")

    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
