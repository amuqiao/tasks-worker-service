#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage: ./scripts/verify.sh <command>

Commands:
  check       Run all phase-1 checks
  env         Check env manifest and .env.example
  registry    Check registry invariants
  syntax      Compile Python sources
  tests       Run pytest
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
  syntax)
    cd "$ROOT_DIR"
    uv run python -m compileall app scripts tests
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
