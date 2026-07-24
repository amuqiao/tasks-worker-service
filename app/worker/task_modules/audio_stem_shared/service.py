from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import io
from pathlib import Path
import time
from typing import Any, Protocol

from app.integrations.aliyun_oss import normalize_object_key
from app.integrations.oss_url_ref import CanonicalObjectRef, canonical_ref_from_oss_url_ref, oss_url_ref_from_output_object
from app.integrations.storage import LocalObjectStorage, ObjectStorage
from app.job_platform_worker.handlers import WorkerContext
from app.worker.task_modules.audio_stem_shared.schemas import (
    STEM_NAMES,
    AudioObjectRef,
    AudioStemInput,
    AudioStemModelService,
    AudioStemOutput,
    StemObjectRef,
)

MODEL_ASSET_PATH = Path(__file__).with_name("model_asset.yaml")


@dataclass(frozen=True, slots=True)
class AudioStemRuntimeConfig:
    storage: ObjectStorage
    output_bucket: str
    output_region: str
    output_prefix: str
    public_endpoint: str = ""
    project_root: str = ""
    input_bucket: str = "audio-inputs"
    input_region: str = "cn-shanghai"
    max_input_bytes: int = 200 * 1024 * 1024
    max_duration_seconds: float = 3600


@dataclass(frozen=True, slots=True)
class DecodedAudio:
    mix: Any
    sample_rate: int
    channels: int
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class SeparationResult:
    stems: dict[str, Any]
    segment_count: int
    execution_provider: str | None = None
    triton_model_version: str | None = None


class AudioStemSeparator(Protocol):
    def separate(self, mix: Any) -> SeparationResult:
        ...


class AudioStemSeparationService:
    def __init__(self, config: AudioStemRuntimeConfig, separator: AudioStemSeparator) -> None:
        self._config = config
        self._separator = separator

    async def run(
        self,
        *,
        data: AudioStemInput,
        run_id: str,
        model_service: AudioStemModelService,
        context: WorkerContext,
    ) -> tuple[AudioStemOutput, dict[str, str]]:
        context.raise_if_cancel_requested()
        input_ref = self._canonical_input_ref(data.input_audio)
        self._validate_ref(input_ref)
        await _safe_report_progress(context, 5, "reading input audio")
        content = await self._read_input(input_ref)
        self._validate_content(content, input_ref)

        await _safe_report_progress(context, 15, "decoding input audio")
        decoded = await asyncio.to_thread(_decode_wav, content)
        duration_limit = self._duration_limit(data)
        if decoded.duration_seconds > duration_limit:
            raise ValueError("input audio exceeds configured duration limit")

        await _safe_report_progress(context, 25, "running stem separation")
        separated = await asyncio.to_thread(self._separator.separate, decoded.mix)
        if set(separated.stems) != set(STEM_NAMES):
            raise ValueError("separator did not return all required stems")

        stems: dict = {}
        for index, stem in enumerate(STEM_NAMES, start=1):
            context.raise_if_cancel_requested()
            stem_bytes = await asyncio.to_thread(_wav_bytes, separated.stems[stem], sample_rate=decoded.sample_rate)
            key = self._object_key(self._output_key(run_id=run_id, stem=stem))
            await self._config.storage.put(
                self._config.output_bucket,
                key,
                stem_bytes,
                content_type="audio/wav",
            )
            stems[stem] = StemObjectRef.model_validate(oss_url_ref_from_output_object(
                bucket=self._config.output_bucket,
                region=self._config.output_region,
                key=key,
                content_type="audio/wav",
                content_hash=f"sha256:{sha256(stem_bytes).hexdigest()}",
                public_endpoint=self._config.public_endpoint or None,
            ))
            await _safe_report_progress(context, 25 + index * 15, f"wrote {stem} stem")

        output = AudioStemOutput(
            model_service=model_service,
            stems=stems,
            sample_rate=decoded.sample_rate,
            channels=decoded.channels,
            duration_seconds=round(decoded.duration_seconds, 6),
            segment_count=separated.segment_count,
            execution_provider=separated.execution_provider if model_service == "local" else None,
            triton_model_version=separated.triton_model_version if model_service == "triton" else None,
        )
        output_ref = {
            "scheme": "oss",
            "bucket": self._config.output_bucket,
            "region": self._config.output_region,
            "key": self._object_key(self._output_key(run_id=run_id, stem="manifest")),
        }
        manifest_bytes = output.model_dump_json().encode()
        output_ref["content_type"] = "application/json"
        output_ref["sha256"] = sha256(manifest_bytes).hexdigest()
        output_ref["size_bytes"] = len(manifest_bytes)
        await self._config.storage.put(
            self._config.output_bucket,
            output_ref["key"],
            manifest_bytes,
            content_type="application/json",
        )
        await _safe_report_progress(context, 100, "audio stem separation completed")
        return output, output_ref

    async def _read_input(self, ref: CanonicalObjectRef) -> bytes:
        return await self._config.storage.get(ref.bucket, ref.key)

    def _canonical_input_ref(self, ref: AudioObjectRef) -> CanonicalObjectRef:
        return canonical_ref_from_oss_url_ref(
            ref.model_dump(mode="json"),
            allowed_buckets={self._config.input_bucket},
            allowed_regions={self._config.input_region},
            allowed_content_types={"audio/wav", "audio/x-wav"},
            public_endpoint=self._config.public_endpoint or None,
            public_endpoint_bucket=self._config.input_bucket,
            public_endpoint_region=self._config.input_region,
        )

    def _validate_ref(self, ref: CanonicalObjectRef) -> None:
        if ref.bucket != self._config.input_bucket or ref.region != self._config.input_region:
            raise ValueError("input audio ref is outside the configured OSS namespace")

    def _validate_content(self, content: bytes, ref: CanonicalObjectRef) -> None:
        if len(content) > self._config.max_input_bytes:
            raise ValueError("input audio exceeds configured max input bytes")
        actual = sha256(content).hexdigest()
        if f"sha256:{actual}" != ref.content_hash:
            raise ValueError("input audio sha256 mismatch")

    def _duration_limit(self, data: AudioStemInput) -> float:
        if data.max_duration_seconds is None:
            return self._config.max_duration_seconds
        return min(data.max_duration_seconds, self._config.max_duration_seconds)

    def _output_key(self, *, run_id: str, stem: str) -> str:
        _validate_run_id(run_id)
        prefix = self._config.output_prefix.strip("/")
        suffix = "manifest.json" if stem == "manifest" else f"{stem}.wav"
        return f"{prefix}/{run_id}/{suffix}" if prefix else f"{run_id}/{suffix}"

    def _object_key(self, key: str) -> str:
        return normalize_object_key(self._config.project_root, key)


class HTDemucsONNXSeparator:
    def __init__(self, *, model_dir: Path, execution_provider: str) -> None:
        self.model_dir = model_dir
        self.asset = _load_model_asset()
        self.sample_rate = int(self.asset["runtime"]["sample_rate"])
        self.channels = int(self.asset["runtime"]["channels"])
        self.segment_samples = int(self.asset["runtime"]["segment_samples"])
        self.overlap_ratio = float(self.asset["runtime"]["overlap_ratio"])
        self.execution_provider = execution_provider
        self.sessions = self._load_sessions()

    def separate(self, mix: Any) -> SeparationResult:
        np = _import_numpy()
        if mix.dtype != np.float32:
            raise ValueError("audio mix must be float32")
        if mix.ndim != 2 or mix.shape[0] != self.channels:
            raise ValueError(f"expected stereo audio shape (2, samples), got {mix.shape}")
        total_len = int(mix.shape[1])
        overlap = int(self.segment_samples * self.overlap_ratio)
        stride = self.segment_samples - overlap
        segments = _segment_ranges(total_len=total_len, segment_samples=self.segment_samples, stride=stride)
        window = _make_transition_window(self.segment_samples, self.overlap_ratio)
        output = {stem: np.zeros((self.channels, total_len), dtype=np.float32) for stem in STEM_NAMES}
        weight = np.zeros(total_len, dtype=np.float32)
        started = time.monotonic()

        for start, end in segments:
            chunk = mix[:, start:end]
            if chunk.shape[1] < self.segment_samples:
                chunk = np.pad(chunk, ((0, 0), (0, self.segment_samples - chunk.shape[1])), mode="constant")
            model_input = chunk[np.newaxis, ...].astype(np.float32)
            chunk_len = end - start
            chunk_window = _chunk_window(
                window,
                chunk_len=chunk_len,
                overlap=overlap,
                is_first=start == 0,
                is_last=end == total_len,
            )
            for stem in STEM_NAMES:
                raw = self.sessions[stem].run(["stems"], {"mix": model_input})[0]
                if not isinstance(raw, np.ndarray) or raw.shape != (1, 4, self.channels, self.segment_samples):
                    raise ValueError(f"{stem} ONNX output shape is invalid")
                if raw.dtype != np.float32:
                    raise ValueError(f"{stem} ONNX output dtype is invalid")
                target_row = int(self.asset["experts"][stem]["target_row"])
                output[stem][:, start:end] += raw[0, target_row, :, :chunk_len] * chunk_window
            weight[start:end] += chunk_window

        weight = np.maximum(weight, 1e-8)
        for stem in STEM_NAMES:
            output[stem] /= weight
        return SeparationResult(
            stems=output,
            segment_count=len(segments),
            execution_provider=self.execution_provider,
        )

    def _load_sessions(self) -> dict[str, Any]:
        ort = _import_onnxruntime()
        sessions = {}
        for stem in STEM_NAMES:
            spec = self.asset["experts"][stem]
            path = self.model_dir / str(spec["file"])
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f"audio stem ONNX file missing or empty: {path}")
            if _hash_file(path) != str(spec["sha256"]):
                raise RuntimeError(f"audio stem ONNX sha256 mismatch: {path.name}")
            sessions[stem] = ort.InferenceSession(str(path), providers=[self.execution_provider])
        return sessions


class HTDemucsTritonSeparator:
    def __init__(
        self,
        *,
        url: str,
        token: str,
        model_version: str,
        request_timeout_seconds: float,
    ) -> None:
        self.asset = _load_model_asset()
        self.channels = int(self.asset["runtime"]["channels"])
        self.segment_samples = int(self.asset["runtime"]["segment_samples"])
        self.overlap_ratio = float(self.asset["runtime"]["overlap_ratio"])
        self.model_version = model_version
        self.client = _TritonAudioStemClient(
            url=url,
            token=token,
            model_version=model_version,
            request_timeout_seconds=request_timeout_seconds,
        )

    def separate(self, mix: Any) -> SeparationResult:
        np = _import_numpy()
        if mix.dtype != np.float32:
            raise ValueError("audio mix must be float32")
        if mix.ndim != 2 or mix.shape[0] != self.channels:
            raise ValueError(f"expected stereo audio shape (2, samples), got {mix.shape}")
        total_len = int(mix.shape[1])
        overlap = int(self.segment_samples * self.overlap_ratio)
        stride = self.segment_samples - overlap
        segments = _segment_ranges(total_len=total_len, segment_samples=self.segment_samples, stride=stride)
        window = _make_transition_window(self.segment_samples, self.overlap_ratio)
        output = {stem: np.zeros((self.channels, total_len), dtype=np.float32) for stem in STEM_NAMES}
        weight = np.zeros(total_len, dtype=np.float32)

        for start, end in segments:
            chunk = mix[:, start:end]
            if chunk.shape[1] < self.segment_samples:
                chunk = np.pad(chunk, ((0, 0), (0, self.segment_samples - chunk.shape[1])), mode="constant")
            model_input = chunk[np.newaxis, ...].astype(np.float32)
            chunk_len = end - start
            chunk_window = _chunk_window(
                window,
                chunk_len=chunk_len,
                overlap=overlap,
                is_first=start == 0,
                is_last=end == total_len,
            )
            for stem in STEM_NAMES:
                raw = self.client.infer_stems(model_name=f"htdemucs_ft_{stem}", model_input=model_input)
                if not isinstance(raw, np.ndarray) or raw.shape != (1, 4, self.channels, self.segment_samples):
                    raise ValueError(f"{stem} Triton output shape is invalid")
                if raw.dtype != np.float32:
                    raise ValueError(f"{stem} Triton output dtype is invalid")
                target_row = int(self.asset["experts"][stem]["target_row"])
                output[stem][:, start:end] += raw[0, target_row, :, :chunk_len] * chunk_window
            weight[start:end] += chunk_window

        weight = np.maximum(weight, 1e-8)
        for stem in STEM_NAMES:
            output[stem] /= weight
        return SeparationResult(stems=output, segment_count=len(segments), triton_model_version=self.model_version)


class _TritonAudioStemClient:
    def __init__(self, *, url: str, token: str, model_version: str, request_timeout_seconds: float) -> None:
        if not url.strip():
            raise RuntimeError("AUDIO_STEM_TRITON__URL must be configured")
        if not model_version.strip():
            raise RuntimeError("AUDIO_STEM_TRITON__MODEL_VERSION must be configured")
        try:
            import tritonclient.http as httpclient
        except ModuleNotFoundError as exc:
            raise RuntimeError("tritonclient[http] is not installed") from exc
        self._httpclient = httpclient
        self._token = token
        self._model_version = model_version
        self._request_timeout_seconds = request_timeout_seconds
        self._client = httpclient.InferenceServerClient(
            url=url,
            connection_timeout=request_timeout_seconds,
            network_timeout=request_timeout_seconds,
        )

    def infer_stems(self, *, model_name: str, model_input: Any) -> Any:
        infer_input = self._httpclient.InferInput("mix", model_input.shape, "FP32")
        infer_input.set_data_from_numpy(model_input)
        headers = {"Authorization": self._token} if self._token else None
        result = self._client.infer(
            model_name=model_name,
            model_version=self._model_version,
            inputs=[infer_input],
            outputs=[self._httpclient.InferRequestedOutput("stems")],
            headers=headers,
            timeout=int(self._request_timeout_seconds * 1_000_000),
        )
        return result.as_numpy("stems")


def build_local_audio_stem_config(
    *,
    storage_path: str,
    output_bucket: str,
    output_region: str,
    output_prefix: str,
    input_bucket: str = "audio-inputs",
    input_region: str = "local",
    max_input_bytes: int = 200 * 1024 * 1024,
    max_duration_seconds: float = 3600,
) -> AudioStemRuntimeConfig:
    return AudioStemRuntimeConfig(
        storage=LocalObjectStorage(Path(storage_path)),
        output_bucket=output_bucket,
        output_region=output_region,
        output_prefix=output_prefix,
        input_bucket=input_bucket,
        input_region=input_region,
        max_input_bytes=max_input_bytes,
        max_duration_seconds=max_duration_seconds,
    )


def _decode_wav(content: bytes) -> DecodedAudio:
    sf = _import_soundfile()
    data, sample_rate = sf.read(io.BytesIO(content), dtype="float32", always_2d=True)
    np = _import_numpy()
    if sample_rate != 44100:
        raise ValueError("audio input must be 44100Hz")
    if data.shape[1] != 2:
        raise ValueError("audio input must be stereo")
    mix = np.ascontiguousarray(data.T, dtype=np.float32)
    return DecodedAudio(
        mix=mix,
        sample_rate=int(sample_rate),
        channels=2,
        duration_seconds=float(mix.shape[1] / sample_rate),
    )


def _wav_bytes(audio: Any, *, sample_rate: int) -> bytes:
    sf = _import_soundfile()
    buffer = io.BytesIO()
    sf.write(buffer, audio.T, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def _load_model_asset() -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError("pyyaml is not installed") from exc
    asset = yaml.safe_load(MODEL_ASSET_PATH.read_text(encoding="utf-8"))
    if not isinstance(asset, dict):
        raise RuntimeError("audio stem model_asset.yaml is invalid")
    return asset


def _segment_ranges(*, total_len: int, segment_samples: int, stride: int) -> list[tuple[int, int]]:
    if total_len < 1:
        raise ValueError("audio input must not be empty")
    segment_count = 1 + max(0, (total_len - segment_samples + stride - 1) // stride)
    return [(index * stride, min(index * stride + segment_samples, total_len)) for index in range(segment_count)]


def _make_transition_window(segment_samples: int, overlap_ratio: float) -> Any:
    np = _import_numpy()
    transition = int(segment_samples * overlap_ratio)
    window = np.ones(segment_samples, dtype=np.float32)
    fade = np.linspace(0, 1, transition, dtype=np.float32)
    window[:transition] = fade
    window[-transition:] = fade[::-1]
    return window


def _chunk_window(window: Any, *, chunk_len: int, overlap: int, is_first: bool, is_last: bool) -> Any:
    result = window[:chunk_len].copy()
    edge = min(overlap, chunk_len)
    if is_first:
        result[:edge] = 1.0
    if is_last:
        result[-edge:] = 1.0
    return result


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _import_numpy() -> Any:
    try:
        import numpy as np
    except ModuleNotFoundError as exc:
        raise RuntimeError("numpy is not installed") from exc
    return np


def _import_soundfile() -> Any:
    try:
        import soundfile as sf
    except ModuleNotFoundError as exc:
        raise RuntimeError("soundfile is not installed") from exc
    return sf


def _import_onnxruntime() -> Any:
    try:
        import onnxruntime as ort
    except ModuleNotFoundError as exc:
        raise RuntimeError("onnxruntime is not installed") from exc
    return ort


async def _safe_report_progress(context: WorkerContext, percent: int, message: str) -> None:
    if context.progress_reporter is not None:
        await context.report_progress(percent, message)


def _validate_run_id(run_id: str) -> None:
    if not run_id or run_id.startswith("/") or "/" in run_id:
        raise ValueError("run_id must be a single OSS key segment")
    if run_id in {".", ".."}:
        raise ValueError("run_id must not contain path traversal")
