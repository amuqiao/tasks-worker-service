from __future__ import annotations

import asyncio

from app.job_platform_worker.handlers import WorkerContext
from app.worker.task_modules.long_running_example.schemas import LongRunningTaskInput, LongRunningTaskOutput


class LongRunningTaskService:
    async def run(
        self,
        payload: LongRunningTaskInput,
        *,
        context: WorkerContext,
    ) -> LongRunningTaskOutput:
        for step in range(1, payload.steps + 1):
            context.raise_if_cancel_requested()
            percent = round(step * 100 / payload.steps)
            await context.report_progress(percent, f"step {step}/{payload.steps}")
            await asyncio.sleep(0)
        context.raise_if_cancel_requested()
        return LongRunningTaskOutput(
            ok=True,
            steps_completed=payload.steps,
            worker=context.worker_name,
        )
