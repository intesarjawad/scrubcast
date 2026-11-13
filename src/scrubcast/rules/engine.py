"""Per-rule member assessments and the union of supported rule violations."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from scrubcast.rules import proxies

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from scrubcast.models.rules import NotEvaluable, Parameter, RuleSelection
    from scrubcast.rules.profile import Profile
    from scrubcast.rules.proxies import ProxyResult

type Proxy = Callable[[Profile, Mapping[str, Parameter]], ProxyResult]


@dataclass(frozen=True)
class RuleHourAssessment:
    """Member evidence and the denominator used for one rule's risk fraction."""

    member_results: tuple[ProxyResult, ...]
    evaluable_members: int
    violating_members: int

    @property
    def risk_fraction(self) -> float | None:
        """Return no fraction when the rule has no evaluable members."""
        return self.violating_members / self.evaluable_members if self.evaluable_members else None


@dataclass(frozen=True)
class HourAssessment:
    """One model/hour, preserving the all-member denominator for the union."""

    members: int
    rules: dict[str, RuleHourAssessment]
    union_violating_members: int
    not_evaluable: tuple[NotEvaluable, ...] = ()

    @property
    def union_risk_fraction(self) -> float | None:
        """Return the violating member union divided by every member supplied."""
        return self.union_violating_members / self.members if self.members else None


def _proxy(kind: Parameter) -> Proxy:
    match kind:
        case "thick_cloud":
            return proxies.thick_cloud
        case "cumulus":
            return proxies.cumulus
        case "anvil":
            return proxies.anvil
        case "disturbed_weather":
            return proxies.disturbed_weather
        case "flight_through_precip":
            return proxies.flight_through_precip
        case _:
            msg = f"Unsupported proxy kind: {kind}"
            raise ValueError(msg)


def _evaluate(
    profiles: list[Profile], proxy: Proxy, params: Mapping[str, Parameter]
) -> RuleHourAssessment:
    results = tuple(proxy(profile, params) for profile in profiles)
    return RuleHourAssessment(
        member_results=results,
        evaluable_members=sum(result.verdict != "not_evaluable" for result in results),
        violating_members=sum(result.verdict == "violated" for result in results),
    )


def assess_hour(profiles: list[Profile], selection: RuleSelection) -> HourAssessment:
    """Evaluate selected site criteria and the vehicle wind limit together.

    Rule risks use evaluable members; union risk uses all members. Only direct
    and medium confidence criteria outside the reference set enter the union.
    """
    rules: dict[str, RuleHourAssessment] = {}
    violating_members: set[int] = set()
    for rule in selection.rules:
        result = _evaluate(profiles, _proxy(rule.proxy["kind"]), rule.proxy)
        rules[rule.rule_id] = result
        if rule.confidence in {"direct", "medium"} and not rule.reference_only:
            violating_members.update(
                member
                for member, evidence in enumerate(result.member_results)
                if evidence.verdict == "violated"
            )
    if selection.vehicle is not None:
        vehicle = selection.vehicle
        result = _evaluate(
            profiles, proxies.liftoff_wind, {**vehicle.parameters(), "measure": vehicle.measure}
        )
        rules[vehicle.rule_id] = result
        violating_members.update(
            member
            for member, evidence in enumerate(result.member_results)
            if evidence.verdict == "violated"
        )
    return HourAssessment(
        members=len(profiles),
        rules=rules,
        union_violating_members=len(violating_members),
        not_evaluable=tuple(selection.not_evaluable),
    )
