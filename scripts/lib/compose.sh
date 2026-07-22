#!/usr/bin/env bash
set -euo pipefail

COMPOSE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$COMPOSE_LIB_DIR/../.." && pwd)}"
source "$ROOT_DIR/scripts/lib/common.sh"

compose_available() {
  docker compose version >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1
}

compose_project_name() {
  local env_file
  local project_name

  env_file="$(env_file_path)"
  project_name="${COMPOSE_PROJECT_NAME:-$(env_value_from COMPOSE_PROJECT_NAME "$env_file")}"
  project_name="${project_name:-fastapi-lite}"
  printf "%s" "$project_name"
}

compose() {
  local env_file
  local resolved_project_name

  env_file="$(env_file_path)"
  resolved_project_name="$(compose_project_name)"

  if docker compose version >/dev/null 2>&1; then
    docker compose --env-file "$env_file" -p "$resolved_project_name" "$@"
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose --env-file "$env_file" -p "$resolved_project_name" "$@"
    return
  fi
  die "Docker Compose is not available. Install Docker Desktop or docker-compose." 2
}
