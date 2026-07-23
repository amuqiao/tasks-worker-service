from __future__ import annotations

from app.worker.task_modules.example.schemas import ExampleTaskInput
from app.worker.task_modules.example.service import ExampleTaskService


async def test_example_task_service_returns_template_output() -> None:
    service = ExampleTaskService()

    output = await service.run(
        ExampleTaskInput(message="hello"),
        input_ref=None,
        worker_name="worker-x-taskiq",
    )

    assert output.ok is True
    assert output.worker == "worker-x-taskiq"
    assert output.input == {"message": "hello"}
    assert output.input_ref is None
