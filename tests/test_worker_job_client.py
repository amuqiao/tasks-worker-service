from __future__ import annotations

import json

import httpx
import pytest

from app.job_platform_worker.job_client import JobServiceClient
from app.job_platform_worker.protocol import QueueEnvelope


HASH = "jsonschema-jcs-v1:sha256:" + "a" * 64


def _envelope() -> QueueEnvelope:
    return QueueEnvelope(
        protocol_version=1,
        run_id="run-1",
        node_id="node-1",
        node_key="main",
        attempt_id="attempt-1",
        task_name="example.task",
        task_version=1,
        queue_name="job.example-task.v1",
        input_schema_hash=HASH,
        output_schema_hash=HASH,
        input={"message": "hello"},
        trace_id="trace-1",
    )


@pytest.mark.asyncio
async def test_cancel_attempt_posts_expected_contract() -> None:
    seen: list[tuple[str, str, dict[str, str], dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.headers), json.loads(request.content)))
        return httpx.Response(
            200,
                json={
                    "code": "OK",
                    "request_id": "req-1",
                    "trace_id": "trace-1",
                    "server_time": "2026-07-24T00:00:00Z",
                    "data": {
                        "accepted": True,
                    "run_status": "cancelled",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = JobServiceClient(
            http_client,
            base_url="http://job-service/internal/v1",
            worker_service="worker-x",
            service_api_key="worker-key",
        )

        response = await client.cancel_attempt(_envelope(), lease_token="lease-1", reason="user requested cancel")

    assert response.accepted is True
    assert response.run_status == "cancelled"
    method, path, headers, body = seen[0]
    assert method == "POST"
    assert path == "/internal/v1/attempts/attempt-1/cancel"
    assert headers["authorization"] == "Bearer worker:worker-x:worker-key"
    assert headers["x-job-trace-id"] == "trace-1"
    assert body == {"lease_token": "lease-1", "reason": "user requested cancel"}
