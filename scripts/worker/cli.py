from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import typer

from app.core.config import get_settings
from app.job_platform_worker.manifest import build_registry_from_manifest, load_worker_manifest, validate_manifest_runtime

ROOT_DIR = Path(__file__).resolve().parents[2]
ENTRYPOINT = "python -m app.job_platform_worker.runner"
DEFAULT_TAIL_LINES = 80
OVERVIEW_PREVIEW_LINES = 10

HELP_EPILOG = """\
职责:
  只读排障入口。查看 worker 状态、配置、manifest 和日志，不启动或停止服务。

副作用与保护边界:
  不创建 pid/meta/log 文件，不注册 manifest，不启动/停止本地或 Docker Worker。
  Worker 生命周期继续使用 ./scripts/dev.sh 或 ./scripts/deploy.sh。

常用示例:
  ./scripts/worker.sh status
  ./scripts/worker.sh config --json
  ./scripts/worker.sh manifest
  ./scripts/worker.sh logs --lines 80
  ./scripts/worker.sh doctor

Exit Codes:
  0  成功
  1  诊断完成但发现 worker 未运行、元数据或日志等关键证据缺失
  2  参数、配置或静态前置条件错误
  其他非 0 由 Python、Typer 或底层配置/manifest 校验透传
"""

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="只读 worker 排障入口。用于查看状态、配置、manifest 和日志，不启动或停止服务。",
    epilog=HELP_EPILOG,
)


def _rewrite_help_alias(argv: Sequence[str] | None) -> list[str]:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "help":
        return args
    if len(args) == 1:
        return ["--help"]
    return [args[1], "--help", *args[2:]]


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT_DIR / path


WORKER_META_CONFIG_KEYS = (
    "TASKIQ__BROKER_KIND",
    "TASKIQ__REDIS_URL",
    "TASKIQ__TASK_NAME",
    "TASKIQ__QUEUE_NAME",
    "WORKER__SERVICE_NAME",
    "WORKER__WORKER_NAME",
    "WORKER__WORKER_SESSION_ID",
    "WORKER__JOB_SERVICE_BASE_URL",
    "WORKER__MANIFEST_PATH",
)


def _launcher_env_file_path() -> Path:
    return _resolve_repo_path(os.environ.get("ENV_FILE", ".env"))


def _app_env_file_path() -> Path:
    return ROOT_DIR / ".env"


def _env_value(key: str) -> str | None:
    value = os.environ.get(key)
    if value is not None:
        return value
    path = _launcher_env_file_path()
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        current_key, current_value = stripped.split("=", 1)
        if current_key == key:
            value = current_value
    return value


def _run_dir() -> Path:
    return _resolve_repo_path(_env_value("RUN_DIR") or ".run")


def _log_dir() -> Path:
    return _resolve_repo_path(_env_value("LOG_DIR") or "logs")


def _tail_lines_default() -> int:
    value = _env_value("TAIL_LINES")
    if value is None:
        return DEFAULT_TAIL_LINES
    lines = int(value)
    if lines < 1:
        raise ValueError("TAIL_LINES must be greater than 0")
    return lines


def _worker_pid_file() -> Path:
    return _run_dir() / "worker.pid"


def _worker_meta_file() -> Path:
    return _run_dir() / "worker.meta"


def _worker_log_file() -> Path:
    return _log_dir() / "worker.log"


def _redact_value(key: str, value: str) -> str:
    upper_key = key.upper()
    if upper_key.endswith("_URL") or upper_key.endswith("__URL") or upper_key.endswith("BASE_URL"):
        return _masked_url(value)
    if any(token in upper_key for token in ("API_KEY", "SECRET", "PASSWORD", "TOKEN")):
        return "<redacted>" if value else ""
    return value


def _redact_mapping(values: dict[str, str]) -> dict[str, str]:
    return {key: _redact_value(key, value) for key, value in values.items()}


def _worker_meta_config() -> dict[str, str]:
    return {key: _env_value(key) or "" for key in WORKER_META_CONFIG_KEYS}


def _parse_key_value_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        if "=" not in line:
            raise ValueError(f"invalid metadata line {index} in {path}: missing '='")
        key, value = line.split("=", 1)
        if key in data:
            raise ValueError(f"duplicate metadata key {key!r} in {path}")
        data[key] = value
    return data


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_command(pid: int) -> str | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    command = result.stdout.strip()
    return command or None


def _file_summary(path: Path) -> dict[str, Any]:
    exists = path.exists()
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": exists,
    }
    if exists:
        stat = path.stat()
        summary["size_bytes"] = stat.st_size
        summary["modified_at"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    return summary


def _read_tail(path: Path, *, lines: int) -> list[str]:
    if lines < 1:
        raise ValueError("lines must be greater than 0")
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [line.rstrip("\n") for line in deque(handle, maxlen=lines)]


def _masked_url(url: str) -> str:
    parsed = urlsplit(url)
    netloc = parsed.netloc
    if parsed.password is not None:
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port is not None else ""
        username = f"{parsed.username}:***@" if parsed.username is not None else "***@"
        netloc = f"{username}{host}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _url_summary(url: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    return {
        "raw": _masked_url(url),
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "path": parsed.path,
        "username": parsed.username,
        "password_present": parsed.password is not None,
    }


def _meta_identity_issues(meta: dict[str, str] | None, pid: int) -> list[str]:
    if meta is None:
        return ["missing_meta"]
    issues: list[str] = []
    if meta.get("pid") != str(pid):
        issues.append("pid_mismatch")
    if meta.get("root_dir") != str(ROOT_DIR):
        issues.append("root_dir_mismatch")
    if meta.get("service") != "worker":
        issues.append("service_mismatch")
    return issues


def _meta_config_issues(meta: dict[str, str] | None) -> list[str]:
    if meta is None:
        return ["missing_meta"]
    current = _worker_meta_config()
    return [key for key, value in current.items() if meta.get(key) != value]


def _collect_status() -> dict[str, Any]:
    pid_file = _worker_pid_file()
    meta_file = _worker_meta_file()
    log_file = _worker_log_file()

    pid: int | None = None
    pid_value: str | None = None
    if pid_file.exists():
        pid_value = pid_file.read_text(encoding="utf-8").strip()
        if pid_value:
            pid = int(pid_value)

    meta = _parse_key_value_file(meta_file) if meta_file.exists() else None
    process_alive = pid is not None and _pid_running(pid)
    command = _process_command(pid) if pid is not None and process_alive else None
    command_matches = command is not None and "app.job_platform_worker.runner" in command
    identity_issues = _meta_identity_issues(meta, pid) if pid is not None else []
    config_issues = _meta_config_issues(meta) if pid is not None else []

    if pid is None:
        state = "stopped"
    elif not process_alive:
        state = "stale_pid"
    elif meta is None:
        state = "missing_metadata"
    elif command_matches:
        if identity_issues:
            state = "unowned_process"
        elif config_issues:
            state = "config_mismatch"
        else:
            state = "running"
    else:
        state = "unexpected_process"

    return {
        "kind": "worker_status",
        "state": state,
        "entrypoint": ENTRYPOINT,
        "pid": pid,
        "pid_value": pid_value,
        "command": command,
        "paths": {
            "pid_file": str(pid_file),
            "meta_file": str(meta_file),
            "log_file": str(log_file),
        },
        "meta": _redact_mapping(meta) if meta is not None else None,
        "ownership": {
            "command_matches": command_matches,
            "identity_issues": identity_issues,
            "config_issues": config_issues,
        },
        "log_file": _file_summary(log_file),
    }


def _collect_config() -> dict[str, Any]:
    settings = get_settings()
    manifest_path = _resolve_repo_path(settings.worker.manifest_path)
    return {
        "kind": "worker_config",
        "runtime": {
            "root_dir": str(ROOT_DIR),
            "launcher_env_file": str(_launcher_env_file_path()),
            "app_env_file": str(_app_env_file_path()),
            "run_dir": str(_run_dir()),
            "log_dir": str(_log_dir()),
            "tail_lines": _tail_lines_default(),
        },
        "worker": {
            "service_name": settings.worker.service_name,
            "worker_name": settings.worker.worker_name,
            "worker_session_id": settings.worker.worker_session_id,
            "job_service_base_url": _url_summary(settings.worker.job_service_base_url),
            "job_service_api_key_present": bool(settings.worker.job_service_api_key_value),
            "job_service_registry_api_key_present": bool(settings.worker.job_service_registry_api_key_value),
            "manifest_path": str(manifest_path),
        },
        "taskiq": {
            "broker_kind": settings.taskiq.broker_kind,
            "redis_url": _url_summary(settings.taskiq.redis_url),
            "task_name": settings.taskiq.task_name,
            "queue_name": settings.taskiq.queue_name,
        },
        "redis": {
            "enabled": settings.redis.enabled,
            "url": _url_summary(settings.redis.url),
        },
        "database": {
            "url": _url_summary(settings.database.url),
            "ssl": settings.database.ssl,
            "pool_size": settings.database.pool_size,
            "max_overflow": settings.database.max_overflow,
        },
        "storage": {
            "backend": settings.storage.backend,
            "local_path": settings.storage.local_path,
            "bucket": settings.storage.bucket,
            "region": settings.storage.region,
        },
    }


def _collect_manifest(*, validate_handlers: bool) -> dict[str, Any]:
    settings = get_settings()
    manifest_path = _resolve_repo_path(settings.worker.manifest_path)
    manifest = load_worker_manifest(manifest_path)
    validate_manifest_runtime(
        manifest,
        worker_service=settings.worker.service_name,
        queue_name=settings.taskiq.queue_name,
    )
    if validate_handlers:
        build_registry_from_manifest(manifest)
    return {
        "kind": "worker_manifest",
        "path": str(manifest_path),
        "manifest_version": manifest.manifest_version,
        "worker_service": manifest.worker_service,
        "queue_name": manifest.queue_name,
        "capabilities": list(manifest.capabilities),
        "task_count": len(manifest.tasks),
        "handlers_validated": validate_handlers,
        "tasks": [
            {
                "task_name": task.task_name,
                "task_version": task.task_version,
                "handler": task.handler,
                "required_worker_capabilities": list(task.required_worker_capabilities),
                "caller_services": [binding.caller_service for binding in task.caller_bindings],
            }
            for task in manifest.tasks
        ],
    }


def _collect_logs(*, lines: int) -> dict[str, Any]:
    log_file = _worker_log_file()
    return {
        "kind": "worker_logs",
        "lines_requested": lines,
        "file": _file_summary(log_file),
        "tail": _read_tail(log_file, lines=lines),
    }


def _collect_overview() -> dict[str, Any]:
    return {
        "kind": "worker_overview",
        "status": _collect_status(),
        "config": _collect_config(),
        "manifest": _collect_manifest(validate_handlers=True),
        "logs": _collect_logs(lines=OVERVIEW_PREVIEW_LINES),
    }


def _doctor_checks(status: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": "worker_process",
            "ok": status["state"] == "running",
            "detail": f"state={status['state']}",
        },
        {
            "name": "metadata_file",
            "ok": status["meta"] is not None,
            "detail": status["paths"]["meta_file"],
        },
        {
            "name": "log_file",
            "ok": bool(status["log_file"]["exists"]),
            "detail": status["paths"]["log_file"],
        },
        {
            "name": "manifest_runtime",
            "ok": True,
            "detail": f"{manifest['worker_service']} -> {manifest['queue_name']}",
        },
        {
            "name": "manifest_handlers",
            "ok": bool(manifest["handlers_validated"]),
            "detail": manifest["path"],
        },
    ]


def _collect_doctor() -> tuple[dict[str, Any], int]:
    status = _collect_status()
    manifest = _collect_manifest(validate_handlers=True)
    checks = _doctor_checks(status, manifest)
    ok = all(check["ok"] for check in checks)
    return (
        {
            "kind": "worker_doctor",
            "ok": ok,
            "status": status,
            "manifest": manifest,
            "checks": checks,
        },
        0 if ok else 1,
    )


def _emit_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))


def _format_url_block(name: str, payload: dict[str, Any]) -> list[str]:
    return [
        f"{name}:",
        f"  raw: {payload['raw']}",
        f"  host: {payload['host']}",
        f"  port: {payload['port']}",
        f"  username: {payload['username']}",
        f"  password_present: {payload['password_present']}",
    ]


def _format_status(payload: dict[str, Any]) -> str:
    lines = [
        "== Worker Status ==",
        f"state: {payload['state']}",
        f"entrypoint: {payload['entrypoint']}",
        f"pid: {payload['pid']}",
        f"command: {payload['command']}",
        f"pid_file: {payload['paths']['pid_file']}",
        f"meta_file: {payload['paths']['meta_file']}",
        f"log_file: {payload['paths']['log_file']}",
        f"log_exists: {payload['log_file']['exists']}",
        f"command_matches: {payload['ownership']['command_matches']}",
        f"identity_issues: {', '.join(payload['ownership']['identity_issues']) or '-'}",
        f"config_issues: {', '.join(payload['ownership']['config_issues']) or '-'}",
    ]
    if payload["meta"] is not None:
        lines.append("meta:")
        lines.extend(f"  {key}: {value}" for key, value in payload["meta"].items())
    return "\n".join(lines)


def _format_config(payload: dict[str, Any]) -> str:
    lines = [
        "== Worker Config ==",
        f"root_dir: {payload['runtime']['root_dir']}",
        f"launcher_env_file: {payload['runtime']['launcher_env_file']}",
        f"app_env_file: {payload['runtime']['app_env_file']}",
        f"run_dir: {payload['runtime']['run_dir']}",
        f"log_dir: {payload['runtime']['log_dir']}",
        f"tail_lines: {payload['runtime']['tail_lines']}",
        "worker:",
        f"  service_name: {payload['worker']['service_name']}",
        f"  worker_name: {payload['worker']['worker_name']}",
        f"  worker_session_id: {payload['worker']['worker_session_id']}",
        f"  job_service_base_url: {payload['worker']['job_service_base_url']['raw']}",
        f"  job_service_api_key_present: {payload['worker']['job_service_api_key_present']}",
        f"  job_service_registry_api_key_present: {payload['worker']['job_service_registry_api_key_present']}",
        f"  manifest_path: {payload['worker']['manifest_path']}",
        "taskiq:",
        f"  broker_kind: {payload['taskiq']['broker_kind']}",
        f"  task_name: {payload['taskiq']['task_name']}",
        f"  queue_name: {payload['taskiq']['queue_name']}",
        "redis:",
    ]
    lines.extend(f"  {line}" for line in _format_url_block("url", payload["redis"]["url"]))
    lines.append("database:")
    lines.extend(f"  {line}" for line in _format_url_block("url", payload["database"]["url"]))
    lines.append(f"  ssl: {payload['database']['ssl']}")
    lines.append(f"  pool_size: {payload['database']['pool_size']}")
    lines.append(f"  max_overflow: {payload['database']['max_overflow']}")
    lines.append("storage:")
    lines.append(f"  backend: {payload['storage']['backend']}")
    lines.append(f"  local_path: {payload['storage']['local_path']}")
    lines.append(f"  bucket: {payload['storage']['bucket']}")
    lines.append(f"  region: {payload['storage']['region']}")
    return "\n".join(lines)


def _format_manifest(payload: dict[str, Any]) -> str:
    capability_text = ", ".join(payload["capabilities"]) if payload["capabilities"] else "-"
    lines = [
        "== Worker Manifest ==",
        f"path: {payload['path']}",
        f"manifest_version: {payload['manifest_version']}",
        f"worker_service: {payload['worker_service']}",
        f"queue_name: {payload['queue_name']}",
        f"capabilities: {capability_text}",
        f"task_count: {payload['task_count']}",
        f"handlers_validated: {payload['handlers_validated']}",
        "tasks:",
    ]
    for task in payload["tasks"]:
        lines.append(f"  - {task['task_name']}@v{task['task_version']} -> {task['handler']}")
    return "\n".join(lines)


def _format_logs(payload: dict[str, Any]) -> str:
    lines = [
        "== Worker Logs ==",
        f"path: {payload['file']['path']}",
        f"exists: {payload['file']['exists']}",
        f"lines_requested: {payload['lines_requested']}",
        "tail:",
    ]
    if payload["tail"]:
        lines.extend(f"  {line}" for line in payload["tail"])
    else:
        lines.append("  <empty>")
    return "\n".join(lines)


def _format_overview(payload: dict[str, Any]) -> str:
    lines: list[str] = ["== Worker Overview =="]
    lines.append(_format_status(payload["status"]))
    lines.append("")
    lines.append(_format_config(payload["config"]))
    lines.append("")
    lines.append(_format_manifest(payload["manifest"]))
    lines.append("")
    lines.append(_format_logs(payload["logs"]))
    return "\n".join(lines)


def _format_doctor(payload: dict[str, Any]) -> str:
    lines = [
        "== Worker Doctor ==",
        f"ok: {payload['ok']}",
        "checks:",
    ]
    for check in payload["checks"]:
        lines.append(f"  {'OK' if check['ok'] else 'ISSUE'} {check['name']}: {check['detail']}")
    lines.append("")
    lines.append(_format_status(payload["status"]))
    return "\n".join(lines)


def _emit(payload: dict[str, Any], *, json_output: bool, formatter: Callable[[dict[str, Any]], str]) -> None:
    if json_output:
        _emit_json(payload)
        return
    typer.echo(formatter(payload))


@app.command()
def overview(
    json_output: bool = typer.Option(False, "--json", help="输出单个 JSON 文档。"),
) -> None:
    """汇总 worker 状态、配置、manifest 和日志预览。"""
    payload = _collect_overview()
    _emit(payload, json_output=json_output, formatter=_format_overview)


@app.command()
def status(
    json_output: bool = typer.Option(False, "--json", help="输出单个 JSON 文档。"),
) -> None:
    """查看 worker 进程、pid/meta/log 路径与当前命令行。"""
    payload = _collect_status()
    _emit(payload, json_output=json_output, formatter=_format_status)


@app.command()
def config(
    json_output: bool = typer.Option(False, "--json", help="输出单个 JSON 文档。"),
) -> None:
    """查看 worker 相关配置摘要，不输出密钥明文。"""
    payload = _collect_config()
    _emit(payload, json_output=json_output, formatter=_format_config)


@app.command()
def manifest(
    json_output: bool = typer.Option(False, "--json", help="输出单个 JSON 文档。"),
) -> None:
    """读取并验证 worker manifest 和 handler 导入。"""
    payload = _collect_manifest(validate_handlers=True)
    _emit(payload, json_output=json_output, formatter=_format_manifest)


@app.command()
def logs(
    lines: int | None = typer.Option(None, "--lines", min=1, help="读取最近 N 行日志；默认读取 TAIL_LINES 或 80。"),
    json_output: bool = typer.Option(False, "--json", help="输出单个 JSON 文档。"),
) -> None:
    """读取 worker 日志尾部，不创建缺失日志文件。"""
    payload = _collect_logs(lines=lines if lines is not None else _tail_lines_default())
    _emit(payload, json_output=json_output, formatter=_format_logs)


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="输出单个 JSON 文档。"),
) -> None:
    """执行只读诊断；当 worker 未运行或关键文件缺失时返回 1。"""
    payload, exit_code = _collect_doctor()
    _emit(payload, json_output=json_output, formatter=_format_doctor)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def main(argv: Sequence[str] | None = None) -> int:
    args = _rewrite_help_alias(argv)
    try:
        app(args=args, prog_name="./scripts/worker.sh", standalone_mode=True)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        raise
    return 0
