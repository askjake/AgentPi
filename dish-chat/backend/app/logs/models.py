from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Enum as SQLEnum, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.db.mixin import TimestampMixin


class LogIngestionStatus(str, Enum):
    """Lifecycle states for a log-ingestion job."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class LogIngestionJob(Base, TimestampMixin):
    """Database model for a log-ingestion job.

    This is intentionally generic so it can back both:
    - Coverity Assist style analysis; and
    - Local LLM-based summarization.
    """
    __tablename__ = "log_ingestion_job"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # Who owns this job; enforced at the service/router layer.
    owner_email: Mapped[str] = mapped_column(
        nullable=False,
        index=True,
        comment="Email of the user who created the job",
    )

    # Optional association to a chat thread for context.
    chat_id: Mapped[str] = mapped_column(
        nullable=False,
        index=True,
        comment="Chat id this job is related to (as a string UUID)",
    )

    # High-level source of the logs: upload | s3 | github | coverity | other.
    source: Mapped[str] = mapped_column(
        nullable=False,
        default="upload",
        comment="Where the logs originated (upload, s3, github, coverity, etc.)",
    )

    # Raw location hint, e.g. S3 prefix or repository path.
    raw_location: Mapped[str | None] = mapped_column(
        nullable=True,
        comment="Path/URL/S3 prefix where logs live",
    )

    status: Mapped[LogIngestionStatus] = mapped_column(
        SQLEnum(LogIngestionStatus, name="log_ingestion_status"),
        nullable=False,
        default=LogIngestionStatus.PENDING,
    )

    # High-level summary + structured details as returned by the analyser.
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Free-form error text if the job failed.
    error: Mapped[str | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("idx_logs_owner_status", "owner_email", "status"),
    )
