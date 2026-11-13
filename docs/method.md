# Method notes

Scrubcast reports what the forecast models do against published launch weather
criteria. A member share is the fraction of ensemble members that break a
criterion. It is model agreement evidence, never a launch probability, and it is
kept apart from the official forecast.

The rules live in `rules/llcc/nasa-std-4010a.json`,
`rules/vehicles/falcon9.json`, `rules/vehicles/falcon-heavy.json` and
`rules/sites/`. Each rule is versioned JSON so a published assessment can be
read back against the rule text that produced it.

## Evaluated rules

Every criterion below is evaluated against model output. Some thresholds are
published; the rows named as stand-ins are not. The source value, the proxy
parameter and the model variable are different things, and the table keeps them
apart.

| Rule id | Source section | Proxy parameter | Value | Basis |
| --- | --- | --- | --- | --- |
| `thick_cloud` | 4.1.8 | `thickness_min_m` | 1400 m | Published layer thickness. |
| `thick_cloud` | 4.1.8 | `cloud_cover_min_pct` | 50 percent | `cloud_cover_min_pct` = 50 is a Scrubcast stand-in for "non-transparent". |
| `cumulus` | 4.1.3 | `cape_min_jkg` | 300 J/kg | `cape_min_jkg` = 300 is a Scrubcast stand-in for convective cloud. |
| `cumulus` | 4.1.3 | `cloud_cover_min_pct` | 30 percent | `cloud_cover_min_pct` = 30 is a Scrubcast stand-in for a cumulus field. |
| `anvil` | 4.1.4-4.1.5 | `cape_min_jkg` | 1000 J/kg | `cape_min_jkg` = 1000 is a Scrubcast stand-in for a thunderstorm. |
| `anvil` | 4.1.4-4.1.5 | `cloud_cover_high_min_pct` | 50 percent | `cloud_cover_high_min_pct` = 50 is a Scrubcast stand-in for an anvil shield. |
| `disturbed_weather` | 4.1.7 | `precip_min_mmh` | 2.54 mm/h | Published moderate precipitation threshold. |
| `disturbed_weather` | 4.1.7 | `cloud_cover_min_pct` | 30 percent | `cloud_cover_min_pct` = 30 is a Scrubcast stand-in for freezing cloud. |
| `flight_through_precip` | 4.2.2 | `precip_min_mmh` | 0.254 mm/h | LLCC precipitation definition. |
| `liftoff_wind` | Vehicle limit | `threshold_mps` | 13.41 m/s | Published for crewed Falcon 9 at 49.4 m above the pad. |

The values marked as Scrubcast stand-ins are the entries whose `origin` map says
`scrub`. No public document fixes them. They are thresholds chosen so that a
model field can stand in for a criterion the model cannot see directly, and
they are the first thing to revisit when a better source appears.

The remaining criteria are not evaluated. Their identifiers still appear in the
published contract so a missing criterion is visible rather than silently
dropped:

| Rule id | Why it is not evaluated |
| --- | --- |
| `lightning` | The ensemble has no lightning field. |
| `surface_electric_fields` | Field-mill readings are not public in real time. |
| `debris_cloud` | Needs radar and cloud history. |
| `smoke_plume` | Not observable from model output. |
| `triboelectrification` | Vehicle-specific exemption status is unknown. |
| `booster_recovery` | Recovery zone and downrange limits are mission-specific and not public. |

## Three evaluations

Scrubcast keeps three evaluations separate. Each one reports its own sample
size and scope, and no number moves between them.

1. The retrospective proxy check compares a model field against a criterion
   proxy at hours when an observation exists. It answers whether the stand-in
   threshold is useful, not whether a launch was safe.
2. The retrospective deterministic surface forecast check compares a
   deterministic forecast with the surface observation for the same hour.
   It covers wind and precipitation. This retrospective check is separate
   from the forward ensemble audit.
3. The forward audit of ledgered ensemble forecasts follows forecasts recorded
   before a launch and scores them after the attempt. It reports agreement with
   the official forecast as an agreement measure, not as observed truth, and it
   keeps attempt outcomes and missing evidence beside the scores. Its paired
   comparison of observed precipitation at the lowest modelled-risk hour and
   at T-0 is the evidence behind the lowest-hour claim, subject to the sample
   size and interval gates. It does not verify cloud or wind at that hour.

A clear model row cannot establish safe launch conditions, and a rule that could
not be evaluated stays visible in the assessment.

## Sources

- [NASA-STD-4010A](https://standards.nasa.gov/sites/default/files/standards/NASA/A/0/NASA-STD-4010A-Approved.pdf),
  the launch commit criteria standard behind the rule text.
- [NASA Kennedy fact sheets](https://www.nasa.gov/kennedy/about-kennedy/fact-sheets/),
  including the Falcon 9 liftoff wind fact sheet FS-2020-05-568-KSC.
- [Open-Meteo ensemble API](https://open-meteo.com/), the ECMWF and GFS member
  source.
- [Launch Library 2](https://thespacedevs.com/llapi), the launch schedule and
  official forecast source.
- [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu/), the surface
  observation source. Observations carry no accuracy warranty.
- [14 CFR 450.163](https://www.ecfr.gov/current/title-14/section-450.163),
  flight commit criteria for commercial launch operators.
