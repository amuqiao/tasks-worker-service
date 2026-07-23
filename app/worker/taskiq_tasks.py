from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.worker.handlers import WorkerContext
from app.worker.job_client import JobServiceClient
from app.worker.registry import build_worker_registry
from app.worker.runtime import WorkerRunResult, run_queue_envelope

settings = get_settings()


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
            handlers=build_worker_registry(),
            context=WorkerContext(
                worker_service=settings.worker.service_name,
                worker_name=settings.worker.worker_name,
                worker_session_id=settings.worker.worker_session_id,
            ),
        )
