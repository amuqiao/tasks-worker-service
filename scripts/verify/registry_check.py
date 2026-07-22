from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.api.operations import operation_registry
from app.core.error_registry import error_registry
from app.core.lifecycle import build_health_registry
from app.core.registry_checks import validate_operation_route_drift
from app.main import build_lifecycle_provider_registry, create_app
from app.tools.example_tool import validate_example_tool_spec

REQUIRED_DOCS = (
    ROOT_DIR / "docs/current/implementation.md",
    ROOT_DIR / "docs/contracts/api-contract.md",
    ROOT_DIR / "docs/contracts/extension-contract.md",
    ROOT_DIR / "docs/plans/drift-checklist.md",
)


def main() -> int:
    error_registry.validate()
    operation_registry.validate()
    health_registry = build_health_registry()
    health_registry.validate()
    lifecycle_registry = build_lifecycle_provider_registry()
    lifecycle_registry.validate()
    validate_example_tool_spec()
    missing_docs = [str(path.relative_to(ROOT_DIR)) for path in REQUIRED_DOCS if not path.is_file()]
    if missing_docs:
        raise RuntimeError(f"required docs are missing: {missing_docs}")
    validate_operation_route_drift(create_app())
    print("OK registries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
