import subprocess
from pathlib import Path
import json
import os
import shutil
import socket
import sys
import time

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
    )


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_tcp_port(port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.1)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError(f"port did not open: {port}")


def write_fake_worker_uv(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "fake-worker-python"
    fake_python.write_text(
        """#!/usr/bin/env sh
if [ "$1" = "-m" ] && [ "$2" = "app.job_platform_worker.runner" ]; then
  while :; do sleep 1; done
fi
exit 2
"""
    )
    fake_python.chmod(0o755)

    uv = bin_dir / "uv"
    uv.write_text(
        """#!/usr/bin/env sh
if [ "$1" = "--version" ]; then
  echo "uv 0.0.0-test"
  exit 0
fi
if [ "$1" = "run" ] && [ "$2" = "python" ] && [ "$3" = "-m" ] && [ "$4" = "app.job_platform_worker.register_cli" ]; then
  exit 0
fi
if [ "$1" = "run" ] && [ "$2" = "python" ] && [ "$3" = "-c" ]; then
  echo "$FAKE_WORKER_PYTHON"
  exit 0
fi
if [ "$1" = "run" ] && [ "$2" = "python" ]; then
  shift 2
  exec "$REAL_PYTHON" "$@"
fi
exit 2
"""
    )
    uv.chmod(0o755)
    return bin_dir


def script_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "RUN_DIR": str(tmp_path / "run"),
            "LOG_DIR": str(tmp_path / "logs"),
            "API_HOST": "127.0.0.1",
            **overrides,
        }
    )
    return env


def test_script_help_commands_work():
    for script in (
        "./scripts/dev.sh",
        "./scripts/deploy.sh",
        "./scripts/k8s.sh",
        "./scripts/verify.sh",
        "./scripts/smoke-job-platform.sh",
        "./scripts/tools.sh",
    ):
        result = run_script(script, "help")
        assert result.returncode == 0
        assert "Usage:" in result.stdout
        assert "Exit Codes:" in result.stdout


def test_script_unknown_command_fails():
    result = run_script("./scripts/verify.sh", "missing")

    assert result.returncode == 2
    assert "unknown command" in result.stderr


def test_smoke_job_platform_unknown_command_fails():
    result = run_script("./scripts/smoke-job-platform.sh", "missing")

    assert result.returncode == 2
    assert "unknown command" in result.stderr


def test_smoke_job_platform_script_does_not_depend_on_first_manifest_task():
    body = (ROOT_DIR / "scripts" / "smoke-job-platform.sh").read_text(encoding="utf-8")

    assert 'manifest["tasks"][0]' not in body
    assert "data.output.worker" not in body
    assert "WORKER_SMOKE_SOURCE_TASK_NAME" in body
    assert "WORKER_SMOKE_INPUT_JSON" in body


def test_script_unexpected_argument_fails():
    result = run_script("./scripts/dev.sh", "status", "api", "extra")

    assert result.returncode == 2
    assert "unexpected argument" in result.stderr


def test_verify_subcommand_help_does_not_execute_task():
    result = run_script("./scripts/verify.sh", "postgres", "--help")

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "专用 PostgreSQL _test 数据库" in result.stdout
    assert "OK test-database" not in result.stdout


def test_verify_job_platform_smoke_help_does_not_execute_task():
    result = run_script("./scripts/verify.sh", "job-platform-smoke", "--help")

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "跨仓 smoke" in result.stdout
    assert "Smoke Prerequisites" not in result.stdout


def test_verify_postgres_rejects_non_test_database_with_config_exit_code():
    result = run_script(
        "env",
        "DATABASE__URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:25435/tasks_worker_service",
        "./scripts/verify.sh",
        "postgres",
    )

    assert result.returncode == 2
    assert "requires *_test database" in result.stderr


def test_migration_roundtrip_help_does_not_execute_task():
    result = run_script("./scripts/verify.sh", "migration-roundtrip", "--help")

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "upgrade head -> downgrade base -> upgrade head" in result.stdout
    assert "OK        upgrade" not in result.stdout


def test_k8s_check_requires_pod_environment():
    result = run_script("./scripts/k8s.sh", "check", "config")

    assert result.returncode == 2
    assert "must run inside a K8s Pod" in result.stderr


def test_k8s_subcommand_help_does_not_execute_task():
    check = run_script("./scripts/k8s.sh", "check", "--help")
    migrate = run_script("./scripts/k8s.sh", "migrate", "--help")

    assert check.returncode == 0
    assert "check <config|postgres|app>" in check.stdout
    assert "KUBERNETES_SERVICE_HOST" not in check.stderr
    assert migrate.returncode == 0
    assert "migrate --confirm" in migrate.stdout
    assert "requires --confirm" not in migrate.stderr


def test_k8s_script_does_not_call_kubectl():
    body = (ROOT_DIR / "scripts" / "k8s.sh").read_text(encoding="utf-8")
    non_example_lines = [
        line
        for line in body.splitlines()
        if "kubectl" in line and "kubectl exec" not in line and "不调用 kubectl" not in line
    ]

    assert non_example_lines == []


def test_k8s_check_config_uses_application_settings(tmp_path):
    result = subprocess.run(
        ["./scripts/k8s.sh", "check", "config"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(
            tmp_path,
            KUBERNETES_SERVICE_HOST="10.96.0.1",
            DATABASE__URL="postgresql+asyncpg://postgres:secret@postgres.default.svc:5432/tasks_worker_service",
            REDIS__URL="redis://redis.default.svc:6379/0",
            REDIS__ENABLED="true",
            STORAGE__BACKEND="disabled",
        ),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "== K8s Config ==" in result.stdout
    assert "host=postgres.default.svc" in result.stdout
    assert "password_present=true" in result.stdout
    assert "secret" not in result.stdout
    assert "OK config" in result.stdout


def test_k8s_check_postgres_rejects_non_postgres_url_with_config_exit_code(tmp_path):
    result = subprocess.run(
        ["./scripts/k8s.sh", "check", "postgres"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(
            tmp_path,
            KUBERNETES_SERVICE_HOST="10.96.0.1",
            DATABASE__URL="sqlite+aiosqlite:///:memory:",
        ),
    )

    assert result.returncode == 2
    assert "must be PostgreSQL" in result.stderr


def test_k8s_migrate_requires_confirm_before_runtime_checks(tmp_path):
    result = subprocess.run(
        ["./scripts/k8s.sh", "migrate"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(tmp_path, KUBERNETES_SERVICE_HOST="10.96.0.1"),
    )

    assert result.returncode == 2
    assert "requires --confirm" in result.stderr


def test_k8s_migrate_confirm_dispatches_alembic(tmp_path):
    root = tmp_path / "root"
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "alembic.log"
    root.mkdir()
    bin_dir.mkdir()
    alembic = bin_dir / "alembic"
    alembic.write_text(
        f"""#!/usr/bin/env sh
echo "$@" >> "{log_file}"
exit 0
"""
    )
    alembic.chmod(0o755)

    result = subprocess.run(
        ["./scripts/k8s.sh", "migrate", "--confirm"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(
            tmp_path,
            KUBERNETES_SERVICE_HOST="10.96.0.1",
            ROOT_DIR=str(root),
            PATH=f"{bin_dir}:{os.environ['PATH']}",
        ),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "RUN" in result.stdout
    assert log_file.read_text().strip() == "upgrade head"


def test_dev_ports_help_does_not_require_json_execution():
    result = run_script("./scripts/dev.sh", "ports", "--help")

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "--json" in result.stdout


def test_dev_doctor_smoke():
    result = run_script("./scripts/dev.sh", "doctor")

    assert result.returncode == 0
    assert "== Tools ==" in result.stdout
    assert "api_port" in result.stdout


def test_dev_ports_json_is_machine_readable():
    result = run_script("./scripts/dev.sh", "ports", "1", "--json", "--allow-busy")

    assert result.returncode == 0
    body = json.loads(result.stdout)
    assert body["kind"] == "local_port_scan"
    assert body["checks"][0]["port"] == 1


def test_stale_pid_file_does_not_kill_unowned_process(tmp_path):
    sleeper = subprocess.Popen(["sleep", "5"])
    try:
        run_dir = tmp_path / "run"
        log_dir = tmp_path / "logs"
        run_dir.mkdir()
        log_dir.mkdir()
        (run_dir / "api.pid").write_text(str(sleeper.pid))

        result = subprocess.run(
            ["./scripts/dev.sh", "stop", "api"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env={"RUN_DIR": str(run_dir), "LOG_DIR": str(log_dir), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        )

        assert result.returncode == 0
        assert "STALE" in result.stdout
        assert sleeper.poll() is None
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=5)


def test_stop_without_target_defaults_to_api(tmp_path):
    result = subprocess.run(
        ["./scripts/dev.sh", "stop"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(tmp_path),
    )

    assert result.returncode == 0
    assert "STOPPED" in result.stdout


def test_stop_and_restart_reject_unknown_target(tmp_path):
    stop = subprocess.run(
        ["./scripts/dev.sh", "stop", "database"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(tmp_path),
    )
    restart = subprocess.run(
        ["./scripts/dev.sh", "restart", "database"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(tmp_path),
    )

    assert stop.returncode == 2
    assert "stop [api|worker|all]" in stop.stderr
    assert restart.returncode == 2
    assert "restart [api|worker]" in restart.stderr


def test_start_status_logs_stop_worker_lifecycle(tmp_path):
    if not shutil.which("lsof"):
        pytest.skip("lsof is required by dev.sh worker ownership checks")
    bin_dir = write_fake_worker_uv(tmp_path)
    env = script_env(
        tmp_path,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        REAL_PYTHON=sys.executable,
        FAKE_WORKER_PYTHON=str(bin_dir / "fake-worker-python"),
    )

    try:
        start = subprocess.run(
            ["./scripts/dev.sh", "start", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert start.returncode == 0, start.stdout + start.stderr
        assert "STARTED" in start.stdout
        worker_pid = (tmp_path / "run" / "worker.pid").read_text().strip()
        worker_meta = (tmp_path / "run" / "worker.meta").read_text()
        assert f"pid={worker_pid}" in worker_meta
        assert "service=worker" in worker_meta
        assert (tmp_path / "logs" / "worker.log").exists()

        status = subprocess.run(
            ["./scripts/dev.sh", "status", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert status.returncode == 0
        assert "== Worker ==" in status.stdout
        assert "running" in status.stdout

        logs = subprocess.run(
            ["./scripts/dev.sh", "logs", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert logs.returncode == 0
    finally:
        subprocess.run(
            ["./scripts/dev.sh", "stop", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )


def test_start_worker_restarts_owned_process_when_worker_config_changes(tmp_path):
    if not shutil.which("lsof"):
        pytest.skip("lsof is required by dev.sh worker ownership checks")
    bin_dir = write_fake_worker_uv(tmp_path)
    first_env = script_env(
        tmp_path,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        REAL_PYTHON=sys.executable,
        FAKE_WORKER_PYTHON=str(bin_dir / "fake-worker-python"),
        TASKIQ__QUEUE_NAME="job.first.v1",
    )
    second_env = {
        **first_env,
        "TASKIQ__QUEUE_NAME": "job.second.v1",
    }
    old_pid = ""

    try:
        first = subprocess.run(
            ["./scripts/dev.sh", "start", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=first_env,
        )
        assert first.returncode == 0, first.stdout + first.stderr
        old_pid = (tmp_path / "run" / "worker.pid").read_text().strip()
        assert "TASKIQ__QUEUE_NAME=job.first.v1" in (tmp_path / "run" / "worker.meta").read_text()

        second = subprocess.run(
            ["./scripts/dev.sh", "start", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=second_env,
        )
        assert second.returncode == 0, second.stdout + second.stderr
        assert "STOPPED" in second.stdout
        assert "STARTED" in second.stdout
        new_pid = (tmp_path / "run" / "worker.pid").read_text().strip()
        assert new_pid != old_pid
        assert "TASKIQ__QUEUE_NAME=job.second.v1" in (tmp_path / "run" / "worker.meta").read_text()
        assert subprocess.run(["ps", "-p", old_pid], check=False, capture_output=True).returncode != 0
    finally:
        subprocess.run(
            ["./scripts/dev.sh", "stop", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=second_env,
        )
        if old_pid:
            subprocess.run(["kill", old_pid], check=False, capture_output=True)


def test_deploy_down_compose_deps_rejects_running_worker_even_when_config_changes(tmp_path):
    if not shutil.which("lsof"):
        pytest.skip("lsof is required by dev.sh worker ownership checks")
    bin_dir = write_fake_worker_uv(tmp_path)
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env sh
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$1" = "ps" ]; then
  exit 0
fi
if [ "$1" = "compose" ]; then
  echo "unexpected compose stop" >&2
  exit 0
fi
exit 1
"""
    )
    docker.chmod(0o755)
    first_env = script_env(
        tmp_path,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        REAL_PYTHON=sys.executable,
        FAKE_WORKER_PYTHON=str(bin_dir / "fake-worker-python"),
        TASKIQ__QUEUE_NAME="job.first.v1",
    )
    second_env = {
        **first_env,
        "TASKIQ__QUEUE_NAME": "job.second.v1",
    }

    try:
        start = subprocess.run(
            ["./scripts/dev.sh", "start", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=first_env,
        )
        assert start.returncode == 0, start.stdout + start.stderr

        result = subprocess.run(
            ["./scripts/deploy.sh", "down", "compose-deps"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=second_env,
        )

        assert result.returncode == 4
        assert "local worker is running" in result.stderr
        assert "unexpected compose stop" not in result.stderr
    finally:
        subprocess.run(
            ["./scripts/dev.sh", "stop", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=first_env,
        )


def test_deploy_down_dev_stops_api_before_worker_blocks_deps(tmp_path):
    if not shutil.which("lsof"):
        pytest.skip("lsof is required by dev.sh worker ownership checks")
    bin_dir = write_fake_worker_uv(tmp_path)
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env sh
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$1" = "ps" ]; then
  exit 0
fi
if [ "$1" = "compose" ]; then
  echo "unexpected compose stop" >&2
  exit 0
fi
exit 1
"""
    )
    docker.chmod(0o755)
    env = script_env(
        tmp_path,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        REAL_PYTHON=sys.executable,
        FAKE_WORKER_PYTHON=str(bin_dir / "fake-worker-python"),
    )

    try:
        start = subprocess.run(
            ["./scripts/dev.sh", "start", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert start.returncode == 0, start.stdout + start.stderr

        result = subprocess.run(
            ["./scripts/deploy.sh", "down", "dev"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

        assert result.returncode == 4
        assert "RUN       local" in result.stdout
        assert "STOPPED   api" in result.stdout
        assert "local worker is running" in result.stderr
        assert "unexpected compose stop" not in result.stderr
    finally:
        subprocess.run(
            ["./scripts/dev.sh", "stop", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )


def test_stale_worker_pid_file_does_not_kill_unowned_process(tmp_path):
    sleeper = subprocess.Popen(["sleep", "5"])
    try:
        run_dir = tmp_path / "run"
        log_dir = tmp_path / "logs"
        run_dir.mkdir()
        log_dir.mkdir()
        (run_dir / "worker.pid").write_text(str(sleeper.pid))

        result = subprocess.run(
            ["./scripts/dev.sh", "stop", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env={"RUN_DIR": str(run_dir), "LOG_DIR": str(log_dir), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        )

        assert result.returncode == 0
        assert "STALE" in result.stdout
        assert sleeper.poll() is None
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=5)


def test_start_worker_rejects_unmanaged_repo_worker_process(tmp_path):
    if not shutil.which("lsof"):
        pytest.skip("lsof is required by dev.sh worker ownership checks")
    bin_dir = write_fake_worker_uv(tmp_path)
    env = script_env(
        tmp_path,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        REAL_PYTHON=sys.executable,
        FAKE_WORKER_PYTHON=str(bin_dir / "fake-worker-python"),
    )
    unmanaged = subprocess.Popen(
        [str(bin_dir / "fake-worker-python"), "-m", "app.job_platform_worker.runner"],
        cwd=ROOT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.2)

        result = subprocess.run(
            ["./scripts/dev.sh", "start", "worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

        assert result.returncode == 4
        assert "worker process already exists" in result.stderr
        assert str(unmanaged.pid) in result.stderr
        assert unmanaged.poll() is None
    finally:
        unmanaged.terminate()
        unmanaged.wait(timeout=5)


def test_start_worker_rejects_running_compose_worker(tmp_path):
    bin_dir = write_fake_worker_uv(tmp_path)
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env sh
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$1" = "ps" ]; then
  case "$*" in
    *"com.docker.compose.service=worker"*) echo "tasks-worker-service-worker-1"; exit 0 ;;
    *) exit 0 ;;
  esac
fi
exit 1
"""
    )
    docker.chmod(0o755)
    env = script_env(
        tmp_path,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        REAL_PYTHON=sys.executable,
        FAKE_WORKER_PYTHON=str(bin_dir / "fake-worker-python"),
    )

    result = subprocess.run(
        ["./scripts/dev.sh", "start", "worker"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 4
    assert "compose worker is running" in result.stderr


def test_stale_pid_with_matching_command_but_wrong_cwd_is_not_killed(tmp_path):
    sleeper = subprocess.Popen(
        ["bash", "-c", 'exec -a "uvicorn app.main:app" sleep 5'],
        cwd=tmp_path,
    )
    try:
        run_dir = tmp_path / "run"
        log_dir = tmp_path / "logs"
        run_dir.mkdir()
        log_dir.mkdir()
        (run_dir / "api.pid").write_text(str(sleeper.pid))
        (run_dir / "api.meta").write_text(f"root_dir={ROOT_DIR}\nservice=api\n")

        result = subprocess.run(
            ["./scripts/dev.sh", "stop", "api"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env={"RUN_DIR": str(run_dir), "LOG_DIR": str(log_dir), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        )

        assert result.returncode == 0
        assert "STALE" in result.stdout
        assert sleeper.poll() is None
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=5)


def test_start_status_stop_api_lifecycle(tmp_path):
    if not shutil.which("curl"):
        pytest.skip("curl is required by dev.sh start api")
    port = unused_port()
    env = script_env(tmp_path, API_PORT=str(port))

    try:
        start = subprocess.run(
            ["./scripts/dev.sh", "start", "api"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert start.returncode == 0, start.stdout + start.stderr
        assert "STARTED" in start.stdout
        assert "READY" in start.stdout

        status = subprocess.run(
            ["./scripts/dev.sh", "status"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert status.returncode == 0
        assert "running" in status.stdout
        assert (tmp_path / "run" / "api.pid").read_text().strip()
        assert "pid=" in (tmp_path / "run" / "api.meta").read_text()
        assert (tmp_path / "logs" / "api.log").exists()
    finally:
        subprocess.run(
            ["./scripts/dev.sh", "stop", "api"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )


def test_start_api_restarts_owned_process_when_api_url_changes(tmp_path):
    if not shutil.which("curl"):
        pytest.skip("curl is required by dev.sh start api")
    first_port = unused_port()
    second_port = unused_port()
    first_env = script_env(tmp_path, API_PORT=str(first_port))
    second_env = script_env(tmp_path, API_PORT=str(second_port))
    old_pid = ""

    try:
        first = subprocess.run(
            ["./scripts/dev.sh", "start", "api"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=first_env,
        )
        assert first.returncode == 0, first.stdout + first.stderr
        old_pid = (tmp_path / "run" / "api.pid").read_text().strip()
        assert f"url=http://127.0.0.1:{first_port}" in (tmp_path / "run" / "api.meta").read_text()

        second = subprocess.run(
            ["./scripts/dev.sh", "start", "api"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=second_env,
        )
        assert second.returncode == 0, second.stdout + second.stderr
        assert "STOPPED" in second.stdout
        assert "STARTED" in second.stdout
        new_pid = (tmp_path / "run" / "api.pid").read_text().strip()
        assert new_pid != old_pid
        assert f"url=http://127.0.0.1:{second_port}" in (tmp_path / "run" / "api.meta").read_text()
        assert subprocess.run(["ps", "-p", old_pid], check=False, capture_output=True).returncode != 0
    finally:
        subprocess.run(
            ["./scripts/dev.sh", "stop", "api"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=second_env,
        )
        if old_pid:
            subprocess.run(["kill", old_pid], check=False, capture_output=True)


def test_restart_without_target_defaults_to_api(tmp_path):
    if not shutil.which("curl"):
        pytest.skip("curl is required by dev.sh restart")
    port = unused_port()
    env = script_env(tmp_path, API_PORT=str(port))

    try:
        restart = subprocess.run(
            ["./scripts/dev.sh", "restart"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

        assert restart.returncode == 0, restart.stdout + restart.stderr
        assert "STOPPED" in restart.stdout
        assert "STARTED" in restart.stdout
        assert "READY" in restart.stdout
    finally:
        subprocess.run(
            ["./scripts/dev.sh", "stop"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )


def test_start_api_rejects_stale_pid_that_owns_port(tmp_path):
    if not shutil.which("lsof"):
        pytest.skip("lsof is required to identify the port owner pid")
    port = unused_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_tcp_port(port)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (run_dir / "api.pid").write_text(str(server.pid))
        (run_dir / "api.meta").write_text(f"pid={server.pid}\nroot_dir={ROOT_DIR}\nservice=api\n")

        result = subprocess.run(
            ["./scripts/dev.sh", "start", "api"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=script_env(tmp_path, API_PORT=str(port)),
        )

        assert result.returncode == 4
        assert "already used" in result.stderr
        assert server.poll() is None
    finally:
        server.terminate()
        server.wait(timeout=5)


def test_run_api_rejects_busy_port_before_uvicorn(tmp_path):
    if not shutil.which("lsof"):
        pytest.skip("lsof is required to identify the port owner pid")
    port = unused_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_tcp_port(port)

        result = subprocess.run(
            ["./scripts/dev.sh", "run"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=script_env(tmp_path, API_PORT=str(port)),
        )

        assert result.returncode == 4
        assert "already used" in result.stderr
        assert "uvicorn" not in result.stderr
        assert server.poll() is None
    finally:
        server.terminate()
        server.wait(timeout=5)


def test_run_api_rejects_repo_owned_background_api_port(tmp_path):
    if not shutil.which("curl") or not shutil.which("lsof"):
        pytest.skip("curl and lsof are required by dev.sh start api")
    port = unused_port()
    env = script_env(tmp_path, API_PORT=str(port))

    try:
        start = subprocess.run(
            ["./scripts/dev.sh", "start", "api"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert start.returncode == 0, start.stdout + start.stderr

        result = subprocess.run(
            ["./scripts/dev.sh", "run"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

        assert result.returncode == 4
        assert "stop it before ./scripts/dev.sh run" in result.stderr
        assert "uvicorn" not in result.stderr
    finally:
        subprocess.run(
            ["./scripts/dev.sh", "stop", "api"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )


def test_migrate_rejects_remote_host_before_alembic():
    result = run_script(
        "env",
        "DATABASE__URL=postgresql+asyncpg://postgres:postgres@prod-localhost.example:5432/app",
        "./scripts/dev.sh",
        "migrate",
    )

    assert result.returncode == 3
    assert "does not look local" in result.stderr


def test_top_level_requires_command():
    result = run_script("./scripts/dev.sh")

    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_deploy_modes_smoke():
    result = run_script("./scripts/deploy.sh", "modes")

    assert result.returncode == 0
    assert "local" in result.stdout
    assert "compose-deps" in result.stdout
    assert "compose-worker" in result.stdout
    assert "compose-full" in result.stdout


def test_deploy_local_status_delegates_to_dev_status():
    result = run_script("./scripts/deploy.sh", "status", "local")

    assert result.returncode == 0
    assert "== API ==" in result.stdout


def test_deploy_compose_subcommand_help():
    result = run_script("./scripts/deploy.sh", "up", "--help")

    assert result.returncode == 0
    assert "compose-deps" in result.stdout
    assert "compose-worker" in result.stdout
    assert "compose-full" in result.stdout


def test_deploy_down_without_mode_requires_explicit_target(tmp_path):
    result = subprocess.run(
        ["./scripts/deploy.sh", "down"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(tmp_path),
    )

    assert result.returncode == 2
    assert "usage: ./scripts/deploy.sh down <dev|dev-worker|local|worker|compose-deps|compose-worker|compose-full|all>" in result.stderr
    assert result.stdout == ""


def test_deploy_down_all_stops_local_then_compose_once(tmp_path):
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "calls.log"
    bin_dir.mkdir()

    docker = bin_dir / "docker"
    docker.write_text(
        f"""#!/usr/bin/env sh
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$1" = "ps" ]; then
  exit 0
fi
if [ "$1" = "compose" ]; then
  echo "docker $@" >> "{log_file}"
  exit 0
fi
exit 1
"""
    )
    docker.chmod(0o755)

    result = subprocess.run(
        ["./scripts/deploy.sh", "down", "all"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(
            tmp_path,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
        ),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Deploy Down All" in result.stdout
    assert "STOPPED" in result.stdout
    calls = log_file.read_text().splitlines()
    assert len(calls) == 1
    assert "--profile app --profile worker stop api worker postgres redis" in calls[0]


def test_deploy_down_all_fails_when_compose_is_unavailable_after_local_stop(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env sh
exit 127
"""
    )
    docker.chmod(0o755)

    result = subprocess.run(
        ["./scripts/deploy.sh", "down", "all"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(
            tmp_path,
            PATH=f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
        ),
    )

    assert result.returncode == 2
    assert "STOPPED" in result.stdout
    assert "Docker Compose is not available" in result.stderr


def test_deploy_down_local_keeps_targeted_behavior_without_compose(tmp_path):
    result = subprocess.run(
        ["./scripts/deploy.sh", "down", "local"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(tmp_path, PATH="/usr/bin:/bin:/usr/sbin:/sbin"),
    )

    assert result.returncode == 0
    assert "STOPPED" in result.stdout


def test_deploy_compose_worker_manages_docker_worker_profile(tmp_path):
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "calls.log"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        f"""#!/usr/bin/env sh
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$1" = "ps" ]; then
  exit 0
fi
if [ "$1" = "compose" ]; then
  echo "docker $@" >> "{log_file}"
  exit 0
fi
exit 1
"""
    )
    docker.chmod(0o755)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as broker:
        broker.bind(("127.0.0.1", 0))
        broker.listen(1)
        broker_port = int(broker.getsockname()[1])
        env = script_env(
            tmp_path,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            POSTGRES_HOST_PORT=str(unused_port()),
            REDIS_HOST_PORT=str(unused_port()),
            TASKIQ__REDIS_URL=f"redis://127.0.0.1:{broker_port}/0",
        )

        up = subprocess.run(
            ["./scripts/deploy.sh", "up", "compose-worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        status = subprocess.run(
            ["./scripts/deploy.sh", "status", "compose-worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        down = subprocess.run(
            ["./scripts/deploy.sh", "down", "compose-worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    assert up.returncode == 0, up.stdout + up.stderr
    assert "== Compose Worker ==" in up.stdout
    assert status.returncode == 0, status.stdout + status.stderr
    assert "== Compose Worker ==" in status.stdout
    assert down.returncode == 0, down.stdout + down.stderr
    calls = log_file.read_text().splitlines()
    assert any("up -d postgres redis" in call for call in calls)
    assert any("--profile worker up -d --build worker" in call for call in calls)
    assert any("--profile worker ps worker postgres redis" in call for call in calls)
    assert any("--profile worker stop worker" in call for call in calls)
    assert any("stop postgres redis" in call for call in calls)


def test_deploy_compose_worker_rejects_missing_job_broker(tmp_path):
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "calls.log"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        f"""#!/usr/bin/env sh
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$1" = "ps" ]; then
  exit 0
fi
if [ "$1" = "compose" ]; then
  echo "docker $@" >> "{log_file}"
  exit 0
fi
exit 1
"""
    )
    docker.chmod(0o755)
    env = script_env(
        tmp_path,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        POSTGRES_HOST_PORT=str(unused_port()),
        REDIS_HOST_PORT=str(unused_port()),
        TASKIQ__REDIS_URL=f"redis://127.0.0.1:{unused_port()}/0",
    )

    result = subprocess.run(
        ["./scripts/deploy.sh", "up", "compose-worker"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 4
    assert "Job Service Redis broker" in result.stderr
    assert "not listening" in result.stderr
    assert not log_file.exists()


def test_deploy_compose_worker_rejects_unmanaged_local_worker(tmp_path):
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "calls.log"
    bin_dir.mkdir()
    fake_python = bin_dir / "fake-worker-python"
    fake_python.write_text(
        """#!/usr/bin/env sh
if [ "$1" = "-m" ] && [ "$2" = "app.job_platform_worker.runner" ]; then
  while :; do sleep 1; done
fi
exit 2
"""
    )
    fake_python.chmod(0o755)
    docker = bin_dir / "docker"
    docker.write_text(
        f"""#!/usr/bin/env sh
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$1" = "ps" ]; then
  exit 0
fi
if [ "$1" = "compose" ]; then
  echo "docker $@" >> "{log_file}"
  exit 0
fi
exit 1
"""
    )
    docker.chmod(0o755)
    env = script_env(
        tmp_path,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        POSTGRES_HOST_PORT=str(unused_port()),
        REDIS_HOST_PORT=str(unused_port()),
    )
    unmanaged = subprocess.Popen(
        [str(fake_python), "-m", "app.job_platform_worker.runner"],
        cwd=ROOT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.2)

        result = subprocess.run(
            ["./scripts/deploy.sh", "up", "compose-worker"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

        assert result.returncode == 4
        assert "local worker is running" in result.stderr
        assert not log_file.exists()
    finally:
        unmanaged.terminate()
        unmanaged.wait(timeout=5)


def test_deploy_compose_deps_down_rejects_running_compose_worker(tmp_path):
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "calls.log"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        f"""#!/usr/bin/env sh
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$1" = "ps" ]; then
  case "$*" in
    *"com.docker.compose.service=worker"*) echo "tasks-worker-service-worker-1"; exit 0 ;;
    *) exit 0 ;;
  esac
fi
if [ "$1" = "compose" ]; then
  echo "docker $@" >> "{log_file}"
  exit 0
fi
exit 1
"""
    )
    docker.chmod(0o755)

    result = subprocess.run(
        ["./scripts/deploy.sh", "down", "compose-deps"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(tmp_path, PATH=f"{bin_dir}:{os.environ['PATH']}"),
    )

    assert result.returncode == 4
    assert "compose worker is running" in result.stderr
    assert not log_file.exists()


def test_deploy_compose_worker_down_keeps_deps_when_compose_api_is_running(tmp_path):
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "calls.log"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        f"""#!/usr/bin/env sh
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$1" = "ps" ]; then
  case "$*" in
    *"com.docker.compose.service=api"*) echo "tasks-worker-service-api-1"; exit 0 ;;
    *) exit 0 ;;
  esac
fi
if [ "$1" = "compose" ]; then
  echo "docker $@" >> "{log_file}"
  exit 0
fi
exit 1
"""
    )
    docker.chmod(0o755)

    result = subprocess.run(
        ["./scripts/deploy.sh", "down", "compose-worker"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(tmp_path, PATH=f"{bin_dir}:{os.environ['PATH']}"),
    )

    assert result.returncode == 4
    assert "compose-full api is running" in result.stderr
    calls = log_file.read_text().splitlines()
    assert any("--profile worker stop worker" in call for call in calls)
    assert not any("stop postgres redis" in call for call in calls)


def test_deploy_compose_deps_rejects_busy_host_port_before_docker(tmp_path):
    port = unused_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_tcp_port(port)

        result = subprocess.run(
            ["./scripts/deploy.sh", "up", "compose-deps"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
            env=script_env(
                tmp_path,
                POSTGRES_HOST_PORT=str(port),
                REDIS_HOST_PORT=str(unused_port()),
            ),
        )

        assert result.returncode == 4
        assert "POSTGRES_HOST_PORT" in result.stderr
        assert "already" in result.stderr
        assert "== Compose Deps ==" not in result.stdout
        assert server.poll() is None
    finally:
        server.terminate()
        server.wait(timeout=5)


def test_deploy_compose_deps_allows_repeated_up_for_current_project(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        f"""#!/usr/bin/env sh
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  exit 0
fi
if [ "$1" = "ps" ]; then
  case "$*" in
    *"com.docker.compose.service=postgres"*) echo "tasks-worker-service-postgres-1"; exit 0 ;;
    *"com.docker.compose.service=redis"*) echo "tasks-worker-service-redis-1"; exit 0 ;;
    *"com.docker.compose.project.working_dir"*) echo "{ROOT_DIR}"; exit 0 ;;
    *) exit 0 ;;
  esac
fi
if [ "$1" = "port" ]; then
  case "$2:$3" in
    tasks-worker-service-postgres-1:5432/tcp) echo "0.0.0.0:25435"; exit 0 ;;
    tasks-worker-service-redis-1:6379/tcp) echo "0.0.0.0:26382"; exit 0 ;;
    *) exit 1 ;;
  esac
fi
if [ "$1" = "compose" ]; then
  echo "fake compose $*"
  exit 0
fi
exit 1
"""
    )
    docker.chmod(0o755)

    result = subprocess.run(
        ["./scripts/deploy.sh", "up", "compose-deps"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        env=script_env(
            tmp_path,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            POSTGRES_HOST_PORT="25435",
            REDIS_HOST_PORT="26382",
        ),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "RUNNING" in result.stdout
    assert "tasks-worker-service-postgres-1" in result.stdout
    assert "== Compose Deps ==" in result.stdout


def test_tools_secret_outputs_prefixed_token():
    result = run_script("./scripts/tools.sh", "secret", "--prefix", "test_")

    assert result.returncode == 0
    token = result.stdout.strip()
    assert token.startswith("test_")
    assert len(token) > len("test_") + 16


def test_tools_env_url_postgres_encodes_password():
    result = subprocess.run(
        [
            "./scripts/tools.sh",
            "env-url",
            "postgres",
            "--username",
            "user name",
            "--host",
            "127.0.0.1",
            "--port",
            "25435",
            "--database",
            "fastapi lite",
            "--password-stdin",
        ],
        cwd=ROOT_DIR,
        input="p@ss word",
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "DATABASE__URL=postgresql+asyncpg://user%20name:p%40ss%20word@127.0.0.1:25435/fastapi%20lite" in result.stdout
    assert "# password_present=true" in result.stdout


def test_tools_env_url_redis_without_password():
    result = run_script("./scripts/tools.sh", "env-url", "redis", "--host", "127.0.0.1", "--port", "26382", "--db", "0")

    assert result.returncode == 0
    assert "REDIS__URL=redis://127.0.0.1:26382/0" in result.stdout
    assert "# password_present=false" in result.stdout
