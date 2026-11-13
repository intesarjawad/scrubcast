"""Record source responses and assess one unmodified upcoming launch offline."""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import httpx

from scrubcast import cli
from scrubcast.build.site_data import Publication, write_site_data
from scrubcast.models.assessment import LaunchAssessment
from scrubcast.rules.loader import load_rules
from scrubcast.sources.launch_library import fetch_upcoming
from scrubcast.sources.open_meteo import OpenMeteoSource
from scrubcast.weather import WeatherCollector

if TYPE_CHECKING:
    from scrubcast.models.launch import Launch

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "tests/fixtures/demo"
FLORIDA_LOCATIONS = {12, 27}
FORECAST_DAYS = 10


def refusal(launch: Launch | None, now: datetime) -> str | None:
    """Name the first reason a launch cannot be the demo, or None when it qualifies."""
    if launch is None:
        return "The launch is not in the upcoming schedule after filtering"
    checks = (
        (launch.rocket_name.startswith("Falcon 9"), "is not a Falcon 9"),
        (launch.pad.location.id in FLORIDA_LOCATIONS, "is not at a Florida pad"),
        (launch.probability is not None, "has no official probability"),
        (bool(launch.weather_concerns), "has no official weather concerns"),
        (
            now <= launch.net <= now + timedelta(days=FORECAST_DAYS),
            f"is outside the {FORECAST_DAYS}-day forecast horizon",
        ),
    )
    return next((f"{launch.name} {reason}" for passed, reason in checks if not passed), None)


def spread(assessment: LaunchAssessment) -> float:
    """Range of the ECMWF member share across the window for the top direct or medium rule."""
    rules = [
        rule
        for rule in assessment.rules
        if rule.confidence in {"direct", "medium"} and "ecmwf" in rule.by_model
    ]
    if not rules:
        return 0.0
    top = max(rules, key=lambda rule: rule.by_model["ecmwf"].risk_fraction or 0.0)
    shares = [share for share in top.risk_by_hour.get("ecmwf", []) if share is not None]
    return max(shares) - min(shares) if shares else 0.0


def widest(directories: list[Path]) -> Path:
    """Pick the recording to keep without changing any recorded value."""
    return max(
        directories,
        key=lambda directory: spread(
            LaunchAssessment.model_validate_json((directory / "assessment.json").read_text())
        ),
    )


def record(destination: Path, launch_id: str) -> None:
    """Preserve decoded HTTP bodies, writing nothing unless the launch qualifies."""
    captured: list[tuple[str, bytes, str]] = []
    requests: list[dict[str, str | int]] = []

    def capture(response: httpx.Response) -> None:
        response.read()
        name = "ll2-upcoming.json" if response.url.host == "ll.thespacedevs.com" else "cape.json"
        headers = f"{name}.headers.txt"
        captured.append(
            (
                name,
                response.content,
                f"HTTP {response.status_code}\n"
                + "".join(f"{key}: {value}\n" for key, value in response.headers.items()),
            )
        )
        requests.append(
            {
                "url": str(response.url),
                "retrieved_at": datetime.now(UTC).isoformat(),
                "status": response.status_code,
                "body": name,
                "headers": headers,
            }
        )

    def save() -> None:
        destination.mkdir(parents=True, exist_ok=False)
        for name, body, headers in captured:
            (destination / name).write_bytes(body)
            (destination / f"{name}.headers.txt").write_text(headers)

    catalog = load_rules()
    with httpx.Client(timeout=120, event_hooks={"response": [capture]}) as client:
        launches = cli.filter_schedule(fetch_upcoming(client, launch_id))
        now = datetime.now(UTC)
        selected = next((launch for launch in launches if launch.id == launch_id), None)
        reason = refusal(selected, now)
        if reason is not None or selected is None:
            message = f"Refusing {launch_id}: {reason}"
            raise SystemExit(message)
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            collector = WeatherCollector(OpenMeteoSource(client), catalog, root=directory)
            forecasts = collector.run([selected], now, force=True)
            if len(captured) != 2:
                message = f"Expected 1 LL2 and 1 Open-Meteo request, made {len(captured)}"
                raise ValueError(message)
            save()
            if not forecasts:
                message = "No weather response was accepted; raw responses remain for inspection"
                raise ValueError(message)
            recorded_at = datetime.now(UTC)
            (destination / "RECORDED_AT").write_text(recorded_at.isoformat() + "\n")
            assessment = assess(directory, destination, selected, recorded_at)
            latest = write_site_data(
                [selected],
                [assessment],
                catalog,
                recorded_at,
                publication=Publication(root=directory),
            )
            (destination / "assessment.json").write_text(
                assessment.model_dump_json(indent=2) + "\n"
            )
            (destination / "latest.json").write_text(latest.model_dump_json(indent=2) + "\n")
    inputs = [
        *sorted((ROOT / "src/scrubcast").rglob("*.py")),
        *sorted((ROOT / "rules").rglob("*.json")),
    ]
    inputs.extend([ROOT / "pyproject.toml", ROOT / "uv.lock"])
    provenance = {
        "mission": selected.name,
        "launch_id": selected.id,
        "recorded_at": recorded_at.isoformat(),
        "pipeline_version": version("scrubcast"),
        "record_command": f"uv run python scripts/record_demo_fixture.py --launch {selected.id}",
        "replay_commands": [
            "scrubcast schedule --fixtures",
            "scrubcast weather --fixtures --force",
            "scrubcast assess --fixtures",
        ],
        "commands": [
            "scrubcast schedule",
            "scrubcast weather --force",
            "scrubcast assess --fixtures",
        ],
        "method": (
            "I preserve the source bodies without changing launch fields or ensemble values. "
            "I use the schedule source client and paced weather collector used by the CLI, "
            "then run the assess command at RECORDED_AT. I select only the recorded launch "
            "from the parsed schedule before weather collection."
        ),
        "selection": (
            "I record only the named Florida Falcon 9 with both official fields inside the "
            "ten-day forecast horizon. Across recordings on different launch days I keep the "
            "one whose top direct or medium rule has the widest range of ECMWF member share "
            "across the window."
        ),
        "window_spread": spread(assessment),
        "limitations": [*limitations(selected), *weather_findings(assessment)],
        "body_encoding": (
            "I save the decoded HTTP entity body with original headers. Replay removes "
            "content-encoding and content-length because the body is already decompressed."
        ),
        "responses": requests,
        "pipeline_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in inputs
        },
        "sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(destination.iterdir())
            if path.is_file()
        },
    }
    (destination / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


def assess(directory: Path, fixtures: Path, launch: Launch, now: datetime) -> LaunchAssessment:
    """Use the normal cached assessment command with the recorded clock."""
    (directory / "data/schedule.json").write_text(
        cli.Schedule(generated_at=now, launches=[launch]).model_dump_json() + "\n"
    )
    previous, previous_fixtures = Path.cwd(), cli.FIXTURES
    try:
        os.chdir(directory)
        cli.FIXTURES = fixtures
        cli.main(["assess", "--fixtures"])
        return LaunchAssessment.model_validate_json(
            (directory / f"site/public/data/launches/{launch.id}.json").read_text()
        )
    finally:
        cli.FIXTURES = previous_fixtures
        os.chdir(previous)


def limitations(selected: Launch) -> list[str]:
    """Describe source wording that could read as a recording error."""
    if selected.weather_concerns and "Unknown concern" in selected.weather_concerns:
        return ["The source literally contains 'Unknown concern'; I preserve it verbatim."]
    return []


def weather_findings(assessment: LaunchAssessment) -> list[str]:
    """Explain constant precipitation only when the recorded evidence establishes it."""
    precipitation = next(
        rule for rule in assessment.rules if rule.rule_id == "flight_through_precip"
    )
    values = [
        value
        for model in ("ecmwf", "gfs")
        for row in precipitation.member_values_by_hour.get(model) or []
        for value in row
    ]
    notes: list[str] = []
    if values and all(value == 0 for value in values):
        notes.append(
            "Both models return zero precipitation for every member at every sampled "
            "launch-window hour. I preserve these repeated zeros from the raw response; "
            "I do not copy values between hours."
        )
    if all(
        risk.risk_fraction in {None, 0}
        for rule in assessment.rules
        for risk in rule.by_model.values()
    ):
        notes.append("Every evaluable rule is clear at launch time.")
    if assessment.lowest_union_hour is None:
        notes.append("No material lowest-risk hour is established.")
    return notes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--launch", help="LL2 id of the upcoming launch to record")
    action.add_argument(
        "--compare",
        nargs="+",
        type=Path,
        metavar="DIRECTORY",
        help="print the recording with the widest window spread",
    )
    parser.add_argument("--output", type=Path, default=DESTINATION)
    args = parser.parse_args()
    if args.compare:
        print(widest(args.compare))  # noqa: T201
    else:
        record(args.output.resolve(), args.launch)
