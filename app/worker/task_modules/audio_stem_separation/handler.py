from __future__ import annotations

from typing import Any
from pathlib import Path

from app.core.config import get_settings
from app.job_platform_worker.handlers import HandlerResult, WorkerContext
from app.job_platform_worker.protocol import QueueEnvelope
from app.worker.task_modules.audio_stem_shared.schemas import AudioStemInput
from app.worker.task_modules.audio_stem_shared.service import (
    AudioStemSeparationService,
    HTDemucsONNXSeparator,
    build_local_audio_stem_config,
)


class AudioStemSeparationHandler:
    def __init__(self, service: AudioStemSeparationService | None = None) -> None:
        self._service = service

    async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
        data = AudioStemInput.model_validate(_input_payload(envelope, model_service="local"))
        output, output_ref = await self._service_or_default().run(
            data=data,
            run_id=envelope.run_id,
            model_service="local",
            context=context,
        )
        return HandlerResult(output=output.model_dump(mode="json"), output_ref=output_ref)

    def _service_or_default(self) -> AudioStemSeparationService:
        if self._service is not None:
            return self._service
        settings = get_settings()
        if settings.storage.backend != "local":
            raise RuntimeError("audio_stem_separation requires STORAGE__BACKEND=local for the local worker adapter")
        config = build_local_audio_stem_config(
            storage_path=settings.storage.local_path,
            output_bucket=settings.audio_stem.output_bucket,
            output_region=settings.audio_stem.output_region,
            output_prefix=settings.audio_stem.output_prefix,
            input_bucket=settings.audio_stem.input_bucket,
            input_region=settings.audio_stem.input_region,
            max_input_bytes=settings.audio_stem.max_input_bytes,
            max_duration_seconds=settings.audio_stem.max_duration_seconds,
        )
        separator = HTDemucsONNXSeparator(
            model_dir=Path(settings.audio_stem.model_dir),
            execution_provider=settings.audio_stem.execution_provider,
        )
        self._service = AudioStemSeparationService(config, separator)
        return self._service


def _input_payload(envelope: QueueEnvelope, *, model_service: str) -> dict[str, Any]:
    if envelope.input is not None:
        payload = dict(envelope.input)
    elif envelope.input_ref is not None:
        payload = {"input_audio": envelope.input_ref}
    else:
        raise ValueError("audio stem task requires input or input_ref")
    payload["model_service"] = model_service
    return payload
