import asyncio
import json
import logging
import textwrap
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.core.llm import get_model
from app.db import get_db_session_ctxmgr

from .models import BackendInsight, ChatSummary


logger = logging.getLogger(__name__)
settings = get_settings()


async def _collect_recent_summaries(
    db: AsyncSession,
    cutoff: datetime,
    limit: int = 200,
) -> List[dict]:
    """Return recent ChatSummary rows as JSON-serialisable dicts."""
    stmt = (
        select(ChatSummary)
        .where(ChatSummary.created_at >= cutoff)  # TimestampMixin field
        .order_by(ChatSummary.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    def _safe_metrics(value):
        # ensure dict-like for json.dumps; fall back to {}
        if isinstance(value, dict):
            return value
        return {}

    return [
        {
            "chat_id": r.chat_id,
            "owner_email": r.owner_email,
            "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
            "model_version": r.model_version,
            "summary_text": r.summary_text,
            "metrics": _safe_metrics(r.metrics),
            "backend_enhancement_ideas": r.backend_enhancement_ideas,
        }
        for r in rows
    ]


async def run_backend_review(days: int = 1) -> None:
    """Aggregate recent ChatSummary rows into BackendInsight recommendations.

    Intended for a periodic job (daily cron / K8s CronJob):
    - Fetch recent ChatSummary entries
    - Ask an LLM to deduplicate and prioritise backend improvements
    - Store recommendations in BackendInsight with source="review"
    """
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=days)

    async with get_db_session_ctxmgr() as db:
        summaries = await _collect_recent_summaries(db, cutoff)
        if not summaries:
            logger.info("No ChatSummary rows found since %s; nothing to review", cutoff)
            return

        model = get_model(efficient=False)

        system = SystemMessage(
            content=textwrap.dedent(
                """\
                You are a senior architect reviewing many conversation-level analytics records from a chatbot system.

                Each record may contain:
                - A conversation summary
                - Conversation-quality metrics
                - Backend enhancement ideas specific to that chat

                Your goal is to aggregate these into a deduplicated list of backlog items that would most improve the chatbot backend.

                Return ONLY valid JSON: a list of recommendation objects like:
                [
                  {
                    "id": "<short stable id>",
                    "title": "<short title>",
                    "description": "<detailed description>",
                    "component": "<component to improve>",
                    "priority": "low|medium|high",
                    "rationale": "<why this matters>"
                  }
                ]

                Rules:
                - Output must be valid JSON (no markdown).
                - Deduplicate similar ideas.
                - Keep IDs stable and human-readable (kebab-case).
                - Prioritize changes that improve reliability, correctness, safety, or developer efficiency.
                """
            ).strip()
        )

        human = HumanMessage(
            content=(
                textwrap.dedent(
                    """\
                    Here are recent per-chat analytics records in JSON form.

                    Analyze them and produce a deduplicated, prioritized list of backend improvement recommendations.
                    """
                ).strip()
                + "\n\n"
                + json.dumps(summaries, ensure_ascii=False)
            )
        )

        resp = await model.ainvoke([system, human])

        content = getattr(resp, "content", None)
        if isinstance(content, list):
            # Bedrock/LC sometimes returns list[dict] parts
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )

        if not isinstance(content, str):
            logger.warning("Backend review produced non-string content; storing generic insight")
            recommendations = [
                {
                    "id": "non-string-output",
                    "title": "Unparsed backend review output",
                    "description": str(content)[:4000],
                    "component": "unknown",
                    "priority": "medium",
                    "rationale": "LLM output could not be parsed as JSON; see description.",
                }
            ]
        else:
            try:
                recommendations = json.loads(content)
                if not isinstance(recommendations, list):
                    raise TypeError("Expected list of recommendations")
            except Exception:  # noqa: BLE001
                logger.warning("Backend review returned non-JSON or unexpected format; storing raw output")
                recommendations = [
                    {
                        "id": "raw-review-output",
                        "title": "Unparsed backend review output",
                        "description": content[:4000],
                        "component": "unknown",
                        "priority": "medium",
                        "rationale": "LLM output could not be parsed as JSON; see description.",
                    }
                ]

        # Store recommendations
        for rec in recommendations:
            if not isinstance(rec, dict):
                rec = {
                    "id": "non-dict-rec",
                    "title": "Non-dict recommendation",
                    "description": str(rec)[:4000],
                    "component": "unknown",
                    "priority": "low",
                    "rationale": "LLM produced a non-dict element in the recommendations list.",
                }
            db.add(BackendInsight(source="review", payload=rec))

        logger.info("Stored %d BackendInsight rows from review job", len(recommendations))


if __name__ == "__main__":
    asyncio.run(run_backend_review())
