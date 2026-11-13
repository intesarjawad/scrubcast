# Recorded fixtures

Raw responses from the real APIs, recorded in one session on 2026-11-05 UTC and
kept unmodified, except that the two upcoming lists and `ll2_previous_florida.json`
are trimmed or paged as described below. Each Open-Meteo, LL2 and IEM call has its
URL, request time and HTTP status in `requests.jsonl` and its response headers in
`headers/<file stem>.txt`. `SHA256SUMS` pins every file listed there.

`RECORDED_AT` is the UTC time of the `ll2_upcoming.json` request, one ISO line.
Fixture runs and goldens use it as `now`; no date is written in code or CI. The
ensemble files cover the 72 hours from that date, so they cover the launch windows
of the near launches in `ll2_upcoming.json`.

## Launch Library

| File | Contents |
| --- | --- |
| `ll2_upcoming.json` | 12 launches picked from the first page of the 2.3.0 normal-mode upcoming list (100 rows, 478 in total). |
| `ll2_2.4.0_upcoming.json` | The same selection from the 2.4.0 list. 11 launches are shared; the twelfth, `Nebula-1 \| Demo Flight`, replaces `Themis Demonstrator \| T1H-1`. |
| `ll2_previous_detailed.json` | 20 detailed launches from the previous list, requested for 2025-10-01 to 2025-11-01: a weather hold (`H3-24 \| HTV-X1`, "Launch delayed due to launch site weather, new date TBD.") and a non-weather scrub (`Falcon 9 Block 5 \| Crew-10`, "Scrubbed for the day due to TEL arm hydraulics issue."). |
| `ll2_2.4.0_previous_detailed.json` | The same 20 launches from 2.4.0, including both of the above. |
| `ll2_previous_florida.json` | First page (100 rows) of Florida launches (locations 12 and 27) since 2025-06-01, normal mode, for the backfill. |

The upcoming selection covers the three site tiers: Cape Canaveral (location 12)
and Vandenberg (11) for tier A, Starbase (143) for tier B, and Xichang, Jiuquan,
Wenchang, Sea Launch and Esrange for tier C. `Falcon 9 Block 5 | NROL-195` and
`Starship | Flight 15` have `net_precision.abbrev` `M`; `Themis Demonstrator | T1H-1`
has `mission.orbit.abbrev` `Sub`. Both were in the live upcoming list.

### Official probability and concerns are null in the upcoming lists

No launch in either upcoming fixture has a `probability` or `weather_concerns`
value. The live list had none either: the five pages of the 2.3.0 upcoming list
under `demo/ll2-*.json` (478 launches, recorded a day later) have no non-null
`probability` and no non-empty `weather_concerns`. The non-null case therefore
comes from `launches/previous`: 80 of the 100 rows in `ll2_previous_florida.json`
and 4 of the 20 in each detailed file carry both fields. Tests for the official
fields use those files.

## Open-Meteo

| File | Contents |
| --- | --- |
| `open_meteo_cape.json`, `open_meteo_vandenberg.json` | Ensemble API, 42 hourly variables, ECMWF IFS (51 members) and GFS (31 members), `forecast_days=3`. |
| `open_meteo_tierc_ecmwf_only.json` | Ensemble API, ECMWF only, for a tier C point (30.400938, 130.97564). |
| `historical_cape_2025-10.json` | Historical Forecast API, Cape, October 2025, both models. |
| `previous_runs_cape_2025-10.json` | Previous Runs API, Cape, October 2025, both models in one file. |

GFS has no high cloud cover, so `cloud_cover_high` is all null for it; this is the
API's response, not a gap in the recording.

## IEM

`iem_xmr_2025-10.csv` holds the October 2025 METARs for station XMR.

## Extra files

`ll2_crew10_2.3.0` and `ll2_crew10_2.4.0` appear only as header files and in
`requests.jsonl`: they record the response headers of a detailed `Crew-10` search in
both API versions.
