from __future__ import annotations

import uuid

import httpx
from pydantic import ValidationError

from app.job_platform_worker.protocol import (
    AcquireAttemptRequest,
    AcquireAttemptResponse,
    CompleteAttemptRequest,
    CompleteAttemptResponse,
    ErrorEnvelope,
    HEADER_AUTHORIZATION,
    HEADER_JOB_REQUEST_ID,
    HEADER_JOB_TRACE_ID,
    HeartbeatAttemptRequest,
    HeartbeatAttemptResponse,
    QueueEnvelope,
    SuccessEnvelope,
    FailAttemptRequest,
    FailAttemptResponse,
)


class JobServiceApiError(Exception):
    def __init__(self, envelope: ErrorEnvelope, *, status_code: int) -> None:
        super().__init__(f"{envelope.code}: {envelope.message}")
        self.envelope = envelope
        self.status_code = status_code

    @property
    def code(self) -> str:
        return self.envelope.code

    @property
    def retryable(self) -> bool:
        return self.envelope.retryable

    @property
    def details(self) -> dict:
        return self.envelope.details


class JobServiceProtocolError(Exception):
    pass


class JobServiceClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        base_url: str,
        worker_service: str,
        service_api_key: str,
    ) -> None:
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")
        self._worker_service = worker_service
        self._service_api_key = service_api_key

    async def acquire_attempt(
        self,
        envelope: QueueEnvelope,
        *,
        worker_session_id: str,
        worker_name: str,
    ) -> AcquireAttemptResponse:
        payload = AcquireAttemptRequest(
            worker_session_id=worker_session_id,
            worker_name=worker_name,
            queue_name=envelope.queue_name,
            task_name=envelope.task_name,
            task_version=envelope.task_version,
            input_schema_hash=envelope.input_schema_hash,
            output_schema_hash=envelope.output_schema_hash,
        )
        data = await self._post(
            f"/attempts/{envelope.attempt_id}/acquire",
            payload.model_dump(mode="json"),
            trace_id=envelope.trace_id,
        )
        return AcquireAttemptResponse.model_validate(data)

    async def complete_attempt(
        self,
        envelope: QueueEnvelope,
        *,
        lease_token: str,
        output: dict | None,
        output_ref: dict | None,
    ) -> CompleteAttemptResponse:
        payload = CompleteAttemptRequest(lease_token=lease_token, output=output, output_ref=output_ref)
        data = await self._post(
            f"/attempts/{envelope.attempt_id}/complete",
            payload.model_dump(mode="json"),
            trace_id=envelope.trace_id,
        )
        return CompleteAttemptResponse.model_validate(data)

    async def heartbeat_attempt(
        self,
        envelope: QueueEnvelope,
        *,
        lease_token: str,
        progress_percent: int | None = None,
        progress_message: str | None = None,
    ) -> HeartbeatAttemptResponse:
        payload = HeartbeatAttemptRequest(
            lease_token=lease_token,
            progress_percent=progress_percent,
            progress_message=progress_message,
        )
        data = await self._post(
            f"/attempts/{envelope.attempt_id}/heartbeat",
            payload.model_dump(mode="json"),
            trace_id=envelope.trace_id,
        )
        return HeartbeatAttemptResponse.model_validate(data)

    async def fail_attempt(
        self,
        envelope: QueueEnvelope,
        *,
        lease_token: str,
        error_kind: str,
        error_code: str,
        message: str,
        retryable: bool,
        details: dict,
    ) -> FailAttemptResponse:
        payload = FailAttemptRequest(
            lease_token=lease_token,
            error_kind=error_kind,
            error_code=error_code,
            message=message,
            retryable=retryable,
            details=details,
        )
        data = await self._post(
            f"/attempts/{envelope.attempt_id}/fail",
            payload.model_dump(mode="json"),
            trace_id=envelope.trace_id,
        )
        return FailAttemptResponse.model_validate(data)

    async def _post(self, path: str, payload: dict, *, trace_id: str) -> dict:
        response = await self._http_client.post(
            f"{self._base_url}{path}",
            json=payload,
            headers={
                HEADER_AUTHORIZATION: f"Bearer worker:{self._worker_service}:{self._service_api_key}",
                HEADER_JOB_REQUEST_ID: f"worker-{uuid.uuid4().hex}",
                HEADER_JOB_TRACE_ID: trace_id,
            },
        )
        body = response.json()
        if response.status_code >= 400:
            try:
                envelope = ErrorEnvelope.model_validate(body)
            except ValidationError as exc:
                raise JobServiceProtocolError("Job Service returned a non-standard error envelope") from exc
            raise JobServiceApiError(envelope, status_code=response.status_code)
        try:
            envelope = SuccessEnvelope[dict].model_validate(body)
        except ValidationError as exc:
            raise JobServiceProtocolError("Job Service returned a non-standard success envelope") from exc
        return envelope.data
