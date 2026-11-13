# Forecast audit

Generated at 2026-11-05T08:59:17.521306+00:00; launches n=12.

Intervals use 2,000 paired percentile resamples with seed 20261104. Any metric with fewer than 10 samples prints insufficient data.

## Wind input against observation

ECMWF and GFS 10 m wind members at the hour of the final NET checked against METAR. The reference is a climatological ensemble from ten years of METAR at the same station, calendar day within 15 days and hour within 1 hour.

| Metric | n | Value | Baseline | 95% interval |
| --- | ---: | ---: | ---: | --- |
| ECMWF wind CRPS (m/s) | 12 | 1 | 7.61905 | not estimated |
| ECMWF wind CRPS skill | 12 | 0.86875 | 0 | not estimated |
| GFS wind CRPS (m/s) | 12 | 1 | 7.61905 | not estimated |
| GFS wind CRPS skill | 12 | 0.86875 | 0 | not estimated |

Rank histogram insufficient data (n=12)

Reliability table insufficient data (n=12)

## Rule against observation

The flight-through-precipitation rule at the 24-hour bucket checked against the observed precipitation event in the hour of the final NET. The reference is the station's climatological event frequency from the same ten-year METAR sample.

| Metric | n | Value | Baseline | 95% interval |
| --- | ---: | ---: | ---: | --- |
| flight_through_precip Brier score | 12 | 0.25 | 0.25 | not estimated |
| flight_through_precip Brier skill | 12 | 0 | 0 | not estimated |

Rank histogram insufficient data (n=12)

Reliability table insufficient data (n=12)

## Agreement with the official forecast

Agreement with the official forecast: the Brier-form score of rule risk at 24 hours against the rule being named in the official concerns. Official concerns are another forecast, not an observed outcome, so this is an agreement measure.

| Metric | n | Value | Baseline | 95% interval |
| --- | ---: | ---: | ---: | --- |
| cumulus Brier score | 12 | 0.25 | 0 | not estimated |
| All direct and medium rules Brier score | 12 | 0.25 | 0 | not estimated |

Rank histogram insufficient data (n=12)

Reliability table insufficient data (n=12)

## Attempt outcomes

Attempt outcomes: launched in the window against did not launch in it, all causes: non-weather scrubs included. Unknown outcomes are excluded and counted. This is the weakest of the evaluations.

Attempts n=12; launched 6, did not launch 6, unknown 0.

AUC 1 (n=12), 95% interval [1, 1].

| Attempt | Scrubcast union risk at 24 h | Official GO% | Outcome | LL2 note |
| --- | ---: | ---: | --- | --- |
| audit-00 | 0.1 | 90 | launched |  |
| audit-01 | 0.1 | 90 | launched |  |
| audit-02 | 0.1 | 90 | launched |  |
| audit-03 | 0.1 | 90 | launched |  |
| audit-04 | 0.1 | 90 | launched |  |
| audit-05 | 0.1 | 90 | launched |  |
| audit-06 | 0.9 | 90 | launched_later | Launch delayed. |
| audit-07 | 0.9 | 90 | launched_later | Launch delayed. |
| audit-08 | 0.9 | 90 | launched_later | Launch delayed. |
| audit-09 | 0.9 | 90 | launched_later | Launch delayed. |
| audit-10 | 0.9 | 90 | launched_later | Launch delayed. |
| audit-11 | 0.9 | 90 | launched_later | Launch delayed. |

## Lowest-risk hour

The lowest modelled-risk hour checked against observed precipitation only, not cloud or wind.

Paired launches n=12; union risk at the marked hour 0.05, at T-0 0.5; observed precipitation event rate at the marked hour 0, at T-0 1.

Difference -1 with 95% interval [-1, -1]; lowest_hour_verified true.
