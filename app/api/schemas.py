from __future__ import annotations

from pydantic import BaseModel, Field


class GmailPollRequest(BaseModel):
    max_results: int = Field(default=10, ge=1, le=50)
    query: str | None = Field(default=None, max_length=500)
