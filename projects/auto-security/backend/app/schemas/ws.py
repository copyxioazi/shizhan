from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class WSEnvelope(BaseModel):
    type: str
    project_id: int
    timestamp: str
    data: dict[str, Any]
