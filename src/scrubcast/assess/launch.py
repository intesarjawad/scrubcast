"""Assemble launch assessments from resolved criteria and supplied forecasts."""

from dataclasses import dataclass, field
from math import isfinite
from statistics import fmean
from typing import TYPE_CHECKING

from scrubcast.assess.best_time import lowest_union_hour
from scrubcast.assess.climatology import Climatology, percentile
from scrubcast.assess.window import select_window
from scrubcast.models.assessment import (
    Context,
    GridPoint,
    LaunchAssessment,
    LowestHour,
    ModelRisk,
    Official,
    OmittedRule,
    RuleRisk,
)
from scrubcast.models.launch import Launch, parse_concerns
from scrubcast.models.rules import Confidence, RuleSelection
from scrubcast.rules.engine import HourAssessment, assess_hour
from scrubcast.rules.loader import RuleCatalog, resolve_plot
from scrubcast.rules.profile import Profile
from scrubcast.rules.proxies import convective, shear_per_km, upper_wind_mps

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from scrubcast.models.weather import EnsembleModel, EnsembleSeries


@dataclass(frozen=True)
class AssessmentRun:
    """Source times and optional historical context supplied by the caller."""

    now: datetime
    fetched_at: Mapping[EnsembleModel, datetime]
    refresh_deferred: bool = False
    climatology: Climatology = field(default_factory=lambda: Climatology((), ()))


MODELS: tuple[EnsembleModel, ...] = ("ecmwf", "gfs")


def _context(profiles: Sequence[Profile], history: Climatology) -> Context:
    convection = [value for profile in profiles if (value := convective(profile)) is not None]
    wind = [value for profile in profiles if (value := upper_wind_mps(profile)) is not None]
    shear = [value for profile in profiles if (value := shear_per_km(profile)) is not None]
    return Context(
        convective_fraction_t0=fmean(convection) if convection else None,
        upper_wind_percentile_t0=percentile(fmean(wind) if wind else None, history.upper_wind_mps),
        shear_percentile_t0=percentile(fmean(shear) if shear else None, history.shear_per_km),
    )


def _rule_metadata(selection: RuleSelection, catalog: RuleCatalog) -> list[RuleRisk]:
    result: list[RuleRisk] = []
    for rule in selection.rules:
        source = next(
            source
            for source in catalog.rule_sets.values()
            if any(item.rule_id == rule.rule_id for item in source.rules)
        )
        threshold, plot = resolve_plot(rule.plot, rule.proxy, rule.origin)
        result.append(
            RuleRisk(
                rule_id=rule.rule_id,
                title=rule.title,
                confidence=rule.confidence,
                reference_only=rule.reference_only,
                approximation_note=rule.approximation_note,
                llccr=rule.llccr,
                source_url=source.source_url,
                rule_set_version=source.version,
                by_model={},
                hours=[],
                risk_by_hour={},
                member_values_by_hour={},
                member_violated_by_hour={},
                threshold=threshold,
                plot=plot,
            )
        )
    if (vehicle := selection.vehicle) is not None:
        threshold, plot = resolve_plot(vehicle.plot, vehicle.parameters())
        result.append(
            RuleRisk(
                rule_id=vehicle.rule_id,
                title="Liftoff wind",
                confidence=Confidence.DIRECT
                if vehicle.measure == "sustained"
                else Confidence.MEDIUM,
                reference_only=False,
                approximation_note=vehicle.source_note,
                llccr=[],
                source_url=vehicle.source_url,
                rule_set_version=catalog.rule_sets[selection.site.rule_sets[0]].version,
                by_model={},
                hours=[],
                risk_by_hour={},
                member_values_by_hour={},
                member_violated_by_hour={},
                threshold=threshold,
                plot=plot,
            )
        )
    return result


def _populate_rule(
    rule: RuleRisk,
    hourly: Mapping[EnsembleModel, list[HourAssessment]],
    hours: list[datetime],
    t0_index: int,
) -> None:
    rule.hours = hours
    for model in MODELS:
        assessments = hourly.get(model, [])
        evidence = [hour.rules[rule.rule_id] for hour in assessments]
        t0 = evidence[t0_index] if evidence else None
        rule.by_model[model] = ModelRisk(
            risk_fraction=t0.risk_fraction if t0 else None,
            evaluable_members=t0.evaluable_members if t0 else 0,
            members=assessments[t0_index].members if assessments else 0,
        )
        rule.risk_by_hour[model] = (
            [hour.risk_fraction for hour in evidence] if evidence else [None] * len(hours)
        )
        rule.member_values_by_hour[model] = (
            [
                [
                    round(member.value, 1)
                    if member.value is not None and isfinite(member.value)
                    else None
                    for member in hour.member_results
                ]
                for hour in evidence
            ]
            if evidence
            else None
        )
        rule.member_violated_by_hour[model] = (
            [
                [
                    None
                    if member.verdict == "not_evaluable"
                    else (1 if member.verdict == "violated" else 0)
                    for member in hour.member_results
                ]
                for hour in evidence
            ]
            if evidence
            else None
        )


def assess_launch(
    launch: Launch,
    series: Sequence[EnsembleSeries],
    catalog: RuleCatalog,
    run: AssessmentRun,
) -> LaunchAssessment:
    """Evaluate a covered window; reject incomplete forecasts for per-launch logging."""
    selection = catalog.rules_for(launch.pad, launch.rocket_name)
    by_model: dict[EnsembleModel, EnsembleSeries] = {item.model: item for item in series}
    if not by_model or len(by_model) != len(series):
        msg = "Expected at least one forecast and no duplicate models"
        raise ValueError(msg)
    primary = by_model.get("ecmwf", next(iter(by_model.values())))
    window = select_window(
        primary.hours,
        net=launch.net,
        window_start=launch.window_start,
        window_end=launch.window_end,
    )
    if window.beyond_forecast_range or window.t0_index is None:
        msg = "window beyond forecast range"
        raise ValueError(msg)
    hours, t0_index = list(window.hours), window.t0_index
    hourly: dict[EnsembleModel, list[HourAssessment]] = {}
    t0_profiles: list[Profile] = []
    for model, forecast in by_model.items():
        if not set(hours) <= set(forecast.hours):
            msg = f"{model}: window beyond forecast range"
            raise ValueError(msg)
        for name, values in forecast.values.items():
            if values.shape != (forecast.members, len(forecast.hours)):
                msg = f"{model} {name}: member/hour shape does not match metadata"
                raise ValueError(msg)
        assessments: list[HourAssessment] = []
        for hour in hours:
            index = forecast.hours.index(hour)
            profiles = [
                Profile.from_series(forecast, member=member, hour=index)
                for member in range(forecast.members)
            ]
            assessments.append(assess_hour(profiles, selection))
            if forecast is primary and hour == hours[t0_index]:
                t0_profiles = profiles
        hourly[model] = assessments
    rules = _rule_metadata(selection, catalog)
    for rule in rules:
        _populate_rule(rule, hourly, hours, t0_index)
    lowest = lowest_union_hour(
        hours,
        hourly.get("ecmwf"),
        t0_index=t0_index,
        window_start=launch.window_start,
        window_end=launch.window_end,
    )
    concerns = parse_concerns(launch.weather_concerns)
    return LaunchAssessment(
        launch=launch,
        tier=selection.site.tier,
        evaluated_at=run.now,
        fetched_at={model: run.fetched_at.get(model) for model in MODELS},
        refresh_deferred=run.refresh_deferred,
        grid_point=GridPoint(
            lat=primary.grid_point.latitude,
            lon=primary.grid_point.longitude,
            elevation_m=primary.grid_point.elevation,
        ),
        t0_index=t0_index,
        rules=rules,
        union_risk_t0={
            model: hourly[model][t0_index].union_risk_fraction if model in hourly else None
            for model in MODELS
        },
        lowest_union_hour=LowestHour(
            hour=lowest.hour, union_risk=lowest.union_risk, members_below_t0=lowest.members_below_t0
        )
        if lowest
        else None,
        not_evaluable=[
            OmittedRule(rule_id=rule.rule_id, title=rule.title, reason=rule.reason)
            for rule in selection.not_evaluable
        ],
        context=_context(t0_profiles, run.climatology),
        official=Official(
            probability_go_pct=launch.probability,
            concerns=concerns,
            unmapped_concerns=[
                name for name in concerns if catalog.normalise_concern(name).rule_id is None
            ],
        ),
    )
