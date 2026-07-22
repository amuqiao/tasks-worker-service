#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage: ./scripts/verify.sh <command>

Commands:
  check       Run the default skeleton verification gate
  env         Check env manifest and .env.example
  registry    Check registry invariants
  syntax      Compile Python sources
  alembic     Check Alembic heads and offline SQL
  tests       Run pytest
  postgres    Run gated PostgreSQL integration checks
  scripts     Check script entrypoints
  help        Show this help
EOF
}

cmd="${1:-help}"
case "$cmd" in
  check)
    "$0" env
    "$0" syntax
    "$0" registry
    "$0" alembic
    "$0" scripts
    "$0" tests
    ;;
  env)
    cd "$ROOT_DIR"
    uv run python scripts/verify/env_config_check.py
    ;;
  tests)
    cd "$ROOT_DIR"
    uv run pytest
    ;;
  registry)
    cd "$ROOT_DIR"
    uv run python scripts/verify/registry_check.py
    ;;
  alembic)
    cd "$ROOT_DIR"
    uv run python scripts/verify/alembic_check.py
    uv run alembic upgrade head --sql >/dev/null
    ;;
  syntax)
    cd "$ROOT_DIR"
    uv run python -m compileall app alembic scripts tests
    ;;
  postgres)
    cd "$ROOT_DIR"
    export DATABASE__URL="${DATABASE__URL:-postgresql+asyncpg://postgres:postgres@127.0.0.1:25432/fastapi_lite_test}"
    uv run python scripts/verify/ensure_test_database.py
    uv run alembic upgrade head
    FASTAPI_LITE_POSTGRES_INTEGRATION=1 uv run pytest -m postgres_integration
    ;;
  scripts)
    cd "$ROOT_DIR"
    ./scripts/dev.sh help >/dev/null
    ./scripts/deploy.sh help >/dev/null
    ./scripts/verify.sh help >/dev/null
    echo "OK scripts"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    die "unknown command: $cmd"
    ;;
esac
