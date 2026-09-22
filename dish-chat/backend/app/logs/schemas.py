from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .models import LogIngestionStatus


class LogIngestionCreate(BaseModel):
    chat_id: str
    source: str = "upload"  # or s3, github, coverity
    raw_location: str | None = None


class LogIngestionResponse(BaseModel):
    """API response schema for a log-ingestion job."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chat_id: str
    status: LogIngestionStatus
    summary: dict | None = None
    details: dict | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
