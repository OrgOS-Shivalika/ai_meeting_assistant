"""S3-compatible object storage service.

Same interface for AWS S3 (prod) and MinIO (dev). The differences are pushed
into the boto3 client construction:

* `endpoint_url` is set for MinIO; unset (default AWS) for prod.
* `addressing_style="path"` is required for MinIO; works either way for AWS.

Callers should treat the bucket as opaque — they only see object keys.
"""

from __future__ import annotations

import io
from typing import BinaryIO, Optional

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.config.settings import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class StorageNotConfigured(RuntimeError):
    """Raised when storage operations are attempted without S3 credentials."""


class StorageService:
    def __init__(self) -> None:
        if not (settings.S3_ACCESS_KEY_ID and settings.S3_SECRET_ACCESS_KEY):
            # Configuration is checked lazily — the rest of the app must keep
            # booting even if storage isn't set up.
            self._client = None
            return

        addressing_style = "path" if settings.S3_USE_PATH_STYLE else "auto"
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            region_name=settings.S3_REGION,
            config=BotoConfig(
                s3={"addressing_style": addressing_style},
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        self._bucket = settings.S3_BUCKET

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def _require_client(self):
        if self._client is None:
            raise StorageNotConfigured(
                "S3 not configured: set S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY "
                "(see .env.example)."
            )
        return self._client

    # ------------------------------------------------------------------ ops

    def ensure_bucket(self) -> None:
        """Idempotent bucket creation — safe to call on every app startup.
        Compose's `minio-init` service does the same thing for fresh stacks;
        this is the belt-and-suspenders for non-compose deployments."""
        client = self._require_client()
        try:
            client.head_bucket(Bucket=self._bucket)
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code not in {"404", "NoSuchBucket"}:
                raise

        try:
            if settings.S3_REGION and settings.S3_REGION != "us-east-1":
                client.create_bucket(
                    Bucket=self._bucket,
                    CreateBucketConfiguration={"LocationConstraint": settings.S3_REGION},
                )
            else:
                # us-east-1 must NOT pass LocationConstraint (AWS quirk).
                client.create_bucket(Bucket=self._bucket)
            logger.info("Created S3 bucket: %s", self._bucket)
        except ClientError as e:
            # Race-safe: bucket may have been created by another worker.
            code = e.response.get("Error", {}).get("Code")
            if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise

    def upload_fileobj(
        self,
        file_obj: BinaryIO,
        key: str,
        content_type: Optional[str] = None,
    ) -> None:
        """Streaming upload — does not buffer the whole file in memory."""
        client = self._require_client()
        extra_args = {"ContentType": content_type} if content_type else {}
        client.upload_fileobj(file_obj, self._bucket, key, ExtraArgs=extra_args)

    def upload_bytes(self, data: bytes, key: str, content_type: Optional[str] = None) -> None:
        self.upload_fileobj(io.BytesIO(data), key, content_type=content_type)

    def download_to_file(self, key: str, path: str) -> None:
        client = self._require_client()
        client.download_file(self._bucket, key, path)

    def download_bytes(self, key: str) -> bytes:
        client = self._require_client()
        buf = io.BytesIO()
        client.download_fileobj(self._bucket, key, buf)
        return buf.getvalue()

    def presigned_get_url(self, key: str, expires_in: int = 3600) -> str:
        client = self._require_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def delete(self, key: str) -> None:
        client = self._require_client()
        client.delete_object(Bucket=self._bucket, Key=key)

    def head_object(self, key: str) -> Optional[dict]:
        client = self._require_client()
        try:
            return client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise


# Module-level singleton — boto3 clients are thread-safe.
storage = StorageService()
