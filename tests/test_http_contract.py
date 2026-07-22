from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.context import REQUEST_ID_HEADER, TRACE_ID_HEADER
from app.core.exceptions import AppError
from app.core.lifecycle import HealthCheck, HealthCheckRegistry, HealthCheckResult


def test_health_envelope_and_context_headers(app):
    with TestClient(app) as client:
        response = client.get("/health", headers={REQUEST_ID_HEADER: "req-test", TRACE_ID_HEADER: "trace-test"})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "req-test"
    assert response.headers[TRACE_ID_HEADER] == "trace-test"
    body = response.json()
    assert body["code"] == "OK"
    assert body["request_id"] == "req-test"
    assert body["trace_id"] == "trace-test"
    assert body["data"]["status"] == "ok"


def test_ready_uses_health_registry(app):
    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "OK"
    assert body["data"]["status"] == "ok"
    assert body["data"]["checks"][0]["name"] == "process"


def test_ready_returns_503_when_required_check_fails(app):
    async def fail_check():
        return HealthCheckResult(name="database", status="failed", details={"reason": "down"})

    registry = HealthCheckRegistry()
    registry.register(HealthCheck(name="database", check=fail_check, required=True))
    registry.freeze()
    with TestClient(app) as client:
        client.app.state.health_checks = registry
        response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE"
    assert body["details"]["status"] == "failed"


def test_invalid_request_id_returns_error_envelope(app):
    with TestClient(app) as client:
        response = client.get("/health", headers={REQUEST_ID_HEADER: "bad id with spaces"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "REQUEST_INVALID"
    assert body["details"]["header"] == REQUEST_ID_HEADER


def test_invalid_trace_id_returns_error_envelope(app):
    with TestClient(app) as client:
        response = client.get("/health", headers={TRACE_ID_HEADER: "bad trace with spaces"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "REQUEST_INVALID"
    assert body["details"]["header"] == TRACE_ID_HEADER


def test_app_error_returns_registered_error_envelope(app):
    router = APIRouter()

    @router.get("/_test/app-error")
    async def raise_app_error():
        raise AppError("FORBIDDEN")

    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/_test/app-error")

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_validation_error_returns_request_invalid(app):
    router = APIRouter()

    @router.get("/_test/validation")
    async def validation_route(count: int):
        return {"count": count}

    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/_test/validation", params={"count": "abc"})

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_unhandled_exception_returns_internal_error(test_settings):
    from app.main import create_app

    app = create_app(test_settings)
    router = APIRouter()

    @router.get("/_test/boom")
    async def boom():
        raise RuntimeError("boom")

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/boom")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"


def test_method_not_allowed_preserves_http_status(app):
    with TestClient(app) as client:
        response = client.post("/health")

    assert response.status_code == 405
    assert response.json()["code"] == "REQUEST_INVALID"
