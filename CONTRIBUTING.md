# Contributing

Read the [engineering standards](docs/engineering-standards.md) and
[code of conduct](CODE_OF_CONDUCT.md) before making changes.

Install the versions listed in the README, then run `make setup`. This installs locked
Python and site dependencies and local pre-commit hooks. Hooks require gitleaks on PATH.
The hooks check Python format, lint and types, site format, lint and types, and staged
secrets. They do not download hook repositories.

Run `make check` before submitting a change. Add deterministic tests for behavior, keep
business logic separate from I/O, and avoid introducing dependencies without an ADR in
`docs/adr/`. Never weaken a check to make a change pass. The browser tests run with
`npm --prefix site run e2e`; screenshot goldens are rendered in CI only (see
[testing](docs/testing.md)).

Use `uv run ruff format .` from the repository root to format Python. To format the
site, change to `site/` and run `npm exec -- biome format --write .`.

## Adding or changing a rule

Rules are versioned JSON under `rules/`: the launch commit criteria in `rules/llcc/`,
vehicle limits in `rules/vehicles/` and per-site overrides in `rules/sites/`. Every
threshold needs a source (the standard's `section`, or a `source_url` and `source_note`),
or an entry marked `scrub` in the rule's `origin` map when no public document fixes it. After editing, run `uv run python scripts/gen-docs.py` so
[docs/rules.md](docs/rules.md) matches; `make check` fails until it does. To see what a
changed threshold would have said about past launches, follow the re-scoring recipe in
[docs/recipes.md](docs/recipes.md).

## Commits

Use small conventional commits with an imperative subject and a body explaining why.
Keep generated lockfiles with dependency changes. Report dependency version checks in
the change description and preserve full commit SHA pins for workflow actions.

Public copy must not combine weather rules into a single launch forecast number.

Security reports go through [SECURITY.md](SECURITY.md), not public issues.
