#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/lib/common.sh"

TRITON_SSH_HOST="${TRITON_SSH_HOST:-wangqiao@47.94.108.140}"
TRITON_REMOTE_HOST="${TRITON_REMOTE_HOST:-127.0.0.1}"
TRITON_REMOTE_PORT="${TRITON_REMOTE_PORT:-8000}"
TRITON_LOCAL_HOST="${TRITON_LOCAL_HOST:-127.0.0.1}"
TRITON_LOCAL_PORT="${TRITON_LOCAL_PORT:-18000}"
TRITON_READY_TIMEOUT_SECONDS="${TRITON_READY_TIMEOUT_SECONDS:-90}"
TRITON_INFER_TIMEOUT_SECONDS="${TRITON_INFER_TIMEOUT_SECONDS:-300}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=2)

usage() {
  cat <<'EOF'
Usage:
  ./scripts/real-flow.sh <command>
  ./scripts/real-flow.sh -h|--help

职责:
  验证本服务通过 SSH tunnel 访问远端开发服务器 Triton 的真实链路。
  默认 tunnel: 127.0.0.1:18000 -> wangqiao@47.94.108.140:127.0.0.1:8000。

命令:
  check          检查工具、.env 和远端 Triton ready 前置条件。
  tunnel         如果本地 tunnel 未 ready，则启动 SSH local forward。
  ready          确保 tunnel 后检查本地 Triton ready endpoint。
  infer          确保 tunnel 后对 4 个 htdemucs-ft Triton model 做最小 tensor infer。
  smoke          确保 tunnel 后复用 smoke-job-platform.sh 跑 audio_stem_separation_triton。
  help           显示帮助。

关键环境变量:
  TRITON_SSH_HOST                 SSH 目标，默认 wangqiao@47.94.108.140。
  TRITON_REMOTE_HOST              远端 Triton 绑定地址，默认 127.0.0.1。
  TRITON_REMOTE_PORT              远端 Triton HTTP 端口，默认 8000。
  TRITON_LOCAL_HOST               本地 tunnel 绑定地址，默认 127.0.0.1。
  TRITON_LOCAL_PORT               本地 tunnel 端口，默认 18000。
  AUDIO_STEM_REAL_FLOW_INPUT_JSON smoke 使用的真实 OSS input JSON object。
  AUDIO_STEM_REAL_FLOW_INPUT_FILE smoke 使用的真实 OSS input JSON 文件。

示例:
  ./scripts/real-flow.sh check
  ./scripts/real-flow.sh tunnel
  ./scripts/real-flow.sh infer
  AUDIO_STEM_REAL_FLOW_INPUT_FILE=.run/audio-stem-input.json ./scripts/real-flow.sh smoke

Exit Codes:
  0  成功
  1  验证失败
  2  参数、工具、文件或配置错误
  4  tunnel、远端 ready、infer 或 smoke 执行失败
EOF
}

triton_local_base_url() {
  printf "http://%s:%s" "$TRITON_LOCAL_HOST" "$TRITON_LOCAL_PORT"
}

read_env_key() {
  local key="$1"
  local value="${!key:-}"
  if [[ -n "$value" ]]; then
    printf "%s" "$value"
    return 0
  fi
  env_value "$key"
}

triton_configured_url() {
  local configured
  configured="$(read_env_key "AUDIO_STEM_TRITON__URL")"
  if [[ -n "$configured" ]]; then
    printf "%s" "$configured"
  else
    triton_local_base_url
  fi
}

triton_client_url() {
  TRITON_URL="$(triton_local_base_url)" uv run python - <<'PY'
import os
from urllib.parse import urlsplit

value = os.environ["TRITON_URL"].strip().rstrip("/")
if value.startswith(("http://", "https://")):
    parsed = urlsplit(value)
    if not parsed.netloc:
        raise SystemExit("AUDIO_STEM_TRITON__URL must include a host")
    print(f"{parsed.netloc}{parsed.path}".rstrip("/"))
else:
    print(value)
PY
}

check_prerequisites() {
  section "Real Flow Prerequisites"
  require_command ssh "install ssh first"
  require_command curl "install curl first"
  require_command uv "install uv first"
  require_file "$(env_file_path)"
  row "ssh_host" "value" "$TRITON_SSH_HOST"
  row "remote" "value" "${TRITON_REMOTE_HOST}:${TRITON_REMOTE_PORT}"
  row "local" "value" "${TRITON_LOCAL_HOST}:${TRITON_LOCAL_PORT}"
  row "env_url" "value" "$(triton_configured_url)"
}

run_check() {
  check_prerequisites
  section "Remote Triton"
  local remote_code
  remote_code="$(remote_ready || true)"
  event "READY" "remote" "$remote_code"
  [[ "$remote_code" == "200" ]] || die "remote Triton is not ready via SSH" 4

  section "SSH Tunnel"
  event "READY" "local" "$(local_ready)"
}

remote_ready() {
  ssh "${SSH_OPTS[@]}" "$TRITON_SSH_HOST" \
    "curl --connect-timeout 5 --max-time 10 -s -o /dev/null -w '%{http_code}' http://${TRITON_REMOTE_HOST}:${TRITON_REMOTE_PORT}/v2/health/ready"
}

local_ready() {
  curl --connect-timeout 2 --max-time 5 -s -o /dev/null -w "%{http_code}" "$(triton_local_base_url)/v2/health/ready" || true
}

wait_local_ready() {
  local elapsed=0
  local code
  while (( elapsed < TRITON_READY_TIMEOUT_SECONDS )); do
    code="$(local_ready)"
    if [[ "$code" == "200" ]]; then
      event "READY" "triton" "$(triton_local_base_url)"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  die "local Triton tunnel was not ready within ${TRITON_READY_TIMEOUT_SECONDS}s" 4
}

ensure_tunnel() {
  check_prerequisites
  section "Remote Triton"
  local remote_code
  remote_code="$(remote_ready || true)"
  event "READY" "remote" "$remote_code"
  [[ "$remote_code" == "200" ]] || die "remote Triton is not ready via SSH" 4

  section "SSH Tunnel"
  local local_code
  local_code="$(local_ready)"
  if [[ "$local_code" == "200" ]]; then
    event "USE" "tunnel" "$(triton_local_base_url)"
    return 0
  fi

  event "START" "tunnel" "${TRITON_LOCAL_HOST}:${TRITON_LOCAL_PORT} -> ${TRITON_SSH_HOST}:${TRITON_REMOTE_HOST}:${TRITON_REMOTE_PORT}"
  ssh "${SSH_OPTS[@]}" -o ExitOnForwardFailure=yes -f -N \
    -L "${TRITON_LOCAL_HOST}:${TRITON_LOCAL_PORT}:${TRITON_REMOTE_HOST}:${TRITON_REMOTE_PORT}" \
    "$TRITON_SSH_HOST"
  wait_local_ready
}

run_ready() {
  ensure_tunnel
  local code
  code="$(local_ready)"
  printf "%s\n" "$code"
  [[ "$code" == "200" ]]
}

run_infer() {
  ensure_tunnel
  section "Triton Infer"
  TRITON_CLIENT_URL="$(triton_client_url)" \
  TRITON_INFER_TIMEOUT_SECONDS="$TRITON_INFER_TIMEOUT_SECONDS" \
  uv run python - <<'PY'
import os

import numpy as np
import tritonclient.http as httpclient

url = os.environ["TRITON_CLIENT_URL"]
timeout_seconds = float(os.environ["TRITON_INFER_TIMEOUT_SECONDS"])
client = httpclient.InferenceServerClient(
    url=url,
    connection_timeout=30,
    network_timeout=timeout_seconds,
)
print(f"server_ready={client.is_server_ready()}")
for model_name, row in [
    ("htdemucs_ft_drums", 0),
    ("htdemucs_ft_bass", 1),
    ("htdemucs_ft_other", 2),
    ("htdemucs_ft_vocals", 3),
]:
    model_input = np.zeros((1, 2, 343980), dtype=np.float32)
    infer_input = httpclient.InferInput("mix", model_input.shape, "FP32")
    infer_input.set_data_from_numpy(model_input)
    result = client.infer(
        model_name=model_name,
        model_version="1",
        inputs=[infer_input],
        outputs=[httpclient.InferRequestedOutput("stems")],
        timeout=int(timeout_seconds * 1_000_000),
    )
    output = result.as_numpy("stems")
    print(f"{model_name} shape={output.shape} dtype={output.dtype} target_row={row}")
PY
}

smoke_input_json() {
  if [[ -n "${AUDIO_STEM_REAL_FLOW_INPUT_JSON:-}" ]]; then
    printf "%s" "$AUDIO_STEM_REAL_FLOW_INPUT_JSON"
    return 0
  fi
  if [[ -n "${AUDIO_STEM_REAL_FLOW_INPUT_FILE:-}" ]]; then
    require_file "$AUDIO_STEM_REAL_FLOW_INPUT_FILE"
    uv run python - "$AUDIO_STEM_REAL_FLOW_INPUT_FILE" <<'PY'
import json
import sys
print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8")), separators=(",", ":")))
PY
    return 0
  fi
  die "set AUDIO_STEM_REAL_FLOW_INPUT_JSON or AUDIO_STEM_REAL_FLOW_INPUT_FILE for smoke" 2
}

run_smoke() {
  ensure_tunnel
  section "Job Platform Smoke"
  WORKER_SMOKE_SOURCE_TASK_NAME=audio_stem_separation_triton \
  WORKER_SMOKE_SOURCE_TASK_VERSION=1 \
  WORKER_SMOKE_TASK_NAME=worker_template_smoke.audio_stem_separation_triton \
  WORKER_SMOKE_INPUT_JSON="$(smoke_input_json)" \
  WORKER_SMOKE_EXPECT_OUTPUT_PATH=model_service \
  AUDIO_STEM_TRITON__URL="$(triton_local_base_url)" \
  "$ROOT_DIR/scripts/smoke-job-platform.sh" run
}

cmd="${1:-}"
case "$cmd" in
  check)
    shift
    if args_include_help "$@"; then usage; exit 0; fi
    reject_extra_args "usage: ./scripts/real-flow.sh check" "$@"
    run_check
    ;;
  tunnel)
    shift
    if args_include_help "$@"; then usage; exit 0; fi
    reject_extra_args "usage: ./scripts/real-flow.sh tunnel" "$@"
    ensure_tunnel
    ;;
  ready)
    shift
    if args_include_help "$@"; then usage; exit 0; fi
    reject_extra_args "usage: ./scripts/real-flow.sh ready" "$@"
    run_ready
    ;;
  infer)
    shift
    if args_include_help "$@"; then usage; exit 0; fi
    reject_extra_args "usage: ./scripts/real-flow.sh infer" "$@"
    run_infer
    ;;
  smoke)
    shift
    if args_include_help "$@"; then usage; exit 0; fi
    reject_extra_args "usage: ./scripts/real-flow.sh smoke" "$@"
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
