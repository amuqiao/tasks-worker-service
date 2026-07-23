from __future__ import annotations

from app.job_platform_worker.handlers import HandlerResult, WorkerContext
from app.job_platform_worker.protocol import QueueEnvelope
from app.worker.task_modules.object_ref_example.schemas import ObjectRefLocation
from app.worker.task_modules.object_ref_example.service import ObjectRefExampleService


class ObjectRefExampleHandler:
    def __init__(self, service: ObjectRefExampleService | None = None) -> None:
        self._service = service or ObjectRefExampleService()

    async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
        if envelope.input_ref is None:
            raise ValueError("object_ref_example requires input_ref")
        idempotency_key = _handler_idempotency_key(envelope)
        output, output_ref = await self._service.run(
            input_ref=ObjectRefLocation.model_validate(envelope.input_ref),
            idempotency_key=idempotency_key,
        )
        return HandlerResult(
            output=output.model_dump(mode="json"),
            output_ref=output_ref.model_dump(mode="json"),
        )


def _handler_idempotency_key(envelope: QueueEnvelope) -> str:
    return f"{envelope.task_name}:v{envelope.task_version}:{envelope.run_id}:{envelope.attempt_id}"
