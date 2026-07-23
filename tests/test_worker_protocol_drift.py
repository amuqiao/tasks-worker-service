from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from app.worker.manifest import WorkerManifest
from app.worker.protocol import QueueEnvelope


def test_worker_queue_envelope_matches_job_platform_protocol() -> None:
    shared_module = _load_shared_protocol_module()
    shared_queue_envelope = shared_module.QueueEnvelope

    local_schema = QueueEnvelope.model_json_schema()
    shared_schema = shared_queue_envelope.model_json_schema()

    assert set(QueueEnvelope.model_fields) == set(shared_queue_envelope.model_fields)
    assert local_schema["additionalProperties"] is False
    assert shared_schema["additionalProperties"] is False
    assert local_schema["required"] == shared_schema["required"]
    assert local_schema["properties"] == shared_schema["properties"]


def test_worker_manifest_matches_job_platform_protocol() -> None:
    shared_module = _load_shared_manifest_module()
    shared_worker_manifest = shared_module.WorkerManifest

    local_schema = WorkerManifest.model_json_schema()
    shared_schema = shared_worker_manifest.model_json_schema()

    assert set(WorkerManifest.model_fields) == set(shared_worker_manifest.model_fields)
    assert local_schema["additionalProperties"] is False
    assert shared_schema["additionalProperties"] is False
    assert local_schema["properties"].keys() == shared_schema["properties"].keys()
    assert set(local_schema["required"]) == set(shared_schema["required"])


def test_worker_manifest_acceptance_matches_job_platform_protocol() -> None:
    shared_module = _load_shared_manifest_module()
    payload = _base_worker_manifest()

    local_value = WorkerManifest.model_validate(payload)
    shared_value = shared_module.WorkerManifest.model_validate(payload)

    assert local_value.model_dump(mode="json") == shared_value.model_dump(mode="json")


def test_worker_manifest_rejects_duplicate_callers_like_job_platform_protocol() -> None:
    shared_module = _load_shared_manifest_module()
    payload = _base_worker_manifest()
    payload["tasks"][0]["caller_bindings"].append(dict(payload["tasks"][0]["caller_bindings"][0]))

    local_error = _validation_error(WorkerManifest, payload)
    shared_error = _validation_error(shared_module.WorkerManifest, payload)

    assert local_error is not None
    assert shared_error is not None


@pytest.mark.parametrize(
    "payload",
    [
        {"input": {"message": "hello"}},
        {"input_ref": {"uri": "s3://bucket/key.json"}},
        {"input": ["message", "hello"]},
        {"input": "hello"},
    ],
)
def test_worker_queue_envelope_acceptance_matches_job_platform_protocol(payload: dict[str, object]) -> None:
    shared_module = _load_shared_protocol_module()
    base_payload = _base_queue_envelope()

    local_value = QueueEnvelope.model_validate(base_payload | payload)
    shared_value = shared_module.QueueEnvelope.model_validate(base_payload | payload)

    assert local_value.model_dump(mode="json") == shared_value.model_dump(mode="json")


def test_worker_queue_envelope_rejects_missing_input_like_job_platform_protocol() -> None:
    shared_module = _load_shared_protocol_module()
    payload = _base_queue_envelope()

    local_error = _validation_error(QueueEnvelope, payload)
    shared_error = _validation_error(shared_module.QueueEnvelope, payload)

    assert local_error is not None
    assert shared_error is not None


def _base_queue_envelope() -> dict[str, object]:
    schema_hash = "jsonschema-jcs-v1:sha256:" + "a" * 64
    return {
        "protocol_version": 1,
        "run_id": "run-1",
        "node_id": "node-1",
        "node_key": "main",
        "attempt_id": "attempt-1",
        "task_name": "example.task",
        "task_version": 1,
        "queue_name": "job.example-task.v1",
        "input_schema_hash": schema_hash,
        "output_schema_hash": schema_hash,
        "trace_id": "trace-1",
    }


def _base_worker_manifest() -> dict[str, object]:
    return {
        "manifest_version": 1,
        "worker_service": "worker-x",
        "queue_name": "job.example-task.v1",
        "capabilities": ["cpu"],
        "tasks": [
            {
                "task_name": "example.task",
                "task_version": 1,
                "handler": "app.worker.task_modules.example:ExampleTaskHandler",
                "input_schema": {"type": "object", "additionalProperties": True},
                "output_schema": {"type": "object", "additionalProperties": True},
                "timeout_seconds": 300,
                "max_retries": 0,
                "retry_policy": {},
                "idempotency_retention_seconds": 86400,
                "required_worker_capabilities": ["cpu"],
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


def _validation_error(model: type, payload: dict[str, object]) -> ValidationError | None:
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        return exc
    return None


def _load_shared_protocol_module() -> ModuleType:
    protocol_path = (
        Path(__file__).resolve().parents[2]
        / "tasks-platform"
        / "job_platform_protocol"
        / "envelopes.py"
    )
    if not protocol_path.exists():
        raise AssertionError(f"Job Platform protocol source not found: {protocol_path}")

    spec = importlib.util.spec_from_file_location("job_platform_protocol_envelopes_for_drift", protocol_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load Job Platform protocol source: {protocol_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_shared_manifest_module() -> ModuleType:
    protocol_path = (
        Path(__file__).resolve().parents[2]
        / "tasks-platform"
        / "job_platform_protocol"
        / "manifest.py"
    )
    if not protocol_path.exists():
        raise AssertionError(f"Job Platform manifest protocol source not found: {protocol_path}")

    spec = importlib.util.spec_from_file_location("job_platform_protocol_manifest_for_drift", protocol_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load Job Platform manifest protocol source: {protocol_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
