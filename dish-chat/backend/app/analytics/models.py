from uuid import UUID, uuid4

from sqlalchemy import Index
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.db.mixin import TimestampMixin


class ChatSummary(Base, TimestampMixin):
    """Per-chat conversation summary and analytics signal."""

    __tablename__ = "chat_summary"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    chat_id: Mapped[str] = mapped_column(index=True)
    owner_email: Mapped[str] = mapped_column(index=True)

    # Optional: which version of the backend / model produced this summary
    model_version: Mapped[str] = mapped_column(default="unknown")

    # Human-readable short summary (first ~4k chars of the LLM output)
    summary_text: Mapped[str] = mapped_column()

    # Full structured payload from the summariser, including:
    # - conversation_quality.{context_continuity,productivity,accuracy,psychoanalysis}
    # - communication_feedback.{bot_strengths,bot_weaknesses,user_suggestions,bot_suggestions}
    # - backend_enhancement_ideas (denormalised copy)
    metrics: Mapped[dict] = mapped_column(JSONB)

    # Denormalised copy of backend_enhancement_ideas for easy querying.
    backend_enhancement_ideas: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        Index("idx_chat_summary_chat_owner", "chat_id", "owner_email"),
    )


class BackendInsight(Base, TimestampMixin):
    """Aggregated suggestions for improving the backend.

    These can be created:
    - Directly from per-chat summaries (source="chat_summary")
    - From periodic review jobs aggregating multiple summaries (source="review")
    - Manually inserted by engineers (source="manual", for example)
    """

    __tablename__ = "backend_insight"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    source: Mapped[str] = mapped_column(
        default="chat_summary",
        comment="chat_summary | review | manual",
    )

    # Arbitrary structured payload with the recommendation content.
    payload: Mapped[dict] = mapped_column(JSONB)

    # Flag that downstream automation or humans can flip when the insight
    # has been actioned.
    applied: Mapped[bool] = mapped_column(default=False)


class WebSearch(Base, TimestampMixin):
    """Web search tracking for analytics and user experience."""

    __tablename__ = "web_searches"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    
    # Chat ID that triggered the search (nullable for non-chat searches)
    chat_id: Mapped[str | None] = mapped_column(index=True, nullable=True)
    
    # The search query
    query: Mapped[str] = mapped_column()
    
    # JSON blob with search results
    results_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_web_searches_chat_id", "chat_id"),
        Index("idx_web_searches_created_at", "created_at"),
    )
