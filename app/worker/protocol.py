from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import Field, model_validator

from app.schemas.common import StrictBaseModel

TData = TypeVar("TData")
HashString = str


HEADER_AUTHORIZATION = "Authorization"
HEADER_JOB_REQUEST_ID = "X-Job-Request-Id"
HEADER_JOB_TRACE_ID = "X-Job-Trace-Id"


class QueueEnvelope(StrictBaseModel):
    protocol_version: int = Field(ge=1)
    run_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    node_key: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    task_name: str = Field(min_length=1)
    task_version: int = Field(ge=1)
    queue_name: str = Field(min_length=1)
    input_schema_hash: HashString = Field(pattern=r"^jsonschema-jcs-v1:sha256:[0-9a-f]{64}$")
    output_schema_hash: HashString = Field(pattern=r"^jsonschema-jcs-v1:sha256:[0-9a-f]{64}$")
    input: Any | None = None
    input_ref: Any | None = None
    trace_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_input_or_ref(self) -> "QueueEnvelope":
        if self.input is None and self.input_ref is None:
            raise ValueError("input or input_ref is required")
        return self


class SuccessEnvelope(StrictBaseModel, Generic[TData]):
    request_id: str
    trace_id: str
    server_time: str
    code: str = "OK"
    data: TData


class ErrorEnvelope(StrictBaseModel):
    request_id: str
    trace_id: str
    server_time: str
    code: str
    message: str
    retryable: bool
    details: dict[str, Any]


class AcquireAttemptRequest(StrictBaseModel):
    worker_session_id: str
    worker_name: str
    queue_name: str
    task_name: str
    task_version: int = Field(ge=1)
    input_schema_hash: str = Field(pattern=r"^jsonschema-jcs-v1:sha256:[0-9a-f]{64}$")
    output_schema_hash: str = Field(pattern=r"^jsonschema-jcs-v1:sha256:[0-9a-f]{64}$")


class AcquireAttemptResponse(StrictBaseModel):
    acquired: bool
    attempt_id: str | None = None
    lease_token: str | None = None
    lease_expires_at: str | None = None
    heartbeat_interval_seconds: float | None = None
    run_id: str | None = None
    node_id: str | None = None
    node_key: str | None = None
    task_name: str | None = None
    task_version: int | None = None
    input: dict[str, Any] | None = None
    input_ref: dict[str, Any] | None = None
    cancel_requested: bool = False


class HeartbeatAttemptRequest(StrictBaseModel):
    lease_token: str
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    progress_message: str | None = None


class HeartbeatAttemptResponse(StrictBaseModel):
    lease_valid: bool
    cancel_requested: bool
    lease_expires_at: str | None = None


class CompleteAttemptRequest(StrictBaseModel):
    lease_token: str
    output: dict[str, Any] | None = None
    output_ref: dict[str, Any] | None = None


class CompleteAttemptResponse(StrictBaseModel):
    accepted: bool
    run_id: str
    run_status: str


class FailAttemptRequest(StrictBaseModel):
    lease_token: str
    error_kind: str
    error_code: str
    message: str
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)
    public_error: dict[str, Any] | None = None


class FailAttemptResponse(StrictBaseModel):
    accepted: bool
    retry_scheduled: bool
    next_attempt_id: str | None
    run_status: str
