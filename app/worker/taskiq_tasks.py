from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.worker.handlers import WorkerContext, build_default_registry
from app.worker.job_client import JobServiceClient
from app.worker.runtime import WorkerRunResult, run_queue_envelope
from app.worker.taskiq_app import broker

settings = get_settings()


@broker.task(task_name=settings.taskiq.task_name)
async def consume_queue_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    result = await run_queue_envelope_with_settings(payload)
    if result.ack_decision == "no_ack":
        raise RuntimeError(f"worker did not ack message: {result.status}")
    return result.model_dump()


async def run_queue_envelope_with_settings(payload: dict[str, Any]) -> WorkerRunResult:
    async with httpx.AsyncClient(timeout=settings.http_client.timeout_seconds) as http_client:
        client = JobServiceClient(
            http_client,
            base_url=settings.worker.job_service_base_url,
            worker_service=settings.worker.service_name,
            service_api_key=settings.worker.job_service_api_key_value,
        )
        return await run_queue_envelope(
            payload,
            client=client,
            handlers=build_default_registry(),
            context=WorkerContext(
                worker_service=settings.worker.service_name,
                worker_name=settings.worker.worker_name,
                worker_session_id=settings.worker.worker_session_id,
            ),
        )
