from __future__ import annotations

from app.job_platform_worker.handlers import HandlerResult, WorkerContext
from app.job_platform_worker.protocol import QueueEnvelope
from app.worker.task_modules.failing_example.schemas import FailingTaskInput


class FailingExampleHandler:
    async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
        payload = FailingTaskInput.model_validate(envelope.input or {})
        raise RuntimeError(payload.message)
