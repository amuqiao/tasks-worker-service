#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage: ./scripts/dev.sh <command>

Commands:
  bootstrap   Install dependencies with uv
  run         Run local API with uvicorn in foreground
  start api   Start local API in background
  stop api    Stop local API background process
  restart api Restart local API background process
  status      Show local API process status
  logs        Tail local API log
  test        Run pytest
  help        Show this help
EOF
}

pid_file="$ROOT_DIR/.run/api.pid"
log_file="$ROOT_DIR/.run/api.log"

api_pid() {
  if [[ -f "$pid_file" ]]; then
    cat "$pid_file"
  fi
}

api_running() {
  local pid
  pid="$(api_pid || true)"
  [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1
}

start_api() {
  if api_running; then
    echo "OK api already running pid=$(api_pid)"
    return 0
  fi
  mkdir -p "$ROOT_DIR/.run"
  cd "$ROOT_DIR"
  local host="${API_HOST:-127.0.0.1}"
  local port="${API_PORT:-8100}"
  nohup uv run uvicorn app.main:app --host "$host" --port "$port" >"$log_file" 2>&1 &
  echo "$!" > "$pid_file"
  disown "$!" 2>/dev/null || true
  echo "OK api started pid=$(api_pid) url=http://$host:$port"
}

stop_api() {
  if ! api_running; then
    echo "OK api not running"
    return 0
  fi
  local pid
  pid="$(api_pid)"
  kill "$pid"
  rm -f "$pid_file"
  echo "OK api stopped pid=$pid"
}

cmd="${1:-help}"
target="${2:-}"
case "$cmd" in
  bootstrap)
    run_uv sync --all-groups
    ;;
  run)
    cd "$ROOT_DIR"
    host="${API_HOST:-127.0.0.1}"
    port="${API_PORT:-8100}"
    uv run uvicorn app.main:app --host "$host" --port "$port" --reload
    ;;
  start)
    [[ "$target" == "api" ]] || die "usage: ./scripts/dev.sh start api"
    start_api
    ;;
  stop)
    [[ "$target" == "api" ]] || die "usage: ./scripts/dev.sh stop api"
    stop_api
    ;;
  restart)
    [[ "$target" == "api" ]] || die "usage: ./scripts/dev.sh restart api"
    stop_api
    start_api
    ;;
  status)
    if api_running; then
      echo "api running pid=$(api_pid)"
    else
      echo "api stopped"
    fi
    ;;
  logs)
    mkdir -p "$ROOT_DIR/.run"
    touch "$log_file"
    tail -n "${TAIL_LINES:-80}" "$log_file"
    ;;
  test)
    cd "$ROOT_DIR"
    uv run pytest
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    die "unknown command: $cmd"
    ;;
esac
