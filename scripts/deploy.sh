#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/deploy.sh <command>
  ./scripts/deploy.sh -h|--help

职责:
  部署形态入口。当前骨架只提供 deploy 前置检查和模式说明，不执行生产部署。

不负责:
  不管理 K8s、远端服务器、云资源、生产数据库、真实 Redis/S3 adapter 或跨仓库编排。

运行环境:
  Requires: Bash.
  Optional: Docker / Docker Compose when a concrete service adds compose files.

命令:
  modes   展示当前骨架支持和预留的部署模式。
  check   校验当前骨架可用的部署前置文件和脚本入口。
  help    显示帮助。

输出:
  stdout: check 结果、模式说明。
  stderr: 缺少文件、非法命令或前置条件失败。

副作用与保护边界:
  check / modes 为只读命令，不启动服务，不修改文件，不访问远端资源。

成功标准:
  check 成功 = pyproject、.env.example、scripts 入口和关键文档存在。

常用示例:
  ./scripts/deploy.sh check
  ./scripts/deploy.sh modes

Exit Codes:
  0  成功
  2  参数、命令或静态前置条件错误
EOF
}

show_modes() {
  section "Deployment Modes"
  event "MODE" "local-api" "由 ./scripts/dev.sh 管理本地 FastAPI 进程"
  event "MODE" "compose" "预留；具体服务添加 docker-compose.yml 后再启用"
  event "MODE" "production" "不属于 fastapi-lite 骨架脚本"
}

check_deploy() {
  section "Files"
  require_file "$ROOT_DIR/pyproject.toml"
  event "OK" "pyproject" "present"
  require_file "$ROOT_DIR/.env.example"
  event "OK" ".env.example" "present"
  require_file "$ROOT_DIR/README.md"
  event "OK" "README" "present"
  require_file "$ROOT_DIR/docs/current/implementation.md"
  event "OK" "current-doc" "present"
  require_file "$ROOT_DIR/docs/contracts/api-contract.md"
  event "OK" "api-contract" "present"
  require_file "$ROOT_DIR/docs/contracts/extension-contract.md"
  event "OK" "extension" "present"
  require_file "$ROOT_DIR/docs/plans/drift-checklist.md"
  event "OK" "plans" "present"

  section "Scripts"
  bash -n "$ROOT_DIR/scripts/dev.sh"
  event "OK" "dev.sh" "syntax"
  bash -n "$ROOT_DIR/scripts/deploy.sh"
  event "OK" "deploy.sh" "syntax"
  bash -n "$ROOT_DIR/scripts/verify.sh"
  event "OK" "verify.sh" "syntax"
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
    if args_include_help "$@"; then usage; exit 0; fi
    reject_extra_args "usage: ./scripts/deploy.sh modes" "$@"
    show_modes
    ;;
  check)
    shift
    if args_include_help "$@"; then usage; exit 0; fi
    reject_extra_args "usage: ./scripts/deploy.sh check" "$@"
    check_deploy
    ;;
  *)
    usage >&2
    die "unknown command: $cmd" 2
    ;;
esac
