# Development notes

## Version verification: 2026-11-05

Package pins were checked against PyPI JSON metadata and `npm view <package> version`.
Vite advanced from 8.3.5 to 8.3.6.
Other direct dependencies keep their earlier pins. The build uses `hatchling==1.33.0`
and site development uses `@types/node==26.6.6`. Scores 2.7.0 was verified as a script-only
reference and is not installed as a dependency.

| Package | Verified version |
| --- | --- |
| uv | 0.13.7 |
| hatchling, build backend | 1.33.0 |
| httpx | 0.28.1 |
| numpy | 2.5.4 |
| pydantic | 2.14.2 |
| ruff | 0.17.3 |
| pyright | 1.1.414 |
| pytest | 9.2.0 |
| hypothesis | 6.170.14 |
| mutmut | 3.8.1 |
| pre-commit | 4.7.0 |
| scores, reference only | 2.7.0 |
| vite | 8.3.6 |
| typescript | 7.0.2 |
| @biomejs/biome | 2.6.5 |
| vitest | 5.1.0 |
| @playwright/test | 1.64.1 |
| @types/node, site development only | 26.6.6 |
| @axe-core/playwright | 4.14.0 |
| json-schema-to-typescript | 16.0.0 |

Python 3.14 is selected consistently in `.python-version`, package metadata, Ruff and
Pyright. A binary-only installation on Python 3.15 failed because the resolved
PyYAML 6.0.3 dependency has no compatible wheel. NumPy, Hypothesis, libcst and
Pydantic's required pydantic-core 2.50.2 do have CPython 3.15 wheels for macOS ARM64,
but the complete development environment does not. Query exact dependency versions:
the newer standalone pydantic-core 2.50.3 has different wheel availability from the
version required by the pinned Pydantic release.

Python 3.14 satisfies the wheel-coverage rule. Keep
`requires-python = ">=3.14"`, Ruff's `target-version = "py314"`, Pyright's
`pythonVersion = "3.14"` and `.python-version` aligned when changing Python.

Hatchling builds the `src/scrubcast` package and includes the rule catalog and
recorded CLI inputs under `scrubcast/resources`. The installed-wheel test runs
the fixture commands outside the checkout. Node declarations match the
Node 26 runtime; TypeScript includes `node` alongside `vite/client` so Vite and
Playwright configuration files receive full strict checking. Both lockfiles were
regenerated with these additions; Vite remains pinned to 8.3.6.

Node's distribution index confirms 26.13.0 is the latest stable LTS release.
Node 26.13.0 and gitleaks 8.30.1 are installed locally. Every workflow action is
pinned to the full commit SHA that `git ls-remote` resolves for its tag, with the tag in
a trailing comment; annotated tags are pinned to the peeled commit. The gitleaks archive
in `ci.yml` is verified against the SHA-256 from its release checksums file. Do not
replace action pins with unverified hashes or floating tags.

## Pending setup

- [ ] Compute budget: verify shared account usage and a zero-spend budget before enabling private collection.
- Remote: create a private repository, confirm its URL and configure
  branch protection. No remote has been created or accessed.
- Workflows: leave `refresh.yml` disabled in GitHub until the repository is public
  and the Pages deploy is configured; its hourly schedule is already in the file.
  When updating an action, resolve the new tag to its commit with `git ls-remote`
  and pin that full SHA. CI runs `make check` and a full-history gitleaks scan on
  pull requests.
- Permissions and credentials: collection, refresh, audit, publishing, provenance,
  Pages, CodeQL and Scorecard require confirmation of repository settings and any
  required credentials. Collection and audit request contents write; release requests contents and identity-token write; Pages deployment requests pages and identity-token write; Scorecard requests identity-token write.
- Community reporting: enable GitHub private vulnerability reporting for security and conduct reports.
- Publication metadata: `CITATION.cff` and `.zenodo.json` name the author and the
  repository URL. They carry no DOI until Zenodo archives the first release.

## Local environment

The Makefile exports repository-local `.cache/npm` and `.cache/uv` directories;
these are ignored. Outside make, set `UV_CACHE_DIR=$PWD/.cache/uv` and
`npm_config_cache=$PWD/.cache/npm` to reuse the same caches.

Biome 2.6.5 accepts the exact recommended-rule configuration but emits
a deprecation notice suggesting `preset`. The configuration is retained;
the notice does not weaken or fail the check.

If `core.hooksPath` is configured, `make setup` preserves it and skips hook installation. Add `uv run --locked pre-commit run --hook-stage pre-commit` to the existing pre-commit hook, retaining its existing checks.

The browser suite uses full Chromium in its new headless mode and WebKit, with
one worker for the GPU-rendered sheet. The old Chromium headless shell can stall
in SwiftShader when a forced-colour context closes before another page opens.
`npm --prefix site run e2e` retains the navigation, accessibility and performance
checks under that context transition.
