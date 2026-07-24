from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LongRunningTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: int = Field(default=3, ge=1, le=100)
    delay_seconds: float = Field(default=0, ge=0, le=5)


class LongRunningTaskOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    steps_completed: int
    worker: str
