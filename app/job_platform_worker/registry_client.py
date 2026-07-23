from __future__ import annotations

import uuid
from typing import Any

import httpx
from pydantic import ValidationError

from app.job_platform_worker.protocol import (
    ErrorEnvelope,
    HEADER_AUTHORIZATION,
    HEADER_JOB_REQUEST_ID,
    HEADER_JOB_TRACE_ID,
    SuccessEnvelope,
)


class JobServiceRegistryApiError(Exception):
    def __init__(self, envelope: ErrorEnvelope, *, status_code: int) -> None:
        super().__init__(f"{envelope.code}: {envelope.message}")
        self.envelope = envelope
        self.status_code = status_code


class JobServiceRegistryProtocolError(Exception):
    pass


class JobServiceRegistryClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        base_url: str,
        worker_service: str,
        registry_api_key: str,
    ) -> None:
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")
        self._worker_service = worker_service
        self._registry_api_key = registry_api_key

    async def register_worker_manifest(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._http_client.put(
            f"{self._base_url}/registry/worker-manifests/{self._worker_service}",
            json=payload,
            headers={
                HEADER_AUTHORIZATION: f"Bearer registry_admin:{self._worker_service}:{self._registry_api_key}",
                HEADER_JOB_REQUEST_ID: f"registry-{uuid.uuid4().hex}",
                HEADER_JOB_TRACE_ID: f"registry-{uuid.uuid4().hex}",
            },
        )
        body = response.json()
        if response.status_code >= 400:
            try:
                envelope = ErrorEnvelope.model_validate(body)
            except ValidationError as exc:
                raise JobServiceRegistryProtocolError("Job Service returned a non-standard error envelope") from exc
            raise JobServiceRegistryApiError(envelope, status_code=response.status_code)
        try:
            envelope = SuccessEnvelope[dict].model_validate(body)
        except ValidationError as exc:
            raise JobServiceRegistryProtocolError("Job Service returned a non-standard success envelope") from exc
        return envelope.data
