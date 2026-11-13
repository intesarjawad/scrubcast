#!/bin/sh
cd "$(dirname "$0")/.." && exec uv run --locked python scripts/check-deploy.py "$@"
