from __future__ import annotations

from app.worker.task_modules.object_ref_example.schemas import ObjectRefExampleOutput, ObjectRefLocation


class InMemoryObjectRefExecutionStore:
    def __init__(self) -> None:
        self._records: dict[str, ObjectRefLocation] = {}
        self.side_effect_count = 0

    def write_once(self, *, idempotency_key: str, output_ref: ObjectRefLocation) -> ObjectRefLocation:
        existing = self._records.get(idempotency_key)
        if existing is not None:
            return existing
        self._records[idempotency_key] = output_ref
        self.side_effect_count += 1
        return output_ref


class ObjectRefExampleService:
    def __init__(self, store: InMemoryObjectRefExecutionStore | None = None) -> None:
        self._store = store or InMemoryObjectRefExecutionStore()

    async def run(
        self,
        *,
        input_ref: ObjectRefLocation,
        idempotency_key: str,
    ) -> tuple[ObjectRefExampleOutput, ObjectRefLocation]:
        output_ref = self._store.write_once(
            idempotency_key=idempotency_key,
            output_ref=ObjectRefLocation(
                uri=f"memory://worker-output/{_sanitize_key(idempotency_key)}.json",
                media_type="application/json",
            ),
        )
        output = ObjectRefExampleOutput(
            ok=True,
            idempotency_key=idempotency_key,
            source_uri=input_ref.uri,
            result_uri=output_ref.uri,
        )
        return output, output_ref


def _sanitize_key(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value)
