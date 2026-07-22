from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.operations import operation_registry


def validate_operation_route_drift(app: FastAPI) -> None:
    actual = {
        (method, route.path, route.operation_id, route.status_code or 200)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    expected = {
        (spec.method, spec.path, spec.operation_id, spec.success_status)
        for spec in operation_registry.all()
    }
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise RuntimeError(f"operation registry drift missing={missing} extra={extra}")
