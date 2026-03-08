"""S3 Resume Storage Service
============================
Handles uploading resumes to S3 and generating presigned download URLs.

Environment variables
---------------------
CAREEROS_RESUME_BUCKET   S3 bucket name (default: careeros-resumes)
AWS_REGION               AWS region (default: us-east-1)

Bucket layout
-------------
    resumes/<user_id>/<timestamp>_<filename>   – versioned per user
    resumes/anonymous/<timestamp>_<filename>   – no user_id provided
"""
from __future__ import annotations

import logging
import os
import time
import re

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

RESUME_BUCKET: str = os.getenv("CAREEROS_RESUME_BUCKET", "careeros-resumes")
REGION:        str = os.getenv("AWS_REGION", "us-east-1")

_s3_client = None


def _client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=REGION)
    return _s3_client


def _safe_filename(name: str) -> str:
    """Strip characters that are unsafe in S3 keys."""
    return re.sub(r"[^a-zA-Z0-9._\-]", "_", name)


def upload_resume(
    file_bytes: bytes,
    filename: str,
    user_id: str | None = None,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload resume bytes to S3 and return the S3 object key.

    Args:
        file_bytes:   Raw bytes of the uploaded file.
        filename:     Original filename (used as suffix in the key).
        user_id:      If provided, stored under ``resumes/<user_id>/``.
        content_type: MIME type stored as S3 object metadata.

    Returns:
        The S3 object key, e.g. ``resumes/user_1/1741200000_resume.pdf``.

    Raises:
        RuntimeError: If the S3 upload fails.
    """
    namespace = user_id or "anonymous"
    timestamp = int(time.time())
    safe_name = _safe_filename(filename)
    key = f"resumes/{namespace}/{timestamp}_{safe_name}"

    try:
        _client().put_object(
            Bucket=RESUME_BUCKET,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
            Metadata={
                "user_id":   namespace,
                "original_filename": filename,
            },
        )
        logger.info("Resume uploaded to s3://%s/%s (%d bytes)", RESUME_BUCKET, key, len(file_bytes))
        return key
    except (BotoCoreError, ClientError) as exc:
        logger.error("S3 upload failed for key '%s': %s", key, exc)
        raise RuntimeError(f"Resume upload failed: {exc}") from exc


def get_resume_presigned_url(s3_key: str, expiry_seconds: int = 3600) -> str:
    """Generate a presigned GET URL for a stored resume.

    Args:
        s3_key:         The S3 object key returned by :func:`upload_resume`.
        expiry_seconds: URL validity window in seconds (default: 1 hour).

    Returns:
        HTTPS presigned URL string.
    """
    try:
        url: str = _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": RESUME_BUCKET, "Key": s3_key},
            ExpiresIn=expiry_seconds,
        )
        return url
    except (BotoCoreError, ClientError) as exc:
        logger.error("Failed to generate presigned URL for '%s': %s", s3_key, exc)
        raise RuntimeError(f"Could not generate presigned URL: {exc}") from exc


def ensure_bucket_exists() -> None:
    """Create the resume bucket if it does not already exist.

    Safe to call on every startup — no-ops if the bucket is already present.
    """
    s3 = _client()
    try:
        s3.head_bucket(Bucket=RESUME_BUCKET)
        logger.debug("Resume bucket '%s' already exists.", RESUME_BUCKET)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            logger.info("Creating resume bucket '%s' in %s …", RESUME_BUCKET, REGION)
            if REGION == "us-east-1":
                s3.create_bucket(Bucket=RESUME_BUCKET)
            else:
                s3.create_bucket(
                    Bucket=RESUME_BUCKET,
                    CreateBucketConfiguration={"LocationConstraint": REGION},
                )
            # Block all public access
            s3.put_public_access_block(
                Bucket=RESUME_BUCKET,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                },
            )
            logger.info("Resume bucket '%s' created and locked.", RESUME_BUCKET)
        else:
            raise
