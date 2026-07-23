from __future__ import annotations

from app.worker.task_modules.example.schemas import ExampleTaskInput, ExampleTaskOutput


class ExampleTaskService:
    async def run(
        self,
        payload: ExampleTaskInput | None,
        *,
        input_ref: dict | None,
        worker_name: str,
    ) -> ExampleTaskOutput:
        return ExampleTaskOutput(
            ok=True,
            worker=worker_name,
            input=payload.model_dump(mode="json") if payload is not None else None,
            input_ref=input_ref,
        )
