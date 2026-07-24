from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AudioStemModelService = Literal["local", "triton"]
AudioObjectScheme = Literal["local"]
StemName = Literal["drums", "bass", "other", "vocals"]

SUPPORTED_AUDIO_CONTENT_TYPES = frozenset({"audio/wav", "audio/x-wav"})
STEM_NAMES: tuple[StemName, ...] = ("drums", "bass", "other", "vocals")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AudioObjectRef(StrictModel):
    scheme: AudioObjectScheme
    bucket: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    region: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    key: str = Field(min_length=1, max_length=1024)
    content_type: str = Field(min_length=1, max_length=64)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    version_id: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if value.startswith("/") or ".." in value.split("/"):
            raise ValueError("key must be a relative object key")
        return value

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str) -> str:
        if value not in SUPPORTED_AUDIO_CONTENT_TYPES:
            raise ValueError("unsupported audio content_type")
        return value


class AudioStemInput(StrictModel):
    input_audio: AudioObjectRef
    model_service: AudioStemModelService = "local"
    payload_schema_version: str = Field(default="audio-stem-separation:v1", pattern=r"^[A-Za-z0-9._:-]{1,64}$")
    max_duration_seconds: float | None = Field(default=None, gt=0, le=3600)


class StemObjectRef(StrictModel):
    scheme: AudioObjectScheme
    bucket: str = Field(min_length=1, max_length=128)
    region: str = Field(min_length=1, max_length=64)
    key: str = Field(min_length=1, max_length=1024)
    content_type: str = "audio/wav"
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)


class AudioStemOutput(StrictModel):
    ok: bool = True
    model_service: AudioStemModelService
    stems: dict[StemName, StemObjectRef]
    sample_rate: int
    channels: int
    duration_seconds: float
    segment_count: int
    execution_provider: str | None = None
    triton_model_version: str | None = None
