from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ObjectRefLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uri: str = Field(min_length=1)
    media_type: str | None = None


class ObjectRefExampleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    idempotency_key: str
    source_uri: str
    result_uri: str
