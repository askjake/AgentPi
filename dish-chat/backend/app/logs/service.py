import json
import logging
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional

import httpx
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.llm import get_model
from langchain_core.messages import SystemMessage, HumanMessage

from .models import LogIngestionJob, LogIngestionStatus

logger = logging.getLogger(__name__)
settings = get_settings()


class LogIngestionService:
    """Service layer for log ingestion and analysis.

    Responsibilities:
    - Create and track log ingestion jobs.
    - Attach uploaded files to a job and trigger analysis.
    - Use the Coverity Assist gateway when available.
    - Fall back to local LLM-based summarization when the gateway is
      unavailable or fails.
    """

    async def create_job(
        self,
        db: AsyncSession,
        owner_email: str,
        payload,
    ) -> LogIngestionJob:
        """Create and persist a new log ingestion job."""
        job = LogIngestionJob(
            owner_email=owner_email,
            chat_id=payload.chat_id,
            source=payload.source or "upload",
            raw_location=payload.raw_location,
            status=LogIngestionStatus.PENDING,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job

    async def get_job(
        self,
        db: AsyncSession,
        job_id: str,
        owner_email: str,
    ) -> LogIngestionJob:
        """Fetch a job by id and enforce ownership."""
        job = await db.get(LogIngestionJob, job_id)
        if not job:
            raise ValueError(f"LogIngestionJob {job_id} not found")

        if job.owner_email.lower() != owner_email.lower():
            raise PermissionError("Not authorized to access this job")

        return job

    async def attach_files_and_analyze(
        self,
        db: AsyncSession,
        job_id: str,
        owner_email: str,
        files: Iterable[UploadFile],
    ) -> LogIngestionJob:
        """Attach uploaded files to the job and perform analysis.

        This will:
        - Persist the uploaded files to a temporary directory.
        - Try the Coverity gateway first, if configured.
        - Fall back to local LLM summarisation if the gateway fails
          or is not configured.
        """
        job = await self.get_job(db=db, job_id=job_id, owner_email=owner_email)

        # Move to RUNNING state
        job.status = LogIngestionStatus.RUNNING
        job.error = None
        await db.commit()
        await db.refresh(job)

        file_paths: List[Path] = []
        try:
            # Persist files to a temp dir for downstream tools
            with tempfile.TemporaryDirectory(prefix="logs_job_") as tmpdir:
                tmpdir_path = Path(tmpdir)
                for f in files:
                    if not f.filename:
                        continue
                    dest = tmpdir_path / f.filename
                    content = await f.read()
                    if not content:
                        # Skip zero-byte uploads
                        continue
                    dest.write_bytes(content)
                    file_paths.append(dest)

                if not file_paths:
                    job.status = LogIngestionStatus.FAILED
                    job.error = "All uploaded files were empty"
                    await db.commit()
                    await db.refresh(job)
                    return job

                # Try gateway first (if configured)
                details: Optional[dict] = None
                summary: Optional[dict] = None
                gateway_url = getattr(settings, "COVERITY_GATEWAY_URL", "")
                used_gateway = False

                if gateway_url:
                    try:
                        details = await self._analyze_via_coverity_gateway(file_paths, job)
                        used_gateway = True
                        if isinstance(details, dict):
                            summary = details.get("summary") or details.get("overview")
                    except Exception:
                        logger.exception("Coverity gateway analysis failed; falling back to local LLM")

                if not used_gateway or details is None:
                    # Local LLM-based summarisation
                    summary, details = await self._summarize_logs_locally(file_paths)

                job.status = LogIngestionStatus.SUCCESS
                job.summary = summary
                job.details = details
                job.error = None
                await db.commit()
                await db.refresh(job)
                return job

        except Exception as exc:  # noqa: BLE001
            logger.exception("attach_files_and_analyze failed for job_id=%s", job_id)
            job.status = LogIngestionStatus.FAILED
            job.error = str(exc)
            await db.commit()
            await db.refresh(job)
            return job

    async def _analyze_via_coverity_gateway(
        self,
        file_paths: List[Path],
        job: LogIngestionJob,
    ) -> dict:
        """Send logs to the Coverity Assist gateway for analysis.

        The gateway endpoint and behaviour are intentionally generic so
        the gateway implementation can evolve independently of this
        chat backend.

        Expected response:
        - JSON object with at least a "summary" field, plus any
          additional structured details.
        """
        gateway_url = settings.COVERITY_GATEWAY_URL.rstrip("/")
        url = f"{gateway_url}/analyze-logs"

        logger.info("Sending %d files to Coverity gateway at %s", len(file_paths), url)

        files = [
            ("logs", (path.name, path.read_bytes(), "text/plain"))
            for path in file_paths
        ]

        data = {
            "job_id": str(job.id),
            "source": job.source,
            "chat_id": job.chat_id or "",
            "owner_email": job.owner_email,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, data=data, files=files)
        resp.raise_for_status()

        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gateway returned non-JSON content: %s", exc)
            text = resp.text
            return {
                "summary": {"text": "Gateway returned non-JSON response"},
                "raw": text[:8000],
            }

        if not isinstance(payload, dict):
            return {
                "summary": {"text": "Gateway returned unexpected non-dict JSON"},
                "raw": payload,
            }

        return payload

    async def _summarize_logs_locally(
        self,
        file_paths: List[Path],
        max_chars: int = 12_000,
    ) -> tuple[dict, dict]:
        """Perform a best-effort LLM-based summarisation of the logs.

        We read the logs into a single string (tail-truncated for safety)
        and ask the LLM to produce a structured JSON description of
        what happened, suspected causes, and recommendations.
        """
        chunks: list[str] = []
        for path in file_paths:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                content = path.read_bytes().decode("utf-8", errors="replace")
            header = f"===== FILE: {path.name} =====\n"
            chunks.append(header + content)

        combined = "\n\n".join(chunks)
        if len(combined) > max_chars:
            combined = combined[-max_chars:]

        model = get_model(efficient=True)

        system = SystemMessage(
            content=(
                "You are a senior diagnostics engineer."
                " You receive raw log files from complex distributed systems."
                " Your task is to produce a concise *JSON* analysis summarizing:"
                " 1) what happened, 2) likely root cause(s), 3) recommended next steps, and"
                " 4) any ideas for how the log analysis pipeline itself could be improved.\n\n"
                "Return ONLY valid JSON in the following structure (no prose outside JSON):\n"
                "{\n"
                "  \"summary\": \"<short text>\",\n"
                "  \"timeline\": [\"<key events in order>\"],\n"
                "  \"suspected_root_cause\": \"<text>\",\n"
                "  \"contributing_factors\": [\"<text>\"],\n"
                "  \"impacted_components\": [\"<component or subsystem>\"],\n"
                "  \"recommended_actions\": [\"<action item>\"],\n"
                "  \"confidence\": <number between 0 and 1>,\n"
                "  \"backend_enhancement_ideas\": [\n"
                "    {\n"
                "      \"id\": \"<short stable id>\",\n"
                "      \"title\": \"<short title>\",\n"
                "      \"description\": \"<detailed description of the idea>\",\n"
                "      \"component\": \"<which part of the system to improve>\",\n"
                "      \"priority\": \"low|medium|high\"\n"
                "    }\n"
                "  ]\n"
                "}\n"
            )
        )

        user = HumanMessage(
            content=(
                "Here are the raw logs collected for a single troubleshooting job.\n\n"
                + combined
            )
        )

        resp = await model.ainvoke([system, user])
        content = getattr(resp, "content", None)
        if isinstance(content, list):
            # Some providers return a list of parts; join them.
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )

        if not isinstance(content, str):
            logger.warning(
                "LLM returned non-string content for log summarization: %r",
                content,
            )
            parsed = {
                "summary": {"text": "Log analysis complete (no model content)."},
                "raw": content,
            }
            return parsed.get("summary"), parsed

        try:
            parsed = json.loads(content)
        except Exception:  # noqa: BLE001
            logger.warning(
                "LLM returned non-JSON for log summarization; wrapping as fallback"
            )
            parsed = {
                "summary": {"text": content[:2000]},
                "raw": content,
            }

        summary = parsed.get("summary", {"text": "Log analysis complete"})
        return summary, parsed
