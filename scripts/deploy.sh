#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/compose.sh"
source "$SCRIPT_DIR/lib/modes.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/deploy.sh <command> [mode]
  ./scripts/deploy.sh -h|--help

职责:
  部署模型入口。提供 dev、dev-worker、local、worker、compose-deps、compose-full 六种运行模型；down all 为显式全量停止目标。

不负责:
  不管理 K8s、远端服务器、云资源、生产数据库、真实 Redis/S3 adapter 或跨仓库编排。

运行环境:
  Requires: Bash.
  Dependencies: Docker / Docker Compose for compose-deps and compose-full.

命令:
  modes                 展示运行模型和特殊目标。
  check                 校验部署文件、compose 配置、入口脚本和 project 名冲突。
  up dev                启动常用本地开发环境：Docker PostgreSQL / Redis + 宿主机 API。
  down dev              停止常用本地开发环境：宿主机 API + Docker PostgreSQL / Redis。
  status dev            查看常用本地开发环境：本地 API + Docker PostgreSQL / Redis。
  up dev-worker         启动本地开发 Worker 环境：Docker PostgreSQL / Redis + 宿主机 API + 宿主机 Worker。
  down dev-worker       停止本地开发 Worker 环境：宿主机 Worker + 宿主机 API + Docker PostgreSQL / Redis。
  status dev-worker     查看本地开发 Worker 环境：本地 API / Worker + Docker PostgreSQL / Redis。
  up local              委托 ./scripts/dev.sh start api。
  up worker             委托 ./scripts/dev.sh start worker。
  down <mode>           停止指定模型；mode 必须显式指定，避免误停服务。
  down local            委托 ./scripts/dev.sh stop api。
  down worker           委托 ./scripts/dev.sh stop worker。
  status local          委托 ./scripts/dev.sh status。
  status worker         委托 ./scripts/dev.sh status worker。
  up compose-deps       启动 PostgreSQL / Redis 本地依赖。
  down compose-deps     停止 PostgreSQL / Redis 本地依赖。
  status compose-deps   查看 PostgreSQL / Redis compose 状态。
  up compose-full       构建并启动 API / PostgreSQL / Redis。
  down compose-full     停止 API / PostgreSQL / Redis。
  status compose-full   查看 compose-full 状态。
  down all              全量停止 local API 和本仓库 compose 服务。
  help                  显示帮助。

配置与环境变量:
  ENV_FILE              可选，指定 compose 使用的 env 文件，默认 .env。
  COMPOSE_PROJECT_NAME  可选，覆盖 compose project 名，默认 fastapi-lite。
  API_HOST_PORT         可选，compose-full API 暴露端口，默认 8100。
  POSTGRES_HOST_PORT    可选，PostgreSQL 暴露端口，默认 25432。
  REDIS_HOST_PORT       可选，Redis 暴露端口，默认 26379。
  POSTGRES_DB           可选，PostgreSQL 数据库名，默认 fastapi_lite。

输出:
  stdout: check 结果、模式说明、compose 状态、启动/停止结果。
  stderr: 缺少文件、非法 mode、Docker Compose 错误、project 名冲突或运行模式冲突。

副作用与保护边界:
  check 只做静态文件和 compose 配置检查；如果 Docker 可用，会检查 project 名冲突。
  up/down/status dev 是常用本地开发 recipe，组合执行 compose-deps 与 local。
  up/down/status dev-worker 是显式 Worker 开发 recipe，组合执行 compose-deps、local 与 worker。
  up/down local 只委托 dev.sh 管理本地 API 进程，不启动 compose 依赖。
  up/down worker 只委托 dev.sh 管理本地 Worker 进程，不启动 compose 依赖。
  up compose-deps 只启动 PostgreSQL / Redis，不启动 API。
  up compose-full 会构建 API 镜像并启动 API / PostgreSQL / Redis；API 容器启动时默认执行 Alembic migration。
  compose-full 会拒绝与本地 API 混跑；local 会拒绝与 compose-full API 混跑。
  worker profile 可用于构建 Worker Pod 形态；只有 worker/dev-worker 显式 mode 会启动宿主机 Worker。
  down 使用 compose stop，不删除 volume；down/status 也会检查 compose project working_dir，避免误操作其他工作树。
  down 必须显式指定 mode；down all 会先停 local API/Worker，再一次性停止本仓库 compose api/worker/postgres/redis。

成功标准:
  check 成功 = 必需部署文件存在、脚本语法正确、compose 配置可解析或 Docker 未安装时静态检查通过。
  up compose-full 成功 = compose 已接收启动命令；健康状态使用 status 查看。

常用示例:
  ./scripts/deploy.sh modes
  ./scripts/deploy.sh check

  # 常见本地开发：Docker 只跑依赖，API 在宿主机运行。
  ./scripts/deploy.sh up dev
  ./scripts/deploy.sh status dev
  ./scripts/deploy.sh down dev

  # 精确控制：只操作 API 或依赖。
  ./scripts/dev.sh restart api
  ./scripts/dev.sh stop api
  ./scripts/dev.sh status
  ./scripts/deploy.sh status compose-deps

  # API/PostgreSQL/Redis 全部由 Compose 管理。
  ./scripts/deploy.sh up compose-full
  ./scripts/deploy.sh status compose-full

  # 停止本仓库全部 local/compose 服务。
  ./scripts/deploy.sh down all

Exit Codes:
  0  成功
  2  参数、命令、mode、静态前置条件或 Docker Compose 缺失
  4  compose project 名冲突、运行模式冲突或 compose 子任务失败
EOF
}

command_usage() {
  local name="$1"
  case "$name" in
    modes|check)
      cat <<EOF
Usage:
  ./scripts/deploy.sh ${name}

职责:
  执行 deploy 子命令 ${name}。查看顶层 help 获取完整配置、输出和退出码合同。

副作用与保护边界:
  ${name} 不启动或停止服务。

常用示例:
  ./scripts/deploy.sh ${name}
EOF
      ;;
    up|status)
      cat <<EOF
Usage:
  ./scripts/deploy.sh ${name} <dev|dev-worker|local|worker|compose-deps|compose-full>

职责:
  对指定部署模型执行 ${name}。

副作用与保护边界:
  dev 是常用本地开发 recipe，组合执行 compose-deps 与 local。
  dev-worker 是显式 Worker 开发 recipe，组合执行 compose-deps、local 与 worker。
  local 委托 ./scripts/dev.sh。
  worker 委托 ./scripts/dev.sh 管理宿主机 Worker。
  compose-deps 只管理 PostgreSQL / Redis。
  compose-full 管理 API / PostgreSQL / Redis，并与 local API 互斥。

常用示例:
  ./scripts/deploy.sh ${name} dev
  ./scripts/deploy.sh ${name} dev-worker
  ./scripts/deploy.sh ${name} local
  ./scripts/deploy.sh ${name} worker
  ./scripts/deploy.sh ${name} compose-deps
  ./scripts/deploy.sh ${name} compose-full
EOF
      ;;
    down)
      cat <<'EOF'
Usage:
  ./scripts/deploy.sh down <dev|dev-worker|local|worker|compose-deps|compose-full|all>

职责:
  停止指定部署模型；必须显式传入 mode。

副作用与保护边界:
  dev 会先停止 local API，再停止 compose-deps。
  dev-worker 会先停止 local Worker，再停止 local API，最后停止 compose-deps。
  local 委托 ./scripts/dev.sh stop api。
  worker 委托 ./scripts/dev.sh stop worker。
  compose-full 管理 API / PostgreSQL / Redis。
  compose-deps 只管理 PostgreSQL / Redis。
  all 会先停止 local API/Worker，再一次性停止本仓库 compose api/worker/postgres/redis。

常用示例:
  ./scripts/deploy.sh down dev
  ./scripts/deploy.sh down dev-worker
  ./scripts/deploy.sh down local
  ./scripts/deploy.sh down worker
  ./scripts/deploy.sh down compose-deps
  ./scripts/deploy.sh down compose-full
  ./scripts/deploy.sh down all
EOF
      ;;
    *)
      usage >&2
      return 2
      ;;
  esac
}

require_env_file_for_compose() {
  local env_file
  env_file="$(env_file_path)"
  [[ -f "$env_file" ]] || die "$env_file not found; run ./scripts/dev.sh bootstrap or set ENV_FILE" 2
}

show_modes() {
  section "Deployment Modes"
  event "MODE" "dev" "常用本地开发：compose-deps + 本地 API；适合日常复制粘贴"
  event "MODE" "dev-worker" "显式 Worker 开发：compose-deps + 本地 API + 本地 Worker"
  event "MODE" "local" "本地 API 进程；由 ./scripts/dev.sh 管理，适合快速开发"
  event "MODE" "worker" "本地 Worker 进程；由 ./scripts/dev.sh 管理，需显式启动"
  event "MODE" "compose-deps" "只启动 postgres/redis；适合给本地 API 提供依赖"
  event "MODE" "compose-full" "API/postgres/redis 全部由 compose 管理；API 容器启动时执行 migration"
  event "TARGET" "all" "仅用于 down；显式停止 local API/Worker 和本仓库 compose api/worker/postgres/redis"
}

check_compose_config_if_available() {
  if ! compose_available; then
    event "WARN" "compose" "Docker Compose not available; skipped compose config"
    return 0
  fi
  ENV_FILE=.env.example compose config --quiet
  event "OK" "compose-deps" "docker compose config"
  ENV_FILE=.env.example compose --profile app config --quiet
  event "OK" "compose-full" "docker compose --profile app config"
  ENV_FILE=.env.example compose --profile worker config --quiet
  event "OK" "compose-worker" "docker compose --profile worker config"
  if docker info >/dev/null 2>&1; then
    assert_no_compose_project_name_conflict
    event "OK" "compose-project" "no working_dir conflict"
  else
    event "WARN" "docker" "daemon not available; skipped project conflict check"
  fi
}

check_deploy() {
  section "Files"
  require_file "$ROOT_DIR/pyproject.toml"
  event "OK" "pyproject" "present"
  require_file "$ROOT_DIR/uv.lock"
  event "OK" "uv.lock" "present"
  require_file "$ROOT_DIR/Dockerfile"
  event "OK" "Dockerfile" "present"
  require_file "$ROOT_DIR/.dockerignore"
  event "OK" ".dockerignore" "present"
  require_file "$ROOT_DIR/docker-compose.yml"
  event "OK" "compose" "present"
  require_file "$ROOT_DIR/start-api.sh"
  event "OK" "start-api.sh" "present"
  require_file "$ROOT_DIR/start-worker.sh"
  event "OK" "start-worker.sh" "present"
  require_file "$ROOT_DIR/.env.example"
  event "OK" ".env.example" "present"
  require_file "$ROOT_DIR/README.md"
  event "OK" "README" "present"
  require_file "$ROOT_DIR/docs/current/implementation.md"
  event "OK" "current-doc" "present"
  require_file "$ROOT_DIR/docs/contracts/extension-contract.md"
  event "OK" "extension" "present"

  section "Compose Config"
  check_compose_config_if_available

  section "Scripts"
  bash -n "$ROOT_DIR/scripts/dev.sh"
  event "OK" "dev.sh" "syntax"
  bash -n "$ROOT_DIR/scripts/deploy.sh"
  event "OK" "deploy.sh" "syntax"
  bash -n "$ROOT_DIR/scripts/verify.sh"
  event "OK" "verify.sh" "syntax"
  bash -n "$ROOT_DIR/scripts/lib/compose.sh"
  event "OK" "compose.sh" "syntax"
  bash -n "$ROOT_DIR/scripts/lib/modes.sh"
  event "OK" "modes.sh" "syntax"
  sh -n "$ROOT_DIR/start-api.sh"
  event "OK" "start-api.sh" "syntax"
  sh -n "$ROOT_DIR/start-worker.sh"
  event "OK" "start-worker.sh" "syntax"
}

up_local() {
  "$ROOT_DIR/scripts/dev.sh" start api
}

up_worker() {
  "$ROOT_DIR/scripts/dev.sh" start worker
}

down_local() {
  "$ROOT_DIR/scripts/dev.sh" stop api
}

down_worker() {
  "$ROOT_DIR/scripts/dev.sh" stop worker
}

down_all() {
  section "Deploy Down All"
  event "RUN" "worker" "down"
  down_worker
  event "RUN" "local" "down"
  down_local
  if ! compose_available; then
    die "Docker Compose is not available; compose modes were not stopped" 2
  fi
  assert_no_compose_project_name_conflict
  event "RUN" "compose" "down api/worker/postgres/redis"
  section "Compose All"
  compose --profile app --profile worker stop api worker postgres redis
}

status_local() {
  "$ROOT_DIR/scripts/dev.sh" status
}

status_worker() {
  "$ROOT_DIR/scripts/dev.sh" status worker
}

up_dev() {
  section "Deploy Dev"
  event "RUN" "compose-deps" "up"
  up_deps
  event "RUN" "local" "up"
  up_local
}

up_dev_worker() {
  section "Deploy Dev Worker"
  event "RUN" "compose-deps" "up"
  up_deps
  event "RUN" "local" "up"
  up_local
  event "RUN" "worker" "up"
  up_worker
}

down_dev() {
  section "Deploy Dev"
  event "RUN" "local" "down"
  down_local
  event "RUN" "compose-deps" "down"
  down_deps
}

down_dev_worker() {
  section "Deploy Dev Worker"
  event "RUN" "worker" "down"
  down_worker
  event "RUN" "local" "down"
  down_local
  event "RUN" "compose-deps" "down"
  down_deps
}

status_dev() {
  section "Deploy Dev"
  event "CHECK" "local" "status"
  status_local
  event "CHECK" "compose-deps" "status"
  status_deps
}

status_dev_worker() {
  section "Deploy Dev Worker"
  event "CHECK" "local" "status"
  status_local
  event "CHECK" "worker" "status"
  status_worker
  event "CHECK" "compose-deps" "status"
  status_deps
}

up_deps() {
  require_env_file_for_compose
  assert_compose_host_ports_free "compose-deps" \
    "POSTGRES_HOST_PORT:25432:postgres:5432/tcp" \
    "REDIS_HOST_PORT:26379:redis:6379/tcp"
  assert_no_compose_project_name_conflict
  section "Compose Deps"
  compose up -d postgres redis
}

down_deps() {
  assert_no_compose_project_name_conflict
  assert_no_compose_full_api_running_for_deps_down
  assert_no_local_worker_running_for_deps_down
  section "Compose Deps"
  compose stop postgres redis
}

status_deps() {
  assert_no_compose_project_name_conflict
  section "Compose Deps"
  compose ps postgres redis
}

compose_api_host_url() {
  local port
  port="$(compose_env_value_or_default API_HOST_PORT 8100)"
  validate_compose_host_port API_HOST_PORT "$port"
  printf "http://127.0.0.1:%s" "$port"
}

up_full() {
  local api_url
  require_env_file_for_compose
  assert_compose_host_ports_free "compose-full" \
    "API_HOST_PORT:8100:api:8100/tcp" \
    "POSTGRES_HOST_PORT:25432:postgres:5432/tcp" \
    "REDIS_HOST_PORT:26379:redis:6379/tcp"
  assert_no_compose_project_name_conflict
  assert_no_local_api_running_for_compose_full
  section "Compose Full"
  compose --profile app up -d --build api
  api_url="$(compose_api_host_url)"
  event "INFO" "api" "url=$api_url docs=${api_url}/docs"
}

down_full() {
  assert_no_compose_project_name_conflict
  section "Compose Full"
  compose --profile app stop api postgres redis
}

status_full() {
  local api_url
  local api_name
  api_url="$(compose_api_host_url)"
  assert_no_compose_project_name_conflict
  section "Compose Full"
  api_name="$(compose_service_running api)"
  if [[ -n "$api_name" ]]; then
    row "url" "configured" "$api_url"
    row "docs" "configured" "${api_url}/docs"
    row "openapi" "configured" "${api_url}/openapi.json"
    row "health" "configured" "${api_url}/health"
  else
    row "api" "stopped" "compose-full API container is not running"
  fi
  compose --profile app ps
}

cmd="${1:-}"
case "$cmd" in
  help|-h|--help)
    usage
    ;;
  "")
    usage >&2
    exit 2
    ;;
  modes)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/deploy.sh modes" "$@"
    show_modes
    ;;
  check)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/deploy.sh check" "$@"
    check_deploy
    ;;
  up|down|status)
    action="$cmd"
    shift
    if args_include_help "$@"; then command_usage "$action"; exit $?; fi
    mode="${1:-}"
    if [[ "$action" == "down" ]]; then
      [[ -n "$mode" ]] || die "usage: ./scripts/deploy.sh down <dev|dev-worker|local|worker|compose-deps|compose-full|all>" 2
    else
      [[ -n "$mode" ]] || die "usage: ./scripts/deploy.sh $action <dev|dev-worker|local|worker|compose-deps|compose-full>" 2
    fi
    shift
    reject_extra_args "usage: ./scripts/deploy.sh $action $mode" "$@"
    case "$action:$mode" in
      up:dev) up_dev ;;
      down:dev) down_dev ;;
      status:dev) status_dev ;;
      up:dev-worker) up_dev_worker ;;
      down:dev-worker) down_dev_worker ;;
      status:dev-worker) status_dev_worker ;;
      up:local) up_local ;;
      down:local) down_local ;;
      status:local) status_local ;;
      up:worker) up_worker ;;
      down:worker) down_worker ;;
      status:worker) status_worker ;;
      up:compose-deps) up_deps ;;
      down:compose-deps) down_deps ;;
      status:compose-deps) status_deps ;;
      up:compose-full) up_full ;;
      down:compose-full) down_full ;;
      status:compose-full) status_full ;;
      down:all) down_all ;;
      *) die "unknown deploy mode for $action: $mode" 2 ;;
    esac
    ;;
  *)
    usage >&2
    die "unknown command: $cmd" 2
    ;;
esac
