# Data

Everything Scrubcast publishes is a static file under `data/` on the site, rebuilt every
hour. The files are CC BY 4.0, like the Open-Meteo forecasts they are computed from.

## Published files

| File | What it holds |
| --- | --- |
| `latest.json` | Launches in the ten-day horizon with the official fields from Launch Library 2, the coverage tier, the worst rule and `members_total`, the ensemble member count behind every share |
| `launches/<id>.json` | One launch: per rule and per model, the members that break the rule at each hour of the window, their plotted values, the threshold, the rules that cannot be evaluated and why, and the official forecast |
| `past.json` | Launches retained for 90 days after T-0, each with its audit footers: the official concerns, the 24 h rule risks and the outcome |
| `calendar.ics` | One event per launch, spanning its window, with the worst rule in the title |
| `hindcast.json` | The three evaluations behind the Audit view, each with its n |
| `badges/{wind,precipitation,attempts}.json` | shields.io endpoint badges for the forecast audit summaries |

Every JSON file carries `schema_version`. Check it before reading anything else and stop on
a version you do not know, as `scrubcast next` does. The JSON Schema for all of them is
generated from the models in `src/scrubcast/build/`:

```sh
uv run python -m scrubcast.build.schema > public.schema.json
```

[Recipes](recipes.md) shows a bot on `latest.json`, the calendar feed and re-scoring the
archive with your own thresholds. The ledger behind the audit (JSONL) is on the `ledger`
branch, and the raw ensemble slices (NPZ) are release assets in the archive repository.

## Reusing the data

Open-Meteo's free API is for non-commercial use only, and that limit carries to anything
built on these files. Commercial use needs an Open-Meteo plan or a GEFS adapter following the design in
[ADR 0003](adr/0003-open-meteo-with-swap-path.md). Credit "Weather data by Open-Meteo.com"
and "Launch data by The Space Devs" wherever the numbers appear.

## Source data contracts

### Observation attribution

Weather observations provided by the Iowa Environmental Mesonet, Iowa State
University. The [IEM usage terms](https://mesonet.agron.iastate.edu/disclaimer.php),
checked 2026-11-05, describe site materials as public domain and freely usable
for lawful purposes. Attribution is appreciated. IEM provides no warranty of
accuracy; observations require independent judgment. See the
[source verification](verification-2026-11.md) for source checks and limits.

### Launch Library models

`src/scrubcast/models/launch.py` validates the fields consumed from LL2 normal and
detailed responses. The parser uses the same model for the committed 2.3.0 and
2.4.0 fixtures. Unused response fields are ignored, including `response_mode`,
`holdreason` and `failreason`.

`Launch.status` is a `LaunchStatus` enum. Unknown abbreviations raise a validation
error. `net_precision`, `launch_service_provider_name` and `rocket_name` expose
the consumed nested source values directly. The model also accepts these field
names when loading its own serialized output. `net_precision` may be null, as
seen in live upcoming responses; null precision does not pass the schedule's
precision allowlist. IDs stay strings, matching the source JSON and allowing
direct use in schedule files and launch paths.

`Pad.location` retains the site's ID, name and IANA time zone name. Pad latitude
and longitude are geographic degrees, bounded to their valid ranges. Launch and
update timestamps must include a UTC offset; timezone information is preserved.

`probability` is the official integer percent of GO, between 0 and 100 inclusive.
It and `weather_concerns` are required keys whose values may be null. The upcoming
fixtures have null official fields for every launch; the detailed fixtures
provide the non-null regression case, Starlink Group 10-37 with probability 95
and `Cumulus Cloud Rule`. Both versions retain `rocket.configuration.name`.

`mission` may be null, and a mission's `orbit` may be null. Unknown orbit names
and precision codes remain available for the schedule filter. The parser does
not exclude suborbital launches or coarse launch times.

`LaunchDetailed.updates` is required and may be empty. Each entry retains
`created_on` and `comment` in source order. Both detailed fixtures parse without
`holdreason`; weather and technical delay evidence remains in the comments.

`parse_concerns` splits on commas, trims surrounding whitespace and discards
empty entries. It preserves spelling, case, duplicates and order. Rule mapping
and reporting of unmapped names belong to the concern mapper.

`tests/unit/test_launch.py` runs these cases against both LL2 versions' fixtures.

### Launch Library requests

`fetch_upcoming` uses LL2 2.3.0 normal mode and reads one page of 100 launches
ordered by NET; that page reached 2026-12-31 when recorded, far past the ten-day
horizon, and the remaining pages would spend four more of the 15 hourly requests.
`fetch_previous` accepts an aware `since` timestamp, optional `location_ids` encoded
as `location__ids`, and normal or detailed mode (detailed by default). It requests
100 rows per page and follows `next` until null. `fetch_audit_launches` sends two detailed requests, previous
launches since an aware timestamp and upcoming launches, and reads the first page
of each. No schedule filters run here. Repeated pagination URLs and
pagination outside the pinned launch endpoint fail with `SourceError`.

Launch models remain strict: any per-launch validation error skips only that
launch. A warning includes the launch ID when available and the validation
message. Other launches on the page and later pages still load. Tests cover
unknown status abbreviations, invalid timestamps, out-of-range probabilities,
missing fields and valid null precision in mixed upcoming and detailed responses.
Malformed JSON or an invalid page envelope still fails the fetch with
`SourceError`, including the response URL. One invalid launch must not keep the
whole schedule stale; systematic API changes remain the responsibility of the
weekly LL2 version watch, `scripts/ll2-version-watch.py`.

The request counter is a request hook installed once on the injected HTTP client.
Reuse that client for all LL2 work in a run. Upcoming, previous, pagination,
failed requests and any other LL2 requests through that client share the budget.
The counter uses monotonic time and refuses request 16 until an earlier request
leaves the rolling hour. Callers can install `RequestCounter(clock=...)` as a
request hook for deterministic pacing tests or share it across clients. Counters
are in memory, with no coordination between processes or independent clients.

HTTP 429 raises `SourceError` with status 429 and the verbatim `Retry-After`
header (seconds or HTTP date, or null if absent). It prevents further LL2 requests
through that counter for the remainder of the run, with no sleeping or retrying.
The CLI must catch this error, reuse `data/schedule.json` and set
`schedule_stale: true`, which `scrubcast schedule` does in `write_schedule`. HTTP,
transport and response validation failures also raise `SourceError`; a failure on
a later page never returns a partial schedule.
