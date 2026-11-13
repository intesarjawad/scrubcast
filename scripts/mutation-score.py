"""Fail when the mutation score in mutmut's CI statistics is below the floor."""

import argparse
import json
import sys
from pathlib import Path

SCORE_FLOOR = 0.80


def main() -> None:
    """Print killed / (total - skipped) and exit 1 when it is below the floor."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", type=Path, default=Path("mutants/mutmut-cicd-stats.json"))
    args = parser.parse_args()
    stats = json.loads(args.stats.read_text())
    tested = stats["total"] - stats["skipped"]
    if tested <= 0:
        sys.exit("No mutants were tested; run `mutmut run` first.")
    score = stats["killed"] / tested
    sys.stdout.write(f"mutation score: {stats['killed']} / {tested} = {score:.1%}\n")
    if score < SCORE_FLOOR:
        sys.exit(f"Below the {SCORE_FLOOR:.0%} floor.")


if __name__ == "__main__":
    main()
