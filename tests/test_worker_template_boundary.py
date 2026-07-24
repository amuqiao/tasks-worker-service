from __future__ import annotations

import ast
from pathlib import Path

from app.job_platform_worker.manifest import load_worker_manifest

ALLOWED_WORKER_CONTRACT_MODULES = {
    "app.job_platform_worker.handlers",
    "app.job_platform_worker.protocol",
}


def test_default_manifest_handlers_stay_in_worker_business_surface() -> None:
    manifest = load_worker_manifest("app/worker/manifest.json")

    for task in manifest.tasks:
        assert task.handler.startswith("app.worker.task_modules.")


def test_worker_business_surface_uses_only_public_worker_contracts() -> None:
    for path in sorted(Path("app/worker").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                if node.module == "app.job_platform_worker":
                    imported = {f"{node.module}.{alias.name}" for alias in node.names}
                    assert imported <= ALLOWED_WORKER_CONTRACT_MODULES, f"{path}: {sorted(imported)}"
                elif node.module.startswith("app.job_platform_worker."):
                    assert node.module in ALLOWED_WORKER_CONTRACT_MODULES, f"{path}: {node.module}"
            elif isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names if alias.name.startswith("app.job_platform_worker")}
                assert imported <= ALLOWED_WORKER_CONTRACT_MODULES, f"{path}: {sorted(imported)}"
