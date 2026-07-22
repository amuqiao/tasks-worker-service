#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy.sh <command>

Commands:
  check   Validate deploy prerequisites available in this skeleton
  help    Show this help
EOF
}

cmd="${1:-help}"
case "$cmd" in
  check)
    cd "$ROOT_DIR"
    test -f pyproject.toml || die "pyproject.toml not found"
    test -f .env.example || die ".env.example not found"
    echo "OK deploy-check"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    die "unknown command: $cmd"
    ;;
esac

