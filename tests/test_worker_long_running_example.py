from __future__ import annotations

import pytest

from app.job_platform_worker.handlers import WorkerCancelRequested, WorkerContext
from app.worker.task_modules.long_running_example.schemas import LongRunningTaskInput
from app.worker.task_modules.long_running_example.service import LongRunningTaskService


async def test_long_running_task_reports_progress_for_each_step() -> None:
    progress: list[tuple[int, str | None]] = []

    async def report_progress(percent: int, message: str | None) -> None:
        progress.append((percent, message))

    context = WorkerContext(
        worker_service="worker-x",
        worker_name="worker-x-taskiq",
        worker_session_id="worker-x-local",
        progress_reporter=report_progress,
    )

    output = await LongRunningTaskService().run(LongRunningTaskInput(steps=4), context=context)

    assert output.steps_completed == 4
    assert progress == [
        (25, "step 1/4"),
        (50, "step 2/4"),
        (75, "step 3/4"),
        (100, "step 4/4"),
    ]


async def test_long_running_task_stops_at_cancel_checkpoint() -> None:
    async def report_progress(percent: int, message: str | None) -> None:
        raise AssertionError("progress should not run after cancel checkpoint")

    context = WorkerContext(
        worker_service="worker-x",
        worker_name="worker-x-taskiq",
        worker_session_id="worker-x-local",
        progress_reporter=report_progress,
        cancel_checker=lambda: True,
    )

    with pytest.raises(WorkerCancelRequested):
        await LongRunningTaskService().run(LongRunningTaskInput(steps=1), context=context)
