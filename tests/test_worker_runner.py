from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.job_platform_worker.runner import handle_message
from app.job_platform_worker.runtime import WorkerRunResult


@dataclass
class FakeMessage:
    data: bytes
    acked: bool = False

    async def ack(self) -> None:
        self.acked = True


async def test_runner_acks_when_runtime_returns_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    message = FakeMessage(_message_data({"attempt_id": "a"}))

    async def fake_run(payload: dict[str, Any]) -> WorkerRunResult:
        return WorkerRunResult(ack_decision="ack", status="completed", details={})

    monkeypatch.setattr("app.job_platform_worker.runner.run_queue_envelope_with_settings", fake_run)

    handled = await handle_message(message)  # type: ignore[arg-type]

    assert handled is True
    assert message.acked is True


async def test_runner_does_not_ack_when_runtime_returns_no_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    message = FakeMessage(_message_data({"attempt_id": "a"}))

    async def fake_run(payload: dict[str, Any]) -> WorkerRunResult:
        return WorkerRunResult(ack_decision="no_ack", status="acquire_unknown", details={})

    monkeypatch.setattr("app.job_platform_worker.runner.run_queue_envelope_with_settings", fake_run)

    handled = await handle_message(message)  # type: ignore[arg-type]

    assert handled is False
    assert message.acked is False


async def test_runner_acks_poison_taskiq_message() -> None:
    message = FakeMessage(b"not-json")

    handled = await handle_message(message)  # type: ignore[arg-type]

    assert handled is True
    assert message.acked is True


def _message_data(payload: dict[str, Any]) -> bytes:
    from app.job_platform_worker.taskiq_app import broker
    from taskiq.message import TaskiqMessage

    return broker.formatter.dumps(
        TaskiqMessage(
            task_id="task-1",
            task_name="job-platform.consume_queue_envelope",
            labels={},
            args=[payload],
            kwargs={},
        )
    ).message
