UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
npm_config_cache ?= $(CURDIR)/.cache/npm
export UV_CACHE_DIR npm_config_cache

.PHONY: setup check check-py demo types crosscheck cold-start goldens-site

setup:
	uv sync --locked
	npm --prefix site ci
	@if git config --get core.hooksPath >/dev/null; then \
		echo "Existing core.hooksPath preserved; add pre-commit to your existing hook (see docs/development.md)."; \
	else uv run --locked pre-commit install; fi

types:
	mkdir -p .cache
	uv run --locked python -m scrubcast.build.schema > .cache/public.schema.json
	site/node_modules/.bin/json2ts -i .cache/public.schema.json -o site/src/types.ts --bannerComment ''
	cd site && node_modules/.bin/biome format --write src/types.ts

crosscheck:
	uv run --with scores==2.7.0 --with xarray python scripts/crosscheck_scores.py

check-py:
	uv lock --check
	uv run --locked ruff format --check .
	uv run --locked ruff check .
	uv run --locked pyright
	uv run --locked python scripts/gen-docs.py --check
	uv run --locked pytest

check: check-py
	npm --prefix site run check
	npm --prefix site run build
	npm --prefix site run budget
	! grep -rniE "scrub probability|chance of launch|GO %|GO percentage" site/src README.md docs/*.md

cold-start:
	npm --prefix site run fixtures
	npm --prefix site run build
	npm --prefix site run cold-start

demo:
	npm --prefix site run fixtures
	npm --prefix site run dev -- --host 127.0.0.1

# Screenshot goldens are rendered on Linux by goldens.yml; macOS font rendering would not match CI.
goldens-site:
	git push -u origin HEAD
	set -e; \
	previous=$$(gh run list -w goldens.yml --limit 1 --json databaseId -q '.[0].databaseId'); \
	gh workflow run goldens.yml -f ref="$$(git branch --show-current)"; \
	run=$$previous; \
	while [ "$$run" = "$$previous" ]; do \
		sleep 3; \
		run=$$(gh run list -w goldens.yml --limit 1 --json databaseId -q '.[0].databaseId'); \
	done; \
	gh run watch "$$run" --exit-status; \
	rm -rf site/tests/e2e/__screenshots__; \
	gh run download "$$run" -n launch-goldens -D site/tests/e2e/__screenshots__; \
	git add site/tests/e2e/__screenshots__
