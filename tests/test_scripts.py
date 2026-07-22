import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
    )


def test_script_help_commands_work():
    for script in ("./scripts/dev.sh", "./scripts/deploy.sh", "./scripts/verify.sh"):
        result = run_script(script, "help")
        assert result.returncode == 0
        assert "Usage:" in result.stdout


def test_script_unknown_command_fails():
    result = run_script("./scripts/verify.sh", "missing")

    assert result.returncode != 0
    assert "unknown command" in result.stderr

