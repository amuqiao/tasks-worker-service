from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.job_platform_worker.handlers import HandlerRegistry, HandlerResult, WorkerContext, build_default_registry
from app.job_platform_worker.job_client import JobServiceApiError
from app.job_platform_worker.protocol import AcquireAttemptResponse, ErrorEnvelope, QueueEnvelope
from app.job_platform_worker.runtime import run_queue_envelope

HASH = "jsonschema-jcs-v1:sha256:" + "a" * 64


def _payload() -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "run_id": "run-1",
        "node_id": "node-1",
        "node_key": "main",
        "attempt_id": "11111111-1111-1111-1111-111111111111",
        "task_name": "example.task",
        "task_version": 1,
        "queue_name": "job.example-task.v1",
        "input_schema_hash": HASH,
        "output_schema_hash": HASH,
        "input": {"message": "hello"},
        "trace_id": "trace-1",
    }


def _context() -> WorkerContext:
    return WorkerContext(
        worker_service="worker-x",
        worker_name="worker-x-taskiq",
        worker_session_id="worker-x-local",
    )


def _api_error(code: str, *, details: dict[str, Any] | None = None) -> JobServiceApiError:
    return JobServiceApiError(
        ErrorEnvelope(
            request_id="req-1",
            trace_id="trace-1",
            server_time="2026-01-01T00:00:00Z",
            code=code,
            message=code,
            retryable=False,
            details=details or {},
        ),
        status_code=409,
    )


class FakeJobClient:
    def __init__(self) -> None:
        self.completed: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []
        self.heartbeats: list[dict[str, Any]] = []

    async def acquire_attempt(self, envelope: QueueEnvelope, *, worker_session_id: str, worker_name: str):
        return AcquireAttemptResponse(acquired=True, lease_token="lease-1", heartbeat_interval_seconds=60)

    async def heartbeat_attempt(
        self,
        envelope: QueueEnvelope,
        *,
        lease_token: str,
        progress_percent: int | None = None,
        progress_message: str | None = None,
    ):
        self.heartbeats.append(
            {
                "lease_token": lease_token,
                "progress_percent": progress_percent,
                "progress_message": progress_message,
            }
        )
        return _Response(lease_valid=True, cancel_requested=False)

    async def complete_attempt(self, envelope: QueueEnvelope, *, lease_token: str, output: dict | None, output_ref: dict | None):
        self.completed.append({"lease_token": lease_token, "output": output, "output_ref": output_ref})
        return _Response(run_status="succeeded")

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
    ):
        self.failed.append(
            {
                "lease_token": lease_token,
                "error_kind": error_kind,
                "error_code": error_code,
                "message": message,
                "retryable": retryable,
                "details": details,
            }
        )
        return _Response(run_status="failed", retry_scheduled=False)


class _Response:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


async def test_run_queue_envelope_completes_and_acks_successful_handler() -> None:
    client = FakeJobClient()

    result = await run_queue_envelope(
        _payload(),
        client=client,  # type: ignore[arg-type]
        handlers=build_default_registry(),
        context=_context(),
    )

    assert result.ack_decision == "ack"
    assert result.status == "completed"
    assert client.completed[0]["lease_token"] == "lease-1"
    assert client.completed[0]["output"]["ok"] is True


async def test_run_queue_envelope_acks_poison_message_without_calling_job_service() -> None:
    client = FakeJobClient()
    payload = _payload()
    del payload["attempt_id"]

    result = await run_queue_envelope(
        payload,
        client=client,  # type: ignore[arg-type]
        handlers=build_default_registry(),
        context=_context(),
    )

    assert result.ack_decision == "ack"
    assert result.status == "poison_message"
    assert client.completed == []


async def test_run_queue_envelope_no_acks_missing_handler() -> None:
    client = FakeJobClient()
    empty_registry = HandlerRegistry()

    result = await run_queue_envelope(
        _payload(),
        client=client,  # type: ignore[arg-type]
        handlers=empty_registry,
        context=_context(),
    )

    assert result.ack_decision == "no_ack"
    assert result.status == "handler_missing"


async def test_run_queue_envelope_acks_attempt_not_acquirable_when_job_service_marks_safe() -> None:
    class Client(FakeJobClient):
        async def acquire_attempt(self, envelope: QueueEnvelope, *, worker_session_id: str, worker_name: str):
            raise _api_error("ATTEMPT_NOT_ACQUIRABLE", details={"reason": "succeeded", "safe_to_ack": True})

    result = await run_queue_envelope(
        _payload(),
        client=Client(),  # type: ignore[arg-type]
        handlers=build_default_registry(),
        context=_context(),
    )

    assert result.ack_decision == "ack"
    assert result.status == "attempt_not_acquirable_safe_to_ack"


async def test_run_queue_envelope_no_acks_attempt_not_acquirable_when_not_safe() -> None:
    class Client(FakeJobClient):
        async def acquire_attempt(self, envelope: QueueEnvelope, *, worker_session_id: str, worker_name: str):
            raise _api_error("ATTEMPT_NOT_ACQUIRABLE", details={"reason": "running", "safe_to_ack": False})

    result = await run_queue_envelope(
        _payload(),
        client=Client(),  # type: ignore[arg-type]
        handlers=build_default_registry(),
        context=_context(),
    )

    assert result.ack_decision == "no_ack"
    assert result.status == "acquire_rejected"


async def test_run_queue_envelope_no_acks_unknown_complete_result() -> None:
    class Client(FakeJobClient):
        async def complete_attempt(self, envelope: QueueEnvelope, *, lease_token: str, output: dict | None, output_ref: dict | None):
            raise httpx.TransportError("connection reset")

    result = await run_queue_envelope(
        _payload(),
        client=Client(),  # type: ignore[arg-type]
        handlers=build_default_registry(),
        context=_context(),
    )

    assert result.ack_decision == "no_ack"
    assert result.status == "complete_unknown"


async def test_run_queue_envelope_reports_handler_failure_then_acks() -> None:
    class FailingHandler:
        async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
            raise RuntimeError("handler exploded")

    registry = HandlerRegistry()
    registry.register("example.task", 1, FailingHandler())
    client = FakeJobClient()

    result = await run_queue_envelope(
        _payload(),
        client=client,  # type: ignore[arg-type]
        handlers=registry,
        context=_context(),
    )

    assert result.ack_decision == "ack"
    assert result.status == "failed"
    assert client.failed[0]["error_code"] == "WORKER_HANDLER_FAILED"


async def test_run_queue_envelope_heartbeats_while_handler_is_running() -> None:
    class SlowHandler:
        async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
            await asyncio.sleep(0.02)
            return HandlerResult(output={"ok": True})

    class Client(FakeJobClient):
        async def acquire_attempt(self, envelope: QueueEnvelope, *, worker_session_id: str, worker_name: str):
            return AcquireAttemptResponse(acquired=True, lease_token="lease-1", heartbeat_interval_seconds=0.001)

    registry = HandlerRegistry()
    registry.register("example.task", 1, SlowHandler())
    client = Client()

    result = await run_queue_envelope(
        _payload(),
        client=client,  # type: ignore[arg-type]
        handlers=registry,
        context=_context(),
    )

    assert result.ack_decision == "ack"
    assert result.status == "completed"
    assert client.heartbeats


async def test_run_queue_envelope_does_not_start_handler_when_acquire_reports_cancel() -> None:
    class Handler:
        async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
            raise AssertionError("handler must not start after cancelled acquire")

    class Client(FakeJobClient):
        async def acquire_attempt(self, envelope: QueueEnvelope, *, worker_session_id: str, worker_name: str):
            return AcquireAttemptResponse(
                acquired=True,
                lease_token="lease-1",
                heartbeat_interval_seconds=60,
                cancel_requested=True,
            )

    registry = HandlerRegistry()
    registry.register("example.task", 1, Handler())
    client = Client()

    result = await run_queue_envelope(
        _payload(),
        client=client,  # type: ignore[arg-type]
        handlers=registry,
        context=_context(),
    )

    assert result.ack_decision == "no_ack"
    assert result.status == "cancel_requested"
    assert client.completed == []
    assert client.heartbeats == []


async def test_run_queue_envelope_no_acks_when_background_heartbeat_reports_cancel() -> None:
    class SlowHandler:
        async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
            await asyncio.sleep(0.02)
            return HandlerResult(output={"ok": True})

    class Client(FakeJobClient):
        async def acquire_attempt(self, envelope: QueueEnvelope, *, worker_session_id: str, worker_name: str):
            return AcquireAttemptResponse(acquired=True, lease_token="lease-1", heartbeat_interval_seconds=0.001)

        async def heartbeat_attempt(
            self,
            envelope: QueueEnvelope,
            *,
            lease_token: str,
            progress_percent: int | None = None,
            progress_message: str | None = None,
        ):
            await super().heartbeat_attempt(
                envelope,
                lease_token=lease_token,
                progress_percent=progress_percent,
                progress_message=progress_message,
            )
            return _Response(lease_valid=True, cancel_requested=True)

    registry = HandlerRegistry()
    registry.register("example.task", 1, SlowHandler())
    client = Client()

    result = await run_queue_envelope(
        _payload(),
        client=client,  # type: ignore[arg-type]
        handlers=registry,
        context=_context(),
    )

    assert result.ack_decision == "no_ack"
    assert result.status == "cancel_requested"
    assert client.completed == []
    assert client.heartbeats


async def test_run_queue_envelope_exposes_progress_reporter_to_handler() -> None:
    class ProgressHandler:
        async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
            await context.report_progress(50, "halfway")
            return HandlerResult(output={"ok": True})

    registry = HandlerRegistry()
    registry.register("example.task", 1, ProgressHandler())
    client = FakeJobClient()

    result = await run_queue_envelope(
        _payload(),
        client=client,  # type: ignore[arg-type]
        handlers=registry,
        context=_context(),
    )

    assert result.ack_decision == "ack"
    assert client.heartbeats == [
        {
            "lease_token": "lease-1",
            "progress_percent": 50,
            "progress_message": "halfway",
        }
    ]


async def test_run_queue_envelope_no_acks_when_progress_reports_cancel() -> None:
    class ProgressHandler:
        async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
            await context.report_progress(50, "halfway")
            return HandlerResult(output={"ok": True})

    class Client(FakeJobClient):
        async def heartbeat_attempt(
            self,
            envelope: QueueEnvelope,
            *,
            lease_token: str,
            progress_percent: int | None = None,
            progress_message: str | None = None,
        ):
            await super().heartbeat_attempt(
                envelope,
                lease_token=lease_token,
                progress_percent=progress_percent,
                progress_message=progress_message,
            )
            return _Response(lease_valid=True, cancel_requested=True)

    registry = HandlerRegistry()
    registry.register("example.task", 1, ProgressHandler())
    client = Client()

    result = await run_queue_envelope(
        _payload(),
        client=client,  # type: ignore[arg-type]
        handlers=registry,
        context=_context(),
    )

    assert result.ack_decision == "no_ack"
    assert result.status == "cancel_requested"
    assert client.completed == []
    assert client.heartbeats == [
        {
            "lease_token": "lease-1",
            "progress_percent": 50,
            "progress_message": "halfway",
        }
    ]
