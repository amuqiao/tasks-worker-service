from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil

import pytest

from app.integrations.storage import LocalObjectStorage
from app.job_platform_worker.handlers import WorkerContext
from app.job_platform_worker.protocol import QueueEnvelope
from app.worker.task_modules.audio_stem_separation.handler import AudioStemSeparationHandler
from app.worker.task_modules.audio_stem_shared.service import (
    AudioStemRuntimeConfig,
    AudioStemSeparationService,
    HTDemucsONNXSeparator,
)
from tests.test_worker_runtime import HASH

pytestmark = [
    pytest.mark.audio_cpu_integration,
    pytest.mark.skipif(
        os.environ.get("FASTAPI_LITE_AUDIO_CPU_INTEGRATION") != "1",
        reason="set FASTAPI_LITE_AUDIO_CPU_INTEGRATION=1 to run local audio CPU integration",
    ),
]


async def test_audio_stem_cpu_integration_with_local_sample(tmp_path: Path) -> None:
    source = Path(".data/misc/2485_0003_S6_梁萧.wav")
    if not source.exists():
        pytest.skip("local audio sample is missing")
    content = source.read_bytes()
    input_key = "inputs/sample.wav"
    (tmp_path / "inputs").mkdir()
    shutil.copyfile(source, tmp_path / input_key)

    service = AudioStemSeparationService(
        AudioStemRuntimeConfig(
            storage=LocalObjectStorage(tmp_path),
            output_bucket="audio-outputs",
            output_region="local",
            output_prefix="audio-stem-cpu-integration",
        ),
        HTDemucsONNXSeparator(
            model_dir=Path(os.environ.get("AUDIO_STEM__MODEL_DIR", ".data/models/htdemucs-ft")),
            execution_provider=os.environ.get("AUDIO_STEM__EXECUTION_PROVIDER", "CPUExecutionProvider"),
        ),
    )
    handler = AudioStemSeparationHandler(service)
    result = await handler.handle(
        QueueEnvelope(
            protocol_version=1,
            run_id="run-audio-cpu-integration",
            node_id="node-1",
            node_key="main",
            attempt_id="attempt-1",
            task_name="audio_stem_separation",
            task_version=1,
            queue_name="job.example-task.v1",
            input_schema_hash=HASH,
            output_schema_hash=HASH,
            input={
                "input_audio": {
                    "scheme": "local",
                    "bucket": "audio-inputs",
                    "region": "local",
                    "key": input_key,
                    "content_type": "audio/wav",
                    "sha256": sha256(content).hexdigest(),
                    "size_bytes": len(content),
                },
                "payload_schema_version": "audio-stem-separation:v1",
                "max_duration_seconds": 3600,
            },
            trace_id="trace-1",
        ),
        WorkerContext(
            worker_service="worker-x",
            worker_name="worker-x-taskiq",
            worker_session_id="worker-x-local",
        ),
    )

    assert result.output is not None
    assert result.output["model_service"] == "local"
    assert result.output["sample_rate"] == 44100
    assert set(result.output["stems"]) == {"drums", "bass", "other", "vocals"}
    assert (tmp_path / "audio-stem-cpu-integration/run-audio-cpu-integration/vocals.wav").exists()
