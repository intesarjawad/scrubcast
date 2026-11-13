import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UV = shutil.which("uv")


def test_installed_wheel_replays_outside_checkout(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    assert UV is not None
    subprocess.run(  # noqa: S603
        [UV, "build", "--wheel", "--out-dir", str(wheelhouse)], cwd=ROOT, check=True
    )
    environment = tmp_path / "venv"
    subprocess.run([UV, "venv", "--python", sys.executable, str(environment)], check=True)  # noqa: S603
    wheel = next(wheelhouse.glob("*.whl"))
    subprocess.run(  # noqa: S603
        [UV, "pip", "install", "--python", str(environment / "bin/python"), str(wheel)],
        check=True,
    )
    working = tmp_path / "outside-checkout"
    working.mkdir()
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    for command in ("build", "next", "backfill", "hindcast"):
        options = ["--request-limit", "30"] if command == "backfill" else []
        result = subprocess.run(  # noqa: S603
            [str(environment / "bin/scrubcast"), command, "--fixtures", *options],
            cwd=working,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        if command == "next":
            assert "Scrubcast launch weather" in result.stdout
    latest = json.loads((working / "site/public/data/latest.json").read_text())
    assert latest["members_total"] == 82
    assert any(launch["assessment"] for launch in latest["launches"])
