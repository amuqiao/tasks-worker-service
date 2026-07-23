from __future__ import annotations

from app.core.config import get_settings
from app.job_platform_worker.handlers import HandlerRegistry
from app.job_platform_worker.manifest import build_registry_from_manifest, load_worker_manifest, validate_manifest_runtime


def build_worker_registry(manifest_path: str | None = None) -> HandlerRegistry:
    settings = get_settings()
    manifest = load_worker_manifest(manifest_path or settings.worker.manifest_path)
    validate_manifest_runtime(manifest, worker_service=settings.worker.service_name, queue_name=settings.taskiq.queue_name)
    return build_registry_from_manifest(manifest)
