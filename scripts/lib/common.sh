#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

run_uv() {
  cd "$ROOT_DIR"
  uv "$@"
}

