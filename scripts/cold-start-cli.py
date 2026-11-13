"""Time the published terminal board from an empty uv cache, then warm, against its budgets."""

import argparse
import os
import shlex
import subprocess
import sys
import time
from tempfile import TemporaryDirectory

COMMAND = ("uvx", "scrubcast@latest", "next")
BUDGETS_S = {"cold": 20.0, "warm": 2.0}
NEXT_STEPS = {
    "cold": (
        "If installing dominates, move numpy to an optional `pipeline` extra so `next` "
        "installs only httpx and pydantic, then rerun."
    ),
    "warm": (
        "Find the slowest imports with `PYTHONPROFILEIMPORTTIME=1 uvx scrubcast@latest next`, "
        "defer them, then rerun."
    ),
}


def timed(env: dict[str, str]) -> float:
    """Run the command once with its output discarded and return the wall-clock seconds."""
    start = time.perf_counter()
    result = subprocess.run(  # noqa: S603
        COMMAND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False
    )
    elapsed = time.perf_counter() - start
    if result.returncode:
        sys.exit(
            f"`{shlex.join(COMMAND)}` exited {result.returncode}: {result.stderr.strip()}\n"
            "Next: run the command by hand to see the full error, fix it, then rerun."
        )
    return elapsed


def over_budget(seconds: dict[str, float]) -> list[str]:
    """Name each run that took longer than its budget, with the fix to try."""
    return [
        f"The {run} run took {elapsed:.2f} s; the budget is {BUDGETS_S[run]:g} s. "
        f"Next: {NEXT_STEPS[run]}"
        for run, elapsed in seconds.items()
        if elapsed > BUDGETS_S[run]
    ]


def main(argv: list[str] | None = None) -> None:
    """Print both times and exit 1 when either is over budget."""
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    with TemporaryDirectory() as cache:
        env = {**os.environ, "UV_CACHE_DIR": cache}
        seconds = {run: timed(env) for run in BUDGETS_S}
    for run, elapsed in seconds.items():
        sys.stdout.write(f"{run}: {elapsed:.2f} s (budget {BUDGETS_S[run]:g} s)\n")
    failures = over_budget(seconds)
    if failures:
        sys.exit("\n".join(failures))


if __name__ == "__main__":
    main()
