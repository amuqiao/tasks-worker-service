from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.job_platform_worker.manifest import build_registry_from_manifest, load_worker_manifest, validate_manifest_runtime
from app.job_platform_worker.protocol import QueueEnvelope
from app.job_platform_worker.registry import build_worker_registry

HASH = "jsonschema-jcs-v1:sha256:" + "a" * 64


def _manifest_payload(**overrides) -> dict:
    payload = {
        "manifest_version": 1,
        "worker_service": "worker-x",
        "queue_name": "job.example-task.v1",
        "capabilities": ["cpu"],
        "tasks": [
            {
                "task_name": "example.task",
                "task_version": 1,
                "handler": "app.worker.task_modules.example.handler:ExampleTaskHandler",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "caller_bindings": [
                    {
                        "caller_service": "business-api-a",
                        "callback_url": None,
                        "compensation_window_seconds": 3600,
                    }
                ],
            }
        ],
    }
    payload.update(overrides)
    return payload


def _write_manifest(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "worker.manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_build_worker_registry_loads_handler_from_manifest(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, _manifest_payload())

    registry = build_worker_registry(str(path))
    handler = registry.get("example.task", 1)

    assert handler is not None


def test_worker_manifest_rejects_duplicate_tasks(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["tasks"].append(dict(payload["tasks"][0]))
    path = _write_manifest(tmp_path, payload)

    with pytest.raises(ValidationError, match="duplicate task"):
        load_worker_manifest(path)


def test_worker_manifest_rejects_duplicate_caller_bindings(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["tasks"][0]["caller_bindings"].append(dict(payload["tasks"][0]["caller_bindings"][0]))
    path = _write_manifest(tmp_path, payload)

    with pytest.raises(ValidationError, match="duplicate caller binding"):
        load_worker_manifest(path)


def test_worker_manifest_runtime_requires_matching_queue(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, _manifest_payload(queue_name="job.other.v1"))
    manifest = load_worker_manifest(path)

    with pytest.raises(ValueError, match="TASKIQ__QUEUE_NAME"):
        validate_manifest_runtime(manifest, worker_service="worker-x", queue_name="job.example-task.v1")


def test_worker_manifest_rejects_missing_handler_import(tmp_path: Path) -> None:
    payload = _manifest_payload(
        tasks=[
            {
                **_manifest_payload()["tasks"][0],
                "handler": "app.worker.task_modules.example.handler:MissingHandler",
            }
        ]
    )
    path = _write_manifest(tmp_path, payload)

    with pytest.raises(AttributeError):
        build_registry_from_manifest(load_worker_manifest(path))


async def test_manifest_registered_handler_can_execute() -> None:
    manifest = load_worker_manifest("app/worker/manifest.json")
    registry = build_registry_from_manifest(manifest)
    handler = registry.get("example.task", 1)
    assert handler is not None

    from app.job_platform_worker.handlers import WorkerContext

    result = await handler.handle(
        QueueEnvelope(
            protocol_version=1,
            run_id="run-1",
            node_id="node-1",
            node_key="main",
            attempt_id="attempt-1",
            task_name="example.task",
            task_version=1,
            queue_name="job.example-task.v1",
            input_schema_hash=HASH,
            output_schema_hash=HASH,
            input={"message": "hello"},
            trace_id="trace-1",
        ),
        WorkerContext(
            worker_service="worker-x",
            worker_name="worker-x-taskiq",
            worker_session_id="worker-x-local",
        ),
    )

    assert result.output["ok"] is True


async def test_manifest_registered_failing_handler_can_execute_failure_path() -> None:
    manifest = load_worker_manifest("app/worker/manifest.json")
    registry = build_registry_from_manifest(manifest)
    handler = registry.get("example.failing", 1)
    assert handler is not None

    from app.job_platform_worker.handlers import WorkerContext

    with pytest.raises(RuntimeError, match="planned failure"):
        await handler.handle(
            QueueEnvelope(
                protocol_version=1,
                run_id="run-1",
                node_id="node-1",
                node_key="main",
                attempt_id="attempt-1",
                task_name="example.failing",
                task_version=1,
                queue_name="job.example-task.v1",
                input_schema_hash=HASH,
                output_schema_hash=HASH,
                input={"message": "planned failure"},
                trace_id="trace-1",
            ),
            WorkerContext(
                worker_service="worker-x",
                worker_name="worker-x-taskiq",
                worker_session_id="worker-x-local",
            ),
        )


def test_default_manifest_declares_template_example_tasks() -> None:
    manifest = load_worker_manifest("app/worker/manifest.json")

    assert "oss-storage" in manifest.capabilities
    assert {(task.task_name, task.task_version) for task in manifest.tasks} == {
        ("example.task", 1),
        ("example.object_ref", 1),
        ("example.long_running", 1),
        ("example.failing", 1),
        ("audio_stem_separation", 1),
        ("audio_stem_separation_triton", 1),
    }
    audio_tasks = {
        task.task_name: task
        for task in manifest.tasks
        if task.task_name in {"audio_stem_separation", "audio_stem_separation_triton"}
    }
    assert set(audio_tasks) == {"audio_stem_separation", "audio_stem_separation_triton"}
    assert all("oss-storage" in task.required_worker_capabilities for task in audio_tasks.values())
    for task in audio_tasks.values():
        input_audio = task.input_schema["properties"]["input_audio"]
        assert input_audio["required"] == ["public_url", "internal_url", "content_type", "sha256"]
        assert "scheme" not in input_audio["properties"]
        assert "size_bytes" not in input_audio["properties"]
