from __future__ import annotations

from app.worker.handlers import HandlerResult, WorkerContext
from app.worker.protocol import QueueEnvelope


class ExampleTaskHandler:
    async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
        return HandlerResult(
            output={
                "ok": True,
                "worker": context.worker_name,
                "input": envelope.input,
                "input_ref": envelope.input_ref,
            }
        )
