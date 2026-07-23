from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.job_platform_worker.protocol import QueueEnvelope

ProgressReporter = Callable[[int, str | None], Awaitable[None]]
CancelChecker = Callable[[], bool]


class WorkerCancelRequested(Exception):
    pass


@dataclass(frozen=True, slots=True)
class WorkerContext:
    worker_service: str
    worker_name: str
    worker_session_id: str
    progress_reporter: ProgressReporter | None = None
    cancel_checker: CancelChecker | None = None

    async def report_progress(self, percent: int, message: str | None = None) -> None:
        if self.progress_reporter is None:
            raise RuntimeError("progress reporting is not available outside a leased worker attempt")
        await self.progress_reporter(percent, message)

    def is_cancel_requested(self) -> bool:
        return self.cancel_checker() if self.cancel_checker is not None else False

    def raise_if_cancel_requested(self) -> None:
        if self.is_cancel_requested():
            raise WorkerCancelRequested("Job Service reported cancel_requested")


@dataclass(frozen=True, slots=True)
class HandlerResult:
    output: dict | None = None
    output_ref: dict | None = None


class TaskHandler(Protocol):
    async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
        """Execute business logic for one acquired task."""


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[tuple[str, int], TaskHandler] = {}

    def register(self, task_name: str, task_version: int, handler: TaskHandler) -> None:
        key = (task_name, task_version)
        if key in self._handlers:
            raise ValueError(f"handler already registered for {task_name}@v{task_version}")
        self._handlers[key] = handler

    def get(self, task_name: str, task_version: int) -> TaskHandler | None:
        return self._handlers.get((task_name, task_version))


def build_default_registry() -> HandlerRegistry:
    from app.job_platform_worker.registry import build_worker_registry

    return build_worker_registry()
