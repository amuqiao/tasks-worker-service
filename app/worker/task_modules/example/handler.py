from __future__ import annotations

from app.job_platform_worker.handlers import HandlerResult, WorkerContext
from app.job_platform_worker.protocol import QueueEnvelope
from app.worker.task_modules.example.schemas import ExampleTaskInput
from app.worker.task_modules.example.service import ExampleTaskService


class ExampleTaskHandler:
    def __init__(self, service: ExampleTaskService | None = None) -> None:
        self._service = service or ExampleTaskService()

    async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
        payload = ExampleTaskInput.model_validate(envelope.input) if envelope.input is not None else None
        output = await self._service.run(
            payload,
            input_ref=envelope.input_ref,
            worker_name=context.worker_name,
        )
        return HandlerResult(output=output.model_dump(mode="json"))
