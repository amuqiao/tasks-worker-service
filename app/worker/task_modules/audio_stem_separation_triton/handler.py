from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.integrations.storage import build_object_storage
from app.job_platform_worker.handlers import HandlerResult, WorkerContext
from app.job_platform_worker.protocol import QueueEnvelope
from app.worker.task_modules.audio_stem_shared.schemas import AudioStemInput
from app.worker.task_modules.audio_stem_shared.service import (
    AudioStemRuntimeConfig,
    AudioStemSeparationService,
    HTDemucsTritonSeparator,
)


class AudioStemSeparationTritonHandler:
    def __init__(self, service: AudioStemSeparationService | None = None) -> None:
        self._service = service

    async def handle(self, envelope: QueueEnvelope, context: WorkerContext) -> HandlerResult:
        data = AudioStemInput.model_validate(_input_payload(envelope, model_service="triton"))
        output, output_ref = await self._service_or_default().run(
            data=data,
            run_id=envelope.run_id,
            model_service="triton",
            context=context,
        )
        return HandlerResult(output=output.model_dump(mode="json"), output_ref=output_ref)

    def _service_or_default(self) -> AudioStemSeparationService:
        if self._service is not None:
            return self._service
        settings = get_settings()
        if settings.storage.backend != "aliyun_oss":
            raise RuntimeError("audio_stem_separation_triton requires STORAGE__BACKEND=aliyun_oss")
        config = AudioStemRuntimeConfig(
            storage=build_object_storage(settings),
            output_bucket=settings.audio_stem.output_bucket,
            output_region=settings.audio_stem.output_region,
            output_prefix=settings.audio_stem.output_prefix,
            public_endpoint=settings.storage.public_endpoint,
            project_root=settings.storage.project_root,
            input_bucket=settings.audio_stem.input_bucket,
            input_region=settings.audio_stem.input_region,
            max_input_bytes=settings.audio_stem.max_input_bytes,
            max_duration_seconds=settings.audio_stem.max_duration_seconds,
        )
        separator = HTDemucsTritonSeparator(
            url=settings.audio_stem_triton.url,
            token=settings.audio_stem_triton.token_value,
            model_version=settings.audio_stem_triton.model_version,
            request_timeout_seconds=settings.audio_stem_triton.request_timeout_seconds,
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
