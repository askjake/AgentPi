from functools import cache
import boto3
from botocore.config import Config
from app.config import get_settings

settings = get_settings()

def get_s3_client():
    """
    Get an S3 client configured for either AWS S3 or local S3-compatible storage.
    
    Returns:
        boto3.client: Configured S3 client
    """
    client_kwargs = {
        'region_name': settings.AWS_REGION,
    }
    
    # Support for local S3-compatible storage (MinIO, LocalStack)
    if settings.AWS_ENDPOINT_URL:
        client_kwargs['endpoint_url'] = settings.AWS_ENDPOINT_URL
        # For local development, use path-style access (required for MinIO)
        client_kwargs['config'] = Config(
            signature_version='s3v4',
            s3={
                'addressing_style': 'path'
            }
        )
    
    return boto3.client("s3", **client_kwargs)
