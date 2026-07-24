from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import wave

import numpy as np

from app.integrations.storage import LocalObjectStorage
from app.job_platform_worker.handlers import HandlerRegistry, WorkerContext
from app.job_platform_worker.protocol import QueueEnvelope
from app.job_platform_worker.runtime import run_queue_envelope
from app.worker.task_modules.audio_stem_separation.handler import AudioStemSeparationHandler
from app.worker.task_modules.audio_stem_separation_triton.handler import AudioStemSeparationTritonHandler
from app.worker.task_modules.audio_stem_separation_triton.handler import _input_payload as triton_input_payload
from app.worker.task_modules.audio_stem_shared.service import AudioStemRuntimeConfig, AudioStemSeparationService
from app.worker.task_modules.audio_stem_shared.service import SeparationResult
from tests.test_worker_runtime import FakeJobClient, HASH


def _wav_bytes() -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\x00\x00\x00\x00" * 128)
    return buffer.getvalue()


class FakeSeparator:
    def __init__(self, *, model_service: str = "local") -> None:
        self.model_service = model_service

    def separate(self, mix) -> SeparationResult:
        stems = {
            "drums": np.zeros_like(mix, dtype=np.float32),
            "bass": np.zeros_like(mix, dtype=np.float32),
            "other": np.zeros_like(mix, dtype=np.float32),
            "vocals": np.zeros_like(mix, dtype=np.float32),
        }
        return SeparationResult(
            stems=stems,
            segment_count=1,
            execution_provider="CPUExecutionProvider" if self.model_service == "local" else None,
            triton_model_version="1" if self.model_service == "triton" else None,
        )


async def _service(tmp_path: Path, *, model_service: str = "local") -> AudioStemSeparationService:
    return AudioStemSeparationService(
        AudioStemRuntimeConfig(
            storage=LocalObjectStorage(tmp_path),
            output_bucket="audio-outputs",
            output_region="local",
            output_prefix="audio-stem-test",
        ),
        FakeSeparator(model_service=model_service),
    )


def _audio_input(tmp_path: Path) -> dict:
    content = _wav_bytes()
    key = "inputs/audio.wav"
    path = tmp_path / key
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return {
        "input_audio": {
            "scheme": "local",
            "bucket": "audio-inputs",
            "region": "local",
            "key": key,
            "content_type": "audio/wav",
            "sha256": sha256(content).hexdigest(),
            "size_bytes": len(content),
        },
        "payload_schema_version": "audio-stem-separation:v1",
    }


def _envelope(*, task_name: str, input_payload: dict) -> QueueEnvelope:
    return QueueEnvelope(
        protocol_version=1,
        run_id="run-audio-1",
        node_id="node-1",
        node_key="main",
        attempt_id="attempt-1",
        task_name=task_name,
        task_version=1,
        queue_name="job.example-task.v1",
        input_schema_hash=HASH,
        output_schema_hash=HASH,
        input=input_payload,
        trace_id="trace-1",
    )


def _context() -> WorkerContext:
    return WorkerContext(
        worker_service="worker-x",
        worker_name="worker-x-taskiq",
        worker_session_id="worker-x-local",
    )


async def test_audio_stem_cpu_handler_writes_four_stems(tmp_path: Path) -> None:
    handler = AudioStemSeparationHandler(await _service(tmp_path))

    result = await handler.handle(
        _envelope(task_name="audio_stem_separation", input_payload=_audio_input(tmp_path)),
        _context(),
    )

    assert result.output is not None
    assert result.output["model_service"] == "local"
    assert set(result.output["stems"]) == {"drums", "bass", "other", "vocals"}
    assert result.output["sample_rate"] == 44100
    assert result.output_ref == {
        "scheme": "local",
        "bucket": "audio-outputs",
        "region": "local",
        "key": "audio-stem-test/run-audio-1/manifest.json",
    }
    assert (tmp_path / "audio-stem-test/run-audio-1/vocals.wav").exists()


async def test_audio_stem_triton_handler_uses_triton_model_service_without_fallback(tmp_path: Path) -> None:
    handler = AudioStemSeparationTritonHandler(await _service(tmp_path, model_service="triton"))

    result = await handler.handle(
        _envelope(task_name="audio_stem_separation_triton", input_payload=_audio_input(tmp_path)),
        _context(),
    )

    assert result.output is not None
    assert result.output["model_service"] == "triton"
    assert result.output["triton_model_version"] == "1"
    assert result.output["execution_provider"] is None


async def test_audio_stem_handler_completes_through_worker_runtime(tmp_path: Path) -> None:
    client = FakeJobClient()
    registry = HandlerRegistry()
    registry.register("audio_stem_separation", 1, AudioStemSeparationHandler(await _service(tmp_path)))
    payload = _envelope(task_name="audio_stem_separation", input_payload=_audio_input(tmp_path)).model_dump(mode="json")

    result = await run_queue_envelope(
        payload,
        client=client,  # type: ignore[arg-type]
        handlers=registry,
        context=_context(),
    )

    assert result.ack_decision == "ack"
    assert result.status == "completed"
    assert client.completed[0]["output"]["model_service"] == "local"
    assert client.completed[0]["output_ref"]["key"] == "audio-stem-test/run-audio-1/manifest.json"


async def test_audio_stem_rejects_sha256_mismatch(tmp_path: Path) -> None:
    handler = AudioStemSeparationHandler(await _service(tmp_path))
    payload = _audio_input(tmp_path)
    payload["input_audio"]["sha256"] = "b" * 64

    try:
        await handler.handle(_envelope(task_name="audio_stem_separation", input_payload=payload), _context())
    except ValueError as exc:
        assert "sha256" in str(exc)
    else:
        raise AssertionError("expected sha256 mismatch")


async def test_audio_stem_rejects_wrong_local_namespace(tmp_path: Path) -> None:
    handler = AudioStemSeparationHandler(await _service(tmp_path))
    payload = _audio_input(tmp_path)
    payload["input_audio"]["bucket"] = "other-bucket"

    try:
        await handler.handle(_envelope(task_name="audio_stem_separation", input_payload=payload), _context())
    except ValueError as exc:
        assert "namespace" in str(exc)
    else:
        raise AssertionError("expected namespace rejection")


def test_triton_input_payload_forces_triton_model_service(tmp_path: Path) -> None:
    payload = triton_input_payload(
        _envelope(
            task_name="audio_stem_separation_triton",
            input_payload={"model_service": "local", "input_audio": _audio_input(tmp_path)["input_audio"]},
        ),
        model_service="triton",
    )

    assert payload["model_service"] == "triton"
