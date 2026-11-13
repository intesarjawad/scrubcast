# Weather collection and request accounting

`scrubcast weather` reads `data/schedule.json`. Run `scrubcast schedule`
first, or use `scrubcast collect` to refresh both sources and archive available
Tier A forecasts. Both weather collection commands accept `--force` to refresh
files fetched less than five hours ago. `--fixtures` uses recorded responses and
an advancing clock without network requests or real pacing delays.

Forecasts live at `data/weather/<point_id>.json`. Each file contains `fetched_at`
from the upstream HTTP Date header, generation time, measured cost and remaining
units, and per-model member-by-hour arrays with returned grid coordinates.
Missing values are JSON null and become float32 NaN when loaded. The cache models
and conversion functions live in `scrubcast.forecast_cache`; archive consumers receive
the existing `ForecastResponse` contract.

`data/cells.json` maps requested point IDs to returned grid points. Tier C points
with a previously observed matching latitude and longitude share one request on
later runs. A cold cache must request each unknown point to learn its cell. Named
Tier A and B points retain their configured identities. A Tier C point takes the
coordinates of its location's next pad, and one location can span distant pads (sea
launch platforms), so a saved cell or forecast more than 100 km from the point's
current coordinates is ignored and the point is requested again.

The planner selects points within ten days, in tier order, under the daily and
per-run budgets. The collector rechecks measured spend before subsequent sends
and paces against actual send times and costs, including the previous month's
last minute. A mismatch greater than one percent logs a warning and sets
`cost_mismatch` on the ledger row.

Rows append to `ledger/budget-YYYY-MM.jsonl`, partitioned by the UTC send time.
They contain `sent_at`, `point_id`, `status`, `cost_units`, `remaining_units`, and
`cost_mismatch`. Status is `fetched`, `deferred_budget`, or
`deferred_upstream_429`. A deferral has zero recorded cost and null remaining
units because the source contract exposes measured headers only for successful
forecasts. Upstream remaining units describe the shared client IP, not this
project's spend. No upstream 429 is retried during the run. Both deferral types
preserve existing point files; a fresh-cache run adds no rows. Any other failed
request, such as a refused connection or a server error, logs one warning naming
the point and the age of the forecast it keeps, writes no row, and the run goes on
with the next point. Collection archives
only launches with an available forecast, so a cold-cache upstream deferral does
not fail the run.

After the ledger checkout has been updated, run:

```sh
uv run python scripts/budget-report.py --month 2026-11
```

The report prints daily units against the daily budget, counts each type of
deferral, and sums elapsed Actions minutes from `collect.yml` run timestamps.
Elapsed duration is not a billing measurement. The command reads Actions with
`gh run list`; live integration awaits a repository remote and authentication.
For an offline report, pass `--ledger <directory>` and `--actions-file <json>`.
The Actions JSON must contain `startedAt` and `updatedAt` timestamps. The fixture
month and expected output live in `tests/fixtures/budget` and
`tests/golden/budget-report.txt`.
