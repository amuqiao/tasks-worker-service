from __future__ import annotations

import httpx

from app.job_platform_worker.registry_client import JobServiceRegistryClient


async def test_registry_client_puts_manifest_with_registry_admin_auth() -> None:
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers["authorization"]
        seen["payload"] = request.read()
        return httpx.Response(
            200,
            json={
                "request_id": "req-1",
                "trace_id": "trace-1",
                "server_time": "2026-01-01T00:00:00Z",
                "code": "OK",
                "data": {
                    "worker_service": "worker-x",
                    "queue_name": "job.example-task.v1",
                    "created_tasks": ["example.task@v1"],
                    "unchanged_tasks": [],
                    "updated_bindings": [],
                    "disabled_tasks": [],
                    "ready_tasks": ["example.task@v1"],
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://job.local") as http_client:
        client = JobServiceRegistryClient(
            http_client,
            base_url="http://job.local/internal/v1",
            worker_service="worker-x",
            registry_api_key="secret",
        )
        data = await client.register_worker_manifest({"worker_service": "worker-x", "tasks": []})

    assert seen["method"] == "PUT"
    assert seen["path"] == "/internal/v1/registry/worker-manifests/worker-x"
    assert seen["authorization"] == "Bearer registry_admin:worker-x:secret"
    assert data["created_tasks"] == ["example.task@v1"]
