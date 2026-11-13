# Recipes

Every command below was run from the repository root against the recorded fixtures in
`tests/fixtures/`, and the output shown is what it printed. On a deployed site, read the
same files from your Pages URL instead of `site/public/data/`.

## A bot on latest.json

`latest.json` lists the launches in the ten-day forecast horizon, each with its worst
rule. Build it from the fixtures:

```sh
uv run scrubcast build --fixtures
jq -r '"generated \(.generated_at), schedule stale: \(.schedule_stale)"' site/public/data/latest.json
jq -r '.launches[] | select(.tier == "A") | "\(.net) \(.name): \(.worst_rule.label)"' site/public/data/latest.json
```

```text
generated 2026-11-05T08:59:17.521306Z, schedule stale: false
2026-11-07T00:46:00Z Falcon 9 Block 5 | USSF-432: No rule above 5%
2026-11-10T03:03:00Z Falcon 9 Block 5 | USSF-627: Forecast unavailable
2026-11-13T04:23:00Z Falcon 9 Block 5 | USSF-317: Forecast unavailable
2026-11-13T17:54:00Z Vulcan VC6L | Amazon Leo (LV-01): Forecast unavailable
```

The fixture forecasts cover 72 hours from the recording, so later launches show
"Forecast unavailable". A bot should:

- check `schema_version` before reading anything else, and stop when it changes;
- skip a run when `schedule_stale` is true, because the launch times may be out of date;
- post `worst_rule.label` as it is: it already names the rule and the share of members
  over its limit (`worst_rule.model` says which ensemble), or says why there is none;
- link each launch by joining `page_url` (for example
  `/launch/54d471e8-695c-4fa7-a3cf-dbd8b389e8ae/`) to the site URL.

On a deployed site, replace the file with `curl -s <pages url>/data/latest.json`. The
site rebuilds every hour, so polling more often returns the same file.

## Subscribing to the calendar

`calendar.ics` has one event per launch, spanning its window, with the worst rule in the
title. From the same build:

```sh
grep -c BEGIN:VEVENT site/public/data/calendar.ics
awk '/BEGIN:VEVENT/{n++} n==3' site/public/data/calendar.ics | sed -n 1,10p
```

```text
9
BEGIN:VEVENT
UID:54d471e8-695c-4fa7-a3cf-dbd8b389e8ae@scrubcast
DTSTAMP:20261105T085917Z
LAST-MODIFIED:20261105T085917Z
DTSTART:20261107T004600Z
DTEND:20261107T044600Z
SUMMARY:Falcon 9 Block 5 | USSF-432 (No rule above 5%)
DESCRIPTION:Official forecast unavailable\n/launch/54d471e8-695c-4fa7-a3cf-
 dbd8b389e8ae/
END:VEVENT
```

Subscribe to `<pages url>/data/calendar.ics` rather than importing it once: in Apple
Calendar use File, New Calendar Subscription; in Google Calendar use Other calendars,
From URL. Event identifiers stay the same between builds, so a moved launch updates in
place instead of appearing twice.

## Fork, change a threshold and re-score history

A fork runs the whole pipeline on its own GitHub Actions:

1. Enable Actions in the fork (forks start with workflows disabled), then set Pages to
   deploy from GitHub Actions under Settings, Pages, Source.
2. Create the branch the workflows write to:
   `git switch --orphan ledger && git commit --allow-empty -m "ledger: start" && git push -u origin ledger && git switch main`.
3. Raw ensemble slices are skipped until the fork sets the `ARCHIVE_REPO` variable and the
   `ARCHIVE_TOKEN` secret, which name a repository for the slice releases and a token that
   can write to it. Without them, collection and the ledger still run.
4. The weather comes from Open-Meteo's free tier, whose limits are per IP address and
   which is for non-commercial use only. Commercial use needs an Open-Meteo plan or the
   GEFS adapter following the design described in
   [ADR 0003](adr/0003-open-meteo-with-swap-path.md).

Re-scoring replays archived ensemble members through the current rule files, so a
changed threshold applies to every launch in the archive. The fixture archive holds one
recorded run; copy it to `archive/`, where `--rescore` looks by default, and keep the
output out of your ledger checkout with `--data-dir`:

```sh
mkdir -p archive && cp tests/fixtures/hindcast/release/slices-20261106T01.* archive/
uv run scrubcast hindcast --rescore --data-dir .cache/rescore
jq -c '{launch: .launch.name, liftoff_wind: .rules.liftoff_wind}' .cache/rescore/ledger/rescored.jsonl
```

```text
Rescored n=1; ledger: .cache/rescore/ledger/rescored.jsonl
Hindcast n=1; validation: .cache/rescore/ledger/validation.md
{"launch":"Falcon 9 Block 5 | USSF-432","liftoff_wind":[0.0,0.0]}
```

The pair is the share of ECMWF and GFS members over the limit at T-0. Lower the Falcon 9
liftoff wind limit in `rules/vehicles/falcon9.json` from `"threshold_mps": 13.41` to
`"threshold_mps": 8`, then run the same two commands again:

```text
Rescored n=1; ledger: .cache/rescore/ledger/rescored.jsonl
Hindcast n=1; validation: .cache/rescore/ledger/validation.md
{"launch":"Falcon 9 Block 5 | USSF-432","liftoff_wind":[0.0392156862745098,0.16129032258064516]}
```

That is 2 of 51 ECMWF members and 5 of 31 GFS members. Run
`uv run python scripts/gen-docs.py` so [rules.md](rules.md) shows the new limit;
`make check` fails until it does.

To re-score the published history instead of the fixture, download the slice releases
from the archive repository into `archive/` and run the same command:

```sh
gh release download archive-2026-11 --repo "$ARCHIVE_REPO" --pattern 'slices-*' --dir archive
uv run scrubcast hindcast --rescore --data-dir .cache/rescore
```

Each release holds one month of slices, named `archive-YYYY-MM`.
