"""Resumable source snapshots and deterministic retrospective audit tables."""

import fcntl
import gzip
import hashlib
import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from time import sleep
from typing import TYPE_CHECKING, Literal

import httpx
import numpy as np
from pydantic import AwareDatetime, BaseModel, Field, JsonValue, TypeAdapter

from scrubcast.assess.window import select_window
from scrubcast.audit.forecast_check import FORECAST_LABEL, forecast_check
from scrubcast.audit.observations import read_observations
from scrubcast.audit.proxy_check import PROXY_LABEL, Evidence, Metric, proxy_check
from scrubcast.budget.cost import request_cost
from scrubcast.budget.ledger import BudgetRow, append_row, read_month
from scrubcast.budget.planner import DAILY_COST_BUDGET, RUN_COST_BUDGET, CostRecord, next_send_at
from scrubcast.models.launch import Launch, parse_concerns
from scrubcast.rules.engine import assess_hour
from scrubcast.rules.profile import Profile
from scrubcast.sources.historical import HistoricalSource
from scrubcast.sources.iem import IEM_MIN_INTERVAL_S, IEMSource
from scrubcast.sources.launch_library import LL2_BASE_URL, RequestCounter, fetch_previous
from scrubcast.weather import VARIABLES

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping
    from pathlib import Path

    from scrubcast.models.observation import Observation
    from scrubcast.models.weather import EnsembleSeries
    from scrubcast.rules.loader import RuleCatalog

START_DATE = date(2024, 2, 3)
logger = logging.getLogger(__name__)


class SliceCompleteError(Exception):
    """The requested slice is saved; another invocation can continue it."""


class DateSelection(BaseModel):
    """An inclusive launch interval with an immutable source selection."""

    start: date
    end: date


class RequestEntry(BaseModel):
    """Persist a reservation before sending, including unsuccessful attempts."""

    sent_at: AwareDatetime
    host: str
    cost_units: float = Field(ge=0, allow_inf_nan=False)


class Snapshot(BaseModel):
    """Raw response provenance used for replay and publication."""

    url: str
    recorded_at: AwareDatetime
    headers: dict[str, str]
    sha256: str
    asset: str


@dataclass(frozen=True)
class SnapshotOptions:
    """Bound network work and inject time for recorded-response verification."""

    request_limit: int = 5
    offline: bool = False
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    wait: Callable[[float], None] = sleep
    budget_directory: Path | None = None


@dataclass(frozen=True)
class StationInputs:
    """Measurements at launch and the fixed reference years stay distinct."""

    observations: list[Observation]
    climatology: list[Observation]


class SnapshotTransport(httpx.BaseTransport):
    """Replay saved bytes first; pace and account only cache misses before transport."""

    def __init__(
        self,
        directory: Path,
        upstream: httpx.BaseTransport,
        options: SnapshotOptions,
    ) -> None:
        self.directory, self.upstream = directory, upstream
        self.request_limit, self.offline = options.request_limit, options.offline
        self.clock, self.wait = options.clock, options.wait
        self.budget_directory = options.budget_directory or directory.parent / "ledger"
        self.sent = 0
        self.spent = 0.0
        self.directory.mkdir(parents=True, exist_ok=True)
        self.journal = directory / "requests.json"
        self.history = (
            TypeAdapter(list[RequestEntry]).validate_json(self.journal.read_bytes())
            if self.journal.exists()
            else []
        )
        self.counter_time = self.clock().timestamp()
        self.counter = RequestCounter(lambda: self.counter_time)
        for entry in self.history:
            if entry.host == "ll.thespacedevs.com" and entry.sent_at > self.clock() - timedelta(
                hours=1
            ):
                self.counter_time = entry.sent_at.timestamp()
                self.counter(httpx.Request("GET", LL2_BASE_URL))

    def close(self) -> None:
        """Release the underlying connection pool."""
        self.upstream.close()

    def _save_journal(self) -> None:
        temporary = self.journal.with_suffix(".tmp")
        temporary.write_bytes(TypeAdapter(list[RequestEntry]).dump_json(self.history, indent=2))
        temporary.replace(self.journal)

    def _other_spend(self, now: datetime) -> list[BudgetRow]:
        months = {f"{now:%Y-%m}", f"{now - timedelta(days=1):%Y-%m}"}
        return [
            row
            for month in sorted(months)
            for row in read_month(self.budget_directory, month)
            if not row.point_id.startswith("backfill:")
        ]

    def _reserve(self, request: httpx.Request) -> RequestEntry:
        if self.offline:
            message = f"Snapshot missing for {request.url}; offline replay cannot fetch it"
            raise ValueError(message)
        if self.sent >= self.request_limit:
            raise SliceCompleteError
        now = self.clock()
        host = request.url.host
        cost = 0.0
        if host == "open-meteo.com" or host.endswith(".open-meteo.com"):
            params = request.url.params
            days = (
                date.fromisoformat(params["end_date"]) - date.fromisoformat(params["start_date"])
            ).days + 1
            cost = request_cost(
                len(params["hourly"].split(",")), len(params["models"].split(",")), days
            )
            today = sum(row.cost_units for row in self.history if row.sent_at.date() == now.date())
            other_spend = self._other_spend(now)
            today += sum(row.cost_units for row in other_spend if row.sent_at.date() == now.date())
            if today + cost > DAILY_COST_BUDGET or self.spent + cost > RUN_COST_BUDGET:
                raise SliceCompleteError
            records = [
                CostRecord(row.sent_at, row.cost_units) for row in self.history if row.cost_units
            ]
            records.extend(CostRecord(row.sent_at, row.cost_units) for row in other_spend)
            send_at = next_send_at(records, cost, now)
        elif host == "ll.thespacedevs.com":
            recent = [
                row.sent_at
                for row in self.history
                if row.host == host and row.sent_at > now - timedelta(hours=1)
            ]
            send_at = recent[-15] + timedelta(hours=1) if len(recent) >= 15 else now
        else:
            recent = [row.sent_at for row in self.history if row.host == host]
            send_at = (
                max(now, recent[-1] + timedelta(seconds=IEM_MIN_INTERVAL_S)) if recent else now
            )
        if send_at > now:
            self.wait((send_at - now).total_seconds())
        self.counter_time = self.clock().timestamp()
        self.counter(request)
        entry = RequestEntry(sent_at=self.clock(), host=host, cost_units=cost)
        self.history.append(entry)
        self._save_journal()
        self.sent += 1
        self.spent += cost
        count = sum(
            row.host == host and row.sent_at > entry.sent_at - timedelta(hours=1)
            for row in self.history
        )
        logger.info("Backfill request host=%s counter=%d cost=%.4f", host, count, cost)
        return entry

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Store successful raw bodies and HTTP headers without refetching existing assets."""
        key = hashlib.sha256(str(request.url).encode()).hexdigest()
        metadata_path = self.directory / f"{key}.json"
        if metadata_path.exists():
            snapshot = Snapshot.model_validate_json(metadata_path.read_bytes())
            raw = gzip.decompress((self.directory / snapshot.asset).read_bytes())
            if (
                snapshot.url != str(request.url)
                or hashlib.sha256(raw).hexdigest() != snapshot.sha256
            ):
                message = f"Snapshot integrity check failed: {metadata_path}"
                raise ValueError(message)
            headers = {
                name: value
                for name, value in snapshot.headers.items()
                if name not in {"content-encoding", "content-length"}
            }
            return httpx.Response(200, content=raw, headers=headers, request=request)
        entry = self._reserve(request)
        response = self.upstream.handle_request(request)
        raw = response.read()
        if entry.cost_units:
            measured = float(response.headers.get("x-ratelimit-cost", entry.cost_units))
            self.spent += measured - entry.cost_units
            entry.cost_units = RequestEntry(
                sent_at=entry.sent_at, host=entry.host, cost_units=measured
            ).cost_units
            self._save_journal()
            append_row(
                self.budget_directory,
                BudgetRow(
                    sent_at=entry.sent_at,
                    point_id=f"backfill:{key}",
                    status="deferred_upstream_429" if response.status_code == 429 else "fetched",
                    cost_units=measured,
                ),
            )
        if response.is_success and b"Too many requests" not in raw:
            snapshot = Snapshot(
                url=str(request.url),
                recorded_at=entry.sent_at,
                headers=dict(response.headers),
                sha256=hashlib.sha256(raw).hexdigest(),
                asset=f"{key}.gz",
            )
            (self.directory / snapshot.asset).write_bytes(gzip.compress(raw, mtime=0))
            temporary = metadata_path.with_suffix(".tmp")
            temporary.write_text(snapshot.model_dump_json(indent=2) + "\n")
            temporary.replace(metadata_path)
        return response


def nearest_observation(observations: list[Observation], net: datetime) -> Observation | None:
    """Ties resolve earlier; observations more than thirty minutes away are missing."""
    nearest = min(observations, key=lambda row: (abs(row.valid - net), row.valid), default=None)
    return (
        nearest
        if nearest is not None and abs(nearest.valid - net) <= timedelta(minutes=30)
        else None
    )


def climatology_median(observations: list[Observation], net: datetime) -> float | None:
    """Use a leap-year calendar and circular day/hour distances at year boundaries."""
    target_day = net.replace(year=2000).timetuple().tm_yday
    winds: list[float] = []
    for row in observations:
        day_distance = abs(row.valid.replace(year=2000).timetuple().tm_yday - target_day)
        hour_distance = abs(row.valid.hour - net.hour)
        if (
            min(day_distance, 366 - day_distance) <= 15
            and min(hour_distance, 24 - hour_distance) <= 1
            and row.wind_speed_mps is not None
        ):
            winds.append(row.wind_speed_mps)
    return float(np.median(winds)) if winds else None


def _verdicts(
    series: EnsembleSeries,
    hour: datetime,
    launch: Launch,
    catalog: RuleCatalog,
    *,
    surface: bool = False,
) -> dict[str, bool | None]:
    if hour not in series.hours:
        return {}
    selection = catalog.rules_for(launch.pad, "Falcon 9" if surface else launch.rocket_name)
    assessment = assess_hour(
        [Profile.from_series(series, member=0, hour=series.hours.index(hour))], selection
    )
    return {
        rule: None if not result.evaluable_members else bool(result.violating_members)
        for rule, result in assessment.rules.items()
    }


def build_evidence(
    launch: Launch,
    series: EnsembleSeries,
    station: StationInputs,
    catalog: RuleCatalog,
    comparison: tuple[Literal[0, 24, 48, 72], Evidence | None] = (0, None),
) -> Evidence:
    """Join by UTC valid hour, retaining missing input and window coverage."""
    lead, analysis = comparison
    hour = launch.net.replace(minute=0, second=0, microsecond=0)
    if launch.net - hour > timedelta(minutes=30):
        hour += timedelta(hours=1)
    values: Mapping[str, float] = (
        Profile.from_series(series, member=0, hour=series.hours.index(hour)).values
        if hour in series.hours
        else {}
    )
    observation = nearest_observation(station.observations, launch.net)
    concerns = (
        None
        if launch.weather_concerns is None
        else [
            catalog.normalise_concern(name).rule_id or name
            for name in parse_concerns(launch.weather_concerns)
        ]
    )
    selection = catalog.rules_for(launch.pad, launch.rocket_name)
    supported = {rule.rule_id for rule in selection.rules} | (
        {"liftoff_wind"} if selection.vehicle else set[str]()
    )
    window = select_window(
        series.hours, net=launch.net, window_start=launch.window_start, window_end=launch.window_end
    )
    window_results = [_verdicts(series, valid, launch, catalog) for valid in window.hours]
    window_verdicts: dict[str, bool | None] = {}
    for rule in supported:
        flags = [row.get(rule) for row in window_results]
        window_verdicts[rule] = (
            True
            if True in flags
            else (
                False if flags and None not in flags and not window.beyond_forecast_range else None
            )
        )

    def finite(name: str) -> float | None:
        value = values.get(name)
        return value if value is not None and np.isfinite(value) else None

    return Evidence(
        launch_id=launch.id,
        net=launch.net,
        model=series.model,
        lead_hours=lead,
        concerns=concerns,
        unevaluable_concerns=[name for name in concerns or [] if name not in supported],
        verdicts=_verdicts(series, hour, launch, catalog, surface=lead != 0),
        window_verdicts=window_verdicts,
        wind_mps=finite("wind_speed_10m"),
        precipitation_mm=finite("precipitation"),
        observation_present=observation is not None,
        observed_wind_mps=observation.wind_speed_mps if observation else None,
        observed_precipitation_in=observation.precipitation_in if observation else None,
        climatology_wind_mps=climatology_median(station.climatology, launch.net),
        analysis_wind_verdict=(
            analysis.analysis_wind_verdict
            if analysis
            else _verdicts(series, hour, launch, catalog, surface=True).get("liftoff_wind")
        ),
    )


def run_backfill(
    client: httpx.Client, catalog: RuleCatalog, root: Path, start: date, end: date
) -> int:
    """Rebuild an inclusive date slice from immutable raw snapshots."""
    selections_path = root / "data/backfill/selections.json"
    selections = _selections(selections_path, start, end)
    sample = _launch_sample(client, selections)
    point = catalog.sites["cape"].forecast_point
    if point is None:
        message = "Cape forecast point is required"
        raise ValueError(message)
    source, iem = HistoricalSource(client), IEMSource(client, wait=lambda _: None)
    rows: list[Evidence] = []
    metars: dict[tuple[str, int], list[Observation]] = {}
    for month in sorted({launch.net.date().replace(day=1) for launch in sample}):
        next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        last_day = min(next_month, max(selection.end for selection in selections))
        history = source.forecast(
            point,
            ("ecmwf", "gfs"),
            list(VARIABLES),
            max(START_DATE, month - timedelta(days=1)),
            last_day,
        )
        previous = {
            model: source.previous_runs(
                point, model, max(START_DATE, month - timedelta(days=1)), last_day
            )
            for model in ("ecmwf", "gfs")
        }
        for launch in (launch for launch in sample if launch.net.date().replace(day=1) == month):
            station = "TTS" if launch.pad.location.id == 27 else "XMR"
            for year in sorted({*range(2016, 2026), launch.net.year}):
                if (station, year) not in metars:
                    metars[station, year] = iem.metars(station, year)
            climate = [
                row
                for (name, year), observations in metars.items()
                if name == station and 2016 <= year <= 2025
                for row in observations
            ]
            for series in history.series:
                analysis = build_evidence(
                    launch,
                    series,
                    StationInputs(metars[station, launch.net.year], climate),
                    catalog,
                )
                rows.append(analysis)
                for group in previous[series.model]:
                    if group.model != series.model:
                        continue
                    leads: tuple[tuple[int, Literal[24, 48, 72]], ...] = ((1, 24), (2, 48), (3, 72))
                    for day, lead in leads:
                        rows.append(
                            build_evidence(
                                launch,
                                group.leads[day],
                                StationInputs(metars[station, launch.net.year], climate),
                                catalog,
                                comparison=(lead, analysis),
                            )
                        )
    ledger = root / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    snapshots = [
        Snapshot.model_validate_json(path.read_bytes())
        for path in sorted((root / "data/backfill/snapshots").glob("*.json"))
        if path.name != "requests.json"
    ]
    provenance = [snapshot.model_dump(mode="json") for snapshot in snapshots]
    (ledger / "backfill.jsonl").write_text(
        "".join(
            json.dumps(
                {"evidence": row.model_dump(mode="json"), "snapshots": provenance}, sort_keys=True
            )
            + "\n"
            for row in rows
        )
    )
    climate_path = root / "data/iem" / "climatology.json"
    climate_path.parent.mkdir(parents=True, exist_ok=True)
    stored_climate = read_observations(climate_path)
    stored_climate.update(
        {
            station: [
                row
                for (name, year), observations in sorted(metars.items())
                if name == station and 2016 <= year <= 2025
                for row in observations
            ]
            for station in sorted({key[0] for key in metars})
        }
    )
    climate_path.write_text(
        json.dumps(
            {
                station: [row.model_dump(mode="json") for row in observations]
                for station, observations in stored_climate.items()
            },
            sort_keys=True,
        )
        + "\n"
    )
    report = {
        "n": len(sample),
        "start": min(selection.start for selection in selections).isoformat(),
        "end": max(selection.end for selection in selections).isoformat(),
        "proxy_check": proxy_check(rows),
        "forecast_check": forecast_check(rows),
    }
    (ledger / "backfill-tables.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    (ledger / "validation.md").write_text(
        render_validation(TypeAdapter(dict[str, JsonValue]).validate_python(report))
    )
    selections_path.write_bytes(TypeAdapter(list[DateSelection]).dump_json(selections, indent=2))
    (ledger / "backfill-manifest.json").write_text(
        json.dumps(
            {
                "release": "backfill-"
                + max(
                    (snapshot.recorded_at.date() for snapshot in snapshots), default=end
                ).isoformat(),
                "snapshots": provenance,
                "rule_set_versions": {
                    name: rule_set.version for name, rule_set in sorted(catalog.rule_sets.items())
                },
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    return len(sample)


@contextmanager
def backfill_lock(root: Path) -> Generator[None]:
    """Serialize commands so two processes cannot reserve the same allowance."""
    path = root / "data/backfill/run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            message = "Another backfill is using this directory; retry when it finishes"
            raise ValueError(message) from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _launch_sample(client: httpx.Client, selections: list[DateSelection]) -> list[Launch]:
    selected: dict[str, Launch] = {}
    for selection in selections:
        launches = fetch_previous(
            client,
            datetime.combine(selection.start, datetime.min.time(), UTC),
            (12, 27),
            mode="normal",
        )
        for launch in launches:
            if (
                selection.start <= launch.net.date() <= selection.end
                and launch.pad.location.id in {12, 27}
                and (launch.probability is not None or launch.weather_concerns is not None)
            ):
                selected[launch.id] = launch
    return sorted(selected.values(), key=lambda launch: (launch.net, launch.id))


def _selections(path: Path, start: date, end: date) -> list[DateSelection]:
    selections = (
        TypeAdapter(list[DateSelection]).validate_json(path.read_bytes()) if path.exists() else []
    )
    selection = DateSelection(start=start, end=end)
    if selection not in selections:
        if any(previous.start == start for previous in selections):
            message = "Existing launch selections are immutable; use a new start date for a top-up"
            raise ValueError(message)
        selections.append(selection)
    return selections


def render_validation(report: dict[str, JsonValue]) -> str:
    """Keep paired denominators and baselines beside each printed metric."""
    lines = [
        "# Retrospective validation",
        "",
        f"Launches n={report['n']}; {report['start']} through {report['end']}.",
        "",
        (
            "Intervals use 2,000 paired percentile resamples with seed 20261104. "
            "Undefined denominators stay undefined; undefined resamples are excluded. "
            "The JSON tables include each interval's valid resample count."
        ),
        "",
    ]
    for key, label in (("proxy_check", PROXY_LABEL), ("forecast_check", FORECAST_LABEL)):
        lines.extend(
            [
                f"## {key.replace('_', ' ').capitalize()}",
                "",
                label,
                "",
                (
                    "| Row | n | Positives | Value | 95% interval | Always flag precision | "
                    "Always flag recall | Balanced accuracy chance |"
                ),
                "| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
            ]
        )
        lines.extend(_metric_rows(report[key], key))
        lines.append("")
    return "\n".join(lines)


def _metric_rows(
    value: JsonValue, path: str, context: tuple[str, ...] = ("", "", "", "")
) -> list[str]:
    if isinstance(value, list):
        return [line for child in value for line in _metric_rows(child, path, context)]
    if not isinstance(value, dict):
        return []
    if "n" in value and "value" in value:
        metric = Metric.model_validate(value)
        interval = (
            "undefined"
            if metric.interval is None
            else f"[{metric.interval[0]:.6g}, {metric.interval[1]:.6g}]"
        )
        return [
            (
                f"| {path} | {metric.n} | {context[0]} | {_number(metric.value)} | {interval} | "
                f"{' | '.join(context[1:])} |"
            )
        ]
    labels = [str(value[key]) for key in ("model", "period", "scope", "lead_hours") if key in value]
    path = " / ".join([path, *labels])
    if "positives" in value:
        context = (_number(value["positives"]), *context[1:])
    if "always_flag_precision" in value:
        context = tuple(
            _number(value.get(key))
            for key in (
                "positives",
                "always_flag_precision",
                "always_flag_recall",
                "balanced_accuracy_chance",
            )
        )
    rows = [
        line
        for key, child in value.items()
        for line in _metric_rows(child, f"{path} / {key}", context)
    ]
    count = value.get("n", value.get("concern_lists", ""))
    rows.extend(
        f"| {path} / {key} | {count} | | {_number(value[key])} | | | | |"
        for key in (
            "missing_metar",
            "concern_lists",
            "unevaluable_concern_launches",
            "unevaluable_concern_share",
        )
        if key in value
    )
    coverage = value.get("concern_coverage")
    if isinstance(coverage, dict):
        rows.extend(
            (
                f"| concern: {name.replace('|', '/')} | {value['concern_lists']} | | "
                f"{_number(count)} | | | | |"
            )
            for name, count in coverage.items()
        )
    return rows


def _number(value: JsonValue) -> str:
    return f"{value:.6g}" if isinstance(value, (float, int)) else "undefined"
