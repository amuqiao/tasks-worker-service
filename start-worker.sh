#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd "$(dirname "$0")" && pwd)"

cd "$ROOT_DIR"

exec uv run python -m app.job_platform_worker.runner
