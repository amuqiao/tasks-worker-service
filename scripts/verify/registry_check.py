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


def main() -> int:
    error_registry.validate()
    operation_registry.validate()
    health_registry = build_health_registry()
    health_registry.validate()
    lifecycle_registry = build_lifecycle_provider_registry()
    lifecycle_registry.validate()
    validate_operation_route_drift(create_app())
    print("OK registries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
