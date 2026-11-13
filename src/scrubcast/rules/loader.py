"""Validate versioned rule files and resolve launch-specific criteria and plots."""

from dataclasses import dataclass
from decimal import Decimal
from importlib.resources import files
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import TypeAdapter

from scrubcast.models.rules import (
    Comparator,
    ConcernMatch,
    ForecastPoint,
    NotEvaluable,
    Parameter,
    Plot,
    ResolvedPlot,
    RuleSelection,
    RuleSet,
    SiteConfig,
    Threshold,
    VehicleConfig,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from scrubcast.models.launch import Pad

_PACKAGED_RULES = Path(str(files("scrubcast").joinpath("resources/rules")))
RULES_ROOT = (
    _PACKAGED_RULES if _PACKAGED_RULES.is_dir() else Path(__file__).resolve().parents[3] / "rules"
)
# Mean Earth radius for great-circle distances between pads and forecast cells.
EARTH_RADIUS_KM = 6371.0088
MAX_OVERRIDE_DISTANCE_KM = 5


def format_param(value: Parameter) -> str:
    """Render numeric parameters with three significant figures and grouped thousands."""
    if isinstance(value, str):
        return value
    rendered = format(Decimal(format(value, ".3g")), ",f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def resolve_plot(
    plot: Plot,
    params: dict[str, Parameter],
    origin: Mapping[str, str] | None = None,
) -> tuple[Threshold, ResolvedPlot]:
    """Resolve the comparison and readout from the same validated parameters."""
    plot.validate_params(params)
    threshold = Threshold(
        value=TypeAdapter(float).validate_python(params[plot.threshold_param]),
        unit=plot.unit,
        comparator=TypeAdapter(Comparator).validate_python(params[plot.comparator_param]),
    )
    resolved = ResolvedPlot(
        variable=plot.variable,
        unit=plot.unit,
        readout_phrase=plot.readout_phrase.format_map(
            {key: format_param(value) for key, value in params.items()},
        ),
        origin="scrub" if (origin or {}).get(plot.threshold_param) == "scrub" else "source",
    )
    return threshold, resolved


class Located(Protocol):
    """Anything with geographic degrees: pads, configured points and returned grid cells."""

    @property
    def latitude(self) -> float:
        """Degrees north."""
        ...

    @property
    def longitude(self) -> float:
        """Degrees east."""
        ...


def distance_km(first: Located, second: Located) -> float:
    """Great-circle distance between two positions in kilometres."""
    latitude, other_latitude = radians(first.latitude), radians(second.latitude)
    half_chord = (
        sin((other_latitude - latitude) / 2) ** 2
        + cos(latitude)
        * cos(other_latitude)
        * sin(radians(second.longitude - first.longitude) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(min(1, half_chord)))


@dataclass(frozen=True)
class RuleCatalog:
    """Validated startup data with site and vehicle selection kept independent."""

    rule_sets: dict[str, RuleSet]
    vehicles: dict[str, VehicleConfig]
    sites: dict[str, SiteConfig]
    concerns: dict[str, str]

    def site_for(self, pad: Pad) -> SiteConfig:
        """Select by LL2 location and reject coordinate corrections outside the pad area."""
        site = next(
            (site for site in self.sites.values() if pad.location.id in site.location_ids),
            self.sites["generic"],
        )
        override = site.coordinate_overrides.get(pad.id)
        if override is not None and distance_km(pad, override) >= MAX_OVERRIDE_DISTANCE_KM:
            msg = f"Coordinate override for pad {pad.id} must be less than 5 km from LL2"
            raise ValueError(msg)
        if site.forecast_point is None:
            site = site.model_copy(
                update={
                    "forecast_point": ForecastPoint(
                        point_id=f"location-{pad.location.id}",
                        latitude=pad.latitude if override is None else override.latitude,
                        longitude=pad.longitude if override is None else override.longitude,
                    ),
                },
            )
        return site

    def rules_for(self, pad: Pad, rocket_name: str) -> RuleSelection:
        """Apply site confidence and add only a vehicle's published wind criterion."""
        site = self.site_for(pad)
        rule_sets = [self.rule_sets[name] for name in site.rule_sets]
        rules = [
            rule.model_copy(
                update={
                    "reference_only": site.reference_only,
                    "confidence": site.confidence or rule.confidence,
                },
            )
            for rule_set in rule_sets
            for rule in rule_set.rules
        ]
        vehicle = next(
            (
                vehicle
                for vehicle in self.vehicles.values()
                if rocket_name.casefold() in {name.casefold() for name in vehicle.rocket_names}
            ),
            None,
        )
        omitted = [rule for rule_set in rule_sets for rule in rule_set.not_evaluable]
        if vehicle is None:
            omitted.append(
                NotEvaluable(
                    rule_id="liftoff_wind",
                    title="Liftoff wind",
                    llccr=[],
                    reason="no published limit",
                ),
            )
        return RuleSelection(site=site, rules=rules, vehicle=vehicle, not_evaluable=omitted)

    def normalise_concern(self, name: str) -> ConcernMatch:
        """Match trimmed case-insensitive names without losing the original text."""
        return ConcernMatch(name=name, rule_id=self.concerns.get(name.strip().casefold()))


def load_rules(root: Path = RULES_ROOT) -> RuleCatalog:
    """Load every JSON file and reject duplicate identities and dangling references."""
    rule_sets: dict[str, RuleSet] = {}
    vehicles: dict[str, VehicleConfig] = {}
    sites: dict[str, SiteConfig] = {}
    for path in sorted((root / "llcc").glob("*.json")):
        rule_set = RuleSet.model_validate_json(path.read_text())
        if rule_set.rule_set_id in rule_sets:
            msg = f"Duplicate rule set: {rule_set.rule_set_id}"
            raise ValueError(msg)
        rule_sets[rule_set.rule_set_id] = rule_set
    rocket_names: set[str] = set()
    for path in sorted((root / "vehicles").glob("*.json")):
        vehicle = VehicleConfig.model_validate_json(path.read_text())
        names = {name.casefold() for name in vehicle.rocket_names}
        if vehicle.vehicle_id in vehicles or names & rocket_names:
            msg = f"Duplicate vehicle: {vehicle.vehicle_id}"
            raise ValueError(msg)
        vehicles[vehicle.vehicle_id] = vehicle
        rocket_names.update(names)
    locations: set[int] = set()
    for path in sorted((root / "sites").glob("*.json")):
        site = SiteConfig.model_validate_json(path.read_text())
        if site.site_id in sites or locations.intersection(site.location_ids):
            msg = f"Duplicate site or location: {site.site_id}"
            raise ValueError(msg)
        if set(site.rule_sets) - rule_sets.keys():
            msg = f"Unknown rule set in site {site.site_id}"
            raise ValueError(msg)
        sites[site.site_id] = site
        locations.update(site.location_ids)
    if "generic" not in sites:
        msg = "Missing generic fallback site"
        raise ValueError(msg)
    concerns = _load_concerns(root / "concerns.json", rule_sets, vehicles)
    return RuleCatalog(rule_sets=rule_sets, vehicles=vehicles, sites=sites, concerns=concerns)


def site_for(pad: Pad) -> SiteConfig:
    """Resolve a site using the validated repository rule data."""
    return load_rules().site_for(pad)


def _load_concerns(
    path: Path,
    rule_sets: dict[str, RuleSet],
    vehicles: dict[str, VehicleConfig],
) -> dict[str, str]:
    aliases = TypeAdapter(dict[str, str]).validate_json(path.read_text())
    concerns: dict[str, str] = {}
    known_ids = {
        rule.rule_id
        for rule_set in rule_sets.values()
        for rule in [*rule_set.rules, *rule_set.not_evaluable]
    } | {vehicle.rule_id for vehicle in vehicles.values()}
    for alias, rule_id in aliases.items():
        key = alias.strip().casefold()
        if key in concerns or rule_id not in known_ids:
            msg = f"Duplicate or unknown concern mapping: {alias} -> {rule_id}"
            raise ValueError(msg)
        concerns[key] = rule_id
    return concerns
