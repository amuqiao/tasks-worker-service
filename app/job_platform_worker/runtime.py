from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from app.job_platform_worker.handlers import HandlerRegistry, WorkerCancelRequested, WorkerContext
from app.job_platform_worker.handlers import TaskHandler
from app.job_platform_worker.job_client import JobServiceApiError, JobServiceClient, JobServiceProtocolError
from app.job_platform_worker.protocol import AcquireAttemptResponse, QueueEnvelope

AckDecision = Literal["ack", "no_ack"]


@dataclass(frozen=True, slots=True)
class WorkerRunResult:
    ack_decision: AckDecision
    status: str
    details: dict[str, Any]

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


class WorkerLeaseLost(Exception):
    pass


def _ack(status: str, **details: Any) -> WorkerRunResult:
    return WorkerRunResult(ack_decision="ack", status=status, details=details)


def _no_ack(status: str, **details: Any) -> WorkerRunResult:
    return WorkerRunResult(ack_decision="no_ack", status=status, details=details)


def _api_error_details(exc: JobServiceApiError) -> dict[str, Any]:
    return {
        "code": exc.code,
        "retryable": exc.retryable,
        "details": exc.details,
        "status_code": exc.status_code,
    }


async def run_queue_envelope(
    payload: dict[str, Any],
    *,
    client: JobServiceClient,
    handlers: HandlerRegistry,
    context: WorkerContext,
) -> WorkerRunResult:
    try:
        envelope = QueueEnvelope.model_validate(payload)
    except ValidationError as exc:
        return _ack("poison_message", errors=exc.errors())

    handler = handlers.get(envelope.task_name, envelope.task_version)
    if handler is None:
        return _no_ack(
            "handler_missing",
            task_name=envelope.task_name,
            task_version=envelope.task_version,
        )

    try:
        acquired = await client.acquire_attempt(
            envelope,
            worker_session_id=context.worker_session_id,
            worker_name=context.worker_name,
        )
    except JobServiceApiError as exc:
        if exc.code == "ATTEMPT_NOT_ACQUIRABLE" and exc.details.get("safe_to_ack") is True:
            return _ack("attempt_not_acquirable_safe_to_ack", **_api_error_details(exc))
        return _no_ack("acquire_rejected", **_api_error_details(exc))
    except (httpx.TransportError, JobServiceProtocolError) as exc:
        return _no_ack("acquire_unknown", error_type=type(exc).__name__, message=str(exc))

    try:
        lease_token = _require_lease_token(acquired)
    except RuntimeError as exc:
        return _no_ack("acquire_protocol_error", message=str(exc))
    try:
        handler_result = await _run_handler_with_heartbeat(
            handler,
            envelope,
            context,
            client=client,
            acquired=acquired,
            lease_token=lease_token,
        )
    except WorkerLeaseLost as exc:
        return _no_ack("lease_lost", message=str(exc))
    except WorkerCancelRequested as exc:
        return _no_ack("cancel_requested", message=str(exc))
    except Exception as exc:
        return await _report_handler_failure(client, envelope, lease_token, exc)

    try:
        completed = await client.complete_attempt(
            envelope,
            lease_token=lease_token,
            output=handler_result.output,
            output_ref=handler_result.output_ref,
        )
    except JobServiceApiError as exc:
        return _no_ack("complete_rejected", **_api_error_details(exc))
    except (httpx.TransportError, JobServiceProtocolError) as exc:
        return _no_ack("complete_unknown", error_type=type(exc).__name__, message=str(exc))

    return _ack("completed", run_status=completed.run_status, attempt_id=envelope.attempt_id)


def _require_lease_token(acquired: AcquireAttemptResponse) -> str:
    if not acquired.acquired or not acquired.lease_token:
        raise RuntimeError("Job Service returned acquired=false or missing lease_token for successful acquire")
    return acquired.lease_token


async def _run_handler_with_heartbeat(
    handler: TaskHandler,
    envelope: QueueEnvelope,
    context: WorkerContext,
    *,
    client: JobServiceClient,
    acquired: AcquireAttemptResponse,
    lease_token: str,
):
    heartbeat_interval = acquired.heartbeat_interval_seconds
    if heartbeat_interval is None:
        raise RuntimeError("Job Service returned missing heartbeat_interval_seconds")
    if acquired.cancel_requested:
        raise WorkerCancelRequested("Job Service reported cancel_requested during acquire")

    stop_event = asyncio.Event()
    state = _ExecutionState()
    execution_context = _context_with_runtime_hooks(
        context,
        client=client,
        envelope=envelope,
        lease_token=lease_token,
        state=state,
    )
    handler_task = asyncio.create_task(handler.handle(envelope, execution_context))
    heartbeat_task = asyncio.create_task(
        _heartbeat_until_stopped(
            client,
            envelope,
            lease_token=lease_token,
            interval_seconds=heartbeat_interval,
            stop_event=stop_event,
            state=state,
        )
    )
    done, pending = await asyncio.wait(
        {handler_task, heartbeat_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    if heartbeat_task in done:
        handler_task.cancel()
        await asyncio.gather(handler_task, return_exceptions=True)
        return heartbeat_task.result()

    stop_event.set()
    heartbeat_task.cancel()
    await asyncio.gather(heartbeat_task, return_exceptions=True)
    return handler_task.result()


async def _heartbeat_until_stopped(
    client: JobServiceClient,
    envelope: QueueEnvelope,
    *,
    lease_token: str,
    interval_seconds: float,
    stop_event: asyncio.Event,
    state: "_ExecutionState",
) -> None:
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            return
        except TimeoutError:
            pass

        heartbeat = await client.heartbeat_attempt(envelope, lease_token=lease_token)
        if not heartbeat.lease_valid:
            raise WorkerLeaseLost("Job Service reported invalid lease during heartbeat")
        if heartbeat.cancel_requested:
            state.cancel_requested = True
            raise WorkerCancelRequested("Job Service reported cancel_requested during heartbeat")


@dataclass(slots=True)
class _ExecutionState:
    cancel_requested: bool = False


def _context_with_runtime_hooks(
    context: WorkerContext,
    *,
    client: JobServiceClient,
    envelope: QueueEnvelope,
    lease_token: str,
    state: _ExecutionState,
) -> WorkerContext:
    async def report_progress(percent: int, message: str | None) -> None:
        heartbeat = await client.heartbeat_attempt(
            envelope,
            lease_token=lease_token,
            progress_percent=percent,
            progress_message=message,
        )
        if not heartbeat.lease_valid:
            raise WorkerLeaseLost("Job Service reported invalid lease during progress heartbeat")
        if heartbeat.cancel_requested:
            state.cancel_requested = True
            raise WorkerCancelRequested("Job Service reported cancel_requested during progress heartbeat")

    return replace(
        context,
        progress_reporter=report_progress,
        cancel_checker=lambda: state.cancel_requested,
    )


async def _report_handler_failure(
    client: JobServiceClient,
    envelope: QueueEnvelope,
    lease_token: str,
    exc: Exception,
) -> WorkerRunResult:
    details = {"type": type(exc).__name__}
    try:
        failed = await client.fail_attempt(
            envelope,
            lease_token=lease_token,
            error_kind="worker_handler_error",
            error_code="WORKER_HANDLER_FAILED",
            message=str(exc)[:500],
            retryable=False,
            details=details,
        )
    except JobServiceApiError as api_exc:
        return _no_ack("fail_rejected", **_api_error_details(api_exc))
    except (httpx.TransportError, JobServiceProtocolError) as api_exc:
        return _no_ack("fail_unknown", error_type=type(api_exc).__name__, message=str(api_exc))
    return _ack("failed", run_status=failed.run_status, retry_scheduled=failed.retry_scheduled)
