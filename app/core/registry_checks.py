from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.operations import operation_registry


def validate_operation_route_drift(app: FastAPI) -> None:
    actual = {
        (method, route.path, route.operation_id)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    expected = {
        (spec.method, spec.path, spec.operation_id)
        for spec in operation_registry.all()
    }
    missing = sorted(expected - actual)
    extra = sorted(item for item in actual - expected if item[1] in {spec.path for spec in operation_registry.all()})
    if missing or extra:
        raise RuntimeError(f"operation registry drift missing={missing} extra={extra}")

