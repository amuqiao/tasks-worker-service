from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExampleTaskInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str | None = Field(default=None)


class ExampleTaskOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    worker: str
    input: dict[str, Any] | None
    input_ref: dict[str, Any] | None
