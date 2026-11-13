# Operations

What runs on its own, what can stop it, and what to do when it does.

| Workflow | When (UTC) | What it writes |
| --- | --- | --- |
| `collect.yml` | 03:20, 09:20, 15:20, 21:20 | Schedule and forecasts to the Actions cache, ledger rows to the `ledger` branch, raw slices to the archive repository |
| `refresh.yml` | 17 minutes past every hour | The Pages site, built from the cache with `scrubcast build --no-weather` |
| `audit.yml` | 05:40 | Attempt outcomes, the validation report and the badges, on the `ledger` branch |

Scheduled runs can start late when GitHub is busy. Nothing depends on the exact minute.

## The archive token

`collect.yml` uploads raw ensemble slices to the repository named by the `ARCHIVE_REPO`
variable, using the `ARCHIVE_TOKEN` secret. The token is a fine-grained personal access
token with Contents read and write on that one repository.

Expiry date of the current token: not yet created.

To renew it before that date:

1. Create a new fine-grained token at GitHub, Settings, Developer settings, Personal
   access tokens, scoped to the archive repository only, with Contents read and write.
2. Store it: `gh secret set ARCHIVE_TOKEN --repo <owner>/<repo>` and paste the token.
3. Run `gh workflow run collect.yml` and confirm the "Check archive access" step passes.
4. Write the new expiry date above.

An expired token stops collection at "Check archive access" with
`ARCHIVE_TOKEN cannot read <repo>`. Until it is renewed, no slices or ledger rows are
written for those runs. Forecasts that were not collected cannot be fetched later, so
renew within a day.

Without `ARCHIVE_REPO` the slice steps are skipped and the run summary says so;
collection and the ledger still run. Wind cannot be scored without those slices.

Before scoring, `audit.yml` restores the ledger runs' `.npz` files and JSON sidecars
from their monthly archive releases. `scrubcast audit` fetches current METAR from
the public IEM service for each pad's configured station. Verifying observations
are cached in `data/iem/observations.json`, separately from the fixed 2016 to 2025
climatology. The workflow restores and saves both IEM data and backfill snapshots;
`scrubcast hindcast` scores these saved inputs without a network request.

## The keepalive

GitHub disables scheduled workflows in a public repository after 60 days without
repository activity. Commits from workflows to the `ledger` branch are not counted on.
The last step of `audit.yml` re-enables `collect.yml`, `refresh.yml` and `audit.yml`
through the API every day, using the job's own `actions: write` permission.

If the schedules stop anyway, check `gh workflow list --all`. A workflow shown as
`disabled_inactivity` is turned back on with `gh workflow enable <file>`.

## Reading the budget report

Open-Meteo charges each request in units that grow with the number of variables, members
and days. The collector plans against a daily budget of 7,500 units and records every
send. After `git worktree add ledger ledger` (or `git -C ledger pull`):

```sh
uv run python scripts/budget-report.py --month 2026-11
```

Against the fixture month, with Actions durations from a file instead of `gh`:

```sh
uv run python scripts/budget-report.py --month 2026-11 --ledger tests/fixtures/budget --actions-file tests/fixtures/budget/actions.json
```

```text
Budget 2026-11 (units; daily budget 7,500)
2026-11-01: 344.40 / 7,500
2026-11-02: 7,600.00 / 7,500 OVER BUDGET
Deferred by budget: 1
Deferred upstream 429: 1
Actions minutes (elapsed): 5.50
```

- A day marked `OVER BUDGET` spent more than the planner allows. Look for a manual
  `collect` run with `--force`, or a change that added variables or points without
  updating the cost model in [weather collection](weather-collection.md).
- `Deferred by budget` counts forecasts the planner skipped to stay under the budget.
  A few near the end of a busy day are expected; many every day mean the schedule has
  more launches than the budget covers.
- `Deferred upstream 429` counts refusals from Open-Meteo. Its limits are per IP
  address, and GitHub runners share addresses, so an occasional 429 is not caused by
  this project. Several a day for a week is worth an issue.
- `Actions minutes (elapsed)` sums wall time from run timestamps. It is not a billing
  figure.

## When collect.yml fails

1. Open the failed run: `gh run list -w collect.yml --limit 5`, then
   `gh run view <id> --log-failed`.
2. Match the failing step:
   - "Check archive access": the token expired or lost access. Renew it as above.
   - "Collect the schedule, weather and slices": read the last lines of the step log.
     When Launch Library 2 fails and a saved schedule exists, the run keeps that
     schedule and marks it stale instead of failing, so a failure here is usually a
     code or contract change. Reproduce it locally with `uv run scrubcast collect` and
     open an issue with the log lines.
   - "Upload slices to the archive release": a GitHub API failure. The next run uploads
     its own slices; the missed ones are not retried.
   - "Commit the ledger": three rebase-and-push attempts lost the race with another
     workflow writing to `ledger`. Re-run the workflow.
3. Re-run with `gh run rerun <id>` once the cause is fixed. A rerun inside the same
   six-hour slot fetches nothing new unless the forecasts are older than five hours.
