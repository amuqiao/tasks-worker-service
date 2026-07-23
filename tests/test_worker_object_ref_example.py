from __future__ import annotations

from app.job_platform_worker.handlers import WorkerContext
from app.job_platform_worker.protocol import QueueEnvelope
from app.worker.task_modules.object_ref_example.handler import ObjectRefExampleHandler
from app.worker.task_modules.object_ref_example.schemas import ObjectRefLocation
from app.worker.task_modules.object_ref_example.service import InMemoryObjectRefExecutionStore, ObjectRefExampleService

HASH = "jsonschema-jcs-v1:sha256:" + "a" * 64


def _envelope() -> QueueEnvelope:
    return QueueEnvelope(
        protocol_version=1,
        run_id="run-1",
        node_id="node-1",
        node_key="main",
        attempt_id="attempt-1",
        task_name="example.object_ref",
        task_version=1,
        queue_name="job.example-task.v1",
        input_schema_hash=HASH,
        output_schema_hash=HASH,
        input_ref={"uri": "s3://bucket/input.json", "media_type": "application/json"},
        trace_id="trace-1",
    )


def _context() -> WorkerContext:
    return WorkerContext(
        worker_service="worker-x",
        worker_name="worker-x-taskiq",
        worker_session_id="worker-x-local",
    )


async def test_object_ref_example_service_is_idempotent_per_key() -> None:
    store = InMemoryObjectRefExecutionStore()
    service = ObjectRefExampleService(store)

    first_output, first_ref = await service.run(
        input_ref=ObjectRefLocation(uri="s3://bucket/input.json"),
        idempotency_key="key-1",
    )
    second_output, second_ref = await service.run(
        input_ref=ObjectRefLocation(uri="s3://bucket/input.json"),
        idempotency_key="key-1",
    )

    assert store.side_effect_count == 1
    assert second_ref == first_ref
    assert second_output.result_uri == first_output.result_uri


async def test_object_ref_example_handler_returns_output_and_output_ref() -> None:
    handler = ObjectRefExampleHandler()

    result = await handler.handle(_envelope(), _context())

    assert result.output is not None
    assert result.output["ok"] is True
    assert result.output["source_uri"] == "s3://bucket/input.json"
    assert result.output_ref == {
        "uri": result.output["result_uri"],
        "media_type": "application/json",
    }
