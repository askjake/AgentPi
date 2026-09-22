from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.dependencies import DBSessionDep, UserEmailDep
from .schemas import LogIngestionCreate, LogIngestionResponse
from .service import LogIngestionService

router = APIRouter(prefix="/logs", tags=["logs"])


@router.post("/", response_model=LogIngestionResponse, status_code=status.HTTP_201_CREATED)
async def create_log_ingestion_job(
    payload: LogIngestionCreate,
    db: DBSessionDep,
    email: UserEmailDep,
) -> LogIngestionResponse:
    """Create a new log-ingestion job.

    This endpoint only records metadata (chat_id, source, raw_location).
    The actual files are attached and analysed via the `/logs/{job_id}/files`
    endpoint.
    """
    svc = LogIngestionService()
    job = await svc.create_job(db=db, owner_email=email, payload=payload)
    return LogIngestionResponse.from_orm(job)


@router.post("/{job_id}/files", response_model=LogIngestionResponse)
async def attach_files_and_analyze(
    job_id: str,
    db: DBSessionDep,
    email: UserEmailDep,
    files: List[UploadFile] = File(...),
) -> LogIngestionResponse:
    """Attach uploaded files to a job and trigger analysis."""
    svc = LogIngestionService()
    try:
        job = await svc.attach_files_and_analyze(
            db=db,
            job_id=job_id,
            owner_email=email,
            files=files,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this job",
        )

    return LogIngestionResponse.from_orm(job)


@router.get("/{job_id}", response_model=LogIngestionResponse)
async def get_log_ingestion_job(
    job_id: str,
    db: DBSessionDep,
    email: UserEmailDep,
) -> LogIngestionResponse:
    """Retrieve the current state of a log-ingestion job."""
    svc = LogIngestionService()
    try:
        job = await svc.get_job(db=db, job_id=job_id, owner_email=email)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this job",
        )

    return LogIngestionResponse.from_orm(job)
