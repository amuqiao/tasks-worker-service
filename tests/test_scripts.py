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
    for script in ("./scripts/dev.sh", "./scripts/deploy.sh", "./scripts/k8s.sh", "./scripts/verify.sh", "./scripts/tools.sh"):
        result = run_script(script, "help")
        assert result.returncode == 0
        assert "Usage:" in result.stdout
        assert "Exit Codes:" in result.stdout


def test_script_unknown_command_fails():
    result = run_script("./scripts/verify.sh", "missing")

    assert result.returncode == 2
    assert "unknown command" in result.stderr


def test_script_unexpected_argument_fails():
    result = run_script("./scripts/dev.sh", "status", "extra")

    assert result.returncode == 2
    assert "unexpected argument" in result.stderr


def test_verify_subcommand_help_does_not_execute_task():
    result = run_script("./scripts/verify.sh", "postgres", "--help")

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "专用 PostgreSQL _test 数据库" in result.stdout
    assert "OK test-database" not in result.stdout


def test_verify_postgres_rejects_non_test_database_with_config_exit_code():
    result = run_script(
        "env",
        "DATABASE__URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:25432/fastapi_lite",
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
            DATABASE__URL="postgresql+asyncpg://postgres:secret@postgres.default.svc:5432/fastapi_lite",
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
    assert "compose-full" in result.stdout


def test_deploy_local_status_delegates_to_dev_status():
    result = run_script("./scripts/deploy.sh", "status", "local")

    assert result.returncode == 0
    assert "== API ==" in result.stdout


def test_deploy_compose_subcommand_help():
    result = run_script("./scripts/deploy.sh", "up", "--help")

    assert result.returncode == 0
    assert "compose-deps" in result.stdout
    assert "compose-full" in result.stdout


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
    *"com.docker.compose.service=postgres"*) echo "fastapi-lite-postgres-1"; exit 0 ;;
    *"com.docker.compose.service=redis"*) echo "fastapi-lite-redis-1"; exit 0 ;;
    *"com.docker.compose.project.working_dir"*) echo "{ROOT_DIR}"; exit 0 ;;
    *) exit 0 ;;
  esac
fi
if [ "$1" = "port" ]; then
  case "$2:$3" in
    fastapi-lite-postgres-1:5432/tcp) echo "0.0.0.0:25432"; exit 0 ;;
    fastapi-lite-redis-1:6379/tcp) echo "0.0.0.0:26379"; exit 0 ;;
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
            POSTGRES_HOST_PORT="25432",
            REDIS_HOST_PORT="26379",
        ),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "RUNNING" in result.stdout
    assert "fastapi-lite-postgres-1" in result.stdout
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
            "25432",
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
    assert "DATABASE__URL=postgresql+asyncpg://user%20name:p%40ss%20word@127.0.0.1:25432/fastapi%20lite" in result.stdout
    assert "# password_present=true" in result.stdout


def test_tools_env_url_redis_without_password():
    result = run_script("./scripts/tools.sh", "env-url", "redis", "--host", "127.0.0.1", "--port", "26379", "--db", "0")

    assert result.returncode == 0
    assert "REDIS__URL=redis://127.0.0.1:26379/0" in result.stdout
    assert "# password_present=false" in result.stdout
