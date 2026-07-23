from __future__ import annotations

from app.worker.handlers import HandlerRegistry
from app.worker.task_modules.example import register_handlers as register_example_handlers


def build_worker_registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    register_example_handlers(registry)
    return registry
