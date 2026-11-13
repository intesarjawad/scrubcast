# Testing

## Layers

- `tests/unit` covers the pure core. Expected values are written by hand or come from the
  independent `scores` reference through `make crosscheck`.
- `tests/integration` covers the command line and the published files.
- `tests/golden` holds expected outputs; numeric ones carry explicit tolerances.

`make check-py` runs format, lint, types and pytest. `make check` adds the site checks.

## Mutation testing

`mutmut` mutates the modules listed under `only_mutate` in `pyproject.toml`: the rules, the
score functions, the budget planner and ledger, and the best-time search. Only `tests/unit`
runs against the mutants. The mutants directory is a copy of `src` and `tests`, so
`also_copy` brings in the directories the unit tests read: `rules`, `data`, `schemas`,
`scripts` and `docs`.

```sh
uv run mutmut run
uv run mutmut export-cicd-stats
uv run python scripts/mutation-score.py
```

`scripts/mutation-score.py` reads `mutants/mutmut-cicd-stats.json`, prints
`killed / (total - skipped)` and exits 1 below 0.80. It also exits 1 when nothing was
tested, so an empty run cannot pass. The `mutation` workflow runs the same three commands
every Sunday. Timeouts and untested mutants do not count as killed.

Mutation results are platform dependent. The survivors below were taken on macOS, whose
file system ignores case in paths. On Linux, CI may kill the case-changed directory
mutants of `load_rules`.

## Surviving mutants

Each group is accepted for the reason given. A group marked "weak test" is a real gap in
the tests, not an equivalent mutant; closing it is welcome but does not change what the
code does for valid input.

| Function | Survivors | Reason |
| --- | --- | --- |
| `audit.scores` `_finite_1d`, `_paired`, `_binary`, `_probabilities`, `auc`, `spearman`, `brier_skill_score`, `crps_ensemble`, `rank_histogram`, `bootstrap_interval` | Error message text changed, emptied or replaced by `None` | Weak test: `test_unusable_input_is_rejected` matches the message with `\w` only, so it checks that a `ValueError` carries some text, not which text. |
| Same functions | The field name passed to `_paired`, `_binary` or `_finite_1d` changed (`"x"`, `"events"`, `"members"`) | The name only appears in those messages. Same weak test. |
| Same functions | `dtype=np.float64` or `dtype=np.int64` removed or set to `None` | Equivalent for the tests' inputs: NumPy already produces float64 from float input and int64 from integer ranges. |
| `rank_histogram` | `or` changed to `and` between the two empty-shape checks, `shape[0]`/`shape[1]` swapped, `== 0` changed to `== 1` | Weak test: only the one-dimensional input is rejected in tests; an array with zero cases or zero members is not tried. |
| `bootstrap_interval` | `resamples` default 2000 to 2001, `resamples < 1` to `<= 1` or `< 2`, `confidence` lower bound `<` to `<=`, `rng.integers` low bound dropped or set to 1, tail doubled or divided by 3 | Weak test: the tests check reproducibility, that the interval brackets 10.5, and the constant and paired cases. They do not pin the interval's numeric end points, the default resample count, or the exact validation boundaries. |
| `brier_skill_score` | `0.0 <=` to `0.0 <`, `<= 1.0` to `< 1.0` | Weak test: reference probabilities of exactly 0 and 1 are not tried. |
| `assess.best_time.lowest_union_hour` | Error message text, `members == 0` to `== 1`, `strict=True` removed or set to `False` or `None`, `window_start <= hour` to `<` | Weak test: misaligned ECMWF assessments, a zero member count and a window starting exactly on a candidate hour are not exercised. |
| `rules.loader._distance_km` | Arithmetic changes inside the haversine formula (signs, factors, exponent, `min(1, ...)` to `min(2, ...)`) | Weak test: the override-distance tests use pads far inside or far outside `MAX_OVERRIDE_DISTANCE_KM`, so a distance that is wrong by a moderate factor still lands on the same side. |
| `rules.loader.RuleCatalog.site_for` | `>` to `>=` on the override distance limit | Equivalent in practice: a distance exactly equal to the limit cannot be produced from decimal coordinates. |
| `rules.loader.load_rules`, `_load_concerns` | Upper-cased directory or file names (`LLCC`, `VEHICLES`, `SITES`, `CONCERNS.JSON`) | Equivalent on case-insensitive file systems such as the macOS default; expected to be killed on Linux. |
| `rules.loader.load_rules`, `_load_concerns` | `or` changed to `and` in the duplicate vehicle, site and concern checks, and message text changed or upper-cased | Weak test: no test supplies a catalog where only one of the two duplicate conditions holds, and messages are not asserted. |
| `rules.loader.format_param` | `.3g` to `.3G`, `,f` to `,F`, strip conditions changed | Equivalent for finite numbers in the shipped rules: the upper-case format codes only differ for `inf` and `nan`, and no rule parameter is non-finite. |
| `rules.proxies` `compare`, `_inputs`, `_number`, `_cold_cloud`, `anvil`, `cumulus`, `thick_cloud`, `disturbed_weather`, `upper_wind_mps`, `shear_per_km` | Message text, `float("nan")` spelling, parameter names, band edge `top + 1` to `top + 2`, `depth_km <= 1`, wind component signs and levels | Weak test: no test profile separates the mutated line from the original. Sign and level mutants in `shear_per_km` and `upper_wind_mps` need profiles with unequal directions and speeds at the levels used. |
| `rules.profile` `cloud_runs`, `height_of_isotherm_m`, `wind_at_height_mps`, `Profile.from_series` | `strict=` removed or `False`, `<= 0` to `< 1` on the crossing test, `and` in the missing-input check, the shear-exponent clamp, `values.get` without a default | Weak test: no test profile separates these from the original. |
| `rules.engine.assess_hour` | Confidence label `"direct"` changed to `"DIRECT"` | Weak test: no test supplies a rule with that confidence and checks that it is evaluated. |
| `budget.planner` `next_send_at`, `plan_requests`, `_require_aware`, `CostRecord.__post_init__` | Message text, `<= 0` to `< 0`, window comparison `>` to `>=`, budget `>` to `>=` | Weak test: the tests check the exception type with `\w`; the exact-boundary cost, a send exactly one minute old and a run exactly at the budget are not tried. |
| `budget.ledger.append_row` | `mkdir(parents=...)` dropped, `None` or `False` | Weak test: the ledger directory in tests already exists up to its parent. |
| `budget.cost.request_cost` | Message text | Weak test, as above. |
| `budget.report.main` | `gh run list` argument strings and spawn options, `os.waitpid` and `seek` arguments, the `parser.exit` call | Not covered: the tests always pass `--actions-file`, so the branch that runs `gh` is never taken. It needs a `gh` account and network, which tests must not use. |
| `budget.report.main` | `--month` and `--ledger` defaults, parser description, `>=` to `>` on the daily budget flag | Weak test: the tests pass both options explicitly and no fixture day is exactly at the budget. |
