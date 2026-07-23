from __future__ import annotations

import asyncio
import logging
from typing import Any

from taskiq.abc.broker import AckableMessage

from app.core.config import get_settings
from app.worker.taskiq_app import broker
from app.worker.taskiq_tasks import run_queue_envelope_with_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _extract_payload(message_data: bytes) -> dict[str, Any] | None:
    taskiq_message = broker.formatter.loads(message=message_data)
    taskiq_message.parse_labels()
    if taskiq_message.task_name != settings.taskiq.task_name:
        logger.error("worker_unknown_task task_name=%s", taskiq_message.task_name)
        return None
    if len(taskiq_message.args) != 1 or taskiq_message.kwargs:
        logger.error("worker_invalid_taskiq_payload task_name=%s", taskiq_message.task_name)
        return None
    payload = taskiq_message.args[0]
    if not isinstance(payload, dict):
        logger.error("worker_non_object_payload task_name=%s", taskiq_message.task_name)
        return None
    return payload


async def handle_message(message: AckableMessage) -> bool:
    try:
        payload = _extract_payload(message.data)
    except Exception:
        logger.exception("worker_unparseable_taskiq_message")
        await message.ack()
        return True
    if payload is None:
        await message.ack()
        return True

    result = await run_queue_envelope_with_settings(payload)
    if result.ack_decision == "ack":
        await message.ack()
        logger.info("worker_message_acked status=%s", result.status)
        return True

    logger.warning("worker_message_not_acked status=%s details=%s", result.status, result.details)
    return False


async def run_forever() -> None:
    await broker.startup()
    try:
        async for message in broker.listen():
            await handle_message(message)
    finally:
        await broker.shutdown()


def main() -> int:
    logging.basicConfig(level=settings.observability.log_level)
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        logger.info("worker_runner_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
