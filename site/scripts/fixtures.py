"""Replay the demo's source responses through the collection and assessment commands."""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from scrubcast import cli
from scrubcast.build.site_data import Publication, write_site_data
from scrubcast.models.assessment import LaunchAssessment

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/demo"


def publish() -> None:
    """Fail if replay changes the assessment instead of overwriting the recording."""
    selected = LaunchAssessment.model_validate_json((FIXTURE / "assessment.json").read_text())
    provenance = json.loads((FIXTURE / "provenance.json").read_text())
    # A recording made with --launch narrows the schedule request to one launch;
    # replay asks for the full list.
    responses = {
        str(httpx.URL(row["url"]).copy_remove_param("id")): row for row in provenance["responses"]
    }

    def response(request: httpx.Request) -> httpx.Response:
        row = responses[str(request.url)]
        headers = dict(
            line.split(": ", 1)
            for line in (FIXTURE / row["headers"]).read_text().splitlines()
            if ": " in line and line.split(":", 1)[0] not in {"content-encoding", "content-length"}
        )
        return httpx.Response(
            row["status"], content=(FIXTURE / row["body"]).read_bytes(), headers=headers
        )

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        previous = Path.cwd()
        previous_fixtures, previous_response = cli.FIXTURES, cli.fixture_response
        try:
            os.chdir(directory)
            cli.FIXTURES, cli.fixture_response = FIXTURE, response
            cli.main(["schedule", "--fixtures"])
            schedule = cli.Schedule.model_validate_json(Path("data/schedule.json").read_text())
            launch = next(launch for launch in schedule.launches if launch.id == selected.launch.id)
            schedule.launches = [launch]
            Path("data/schedule.json").write_text(schedule.model_dump_json() + "\n")
            cli.main(["weather", "--fixtures", "--force"])
            cli.main(["assess", "--fixtures"])
            path = Path(f"site/public/data/launches/{launch.id}.json")
            replayed = LaunchAssessment.model_validate_json(path.read_text())
            if replayed != selected:
                message = "Replayed assessment differs from the recorded assessment"
                raise ValueError(message)
            now = datetime.fromisoformat((FIXTURE / "RECORDED_AT").read_text().strip())
            fixture_ledger = ROOT / "tests/fixtures/past"
            latest = write_site_data(
                [launch],
                [replayed],
                cli.load_rules(),
                now,
                publication=Publication(
                    root=directory,
                    fixture_ledger=fixture_ledger if fixture_ledger.is_dir() else None,
                ),
            )
            if latest.model_dump(mode="json") != json.loads((FIXTURE / "latest.json").read_text()):
                message = "Replayed index differs from the recorded index"
                raise ValueError(message)
            destination = ROOT / "site/public/data"
            for old in (destination / "launches").glob("*.json"):
                old.unlink()
            shutil.copytree(directory / "site/public/data", destination, dirs_exist_ok=True)
        finally:
            cli.FIXTURES, cli.fixture_response = previous_fixtures, previous_response
            os.chdir(previous)


if __name__ == "__main__":
    publish()
