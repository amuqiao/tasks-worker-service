from app.api.operations import operation_registry
from app.core.error_registry import error_registry
from app.core.lifecycle import build_health_registry
from app.core.registry_checks import validate_operation_route_drift
from app.main import build_lifecycle_provider_registry, create_app


def test_error_registry_contains_internal_error():
    error_registry.validate()
    assert error_registry.get("INTERNAL_ERROR").http_status == 500


def test_operation_registry_contains_foundation_routes():
    operation_registry.validate()
    paths = {item.path for item in operation_registry.all()}

    assert "/health" in paths
    assert "/ready" in paths


def test_health_registry_contains_process_check():
    registry = build_health_registry()

    assert [item.name for item in registry.all()] == ["process"]


def test_operation_registry_matches_mounted_routes():
    validate_operation_route_drift(create_app())


def test_default_lifecycle_provider_registry_contains_foundation_providers():
    registry = build_lifecycle_provider_registry()
    names = {provider.name for provider in registry.all()}

    assert names == {"postgres", "redis", "object_storage", "http_client"}
