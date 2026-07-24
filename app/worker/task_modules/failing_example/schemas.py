from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FailingTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(default="planned worker failure", min_length=1)
