# shared/storage.py
"""Access to object storage (our data lake) through the standard S3 API.

We use `boto3`, the same library used for Amazon S3. Because the S3 API is a
standard, this code works unchanged against Silo/MinIO locally and AWS S3 in
production. Only the endpoint URL and credentials change.
"""

import logging
import time
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class ObjectStorage:
    """Thin wrapper around an S3 client with only the operations we need.

    Wrapping the library keeps S3 details in one place, and lets tests replace
    this class with a simple in-memory fake.
    """

    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, region: str = "us-east-1"):
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                signature_version="s3v4",
                # Path style: http://host:9000/bucket/key (needed for local servers).
                s3={"addressing_style": "path"},
                # Newer boto3 adds extra checksums that some S3-compatible servers
                # do not understand; only use them when strictly required.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                retries={"max_attempts": 3},
            ),
        )

    def ensure_bucket(self, bucket: str) -> None:
        """Create a bucket if it does not exist yet (safe to call repeatedly).

        Args:
            bucket: Bucket name, e.g. "raw".
        """
        try:
            self._client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchBucket", "NotFound"}:
                self._client.create_bucket(Bucket=bucket)
                logger.info("Created bucket '%s'", bucket)
            else:
                raise

    def wait_until_ready(self, buckets: list[str], timeout_seconds: int = 90) -> None:
        """Wait for the storage server to accept connections, then create buckets.

        Containers start in parallel, so storage may not be ready when we start.
        We simply retry until it answers or the timeout is reached.

        Args:
            buckets: Buckets that must exist.
            timeout_seconds: Give up (raise) after this many seconds.
        """
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                for bucket in buckets:
                    self.ensure_bucket(bucket)
                return
            except Exception as exc:  # Any connection problem means "not ready yet".
                if time.monotonic() >= deadline:
                    raise
                logger.info("Object storage not ready yet (%s). Retrying...", type(exc).__name__)
                time.sleep(2)

    def upload_file(
        self,
        bucket: str,
        key: str,
        local_path: Path,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Upload a local file as an object.

        Args:
            bucket: Destination bucket.
            key: Object name inside the bucket (like a path), e.g. "a/b/file.parquet".
            local_path: File on local disk.
            content_type: Optional MIME type.
            metadata: Optional small text labels stored with the object.
        """
        extra: dict = {}
        if content_type:
            extra["ContentType"] = content_type
        if metadata:
            extra["Metadata"] = metadata
        self._client.upload_file(str(local_path), bucket, key, ExtraArgs=extra or None)

    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str | None = None) -> None:
        """Store in-memory bytes (for example a small JSON report) as an object.

        Args:
            bucket: Destination bucket.
            key: Object key.
            data: The content.
            content_type: Optional MIME type.
        """
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=bucket, Key=key, Body=data, **extra)

    def get_bytes(self, bucket: str, key: str) -> bytes:
        """Read a whole (small) object into memory.

        Args:
            bucket: Bucket name.
            key: Object key.

        Returns:
            The object's content.
        """
        return self._client.get_object(Bucket=bucket, Key=key)["Body"].read()

    def object_exists(self, bucket: str, key: str) -> bool:
        """Check whether an object exists.

        Args:
            bucket: Bucket name.
            key: Object key.

        Returns:
            True if the object exists.
        """
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code", "")) in {
                "404",
                "NoSuchKey",
                "NotFound",
            }:
                return False
            raise

    def list_objects(self, bucket: str, prefix: str = "") -> list[dict]:
        """List objects in a bucket under a prefix.

        Args:
            bucket: Bucket name.
            prefix: Only keys starting with this text are returned.

        Returns:
            A list of dicts with `key`, `size_bytes` and `last_modified`.
        """
        items = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                items.append(
                    {
                        "key": obj["Key"],
                        "size_bytes": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat(),
                    }
                )
        return items

    def download_file(self, bucket: str, key: str, local_path: Path) -> None:
        """Download an object to local disk.

        Args:
            bucket: Bucket name.
            key: Object key.
            local_path: Where to write the file.
        """
        self._client.download_file(bucket, key, str(local_path))

    def is_reachable(self) -> bool:
        """Check that the storage server answers requests.

        Returns:
            True if a simple request succeeds.
        """
        try:
            self._client.list_buckets()
            return True
        except Exception:
            return False
