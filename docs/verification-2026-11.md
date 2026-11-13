# Source verification, November 2026

Checked on 2026-11-05 UTC. Weather probes used the Cape point
(28.5618, -80.577), explicit models, UTC and `wind_speed_unit=ms`.
Exact URLs, timestamps, HTTP status and derived non-null summaries are in
[requests.json](verification-2026-11-evidence/requests.json) and
[historical-start.json](verification-2026-11-evidence/historical-start.json).
The JSON files contain summaries, not raw weather snapshots.

- (a) 2026-11-05 [Ensemble API](https://ensemble-api.open-meteo.com/v1/ensemble) VERIFIED: the three recorded cost shapes returned 39.9, 385.4 and 34.24286 units; the production shape returned 344.4. All agree with the planned `request_cost()` formula within 0.01 units. This check compares the formula independently, not executable production code. See the cost table and saved headers below.
- (b) 2026-11-05 [Ensemble history probe](verification-2026-11-evidence/requests.json) VERIFIED with updated depth: `past_days=93&forecast_days=1`, one variable (`wind_speed_10m`), four explicit models. First non-null control hour is 2026-11-01T00:00 for `ecmwf_ifs025`, and 2026-11-02T00:00 for `gfs_seamless`, `ecmwf_aifs025` and `gfs025`. The requested range begins 2026-08-04T00:00; preceding hours are null. These are point/variable observations, not a guaranteed retention policy. The forward-only ensemble audit remains necessary.
- (c) 2026-11-05 [Historical Forecast API](https://historical-forecast-api.open-meteo.com/v1/forecast) CHANGED: probing all 42 production variables with `models=ecmwf_ifs025` over 2024-02-01 through 2024-02-04 finds 10 m wind first available at 2024-02-03T00:00, but not all variables are available. Precipitation starts at 2024-02-02T22:00. Nine variables remain entirely null throughout this range; see below. The claim of all variables from February 3 is not supported.
- (d) 2026-11-05 [NASA Atlas V fact sheet](https://www3.nasa.gov/centers/kennedy/pdf/633165main_atlas-5-weather.pdf) and [NASA Artemis II weather criteria](https://www.nasa.gov/artemis-ii-weather-criteria/) VERIFIED with qualification: Atlas V prohibits pad wind above 33 knots (16.9767 m/s, rounded 16.98), but the sheet does not define reference height or sustained versus peak. SLS peak liftoff wind limits run from 29 knots at 132.5 feet to 39 knots at 457.5 feet. The lower bound converts to 14.9189 m/s (14.92) at 40.386 m (40.4), comparator `>`. The SLS figure is mission-specific and covers one height of a vertical constraint, not the entire constraint. Atlas V needs a decision on missing measurement parameters before a complete rule can ship; no measurement convention is inferred here.
- (e) 2026-11-05 [IEM disclaimer](https://mesonet.agron.iastate.edu/disclaimer.php) VERIFIED: site materials are public domain and usable for lawful purposes. Attribution is appreciated; no mandatory citation template appears. Data carry no accuracy warranty. Suggested project attribution: Weather observations provided by the Iowa Environmental Mesonet, Iowa State University. Added to `docs/data.md`.
- (f) 2026-11-05 [GitHub release quotas](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases#storage-and-bandwidth-quotas) VERIFIED: at most 1,000 assets per release, each under 2 GiB; total release size and bandwidth are unlimited. The projected 124 monthly slice assets fit the count limit. This is a documented limit check; no release was created or uploaded.
- (g) 2026-11-05 [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) CHANGED: public documentation now expresses GitHub Free's monthly compute allowance as USD 12, shared with other eligible compute. At the documented USD 0.006 per minute for standard Linux x64, that is 2,000 equivalent minutes if nothing else consumes the allowance. It is not a dedicated 2,000-minute pool. This account's subscription tier, remaining allowance and zero-spend budget are unverified. No authenticated billing endpoint was called. Account verification remains an unchecked [compute budget prerequisite](development.md#pending-setup) before private collection runs.
- (h) 2026-11-05 [LL2 access terms](https://thespacedevs.com/llapi) and [live documentation](https://ll.thespacedevs.com/docs/) VERIFIED: anonymous access remains 15 requests per hour. The live Swagger configuration still loads `/2.3.0/json`; the official API link still targets `/2.3.0/launches/`. See [the saved configuration excerpt](verification-2026-11-evidence/ll2-docs.txt). Availability of 2.4.0 fixtures does not itself make it the documented version. No switch trigger was found, so the planned LL2 2.4 migration was not run. The initial urllib documentation request returned 403; a browser-user-agent curl request succeeded.

## Cost evidence and reproduction

The fixture request manifest records the 42-variable production list in
`open_meteo_cape.json`'s URL. It does not contain the three cost-probe URLs.
The three-variable request uses
the first three production variables: 10 m wind, 10 m gusts and 100 m wind.
The 47-variable request adds `temperature_2m`, `relative_humidity_2m`,
`dew_point_2m`, `surface_pressure` and `cloud_cover` to that production list.
All four requests returned HTTP 200.

Evaluate the request cost as
`n_vars / 10 * members * max(1, days / 14)`; history days include both
`past_days` and `forecast_days`. ECMWF IFS and AIFS each have 51 members,
and GFS has 31, including control series.

| Shape | Members | Days | Calculated units | Header units | Absolute difference | Headers |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 3 variables, IFS + GFS + AIFS | 133 | 1 | 39.9 | 39.9 | 0 | [cost-three-models.txt](verification-2026-11-evidence/cost-three-models.txt) |
| 47 variables, IFS + GFS | 82 | 10 | 385.4 | 385.4 | 0 | [cost-47-variables.txt](verification-2026-11-evidence/cost-47-variables.txt) |
| 1 variable, IFS, 93 past + 1 forecast day | 51 | 94 | 34.242857142857 | 34.24286 | 0.000002857143 | [cost-history.txt](verification-2026-11-evidence/cost-history.txt) |
| 42 variables, IFS + GFS, production | 82 | 10 | 344.4 | 344.4 | 0 | [cost-production.txt](verification-2026-11-evidence/cost-production.txt) |

The separate four-model history probe cost 110.11429 units. The production
request was sent after a 65-second pause following the 47-variable response.
These five ensemble probes total 914.05715 units as reported by the headers.
The historical probe's headers are saved separately. No weather probe was retried.

## Historical coverage discrepancy

The nine all-null series in the four-day ECMWF deterministic probe are
`wind_gusts_10m`, `wind_speed_100m`, `cape`, and temperature, cloud cover and
geopotential height at both 600 and 400 hPa. Other requested series first
become non-null at February 3 00:00, except precipitation as noted above.
This probe does not establish the eventual start date of the nine missing
series. Backfill must preserve missingness and report per-rule coverage;
February 3 cannot be described as the start of complete production-variable
coverage. It does not establish ensemble history either.

## Open points

Atlas V's threshold has a primary source (NASA fact sheet
FS-2013-01-010-KSC, page 1), but its required height and measure remain
unsettled. Options are to obtain a primary source for both parameters or defer
the vehicle file. This verification changed no rule file. For SLS, retain the
Artemis II scope and vertical-constraint qualification in any rule description.

For historical backfill, recheck variable-specific start dates before
selecting evaluation periods. For collection and budget reporting, account
verification must include shared compute usage and a zero-spend budget, not
only an assumed minute quota. IEM attribution is present in README and `docs/data.md`.

## Checks

The list at the top holds eight findings, which this command confirms:

```sh
test "$(grep -cE '^- \((a|b|c|d|e|f|g|h)\) ' docs/verification-2026-11.md)" = 8
```

The four cost comparisons also passed an independent arithmetic check at an
absolute tolerance of 0.01 units. `git diff --check` passed.
