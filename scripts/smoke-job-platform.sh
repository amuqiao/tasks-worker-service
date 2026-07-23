#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/lib/common.sh"

JOB_PLATFORM_REPO="${JOB_PLATFORM_REPO:-/Users/admin/Code/tasks-platform}"
JOB_PLATFORM_API_HOST="${JOB_PLATFORM_API_HOST:-127.0.0.1}"
JOB_PLATFORM_API_PORT="${JOB_PLATFORM_API_PORT:-8110}"
JOB_PLATFORM_BASE_URL="${JOB_PLATFORM_BASE_URL:-http://${JOB_PLATFORM_API_HOST}:${JOB_PLATFORM_API_PORT}}"
JOB_PLATFORM_INTERNAL_BASE_URL="${JOB_PLATFORM_INTERNAL_BASE_URL:-${JOB_PLATFORM_BASE_URL}/internal/v1}"
JOB_PLATFORM_REUSE_API="${JOB_PLATFORM_REUSE_API:-false}"
JOB_PLATFORM_DATABASE_URL="${JOB_PLATFORM_DATABASE_URL:-postgresql+asyncpg://postgres:postgres@127.0.0.1:25433/job_platform}"
JOB_PLATFORM_REDIS_URL="${JOB_PLATFORM_REDIS_URL:-redis://127.0.0.1:26380/0}"
JOB_PLATFORM_SERVICE_API_KEY="${JOB_PLATFORM_SERVICE_API_KEY:-dev-service-key}"
JOB_PLATFORM_CALLER_SERVICE="${JOB_PLATFORM_CALLER_SERVICE:-business-api-a}"

WORKER_SERVICE_NAME="${WORKER_SERVICE_NAME:-worker-template-smoke}"
WORKER_NAME="${WORKER_NAME:-worker-template-smoke-taskiq}"
WORKER_SESSION_ID="${WORKER_SESSION_ID:-worker-template-smoke-local}"
WORKER_QUEUE_NAME="${WORKER_QUEUE_NAME:-job.worker-template-smoke.v1}"
WORKER_JOB_SERVICE_API_KEY="${WORKER_JOB_SERVICE_API_KEY:-$JOB_PLATFORM_SERVICE_API_KEY}"
WORKER_JOB_SERVICE_REGISTRY_API_KEY="${WORKER_JOB_SERVICE_REGISTRY_API_KEY:-dev-registry-key}"
WORKER_MANIFEST_SOURCE="${WORKER_MANIFEST_SOURCE:-app/worker/manifest.json}"
WORKER_SMOKE_SOURCE_TASK_NAME="${WORKER_SMOKE_SOURCE_TASK_NAME:-example.task}"
WORKER_SMOKE_SOURCE_TASK_VERSION="${WORKER_SMOKE_SOURCE_TASK_VERSION:-1}"
WORKER_SMOKE_TASK_NAME="${WORKER_SMOKE_TASK_NAME:-worker_template_smoke.${WORKER_SMOKE_SOURCE_TASK_NAME}}"
WORKER_SMOKE_TASK_VERSION="${WORKER_SMOKE_TASK_VERSION:-$WORKER_SMOKE_SOURCE_TASK_VERSION}"
WORKER_SMOKE_INPUT_JSON="${WORKER_SMOKE_INPUT_JSON:-{\"message\":\"hello from worker template smoke\"}}"
WORKER_SMOKE_INPUT_REF_JSON="${WORKER_SMOKE_INPUT_REF_JSON:-}"
WORKER_SMOKE_EXPECT_OUTPUT_PATH="${WORKER_SMOKE_EXPECT_OUTPUT_PATH:-}"
JOB_PLATFORM_REGISTRY_API_KEYS="${JOB_PLATFORM_REGISTRY_API_KEYS:-{\"${WORKER_SERVICE_NAME}\":\"${WORKER_JOB_SERVICE_REGISTRY_API_KEY}\"}}"

JOB_API_PID=""
WORKER_PID=""
SMOKE_MANIFEST=""
CREATE_RESPONSE=""
GET_RESPONSE=""
JOB_REQUEST=""
REGISTER_RESPONSE=""

usage() {
  cat <<'EOF'
Usage:
  ./scripts/smoke-job-platform.sh <command>
  ./scripts/smoke-job-platform.sh -h|--help

职责:
  对当前 Worker 模板和独立 tasks-platform Job Service 做一次本地跨仓 smoke：
  注册 manifest -> 创建 job -> dispatcher 发布 -> worker 消费 -> Job Service 返回 succeeded。

不负责:
  不启动 PostgreSQL / Redis。
  不修改 tasks-platform 代码。
  不替代完整集成测试或生产部署验收。

命令:
  check  只检查本地工具、仓库、URL 和 manifest 前置条件。
  run    执行完整跨仓 smoke。
  help   显示帮助。

常用示例:
  JOB_PLATFORM_REPO=/Users/admin/Code/tasks-platform \
  JOB_PLATFORM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:25433/job_platform \
  JOB_PLATFORM_REDIS_URL=redis://127.0.0.1:26380/0 \
  ./scripts/smoke-job-platform.sh run

关键环境变量:
  JOB_PLATFORM_REPO                  Job Service 仓库路径，默认 /Users/admin/Code/tasks-platform。
  JOB_PLATFORM_BASE_URL              Job Service API 地址，默认 http://127.0.0.1:8110。
  JOB_PLATFORM_REUSE_API             是否复用已 ready 的 Job Service API，默认 false。
  JOB_PLATFORM_DATABASE_URL          Job Service 数据库地址，必须是本地地址。
  JOB_PLATFORM_REDIS_URL             Job Service taskiq Redis Stream 地址，必须是本地地址。
  JOB_PLATFORM_REGISTRY_API_KEYS     Job Service registry token map。
  JOB_PLATFORM_CALLER_SERVICE        提交 job 的 caller service，默认 business-api-a。
  WORKER_SERVICE_NAME                当前 smoke worker service，默认 worker-template-smoke。
  WORKER_QUEUE_NAME                  当前 smoke queue，默认 job.worker-template-smoke.v1。
  WORKER_SMOKE_SOURCE_TASK_NAME      从 manifest 选择的原始 task_name，默认 example.task。
  WORKER_SMOKE_SOURCE_TASK_VERSION   从 manifest 选择的原始 task_version，默认 1。
  WORKER_SMOKE_TASK_NAME             注册和提交用的临时 smoke task_name。
  WORKER_SMOKE_TASK_VERSION          注册和提交用的临时 smoke task_version。
  WORKER_SMOKE_INPUT_JSON            提交 job 的 input JSON object。
  WORKER_SMOKE_INPUT_REF_JSON        可选，提交 job 的 input_ref JSON object。
  WORKER_SMOKE_EXPECT_OUTPUT_PATH    可选，成功后打印 data.output 下的点路径。

副作用与保护边界:
  run 会对 JOB_PLATFORM_DATABASE_URL 执行 alembic upgrade head。
  run 会启动临时 Job Service API 和 Worker runner；脚本退出时会清理本脚本启动的进程。
  如果 JOB_PLATFORM_BASE_URL 已经有 ready 的 Job Service，默认拒绝复用；确认它和本脚本 DB/Redis/Repo 一致后，可设置 JOB_PLATFORM_REUSE_API=true。

Exit Codes:
  0  成功
  1  smoke 执行完成但 job 未成功
  2  参数、工具、文件或配置错误
  3  本地地址保护拒绝
  4  进程、网络、迁移、注册、dispatch 或轮询失败
EOF
}

cleanup() {
  if [[ -n "$WORKER_PID" ]] && ps -p "$WORKER_PID" >/dev/null 2>&1; then
    kill "$WORKER_PID" >/dev/null 2>&1 || true
    wait "$WORKER_PID" 2>/dev/null || true
  fi
  if [[ -n "$JOB_API_PID" ]] && ps -p "$JOB_API_PID" >/dev/null 2>&1; then
    kill "$JOB_API_PID" >/dev/null 2>&1 || true
    wait "$JOB_API_PID" 2>/dev/null || true
  fi
  if [[ -n "$SMOKE_MANIFEST" && -f "$SMOKE_MANIFEST" ]]; then
    rm -f "$SMOKE_MANIFEST"
  fi
  if [[ -n "$CREATE_RESPONSE" && -f "$CREATE_RESPONSE" ]]; then
    rm -f "$CREATE_RESPONSE"
  fi
  if [[ -n "$GET_RESPONSE" && -f "$GET_RESPONSE" ]]; then
    rm -f "$GET_RESPONSE"
  fi
  if [[ -n "$JOB_REQUEST" && -f "$JOB_REQUEST" ]]; then
    rm -f "$JOB_REQUEST"
  fi
  if [[ -n "$REGISTER_RESPONSE" && -f "$REGISTER_RESPONSE" ]]; then
    rm -f "$REGISTER_RESPONSE"
  fi
}

require_local_url_value() {
  local key="$1"
  local value="$2"
  require_command uv "install uv first"
  local host
  host="$(URL_VALUE="$value" uv run python -c 'from urllib.parse import urlsplit; import os; print(urlsplit(os.environ["URL_VALUE"]).hostname or "")')"
  case "$host" in
    127.0.0.1|localhost|0.0.0.0|::1|host.docker.internal|postgres|redis)
      return 0
      ;;
  esac
  die "$key host does not look local: ${host:-unknown}" 3
}

job_platform_env() {
  env \
    APP_ENV=local \
    DATABASE__URL="$JOB_PLATFORM_DATABASE_URL" \
    TASKIQ__BROKER_KIND=redis_stream \
    TASKIQ__REDIS_URL="$JOB_PLATFORM_REDIS_URL" \
    TASKIQ__QUEUE_NAME="$WORKER_QUEUE_NAME" \
    SECURITY__SERVICE_API_KEY="$JOB_PLATFORM_SERVICE_API_KEY" \
    SECURITY__WORKER_REGISTRY_API_KEYS="$JOB_PLATFORM_REGISTRY_API_KEYS" \
    "$@"
}

worker_env() {
  env \
    TASKIQ__BROKER_KIND=redis_stream \
    TASKIQ__REDIS_URL="$JOB_PLATFORM_REDIS_URL" \
    TASKIQ__QUEUE_NAME="$WORKER_QUEUE_NAME" \
    WORKER__SERVICE_NAME="$WORKER_SERVICE_NAME" \
    WORKER__WORKER_NAME="$WORKER_NAME" \
    WORKER__WORKER_SESSION_ID="$WORKER_SESSION_ID" \
    WORKER__JOB_SERVICE_BASE_URL="$JOB_PLATFORM_INTERNAL_BASE_URL" \
    WORKER__JOB_SERVICE_API_KEY="$WORKER_JOB_SERVICE_API_KEY" \
    WORKER__JOB_SERVICE_REGISTRY_API_KEY="$WORKER_JOB_SERVICE_REGISTRY_API_KEY" \
    WORKER__MANIFEST_PATH="$SMOKE_MANIFEST" \
    "$@"
}

check_prerequisites() {
  section "Smoke Prerequisites"
  require_command uv "install uv first"
  require_command curl "install curl first"
  require_file "$ROOT_DIR/$WORKER_MANIFEST_SOURCE"
  require_file "$JOB_PLATFORM_REPO/pyproject.toml"
  require_file "$JOB_PLATFORM_REPO/app/main.py"
  require_file "$JOB_PLATFORM_REPO/alembic.ini"
  require_local_url_value "JOB_PLATFORM_BASE_URL" "$JOB_PLATFORM_BASE_URL"
  require_local_url_value "JOB_PLATFORM_DATABASE_URL" "$JOB_PLATFORM_DATABASE_URL"
  require_local_url_value "JOB_PLATFORM_REDIS_URL" "$JOB_PLATFORM_REDIS_URL"
  event "OK" "worker-repo" "$ROOT_DIR"
  event "OK" "job-repo" "$JOB_PLATFORM_REPO"
  event "OK" "job-api" "$JOB_PLATFORM_BASE_URL"
  event "OK" "worker-queue" "$WORKER_QUEUE_NAME"
}

wait_for_job_api() {
  local timeout_seconds="${1:-20}"
  local elapsed=0
  while true; do
    if curl -fsS "$JOB_PLATFORM_BASE_URL/ready" >/dev/null 2>&1; then
      event "READY" "job-api" "$JOB_PLATFORM_BASE_URL/ready"
      return 0
    fi
    if (( elapsed >= timeout_seconds )); then
      tail -n 80 "$LOG_DIR/job-platform-smoke-api.log" >&2 2>/dev/null || true
      die "job platform api health check failed after ${timeout_seconds}s" 4
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
}

ensure_job_api() {
  if curl -fsS "$JOB_PLATFORM_BASE_URL/ready" >/dev/null 2>&1; then
    if [[ "$JOB_PLATFORM_REUSE_API" != "true" ]]; then
      die "job platform api is already ready at $JOB_PLATFORM_BASE_URL; stop it or set JOB_PLATFORM_REUSE_API=true after confirming repo/db/redis match this smoke" 4
    fi
    event "USE" "job-api" "already running at $JOB_PLATFORM_BASE_URL"
    return 0
  fi
  if curl -fsS "$JOB_PLATFORM_BASE_URL/health" >/dev/null 2>&1; then
    die "job platform api is running but not ready: $JOB_PLATFORM_BASE_URL/ready" 4
  fi

  mkdir -p "$LOG_DIR"
  section "Job Service"
  event "RUN" "alembic" "upgrade head"
  (cd "$JOB_PLATFORM_REPO" && job_platform_env uv run alembic upgrade head) || die "job platform migration failed" 4

  event "START" "job-api" "$JOB_PLATFORM_BASE_URL"
  (cd "$JOB_PLATFORM_REPO" && job_platform_env uv run python -m uvicorn app.main:app --host "$JOB_PLATFORM_API_HOST" --port "$JOB_PLATFORM_API_PORT") \
    >"$LOG_DIR/job-platform-smoke-api.log" 2>&1 &
  JOB_API_PID="$!"
  wait_for_job_api 25
}

render_smoke_manifest() {
  SMOKE_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/fastapi-lite-worker-smoke-manifest.XXXXXX")"
  if ! WORKER_SERVICE_NAME="$WORKER_SERVICE_NAME" \
    WORKER_QUEUE_NAME="$WORKER_QUEUE_NAME" \
    WORKER_SMOKE_SOURCE_TASK_NAME="$WORKER_SMOKE_SOURCE_TASK_NAME" \
    WORKER_SMOKE_SOURCE_TASK_VERSION="$WORKER_SMOKE_SOURCE_TASK_VERSION" \
    WORKER_SMOKE_TASK_NAME="$WORKER_SMOKE_TASK_NAME" \
    WORKER_SMOKE_TASK_VERSION="$WORKER_SMOKE_TASK_VERSION" \
    JOB_PLATFORM_CALLER_SERVICE="$JOB_PLATFORM_CALLER_SERVICE" \
    uv run python - "$ROOT_DIR/$WORKER_MANIFEST_SOURCE" "$SMOKE_MANIFEST" <<'PY'
import json
import os
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
manifest = json.loads(source.read_text(encoding="utf-8"))
manifest["worker_service"] = os.environ["WORKER_SERVICE_NAME"]
manifest["queue_name"] = os.environ["WORKER_QUEUE_NAME"]

source_task_name = os.environ["WORKER_SMOKE_SOURCE_TASK_NAME"]
source_task_version = int(os.environ["WORKER_SMOKE_SOURCE_TASK_VERSION"])
task = next(
    (
        item
        for item in manifest["tasks"]
        if item["task_name"] == source_task_name and item["task_version"] == source_task_version
    ),
    None,
)
if task is None:
    raise SystemExit(f"smoke source task not found: {source_task_name}@v{source_task_version}")

task = dict(task)
manifest["tasks"] = [task]
task["task_name"] = os.environ["WORKER_SMOKE_TASK_NAME"]
task["task_version"] = int(os.environ["WORKER_SMOKE_TASK_VERSION"])
for binding in task.get("caller_bindings", []):
    binding["caller_service"] = os.environ["JOB_PLATFORM_CALLER_SERVICE"]

target.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
PY
  then
    die "failed to render smoke manifest" 4
  fi
  event "CREATED" "manifest" "$SMOKE_MANIFEST"
}

register_worker_manifest() {
  section "Worker Registration"
  REGISTER_RESPONSE="$(mktemp "${TMPDIR:-/tmp}/fastapi-lite-worker-smoke-register.XXXXXX")"
  worker_env uv run python -m app.job_platform_worker.register_cli validate --manifest "$SMOKE_MANIFEST" || die "worker manifest validation failed" 4
  worker_env uv run python -m app.job_platform_worker.register_cli register --manifest "$SMOKE_MANIFEST" >"$REGISTER_RESPONSE" || die "worker manifest registration failed" 4
  event "OK" "register" "$WORKER_SERVICE_NAME"
}

start_worker_runner() {
  mkdir -p "$LOG_DIR"
  section "Worker Runner"
  event "START" "worker" "$WORKER_QUEUE_NAME"
  worker_env uv run python -m app.job_platform_worker.runner >"$LOG_DIR/worker-smoke-runner.log" 2>&1 &
  WORKER_PID="$!"
  sleep 1
  if ! ps -p "$WORKER_PID" >/dev/null 2>&1; then
    tail -n 80 "$LOG_DIR/worker-smoke-runner.log" >&2 2>/dev/null || true
    die "worker runner exited before smoke job was submitted" 4
  fi
}

create_job() {
  local response_file="$1"
  local idempotency_key="worker-template-smoke-$(date +%s)-$RANDOM"
  JOB_REQUEST="$(mktemp "${TMPDIR:-/tmp}/fastapi-lite-worker-smoke-request.XXXXXX")"
  WORKER_SMOKE_TASK_NAME="$WORKER_SMOKE_TASK_NAME" \
  WORKER_SMOKE_TASK_VERSION="$WORKER_SMOKE_TASK_VERSION" \
  WORKER_SMOKE_INPUT_JSON="$WORKER_SMOKE_INPUT_JSON" \
  WORKER_SMOKE_INPUT_REF_JSON="$WORKER_SMOKE_INPUT_REF_JSON" \
  uv run python - "$JOB_REQUEST" <<'PY' || die "failed to render create job request" 4
import json
import os
import sys

payload = {
    "task_name": os.environ["WORKER_SMOKE_TASK_NAME"],
    "task_version": int(os.environ["WORKER_SMOKE_TASK_VERSION"]),
    "metadata": {"source": "fastapi-lite-smoke"},
}
input_ref_json = os.environ.get("WORKER_SMOKE_INPUT_REF_JSON", "")
if input_ref_json:
    payload["input_ref"] = json.loads(input_ref_json)
else:
    payload["input"] = json.loads(os.environ["WORKER_SMOKE_INPUT_JSON"])
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
PY
  curl -fsS \
    -X POST "$JOB_PLATFORM_BASE_URL/v1/jobs" \
    -H "Authorization: Bearer caller:${JOB_PLATFORM_CALLER_SERVICE}:${JOB_PLATFORM_SERVICE_API_KEY}" \
    -H "Content-Type: application/json" \
    -H "X-Job-Idempotency-Key: ${idempotency_key}" \
    --data-binary "@${JOB_REQUEST}" \
    >"$response_file" || die "create job request failed" 4
}

json_get() {
  local path="$1"
  local file="$2"
  JSON_PATH="$path" uv run python - "$file" <<'PY'
import json
import os
import sys

value = json.loads(open(sys.argv[1], encoding="utf-8").read())
for part in os.environ["JSON_PATH"].split("."):
    value = value[part]
print(value)
PY
}

dispatch_job() {
  local run_id="$1"
  section "Dispatch"
  (cd "$JOB_PLATFORM_REPO" && job_platform_env uv run python -m app.runtime.taskiq_dispatcher once --run-id "$run_id") || die "job platform dispatch failed" 4
}

wait_for_job_success() {
  local run_id="$1"
  local response_file="$2"
  local status=""
  local elapsed=0
  while (( elapsed < 30 )); do
    curl -fsS \
      -H "Authorization: Bearer caller:${JOB_PLATFORM_CALLER_SERVICE}:${JOB_PLATFORM_SERVICE_API_KEY}" \
      "$JOB_PLATFORM_BASE_URL/v1/jobs/$run_id" >"$response_file" || die "query job failed" 4
    status="$(json_get "data.status" "$response_file")"
    if [[ "$status" == "succeeded" ]]; then
      event "OK" "job" "succeeded run_id=$run_id"
      return 0
    fi
    if [[ "$status" == "failed" || "$status" == "cancelled" ]]; then
      cat "$response_file" >&2
      die "job reached terminal non-success status: $status" 1
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  cat "$response_file" >&2
  die "job did not succeed within 30s; last status=$status" 1
}

run_smoke() {
  trap cleanup EXIT
  check_prerequisites
  ensure_job_api
  render_smoke_manifest
  register_worker_manifest
  start_worker_runner

  section "Submit Job"
  CREATE_RESPONSE="$(mktemp "${TMPDIR:-/tmp}/fastapi-lite-worker-smoke-create.XXXXXX")"
  GET_RESPONSE="$(mktemp "${TMPDIR:-/tmp}/fastapi-lite-worker-smoke-get.XXXXXX")"
  create_job "$CREATE_RESPONSE"
  local run_id
  run_id="$(json_get "data.run_id" "$CREATE_RESPONSE")"
  event "OK" "created" "$run_id"

  dispatch_job "$run_id"
  wait_for_job_success "$run_id" "$GET_RESPONSE"
  if [[ -n "$WORKER_SMOKE_EXPECT_OUTPUT_PATH" ]]; then
    event "RESULT" "job" "$(json_get "data.output.${WORKER_SMOKE_EXPECT_OUTPUT_PATH}" "$GET_RESPONSE")"
  else
    event "RESULT" "job" "succeeded"
  fi
}

cmd="${1:-}"
case "$cmd" in
  check)
    shift
    if args_include_help "$@"; then usage; exit 0; fi
    reject_extra_args "usage: ./scripts/smoke-job-platform.sh check" "$@"
    check_prerequisites
    ;;
  run)
    shift
    if args_include_help "$@"; then usage; exit 0; fi
    reject_extra_args "usage: ./scripts/smoke-job-platform.sh run" "$@"
    run_smoke
    ;;
  help|-h|--help)
    usage
    ;;
  "")
    usage >&2
    exit 2
    ;;
  *)
    usage >&2
    die "unknown command: $cmd" 2
    ;;
esac
