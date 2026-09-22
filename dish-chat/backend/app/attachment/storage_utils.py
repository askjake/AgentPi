"""
Utility functions for file storage - supports both S3 and local filesystem (agent sandbox).
"""
from pathlib import Path
from typing import BinaryIO, Optional
import os
import shutil
import logging

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def is_log_file(filename: str, content_type: str) -> bool:
    """Check if a file is a log file based on filename or content type."""
    if content_type in settings.SUPPORTED_LOG_TYPES:
        return True
    
    filename_lower = filename.lower()
    log_extensions = [
        '.log',
        '.gz',
        '.gzip',
        '.zip',
        '.tar',
        '.tar.gz',
        '.tgz',
    ]
    
    # Check for numbered logs (.log.1, .log.2, etc.)
    import re
    if re.match(r'.*\.log\.\d+$', filename_lower):
        return True
    
    return any(filename_lower.endswith(ext) for ext in log_extensions)


def get_agent_upload_path(email: str, attachment_id: str, filename: str) -> Path:
    """Get the path for storing an upload in the agent sandbox."""
    base_dir = Path(settings.AGENT_UPLOADS_DIR)
    # Organize by user email
    user_dir = base_dir / email.replace('@', '_at_').replace('.', '_')
    file_dir = user_dir / attachment_id
    file_dir.mkdir(parents=True, exist_ok=True)
    
    return file_dir / filename


def save_file_to_agent_sandbox(
    file: BinaryIO,
    email: str,
    attachment_id: str,
    filename: str
) -> str:
    """
    Save a file to the agent sandbox.
    Returns the local file path as a string (prefixed with 'local://')
    """
    try:
        target_path = get_agent_upload_path(email, attachment_id, filename)
        
        # Save the file
        with open(target_path, 'wb') as f:
            shutil.copyfileobj(file, f)
        
        logger.info(f"Saved file to agent sandbox: {target_path}")
        
        # Return with local:// prefix to distinguish from S3 URLs
        return f"local://{target_path}"
    
    except Exception as e:
        logger.error(f"Failed to save file to agent sandbox: {e}")
        raise


def load_file_from_agent_sandbox(location: str) -> Optional[Path]:
    """
    Load a file from the agent sandbox.
    Location should be in format 'local:///path/to/file'
    Returns Path object or None if not found.
    """
    if not location.startswith('local://'):
        return None
    
    file_path = Path(location.replace('local://', ''))
    
    if file_path.exists():
        return file_path
    
    logger.warning(f"File not found in agent sandbox: {file_path}")
    return None


def delete_from_agent_sandbox(location: str) -> bool:
    """
    Delete a file from the agent sandbox.
    Returns True if successful, False otherwise.
    """
    if not location.startswith('local://'):
        return False
    
    file_path = Path(location.replace('local://', ''))
    
    try:
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted file from agent sandbox: {file_path}")
            
            # Try to remove empty parent directories
            try:
                parent = file_path.parent
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
                    # Try one more level up
                    grandparent = parent.parent
                    if grandparent.exists() and not any(grandparent.iterdir()):
                        grandparent.rmdir()
            except:
                pass  # Don't fail if we can't clean up directories
            
            return True
    except Exception as e:
        logger.error(f"Failed to delete file from agent sandbox: {e}")
    
    return False
