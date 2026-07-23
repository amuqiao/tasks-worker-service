from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.worker.protocol import QueueEnvelope


@dataclass(frozen=True, slots=True)
class WorkerContext:
    worker_service: str
    worker_name: str
    worker_session_id: str


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


def build_default_registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register("example.task", 1, ExampleTaskHandler())
    return registry
