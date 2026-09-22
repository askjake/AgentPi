from typing import Optional, BinaryIO, Any
from uuid import uuid4
import os.path
import logging
import asyncio
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from pathlib import Path
import shutil
from app.aws.utils import (
    s3_upload_files_to_prefix,
    s3_delete_by_prefix,
    s3_download_file_to_temp,
    s3_download_fileobj,
)
from app.core.utils import datetime_to_iso_utc, copy_as_spooled_temporary_file
from app.embedding.service import embed_document, load_embedding_from_s3
from app.embedding.schemas import EmbeddedDocument
from app.background_mgr import ProgressStatusEnum
from app.background_mgr.service import TaskProgressTracker, get_task_manager
from app.db import get_db_session_ctxmgr

from .repository import AttachmentRepository
from .schemas import (
    AttachmentDBRecord,
    AttachmentUploadError,
    AttachmentSchma,
    AttachmentStatusResp,
    AttachmentFullInfo
)
from .exceptions import AttachmentNotFoundError, NotAuthorizedError, VaultAccessError
from .utils import downsize_image_if_oversized, parse_s3_url
from .storage_utils import is_log_file, save_file_to_agent_sandbox, delete_from_agent_sandbox, load_file_from_agent_sandbox

settings = get_settings()
logger = logging.getLogger(__name__)

def get_attachment_service():
    return AttachmentService()

class AttachmentService:
    def __init__(self, repository: Optional[AttachmentRepository] = None):
        if not repository:
            repository = AttachmentRepository()
        self.attachment_repo = repository
        self.bg_task_mgr = get_task_manager()

    async def _preprocess_attachment(
        self,
        email: str,
        attachment_id: str,
        file: BinaryIO,
        filename: str,
        filetype: str,
        bg_tracker: TaskProgressTracker,
        vault_key: str = ""
    ) -> None:
        # Embed documents
        if filetype in settings.SUPPORTED_DOC_TYPES:
            await embed_document(
                attachment_id,
                file,
                filename,
                filetype,
                output_loc=f"{email}/{attachment_id}",
                vault_key=vault_key,
                bg_tracker=bg_tracker
            )
        # Check image size
        elif filetype in settings.SUPPORTED_IMAGE_TYPES:
            await downsize_image_if_oversized(
                file,
                filename,
                settings.MAX_IMAGE_RES,
                bg_tracker=bg_tracker,
                s3_prefix=f"{email}/{attachment_id}"
            )

        # Set preprocessed to true
        async with get_db_session_ctxmgr() as session:
            progress = await self.bg_task_mgr.get_task_status(session, attachment_id)
            if progress.status == ProgressStatusEnum.ready:
                attachment = await self.attachment_repo.get_one_by_id(session, attachment_id)
                await self.attachment_repo.update(
                    session,
                    db_obj=attachment,
                    obj_in={"preprocessed": True}
                )

    async def _get_fullinfo(
        self,
        db: AsyncSession,
        attachment_ids: list[str],
        email: str,
        vault_key: str = ""
    ) -> dict[str, AttachmentFullInfo | Exception]:
        # Get attachment record
        results = {aid: AttachmentNotFoundError(f"Attachment {aid} not found") for aid in attachment_ids}

        attachments = await self.attachment_repo.get_many_by_ids(db, attachment_ids)
        for attachment in attachments:
            aid = str(attachment.attachment_id)
            if attachment.owner_id != email:
                results[aid] = NotAuthorizedError("Not authorized to access this attachment")

            if attachment.vault_mode and not vault_key:
                results[aid] =  VaultAccessError("Accessing vault attachments requires vault mode")
            
            # Check if we need real-time progress updates
            if attachment.preprocessed:
                progress = 100
                message = ""
                status = ProgressStatusEnum.ready
            else:
                # Try to get real-time status from background tasks
                task_status = await self.bg_task_mgr.get_task_status(db, attachment.attachment_id)
                if task_status:
                    progress = task_status.progress
                    message = task_status.message
                    status = task_status.status
                else:
                    progress = 0
                    message = "Can't find attachment status."
                    status = ProgressStatusEnum.ready
            
            results[aid] = AttachmentFullInfo(
                attachment_id=str(attachment.attachment_id),
                filename=attachment.filename,
                media_type=attachment.media_type,
                created_at=datetime_to_iso_utc(attachment.created_at),
                updated_at=datetime_to_iso_utc(attachment.updated_at),
                vault_mode=attachment.vault_mode,
                owner_id=attachment.owner_id,
                s3_location=attachment.s3_location,
                preprocessed=attachment.preprocessed,
                status=status,
                progress=progress,
                message=message
            )

        return results

    async def upload_files_for_user(
        self,
        files: list[UploadFile],
        email: str,
        db_session: AsyncSession,
        vault_key: str = ""
    ) -> list[AttachmentSchma | AttachmentUploadError]:
        """
        Upload user files to either S3 (images/docs) or agent sandbox (log files).
        Save records to db, and process the files.
        """
        upload_status = [None] * len(files)
        valid_files: list[UploadFile] = []
        valid_indices = []
        is_log = []  # Track which files are log files

        # Input validation and categorization
        for i, f in enumerate(files):
            log_file = is_log_file(f.filename, f.content_type or "")
        
            if log_file:
                # Log files go to agent sandbox
                if f.content_type not in settings.SUPPORTED_LOG_TYPES and                f.content_type not in ['text/plain', 'application/octet-stream']:
                    logger.warning(f"Log file {f.filename} has unusual MIME type: {f.content_type}")
                valid_files.append(f)
                valid_indices.append(i)
                is_log.append(True)
            elif f.content_type in settings.SUPPORTED_DOC_TYPES + settings.SUPPORTED_IMAGE_TYPES:
                # Regular files go to S3
                valid_files.append(f)
                valid_indices.append(i)
                is_log.append(False)
            else:
                upload_status[i] = AttachmentUploadError(
                    filename=f.filename,
                    media_type=f.content_type,
                    error_message="Unsupported file type."
                )

        if not valid_files:
            return upload_status

        # Assign uuid to each file
        att_ids = [str(uuid4()) for _ in valid_files]

        # Separate files for S3 vs local storage
        s3_files = []
        s3_indices = []
        s3_att_ids = []
        local_files = []
        local_indices = []
        local_att_ids = []
    
        for idx, (f, att_id, is_log_file_flag) in enumerate(zip(valid_files, att_ids, is_log)):
            if is_log_file_flag:
                local_files.append(f)
                local_indices.append(valid_indices[idx])
                local_att_ids.append(att_id)
            else:
                s3_files.append(f)
                s3_indices.append(valid_indices[idx])
                s3_att_ids.append(att_id)

        records = []

        # Upload S3 files
        if s3_files:
            bucket = settings.AWS_FILESTORE_BUCKET
            upload_resp = await s3_upload_files_to_prefix(
                bucket=bucket,
                prefix=email,
                files=[f.file for f in s3_files],
                names=[f"{att_id}/{f.filename}" for f, att_id in zip(s3_files, s3_att_ids)]
            )

            for f, i, key, att_id in zip(s3_files, s3_indices, upload_resp, s3_att_ids):
                if key:
                    # Upload success
                    upload_status[i] = AttachmentSchma(
                        attachment_id=att_id,
                        filename=f.filename,
                        media_type=f.content_type,
                        vault_mode=vault_key != "",
                        owner_id=email
                    )
                    records.append(AttachmentDBRecord(
                        **upload_status[i].model_dump(),
                        s3_location=f"s3://{bucket}/{key}"
                    ))
                else:
                    # Upload failed
                    upload_status[i] = AttachmentUploadError(
                        filename=f.filename,
                        media_type=f.content_type,
                        error_message="S3 upload failed."
                    )

        # Save local files (log files) to agent sandbox
        if local_files:
            for f, i, att_id in zip(local_files, local_indices, local_att_ids):
                try:
                    # Reset file pointer
                    f.file.seek(0)
                
                    # Save to local filesystem
                    location = save_file_to_agent_sandbox(
                        f.file,
                        email,
                        att_id,
                        f.filename
                    )
                
                    # Success
                    upload_status[i] = AttachmentSchma(
                        attachment_id=att_id,
                        filename=f.filename,
                        media_type=f.content_type or 'application/octet-stream',
                        vault_mode=vault_key != "",
                        owner_id=email
                    )
                    records.append(AttachmentDBRecord(
                        **upload_status[i].model_dump(),
                        s3_location=location  # Store with local:// prefix
                    ))
                
                except Exception as e:
                    logger.exception(f"Failed to save log file {f.filename}: {e}")
                    upload_status[i] = AttachmentUploadError(
                        filename=f.filename,
                        media_type=f.content_type,
                        error_message=f"Local storage failed: {str(e)}"
                    )

        # Save attachment records to DB
        if records:
            try:
                await self.attachment_repo.create_many(db_session, objs_in=records)
            except Exception as e:
                logger.exception("Failed to save attachment records to database")
                # Mark successful uploads as failed if DB save fails
                for f, i in zip(valid_files, valid_indices):
                    if not isinstance(upload_status[i], AttachmentUploadError):
                        upload_status[i] = AttachmentUploadError(
                            filename=f.filename,
                            media_type=f.content_type,
                            error_message=f"Failed to save attachment record to database: {str(e)}"
                        )

                # Clean up uploaded files
                import asyncio
                tasks = []
                for r in records:
                    if r.s3_location.startswith('s3://'):
                        # Clean up S3
                        bucket = settings.AWS_FILESTORE_BUCKET
                        tasks.append(s3_delete_by_prefix(bucket, prefix=f"{email}/{r.attachment_id}"))
                    elif r.s3_location.startswith('local://'):
                        # Clean up local files
                        from .storage_utils import delete_from_agent_sandbox
                        delete_from_agent_sandbox(r.s3_location)
            
                if tasks:
                    await asyncio.gather(*tasks)
            
                logger.info(f"Cleaned up {len(records)} files after database error")

        # Add file to preprocessing queue
        # Only preprocess non-log files (images/docs)
        for f, i in zip(valid_files, valid_indices):
            if not isinstance(upload_status[i], AttachmentUploadError):
                # Only preprocess non-log files
                if f.content_type in settings.SUPPORTED_DOC_TYPES + settings.SUPPORTED_IMAGE_TYPES:
                    self.bg_task_mgr.add_task(
                        self._preprocess_attachment,
                        upload_status[i].attachment_id,
                        task_type="attachment",
                        email=email,
                        attachment_id=upload_status[i].attachment_id,
                        file=copy_as_spooled_temporary_file(f.file),
                        filename=f.filename,
                        filetype=f.content_type,
                        vault_key=vault_key
                    )
                else:
                    # Log files don't need preprocessing - mark as ready
                    logger.info(f"Log file {f.filename} uploaded, no preprocessing needed")

        return upload_status


    async def get_attachments_status(
        self,
        db: AsyncSession,
        attachment_ids: list[str],
        email: str,
        vault_key: str = ""
    ) -> dict[str, AttachmentStatusResp | None]:
        """
        Get status of multiple attachments with processing information.

        Returns a dictionary with attachment IDs as keys and status objects or None as values.
        None is returned for attachments that don't exist or user isn't authorized to access.
        """
        # Get all attachments info
        attachments = await self._get_fullinfo(db, attachment_ids, email, vault_key)

        # Process each attachment
        result = {
            att_id: (
                AttachmentStatusResp(**attachment.model_dump()) 
                if not isinstance(attachment, Exception)
                else None
            )
            for att_id, attachment in attachments.items()
        }

        return result

    async def get_attachment_file(
        self,
        db: AsyncSession,
        attachment_id: str,
        email: str,
        vault_key: str = ""
    ) -> tuple[str, str, str]:
        """
        Get attachment file for download.

        Args:
            db: Database session
            attachment_id: ID of the attachment to retrieve
            email: User's email address
            vault_key: Optional vault key for accessing vault attachments

        Returns:
            Tuple of (file_object, media_type, filename)

        Raises:
            AttachmentNotFoundError: If attachment doesn't exist
            NotAuthorizedError: If user isn't authorized to access the attachment
            VaultAccessError: If trying to access vault attachment without vault mode
        """
        # Get attachment details
        attachment = next(iter((await self._get_fullinfo(db, [attachment_id], email, vault_key)).values()))

        if isinstance(attachment, Exception):
            raise attachment

        s3_location = attachment.s3_location
        
        if s3_location.startswith('local://'):
            local_path = load_file_from_agent_sandbox(s3_location)
            if local_path is None:
                raise AttachmentNotFoundError(f"File not found: {attachment_id}")
            return str(local_path), attachment.media_type, attachment.filename
        else:
            bucket, key = parse_s3_url(s3_location)
            filepath, _ = await s3_download_file_to_temp(bucket, key)
            return filepath, attachment.media_type, attachment.filename

    async def get_attachment_status(
        self,
        db: AsyncSession,
        attachment_id: str,
        email: str,
        vault_key: str = ""
    ) -> AttachmentStatusResp:
        """
        Get attachment status with processing information.

        Args:
            db: Database session
            attachment_id: ID of the attachment to retrieve status for
            email: User's email address
            vault_key: Optional vault key for accessing vault attachments

        Returns:
            AttachmentStatusResp with status and progress information

        Raises:
            AttachmentNotFoundError: If attachment doesn't exist
            NotAuthorizedError: If user isn't authorized to access the attachment
            VaultAccessError: If trying to access vault attachment without vault mode
        """
        # Get attachment details
        attachment = next(iter((await self._get_fullinfo(db, [attachment_id], email, vault_key)).values()))

        if isinstance(attachment, Exception):
            raise attachment

        # Create base status response
        return AttachmentStatusResp(**attachment.model_dump())
    
    async def download_attachment_internal(
        self,
        db: AsyncSession,
        attachment_ids: list[str],
        email: str,
        vault_key: str = ""
    ) -> dict[str, tuple[AttachmentStatusResp, BinaryIO | EmbeddedDocument] | None]:
        """Download attachments for internal services.
        If an attachment is not ready, return None."""

        results = {aid: None for aid in attachment_ids}
        # Get all attachments info
        attachments = await self._get_fullinfo(db, attachment_ids, email, vault_key)

        for aid, a in attachments.items():
            if isinstance(a, Exception):
                logger.warning(f"Encountered surpressed exception: {str(a)}")
                continue

            if a.status != ProgressStatusEnum.ready:
                logger.warning(f"Attachment is not ready for download: {aid}")
                continue

            if a.media_type in settings.SUPPORTED_IMAGE_TYPES:
                bucket, key = parse_s3_url(a.s3_location)
                fileobj = await s3_download_fileobj(bucket, key)
                results[aid] = (a, fileobj)
            elif a.media_type in settings.SUPPORTED_DOC_TYPES:
                bucket, key = parse_s3_url(a.s3_location)
                prefix = os.path.dirname(key)
                embedding = await load_embedding_from_s3(aid, prefix)
                results[aid] = (a, embedding)
            elif a.media_type in settings.SUPPORTED_LOG_TYPES:
                # Handle log files from local storage
                if a.s3_location.startswith("local://"):
                    local_path = load_file_from_agent_sandbox(a.s3_location)
                    if local_path and local_path.exists():
                        # Open file and return file object
                        fileobj = open(local_path, "rb")
                        results[aid] = (a, fileobj)
                    else:
                        logger.warning(f"Log file not found in local storage: {aid}")
                else:
                    # Handle S3-stored log files (if any)
                    bucket, key = parse_s3_url(a.s3_location)
                    fileobj = await s3_download_fileobj(bucket, key)
                    results[aid] = (a, fileobj)
            else:
                logger.warning(
                    f"Encountered unsupported attachment type: {a.media_type} {aid}"
                )

        return results