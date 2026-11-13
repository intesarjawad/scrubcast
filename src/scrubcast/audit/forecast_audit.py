"""Forward checks of ledgered ensemble forecasts against observations and outcomes."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from statistics import fmean
from typing import TYPE_CHECKING, Literal

import numpy as np
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

from scrubcast.archive.slices import load_slices
from scrubcast.audit.backfill import nearest_observation
from scrubcast.audit.observations import read_observations, station_for
from scrubcast.audit.outcomes import AttemptOutcome, Outcome, select_attempts
from scrubcast.audit.proxy_check import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, SPLIT_DATE
from scrubcast.models.assessment import AuditFooter, AuditNote, AuditRule, LedgerRow
from scrubcast.models.observation import Observation
from scrubcast.models.rules import Confidence

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from scrubcast.rules.loader import RuleCatalog


LEADS = (72, 48, 24, 12, 6)
BUCKET_TOLERANCE = timedelta(hours=3)
NET_TOLERANCE = timedelta(minutes=30)
MIN_METRIC_N = 10
MIN_RANK_N = 30
MIN_RELIABILITY_N = 50
MIN_ATTEMPT_CLASS_N = 5
RELIABILITY_BINS = 5
RANK_BINS = 10
PRECIPITATION_EVENT_IN = 0.01
WIND_LABEL = (
    "ECMWF and GFS 10 m wind members at the hour of the final NET checked against METAR. "
    "The reference is a climatological ensemble from ten years of METAR at the same station, "
    "calendar day within 15 days and hour within 1 hour."
)
OBSERVATION_LABEL = (
    "The flight-through-precipitation rule at the 24-hour bucket checked against the observed "
    "precipitation event in the hour of the final NET. The reference is the station's "
    "climatological event frequency from the same ten-year METAR sample."
)
CONCERNS_LABEL = (
    "Agreement with the official forecast: the Brier-form score of rule risk at 24 hours against "
    "the rule being named in the official concerns. Official concerns are another forecast, "
    "not an observed outcome, so this is an agreement measure."
)
ATTEMPT_LABEL = (
    "Attempt outcomes: launched in the window against did not launch in it, all causes: "
    "non-weather scrubs included. Unknown outcomes are excluded and counted. This is the "
    "weakest of the evaluations."
)
LOWEST_LABEL = (
    "The lowest modelled-risk hour checked against observed precipitation only, not cloud or wind."
)
INSUFFICIENT = "insufficient data"


@dataclass(frozen=True)
class _FooterEvidence:
    attempt_id: str
    attempt_net: datetime
    official_concerns: Sequence[str]
    samples: Sequence[RuleRiskSample]
    outcome: Outcome
    net_now: datetime | None
    note: AuditNote | None


class RuleRiskSample(BaseModel):
    """One rule's 24-hour risk and whether the rule can carry direct or medium confidence."""

    rule_id: str
    title: str
    confidence: Confidence
    risk: float | None = Field(default=None, ge=0, le=1)


class ForecastRun(BaseModel):
    """One archived forecast run for a launch, including the raw wind members."""

    model_config = ConfigDict(extra="forbid")

    run_at: AwareDatetime
    net: AwareDatetime
    wind_members: dict[Literal["ecmwf", "gfs"], list[float]] = Field(
        default_factory=dict[Literal["ecmwf", "gfs"], list[float]]
    )
    precipitation_risk: float | None = Field(default=None, ge=0, le=1)
    union_risk: float | None = Field(default=None, ge=0, le=1)
    lowest_hour: AwareDatetime | None = None
    lowest_hour_union: float | None = Field(default=None, ge=0, le=1)
    rules: list[RuleRiskSample] = Field(default_factory=list[RuleRiskSample])
    official_go_pct: int | None = Field(default=None, ge=0, le=100)
    official_concerns: list[str] = Field(default_factory=list)


class ForecastLaunch(BaseModel):
    """A launch's archived runs, station measurements and audited attempt outcome."""

    model_config = ConfigDict(extra="forbid")

    launch_id: str
    net: AwareDatetime
    runs: list[ForecastRun]
    station: str | None = None
    observations: list[Observation] = Field(default_factory=list[Observation])
    outcome: Outcome | None = None
    outcome_net: AwareDatetime | None = None
    note: str | None = None
    note_created_on: AwareDatetime | None = None


class ForecastLedger(BaseModel):
    """The forward ledger plus the fixed ten-year climatological METAR sample."""

    model_config = ConfigDict(extra="forbid")

    launches: list[ForecastLaunch]
    climatology: list[Observation] = Field(default_factory=list[Observation])


class AuditMetric(BaseModel):
    """A printed metric with its sample size and the reference it is read against."""

    label: str
    n: int = Field(ge=0)
    value: float | None = None
    baseline: float | None = None
    interval: tuple[float, float] | None = None
    sufficient: bool = False

    @property
    def display(self) -> str:
        """Keep the sample size beside every value, including missing metrics."""
        if not self.sufficient or self.value is None:
            return f"{INSUFFICIENT} (n={self.n})"
        return f"{self.value:.6g} (n={self.n})"


class ReliabilityBin(BaseModel):
    """Predicted risk and observed event frequency in one fixed-width bin."""

    lower: float
    upper: float
    n: int
    predicted: float | None
    observed: float | None


class Evaluation(BaseModel):
    """One of the three evidence families kept apart on the audit page."""

    key: Literal["wind", "observation", "concerns"]
    title: str
    label: str
    summary: str
    n: int
    rows: list[AuditMetric]
    reliability: list[ReliabilityBin] | None = None
    rank_histogram: list[float] | None = None
    rank_histograms: dict[str, list[float]] | None = None


class AttemptRow(BaseModel):
    """One audited attempt with its 24-hour union risk and official GO value."""

    attempt_id: str
    net: AwareDatetime
    union_risk: float | None
    official_go_pct: int | None
    outcome: Outcome
    note: str | None
    scored: bool


class AttemptEvaluation(BaseModel):
    """Launch-versus-scrub comparison, kept separate from calibration metrics."""

    label: str
    n: int
    launched: int
    not_launched: int
    unknown: int
    rows: list[AttemptRow]
    auc: float | None = None
    interval: tuple[float, float] | None = None
    message: str | None = None


class LowestHourEvaluation(BaseModel):
    """Paired observed precipitation at the marked hour and at T-0."""

    label: str
    n: int
    risk_at_lowest: float | None
    risk_at_t0: float | None
    precipitation_at_lowest: float | None
    precipitation_at_t0: float | None
    difference: float | None
    interval: tuple[float, float] | None
    verified: bool


class ForecastAudit(BaseModel):
    """Forward audit tables, with an explicit insufficient-data state at every metric."""

    n_launches: int
    evaluations: list[Evaluation]
    attempts: AttemptEvaluation
    lowest_hour: LowestHourEvaluation
    lowest_hour_verified: bool


def bucket_run(launch: ForecastLaunch, lead: int) -> ForecastRun | None:
    """Select the nearest run within three hours whose final NET matches within thirty minutes."""
    candidates = [
        run
        for run in launch.runs
        if abs((run.net - run.run_at) - timedelta(hours=lead)) <= BUCKET_TOLERANCE
        and abs(run.net - launch.net) <= NET_TOLERANCE
    ]
    return min(
        candidates,
        key=lambda run: (abs((run.net - run.run_at) - timedelta(hours=lead)), run.run_at),
        default=None,
    )


def _climatology_sample(
    observations: Sequence[Observation], net: datetime, station: str | None
) -> list[Observation]:
    target_day = net.replace(year=2000).timetuple().tm_yday
    selected: list[Observation] = []
    for row in observations:
        if row.station != station:
            continue
        day_distance = abs(row.valid.replace(year=2000).timetuple().tm_yday - target_day)
        hour_distance = abs(row.valid.hour - net.hour)
        if (
            min(day_distance, 366 - day_distance) <= 15
            and min(hour_distance, 24 - hour_distance) <= 1
        ):
            selected.append(row)
    return selected


def _observed_event(observation: Observation | None) -> float | None:
    if observation is None or observation.precipitation_in is None:
        return None
    return float(observation.precipitation_in >= PRECIPITATION_EVENT_IN)


def fair_crps(members: Sequence[float], observed: float) -> float | None:
    """Use the fair ensemble score so a small member set is not rewarded for sharpness."""
    values = [value for value in members if isfinite(value)]
    if not values:
        return None
    first = fmean(abs(value - observed) for value in values)
    if len(values) < 2:
        return first
    pairwise = sum(
        abs(left - right) for index, left in enumerate(values) for right in values[index + 1 :]
    )
    return first - pairwise / (len(values) * (len(values) - 1))


def _mean(values: Sequence[float]) -> float | None:
    return fmean(values) if values else None


def _bootstrap_mean(
    values: Sequence[float], *, seed: int = BOOTSTRAP_SEED
) -> tuple[float, float] | None:
    if not values:
        return None
    data = np.asarray(values, dtype=np.float64)
    if len(data) == 1:
        return (float(data[0]), float(data[0]))
    rng = np.random.default_rng(seed)
    draws = rng.integers(len(data), size=(BOOTSTRAP_RESAMPLES, len(data)))
    means = data[draws].mean(axis=1)
    interval = np.quantile(means, [0.025, 0.975])
    return (float(interval[0]), float(interval[1]))


def _metric(
    label: str, pairs: Sequence[tuple[float, float] | tuple[float, float, float]]
) -> AuditMetric:
    values = [
        [float(value) for value in pair] for pair in pairs if all(isfinite(value) for value in pair)
    ]
    if not values:
        return AuditMetric(label=label, n=0, sufficient=False)
    n = len(values)
    value = fmean(row[0] for row in values)
    baseline = fmean(row[1] for row in values) if len(values[0]) > 1 else None
    return AuditMetric(
        label=label,
        n=n,
        value=value,
        baseline=baseline,
        sufficient=n >= MIN_METRIC_N,
    )


def _skill_metric(label: str, pairs: Sequence[tuple[float, float]]) -> AuditMetric:
    metric = _metric(label, pairs)
    metric.value = (
        1 - metric.value / metric.baseline
        if metric.value is not None and metric.baseline not in (None, 0)
        else None
    )
    metric.baseline = 0.0 if metric.value is not None else None
    return metric


def _station_observation(launch: ForecastLaunch, at: datetime) -> Observation | None:
    return nearest_observation(
        [row for row in launch.observations if row.station == launch.station], at
    )


def _wind_evaluation(ledger: ForecastLedger) -> Evaluation:
    rows: list[AuditMetric] = []
    histograms: dict[str, list[float]] = {}
    for model in ("ecmwf", "gfs"):
        crps: list[tuple[float, float]] = []
        rank_counts = [0.0] * RANK_BINS
        rank_n = 0
        for launch in ledger.launches:
            run = bucket_run(launch, 24)
            observation = _station_observation(launch, launch.net)
            if run is None or observation is None or observation.wind_speed_mps is None:
                continue
            members = run.wind_members.get(model, [])
            forecast = fair_crps(members, observation.wind_speed_mps)
            climate_members = [
                row.wind_speed_mps
                for row in _climatology_sample(ledger.climatology, launch.net, launch.station)
                if row.wind_speed_mps is not None
            ]
            climate = fair_crps(climate_members, observation.wind_speed_mps)
            if forecast is None or climate is None:
                continue
            crps.append((forecast, climate))
            if members:
                below = sum(member < observation.wind_speed_mps for member in members)
                equal = sum(member == observation.wind_speed_mps for member in members)
                for rank in range(below, below + equal + 1):
                    rank_counts[min(RANK_BINS - 1, rank * RANK_BINS // (len(members) + 1))] += 1 / (
                        equal + 1
                    )
                rank_n += 1
        rows.append(_metric(f"{model.upper()} wind CRPS (m/s)", crps))
        rows.append(_skill_metric(f"{model.upper()} wind CRPS skill", crps))
        if rank_n >= MIN_RANK_N:
            histograms[model.upper()] = rank_counts
    best = max(
        (row for row in rows if row.label.endswith("CRPS skill")),
        key=lambda row: row.value if row.value is not None else float("-inf"),
        default=None,
    )
    summary = (
        f"{best.label} {best.display} (best model)"
        if best is not None and best.sufficient and best.value is not None
        else f"Wind: {INSUFFICIENT} (n={max((row.n for row in rows), default=0)})"
    )
    return Evaluation(
        key="wind",
        title="Wind input against observation",
        label=WIND_LABEL,
        summary=summary,
        n=max((row.n for row in rows), default=0),
        rows=rows,
        rank_histogram=[sum(values) for values in zip(*histograms.values(), strict=True)]
        if histograms
        else None,
        rank_histograms=histograms or None,
    )


def _reliability(rows: Sequence[tuple[float, float]]) -> list[ReliabilityBin]:
    bins: list[ReliabilityBin] = []
    for index in range(RELIABILITY_BINS):
        lower = index / RELIABILITY_BINS
        upper = (index + 1) / RELIABILITY_BINS
        selected = [
            (risk, observed)
            for risk, observed in rows
            if lower <= risk < upper or (index == RELIABILITY_BINS - 1 and risk == 1)
        ]
        bins.append(
            ReliabilityBin(
                lower=lower,
                upper=upper,
                n=len(selected),
                predicted=_mean([risk for risk, _ in selected]),
                observed=_mean([observed for _, observed in selected]),
            )
        )
    return bins


def _observation_evaluation(ledger: ForecastLedger) -> Evaluation:
    pairs: list[tuple[float, float, float]] = []
    for launch in ledger.launches:
        run = bucket_run(launch, 24)
        observation = _station_observation(launch, launch.net)
        observed = _observed_event(observation)
        if run is None or run.precipitation_risk is None or observed is None:
            continue
        climate = _climatology_sample(ledger.climatology, launch.net, launch.station)
        climate_events = [
            float(row.precipitation_in >= PRECIPITATION_EVENT_IN)
            for row in climate
            if row.precipitation_in is not None
        ]
        if not climate_events:
            continue
        pairs.append((run.precipitation_risk, observed, fmean(climate_events)))
    # Keep the Brier score and its reference in the same row so the baseline stays visible.
    brier = _metric(
        "flight_through_precip Brier score",
        [((pair[0] - pair[1]) ** 2, (pair[2] - pair[1]) ** 2) for pair in pairs],
    )
    rows = [
        brier,
        _skill_metric(
            "flight_through_precip Brier skill",
            [
                ((risk - observed) ** 2, (climate - observed) ** 2)
                for risk, observed, climate in pairs
            ],
        ),
    ]
    reliability = (
        _reliability([(pair[0], pair[1]) for pair in pairs])
        if len(pairs) >= MIN_RELIABILITY_N
        else None
    )
    summary = (
        f"Precipitation Brier skill {rows[1].display}"
        if rows[1].sufficient and rows[1].value is not None
        else f"Precipitation: {INSUFFICIENT} (n={brier.n})"
    )
    return Evaluation(
        key="observation",
        title="Rule against observation",
        label=OBSERVATION_LABEL,
        summary=summary,
        n=brier.n,
        rows=rows,
        reliability=reliability,
    )


def _concern_observations(
    ledger: ForecastLedger,
) -> dict[str, list[tuple[float, float, str]]]:
    grouped: dict[str, list[tuple[float, float, str]]] = {}
    for launch in ledger.launches:
        run = bucket_run(launch, 24)
        if run is None:
            continue
        for rule in run.rules:
            if rule.confidence not in {Confidence.DIRECT, Confidence.MEDIUM} or rule.risk is None:
                continue
            observed = float(rule.rule_id in run.official_concerns)
            day = launch.net.date().isoformat()
            grouped.setdefault(rule.rule_id, []).append((rule.risk, observed, day))
    return grouped


def _concerns_evaluation(ledger: ForecastLedger) -> Evaluation:
    rows: list[AuditMetric] = []
    grouped = _concern_observations(ledger)
    overall: list[tuple[float, float]] = []
    for rule_id, pairs in sorted(grouped.items()):
        development = [observed for _, observed, day in pairs if day < SPLIT_DATE.isoformat()]
        base_rate = fmean(development) if development else fmean(pair[1] for pair in pairs)
        scored = [
            ((risk - observed) ** 2, (base_rate - observed) ** 2) for risk, observed, _ in pairs
        ]
        rows.append(_metric(f"{rule_id} Brier score", scored))
        overall.extend(scored)
    combined = _metric("All direct and medium rules Brier score", overall)
    rows.append(combined)
    summary = (
        f"Official-concern Brier score {combined.display}"
        if combined.sufficient and combined.value is not None
        else f"Official concerns: {INSUFFICIENT} (n={combined.n})"
    )
    return Evaluation(
        key="concerns",
        title="Agreement with the official forecast",
        label=CONCERNS_LABEL,
        summary=summary,
        n=combined.n,
        rows=rows,
    )


def _auc(scored: Sequence[tuple[float, bool]]) -> float | None:
    positives = [score for score, launched in scored if launched]
    negatives = [score for score, launched in scored if not launched]
    if not positives or not negatives:
        return None
    total = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return total / (len(positives) * len(negatives))


def _attempts(ledger: ForecastLedger) -> AttemptEvaluation:
    rows: list[AttemptRow] = []
    for launch in ledger.launches:
        if launch.outcome is None:
            continue
        run = bucket_run(launch, 24)
        rows.append(
            AttemptRow(
                attempt_id=launch.launch_id,
                net=launch.net,
                union_risk=run.union_risk if run is not None else None,
                official_go_pct=run.official_go_pct if run is not None else None,
                outcome=launch.outcome,
                note=launch.note,
                scored=(
                    launch.outcome != "unknown" and run is not None and run.union_risk is not None
                ),
            )
        )
    known = [
        row
        for row in rows
        if row.outcome
        in {
            "launched",
            "launched_later",
            "new_t0_pending",
            "hold",
        }
        and row.union_risk is not None
    ]
    launched = sum(row.outcome == "launched" for row in known)
    not_launched = len(known) - launched
    unknown = sum(row.outcome == "unknown" for row in rows)
    # Lower union risk should score higher for a launch, matching the page's reading order.
    scored = [
        (1 - row.union_risk, row.outcome == "launched")
        for row in known
        if row.union_risk is not None
    ]
    auc = _auc(scored)
    interval = None
    message = None
    if launched < MIN_ATTEMPT_CLASS_N or not_launched < MIN_ATTEMPT_CLASS_N:
        auc = None
        message = f"{INSUFFICIENT} (attempts not launched n={not_launched})"
    else:
        interval = _bootstrap_auc(scored)
    return AttemptEvaluation(
        label=ATTEMPT_LABEL,
        n=len(known),
        launched=launched,
        not_launched=not_launched,
        unknown=unknown,
        rows=rows,
        auc=auc,
        interval=interval,
        message=message,
    )


def _bootstrap_auc(scored: Sequence[tuple[float, bool]]) -> tuple[float, float] | None:
    if not scored:
        return None
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    values = list(scored)
    draws: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        indexes = [int(index) for index in rng.integers(len(values), size=len(values))]
        sample = [values[index] for index in indexes]
        score = _auc(sample)
        if score is not None:
            draws.append(score)
    if not draws:
        return None
    interval = np.quantile(draws, [0.025, 0.975])
    return (float(interval[0]), float(interval[1]))


def _lowest_hour(ledger: ForecastLedger) -> LowestHourEvaluation:
    differences: list[float] = []
    risks_lowest: list[float] = []
    risks_t0: list[float] = []
    observed_lowest: list[float] = []
    observed_t0: list[float] = []
    for launch in ledger.launches:
        run = bucket_run(launch, 24)
        if run is None or run.lowest_hour is None:
            continue
        low_observation = _station_observation(launch, run.lowest_hour)
        net_observation = _station_observation(launch, launch.net)
        low_event = _observed_event(low_observation)
        net_event = _observed_event(net_observation)
        if low_event is None or net_event is None:
            continue
        observed_lowest.append(low_event)
        observed_t0.append(net_event)
        if run.lowest_hour_union is not None:
            risks_lowest.append(run.lowest_hour_union)
        if run.union_risk is not None:
            risks_t0.append(run.union_risk)
        differences.append(low_event - net_event)
    interval = _bootstrap_mean(differences)
    n = len(differences)
    verified = n >= MIN_METRIC_N and interval is not None and interval[1] < 0
    return LowestHourEvaluation(
        label=LOWEST_LABEL,
        n=n,
        risk_at_lowest=_mean(risks_lowest),
        risk_at_t0=_mean(risks_t0),
        precipitation_at_lowest=_mean(observed_lowest),
        precipitation_at_t0=_mean(observed_t0),
        difference=_mean(differences),
        interval=interval,
        verified=verified,
    )


def audit_forecasts(ledger: ForecastLedger) -> ForecastAudit:
    """Evaluate every family independently, reporting insufficient data instead of inventing it."""
    lowest = _lowest_hour(ledger)
    return ForecastAudit(
        n_launches=len(ledger.launches),
        evaluations=[
            _wind_evaluation(ledger),
            _observation_evaluation(ledger),
            _concerns_evaluation(ledger),
        ],
        attempts=_attempts(ledger),
        lowest_hour=lowest,
        lowest_hour_verified=lowest.verified,
    )


def read_ledger_records(directory: Path) -> list[LedgerRow]:
    """Read collector rows from one directory and ignore retrospective evidence records."""
    rows: list[LedgerRow] = []
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            try:
                rows.append(LedgerRow.model_validate_json(line))
            except ValueError:
                continue
    return sorted(rows, key=lambda row: (row.run_at, row.launch_id))


def read_forward_ledger(root: Path) -> list[LedgerRow]:
    """Read collector rows and ignore retrospective evidence records."""
    return read_ledger_records(root / "ledger")


def load_outcome_records(directory: Path) -> dict[str, AttemptOutcome]:
    """Read committed outcome records from one ledger directory."""
    path = directory / "outcomes.jsonl"
    results: list[AttemptOutcome] = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                results.append(AttemptOutcome.model_validate_json(line))
            except ValueError:
                continue
    else:
        legacy = directory / "outcomes.json"
        if legacy.exists():
            results = TypeAdapter(list[AttemptOutcome]).validate_json(legacy.read_text())
    return {result.attempt_id: result for result in results}


def load_outcomes(root: Path) -> dict[str, AttemptOutcome]:
    """Read the committed outcome records kept beside the monthly ledger rows."""
    return load_outcome_records(root / "ledger")


def _outcomes(root: Path) -> dict[tuple[str, datetime], AttemptOutcome]:
    latest: dict[tuple[str, datetime], AttemptOutcome] = {}
    for result in load_outcomes(root).values():
        launch_id = result.attempt_id.rsplit("@", 1)[0]
        latest[(launch_id, result.attempt_net)] = result
    return latest


def _slice_members(
    root: Path,
) -> dict[tuple[str, datetime], dict[Literal["ecmwf", "gfs"], list[float]]]:
    members: dict[tuple[str, datetime], dict[Literal["ecmwf", "gfs"], list[float]]] = {}
    for path in sorted((root / "archive").glob("*.npz")):
        metadata, arrays = load_slices(path)
        for saved in metadata.launches:
            for model, item in saved.models.items():
                values = arrays[item.array_key]
                if "wind_speed_10m" not in item.variable_order:
                    continue
                index = item.variable_order.index("wind_speed_10m")
                hour = saved.launch.net.replace(minute=0, second=0, microsecond=0)
                if saved.launch.net - hour > timedelta(minutes=30):
                    hour += timedelta(hours=1)
                if hour not in item.hours:
                    continue
                column = item.hours.index(hour)
                members.setdefault((saved.launch.id, metadata.run_at), {})[model] = [
                    float(value) for value in values[index, :, column] if isfinite(float(value))
                ]
    return members


def _rule_samples(row: LedgerRow, confidences: dict[str, Confidence]) -> list[RuleRiskSample]:
    titles = {
        "thick_cloud": "Thick cloud",
        "cumulus": "Cumulus cloud",
        "anvil": "Anvil cloud",
        "disturbed_weather": "Disturbed weather",
        "flight_through_precip": "Flight through precipitation",
        "liftoff_wind": "Liftoff wind",
    }
    return [
        RuleRiskSample(
            rule_id=rule_id,
            title=titles.get(rule_id, rule_id.replace("_", " ").capitalize()),
            confidence=confidences.get(rule_id, Confidence.DIRECT),
            risk=risks[0],
        )
        for rule_id, risks in sorted(row.rules.items())
        if risks[0] is not None
    ]


def load_forecast_ledger(root: Path, catalog: RuleCatalog | None = None) -> ForecastLedger:
    """Join collector rows, archived members, station measurements and attempt outcomes."""
    observations = read_observations(root / "data/iem/observations.json")
    climate = read_observations(root / "data/iem/climatology.json")
    outcomes = _outcomes(root)
    slices = _slice_members(root)
    confidences = _confidences(catalog)
    grouped: dict[tuple[str, datetime], list[LedgerRow]] = {}
    for row in read_forward_ledger(root):
        grouped.setdefault((row.launch_id, row.net), []).append(row)
    launches: list[ForecastLaunch] = []
    for (launch_id, net), rows in sorted(grouped.items()):
        result = outcomes.get((launch_id, net))
        station = station_for(rows[-1], catalog) if catalog is not None else None
        runs = [
            ForecastRun(
                run_at=row.run_at,
                net=row.net,
                wind_members=slices.get((launch_id, row.run_at), {}),
                precipitation_risk=row.rules.get("flight_through_precip", (None, None))[0],
                union_risk=row.union[0],
                lowest_hour=row.lowest_hour,
                lowest_hour_union=row.lowest_hour_union,
                rules=_rule_samples(row, confidences),
                official_go_pct=row.official_go_pct,
                official_concerns=row.official_concerns,
            )
            for row in rows
        ]
        launches.append(
            ForecastLaunch(
                launch_id=launch_id,
                net=net,
                runs=runs,
                station=station,
                observations=observations.get(station, []) if station else [],
                outcome=result.outcome if result is not None else None,
                outcome_net=result.net_now if result is not None else None,
                note=result.note.text if result is not None and result.note is not None else None,
                note_created_on=(
                    result.note.created_on
                    if result is not None and result.note is not None
                    else None
                ),
            )
        )
    return ForecastLedger(
        launches=launches, climatology=[row for station in climate.values() for row in station]
    )


def _audit_footer(evidence: _FooterEvidence) -> AuditFooter:
    rules = [
        AuditRule(rule_id=rule.rule_id, title=rule.title, risk_fraction=rule.risk)
        for rule in evidence.samples
        if rule.risk is not None and rule.risk > 0
    ]
    return AuditFooter(
        attempt_id=evidence.attempt_id,
        attempt_net=evidence.attempt_net,
        official_concerns=list(evidence.official_concerns),
        scrubcast_24h=sorted(rules, key=lambda rule: -rule.risk_fraction),
        outcome=evidence.outcome,
        net_now=evidence.net_now,
        note=evidence.note,
    )


def _confidences(catalog: RuleCatalog | None) -> dict[str, Confidence]:
    return {
        rule.rule_id: rule.confidence
        for rule_set in (catalog.rule_sets.values() if catalog is not None else ())
        for rule in rule_set.rules
    }


def attempt_footers(
    rows: Sequence[LedgerRow],
    outcomes: Mapping[str, AttemptOutcome],
    catalog: RuleCatalog | None = None,
) -> dict[str, list[AuditFooter]]:
    """Attach footers from the 24-hour ledger row and committed outcomes alone."""
    confidences = _confidences(catalog)
    footers: dict[str, list[AuditFooter]] = {}
    for attempt in select_attempts(rows):
        result = outcomes.get(attempt.attempt_id)
        if result is None:
            continue
        row = attempt.forecast
        footers.setdefault(row.launch_id, []).append(
            _audit_footer(
                _FooterEvidence(
                    attempt_id=attempt.attempt_id,
                    attempt_net=attempt.attempt_net,
                    official_concerns=row.official_concerns,
                    samples=_rule_samples(row, confidences),
                    outcome=result.outcome,
                    net_now=result.net_now,
                    note=result.note,
                )
            )
        )
    return {
        launch_id: sorted(items, key=lambda footer: footer.attempt_net, reverse=True)
        for launch_id, items in footers.items()
    }


def launch_footers(ledger: ForecastLedger) -> dict[str, list[AuditFooter]]:
    """Attach one footer per audited attempt, newest first, for past launch pages."""
    footers: dict[str, list[AuditFooter]] = {}
    for launch in ledger.launches:
        if launch.outcome is None:
            continue
        run = bucket_run(launch, 24)
        footers.setdefault(launch.launch_id, []).append(
            _audit_footer(
                _FooterEvidence(
                    attempt_id=(
                        f"{launch.launch_id}@{launch.net.isoformat().replace('+00:00', 'Z')}"
                    ),
                    attempt_net=launch.net,
                    official_concerns=run.official_concerns if run is not None else [],
                    samples=run.rules if run is not None else [],
                    outcome=launch.outcome,
                    net_now=launch.outcome_net,
                    note=(
                        AuditNote(created_on=launch.note_created_on or launch.net, text=launch.note)
                        if launch.note is not None
                        else None
                    ),
                )
            )
        )
    return {
        launch_id: sorted(items, key=lambda footer: footer.attempt_net, reverse=True)
        for launch_id, items in footers.items()
    }
