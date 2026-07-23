#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/verify.sh <command>
  ./scripts/verify.sh -h|--help

职责:
  一次性验证入口。负责 env、syntax、registry、Alembic、脚本 smoke、pytest、显式 PostgreSQL integration gate、显式 Redis Stream broker gate 和可选跨仓 Job Platform smoke。

不负责:
  默认 check/env/registry/syntax/alembic/scripts/tests 不启动或停止本地服务；显式 job-platform-smoke 会启动临时本地 Job Service API 和 Worker runner。
  不连接生产数据库；不管理远端资源。

命令:
  check       Run the default skeleton verification gate
  env         Check env manifest and .env.example
  registry    Check registry invariants and required docs
  syntax      Compile Python sources
  alembic     Check Alembic heads and offline SQL
  tests       Run pytest
  postgres    Run gated PostgreSQL integration checks
  redis-stream Run gated Redis Stream broker integration checks
  job-platform-smoke Run optional cross-repo Job Platform smoke
  migration-roundtrip Run upgrade/downgrade/re-upgrade against a temporary local PostgreSQL database
  scripts     Check script entrypoints
  help        Show this help

输出:
  stdout: 阶段化验证结果；pytest/Alembic 输出按需透传。
  stderr: 非法命令、配置错误、测试失败和子任务失败详情。

副作用与保护边界:
  check/env/registry/syntax/alembic/scripts/tests 不启动服务。
  postgres 会对 DATABASE__URL 指向的专用 _test 数据库执行迁移和集成测试；非 _test 数据库会失败。
  redis-stream 只连接 FASTAPI_LITE_REDIS_STREAM_URL 指向的 Redis，并使用测试专用 stream/group。

成功标准:
  check 成功 = env、syntax、registry、alembic、scripts、tests 全部通过。

常用示例:
  ./scripts/verify.sh check
  ./scripts/verify.sh registry
  ./scripts/verify.sh postgres
  FASTAPI_LITE_REDIS_STREAM_URL=redis://127.0.0.1:6379/0 ./scripts/verify.sh redis-stream
  ./scripts/verify.sh job-platform-smoke
  ./scripts/verify.sh migration-roundtrip

Exit Codes:
  0  成功
  1  检查运行完成但结果不满足预期
  2  参数、命令、配置或静态前置条件错误
  其他非 0 由 pytest、Python、Alembic 或子任务透传
EOF
}

command_usage() {
  local name="$1"
  case "$name" in
    check)
      cat <<'EOF'
Usage:
  ./scripts/verify.sh check

职责:
  执行默认骨架验证门禁：env、syntax、registry、alembic、scripts、tests。

副作用与保护边界:
  不启动服务，不访问生产数据库。

常用示例:
  ./scripts/verify.sh check
EOF
      ;;
    env|registry|syntax|alembic|tests|scripts)
      cat <<EOF
Usage:
  ./scripts/verify.sh ${name}

职责:
  执行 ${name} 验证子任务。查看顶层 help 获取完整输出和退出码合同。

副作用与保护边界:
  不启动或停止服务。

常用示例:
  ./scripts/verify.sh ${name}
EOF
      ;;
    migration-roundtrip)
      cat <<'EOF'
Usage:
  ./scripts/verify.sh migration-roundtrip

职责:
  使用临时本地 PostgreSQL 数据库验证 Alembic upgrade head -> downgrade base -> upgrade head。

配置与环境变量:
  DATABASE__URL 可覆盖本地 admin 连接来源；目标数据库会自动追加 _migration_rt_<suffix>。

副作用与保护边界:
  会创建并删除一个临时本地 PostgreSQL 数据库。
  会拒绝明显非本地主机。
  不修改当前应用数据库。

常用示例:
  ./scripts/verify.sh migration-roundtrip

Exit Codes:
  0  成功
  2  配置或前置条件错误
  其他非 0 由 PostgreSQL / Alembic 透传
EOF
      ;;
    postgres)
      cat <<'EOF'
Usage:
  ./scripts/verify.sh postgres

职责:
  对专用 PostgreSQL _test 数据库运行迁移和 integration tests。

配置与环境变量:
  DATABASE__URL 可覆盖目标数据库；默认指向 fastapi_lite_test。

副作用与保护边界:
  会写入 DATABASE__URL 指向的数据库。
  目标数据库名必须以 _test 结尾，否则 ensure_test_database.py 会失败。

常用示例:
  ./scripts/verify.sh postgres

Exit Codes:
  0  成功
  2  数据库目标不安全或配置错误
  其他非 0 由 Alembic / pytest / database driver 透传
EOF
      ;;
    redis-stream)
      cat <<'EOF'
Usage:
  FASTAPI_LITE_REDIS_STREAM_URL=redis://127.0.0.1:6379/0 ./scripts/verify.sh redis-stream

职责:
  对真实 Redis Stream broker 运行 Worker taskiq ack/no_ack 集成测试。

配置与环境变量:
  FASTAPI_LITE_REDIS_STREAM_URL 必须显式设置。

副作用与保护边界:
  会在 Redis 中创建并删除测试专用 stream 和 consumer group。
  不启动或停止 Redis 服务。

常用示例:
  FASTAPI_LITE_REDIS_STREAM_URL=redis://127.0.0.1:6379/0 ./scripts/verify.sh redis-stream
EOF
      ;;
    job-platform-smoke)
      cat <<'EOF'
Usage:
  ./scripts/verify.sh job-platform-smoke

职责:
  调用 scripts/smoke-job-platform.sh run，对当前 Worker 模板和本地 tasks-platform Job Service 做跨仓 smoke。

配置与环境变量:
  见 ./scripts/smoke-job-platform.sh help。默认使用本地 Job Service repo、PostgreSQL、Redis 和端口。

副作用与保护边界:
  会对 JOB_PLATFORM_DATABASE_URL 执行 Job Service Alembic migration。
  会启动临时 Job Service API 和 Worker runner，并在退出时清理本脚本启动的进程。
  不启动 PostgreSQL / Redis，不修改 tasks-platform 代码。

常用示例:
  ./scripts/verify.sh job-platform-smoke
EOF
      ;;
    *)
      usage >&2
      return 2
      ;;
  esac
}

cmd="${1:-}"
case "$cmd" in
  check)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/verify.sh check" "$@"
    "$0" env
    "$0" syntax
    "$0" registry
    "$0" alembic
    "$0" scripts
    "$0" tests
    ;;
  env)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/verify.sh env" "$@"
    cd "$ROOT_DIR"
    uv run python scripts/verify/env_config_check.py
    ;;
  tests)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/verify.sh tests" "$@"
    cd "$ROOT_DIR"
    uv run pytest
    ;;
  registry)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/verify.sh registry" "$@"
    cd "$ROOT_DIR"
    uv run python scripts/verify/registry_check.py
    uv run python -m app.job_platform_worker.register_cli validate
    ;;
  alembic)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/verify.sh alembic" "$@"
    cd "$ROOT_DIR"
    uv run python scripts/verify/alembic_check.py
    uv run alembic upgrade head --sql >/dev/null
    ;;
  syntax)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/verify.sh syntax" "$@"
    cd "$ROOT_DIR"
    uv run python -m compileall app alembic scripts tests
    ;;
  postgres)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/verify.sh postgres" "$@"
    cd "$ROOT_DIR"
    export DATABASE__URL="${DATABASE__URL:-postgresql+asyncpg://postgres:postgres@127.0.0.1:25432/fastapi_lite_test}"
    uv run python scripts/verify/ensure_test_database.py
    uv run alembic upgrade head
    FASTAPI_LITE_POSTGRES_INTEGRATION=1 uv run pytest -m postgres_integration
    ;;
  redis-stream)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/verify.sh redis-stream" "$@"
    cd "$ROOT_DIR"
    if [ -z "${FASTAPI_LITE_REDIS_STREAM_URL:-}" ]; then
      die "FASTAPI_LITE_REDIS_STREAM_URL is required" 2
    fi
    uv run pytest -m redis_stream_integration
    ;;
  job-platform-smoke)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/verify.sh job-platform-smoke" "$@"
    cd "$ROOT_DIR"
    ./scripts/smoke-job-platform.sh run
    ;;
  migration-roundtrip)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/verify.sh migration-roundtrip" "$@"
    cd "$ROOT_DIR"
    uv run python scripts/verify/migration_roundtrip.py
    ;;
  scripts)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/verify.sh scripts" "$@"
    cd "$ROOT_DIR"
    bash -n scripts/dev.sh
    bash -n scripts/deploy.sh
    bash -n scripts/k8s.sh
    bash -n scripts/verify.sh
    bash -n scripts/smoke-job-platform.sh
    bash -n start-worker.sh
    bash -n scripts/tools.sh
    bash -n scripts/lib/compose.sh
    bash -n scripts/lib/modes.sh
    ./scripts/dev.sh help >/dev/null
    ./scripts/dev.sh doctor >/dev/null
    ./scripts/dev.sh ports 1 --json --allow-busy >/dev/null
    ./scripts/deploy.sh help >/dev/null
    ./scripts/deploy.sh modes >/dev/null
    ./scripts/k8s.sh help >/dev/null
    ./scripts/verify.sh help >/dev/null
    ./scripts/smoke-job-platform.sh help >/dev/null
    ./scripts/tools.sh help >/dev/null
    ./scripts/tools.sh secret --prefix test_ >/dev/null
    echo "OK scripts"
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
