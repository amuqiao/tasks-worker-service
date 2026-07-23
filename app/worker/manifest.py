from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from app.schemas.common import StrictBaseModel
from app.worker.handlers import HandlerRegistry, TaskHandler


class ManifestCallerBinding(StrictBaseModel):
    caller_service: str = Field(min_length=1)
    callback_url: str | None = None
    compensation_window_seconds: int = Field(default=86_400, ge=1)


class ManifestTask(StrictBaseModel):
    task_name: str = Field(min_length=1)
    task_version: int = Field(ge=1)
    handler: str = Field(min_length=1)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    timeout_seconds: int = Field(default=300, ge=1)
    max_retries: int = Field(default=0, ge=0)
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    idempotency_retention_seconds: int = Field(default=86_400, ge=1)
    required_worker_capabilities: list[str] = Field(default_factory=list)
    caller_bindings: list[ManifestCallerBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_unique_callers(self) -> "ManifestTask":
        seen: set[str] = set()
        for binding in self.caller_bindings:
            if binding.caller_service in seen:
                raise ValueError(f"duplicate caller binding in task: {self.task_name}@v{self.task_version}")
            seen.add(binding.caller_service)
        return self


class WorkerManifest(StrictBaseModel):
    manifest_version: int = Field(default=1, ge=1)
    worker_service: str = Field(min_length=1)
    queue_name: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    tasks: list[ManifestTask] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_tasks(self) -> "WorkerManifest":
        seen: set[tuple[str, int]] = set()
        for task in self.tasks:
            key = (task.task_name, task.task_version)
            if key in seen:
                raise ValueError(f"duplicate task in manifest: {task.task_name}@v{task.task_version}")
            seen.add(key)
        return self


def load_worker_manifest(path: str | Path) -> WorkerManifest:
    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return WorkerManifest.model_validate(payload)


def build_registry_from_manifest(manifest: WorkerManifest) -> HandlerRegistry:
    registry = HandlerRegistry()
    for task in manifest.tasks:
        registry.register(task.task_name, task.task_version, import_handler(task.handler))
    return registry


def manifest_registration_payload(manifest: WorkerManifest) -> dict[str, Any]:
    return manifest.model_dump(mode="json")


def validate_manifest_runtime(manifest: WorkerManifest, *, worker_service: str, queue_name: str) -> None:
    if manifest.worker_service != worker_service:
        raise ValueError(
            "worker manifest worker_service must match WORKER__SERVICE_NAME: "
            f"{manifest.worker_service} != {worker_service}"
        )
    if manifest.queue_name != queue_name:
        raise ValueError(
            "worker manifest queue_name must match TASKIQ__QUEUE_NAME: "
            f"{manifest.queue_name} != {queue_name}"
        )


def import_handler(path: str) -> TaskHandler:
    module_name, separator, attribute_name = path.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError("handler path must use module:attribute format")
    module = importlib.import_module(module_name)
    candidate = getattr(module, attribute_name)
    handler = candidate() if inspect.isclass(candidate) else candidate
    handle = getattr(handler, "handle", None)
    if handle is None or not inspect.iscoroutinefunction(handle):
        raise TypeError(f"handler must expose async handle(): {path}")
    return handler
