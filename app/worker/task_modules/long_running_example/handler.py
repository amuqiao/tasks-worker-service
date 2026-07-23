from __future__ import annotations

from app.job_platform_worker.handlers import HandlerResult, WorkerContext
from app.job_platform_worker.protocol import QueueEnvelope
from app.worker.task_modules.long_running_example.schemas import LongRunningTaskInput
from app.worker.task_modules.long_running_example.service import LongRunningTaskService


class LongRunningExampleHandler:
    def __init__(self, service: LongRunningTaskService | None = None) -> None:
        self._service = service or LongRunningTaskService()

    async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
        payload = LongRunningTaskInput.model_validate(envelope.input or {})
        output = await self._service.run(payload, context=context)
        return HandlerResult(output=output.model_dump(mode="json"))
