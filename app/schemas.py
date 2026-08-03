from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["queued", "running", "completed", "failed"]


class JobCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)


class JobUpdate(BaseModel):
    status: JobStatus


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: JobStatus
    created_at: datetime
