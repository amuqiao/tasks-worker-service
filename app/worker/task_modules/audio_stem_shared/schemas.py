from __future__ import annotations

from typing import Literal

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator

AudioStemModelService = Literal["local", "triton"]
StemName = Literal["drums", "bass", "other", "vocals"]

SUPPORTED_AUDIO_CONTENT_TYPES = frozenset({"audio/wav", "audio/x-wav"})
STEM_NAMES: tuple[StemName, ...] = ("drums", "bass", "other", "vocals")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AudioObjectRef(StrictModel):
    public_url: AnyUrl
    internal_url: AnyUrl
    content_type: str = Field(min_length=1, max_length=64)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("public_url", "internal_url")
    @classmethod
    def validate_https_url(cls, value: AnyUrl) -> AnyUrl:
        if value.scheme != "https":
            raise ValueError("OSS URL must use https")
        if value.query or value.fragment:
            raise ValueError("OSS URL must not contain query string or fragment")
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
    public_url: AnyUrl
    internal_url: AnyUrl
    content_type: str = "audio/wav"
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


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
