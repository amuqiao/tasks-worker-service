from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from redis.asyncio import Redis
from taskiq.abc.broker import AckableMessage
from taskiq.message import TaskiqMessage
from taskiq_redis import RedisStreamBroker

from app.job_platform_worker.runner import handle_message
from app.job_platform_worker.runtime import WorkerRunResult


pytestmark = [
    pytest.mark.redis_stream_integration,
    pytest.mark.skipif(
        not os.getenv("FASTAPI_LITE_REDIS_STREAM_URL"),
        reason="set FASTAPI_LITE_REDIS_STREAM_URL to run Redis Stream broker integration tests",
    ),
]


async def test_redis_stream_broker_ack_clears_pending_message(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_url = _redis_url()
    queue_name = _queue_name()
    group_name = _group_name()
    broker = _broker(redis_url, queue_name=queue_name, group_name=group_name, consumer_name="consumer-a")
    redis = Redis.from_url(redis_url)

    await broker.startup()
    try:
        async def fake_run(payload: dict[str, Any]) -> WorkerRunResult:
            return WorkerRunResult(ack_decision="ack", status="completed", details={"payload": payload})

        monkeypatch.setattr("app.job_platform_worker.runner.run_queue_envelope_with_settings", fake_run)
        await _kick(broker, queue_name, {"attempt_id": "attempt-1"})
        async with _listen_once(broker) as message:
            handled = await handle_message(message)

        assert handled is True

        pending = await redis.xpending(queue_name, group_name)
        assert pending["pending"] == 0
    finally:
        await broker.shutdown()
        await redis.delete(queue_name)
        await redis.aclose()


async def test_redis_stream_broker_unacked_message_can_be_reclaimed(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_url = _redis_url()
    queue_name = _queue_name()
    group_name = _group_name()
    producer = _broker(redis_url, queue_name=queue_name, group_name=group_name, consumer_name="consumer-a")
    reclaimer = _broker(redis_url, queue_name=queue_name, group_name=group_name, consumer_name="consumer-b")
    redis = Redis.from_url(redis_url)

    await producer.startup()
    await reclaimer.startup()
    try:
        async def fake_no_ack(payload: dict[str, Any]) -> WorkerRunResult:
            return WorkerRunResult(ack_decision="no_ack", status="acquire_unknown", details={"payload": payload})

        monkeypatch.setattr("app.job_platform_worker.runner.run_queue_envelope_with_settings", fake_no_ack)
        await _kick(producer, queue_name, {"attempt_id": "attempt-2"})
        async with _listen_once(producer) as first_message:
            first_payload = first_message.data
            handled = await handle_message(first_message)

        assert handled is False
        pending_before_reclaim = await redis.xpending(queue_name, group_name)
        assert pending_before_reclaim["pending"] == 1

        async def fake_ack(payload: dict[str, Any]) -> WorkerRunResult:
            return WorkerRunResult(ack_decision="ack", status="completed", details={"payload": payload})

        monkeypatch.setattr("app.job_platform_worker.runner.run_queue_envelope_with_settings", fake_ack)
        await asyncio.sleep(0.01)
        async with _listen_once(reclaimer) as reclaimed_message:
            assert reclaimed_message.data == first_payload
            reclaimed_handled = await handle_message(reclaimed_message)

        assert reclaimed_handled is True
        pending_after_reclaim = await redis.xpending(queue_name, group_name)
        assert pending_after_reclaim["pending"] == 0
    finally:
        await producer.shutdown()
        await reclaimer.shutdown()
        await redis.delete(queue_name)
        await redis.aclose()


def _redis_url() -> str:
    value = os.getenv("FASTAPI_LITE_REDIS_STREAM_URL")
    if not value:
        raise RuntimeError("FASTAPI_LITE_REDIS_STREAM_URL is required")
    return value


def _queue_name() -> str:
    return f"fastapi-lite-worker-test-{uuid.uuid4().hex}"


def _group_name() -> str:
    return f"fastapi-lite-worker-test-{uuid.uuid4().hex}"


def _broker(
    redis_url: str,
    *,
    queue_name: str,
    group_name: str,
    consumer_name: str,
) -> RedisStreamBroker:
    return RedisStreamBroker(
        redis_url,
        queue_name=queue_name,
        consumer_group_name=group_name,
        consumer_name=consumer_name,
        xread_block=10,
        idle_timeout=1,
        unacknowledged_batch_size=10,
    )


async def _kick(broker: RedisStreamBroker, queue_name: str, payload: dict[str, Any]) -> None:
    await broker.kick(
        broker.formatter.dumps(
            TaskiqMessage(
                task_id=str(uuid.uuid4()),
                task_name="job-platform.consume_queue_envelope",
                labels={"queue_name": queue_name},
                args=[payload],
                kwargs={},
            )
        )
    )


class _listen_once:
    def __init__(self, broker: RedisStreamBroker) -> None:
        self._listener: AsyncIterator[AckableMessage] | None = None
        self._broker = broker

    async def __aenter__(self) -> AckableMessage:
        listener = self._broker.listen()
        self._listener = listener
        return await asyncio.wait_for(listener.__anext__(), timeout=3)

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._listener is not None:
            await self._listener.aclose()
