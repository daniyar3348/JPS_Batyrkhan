"""Object storage for uploaded files.

Browsers upload and download directly with short-lived signed URLs, so the API never holds a large
file in memory. Two implementations share one interface:

* ``S3Storage`` for production: any S3-compatible service (the platform keeps files in Kazakhstan).
* ``LocalStorage`` for development and tests: files on disk; the signed URLs point to
  ``/api/v1/storage/...`` endpoints served by this application (see ``storage_routes.py``).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import quote

from app.core.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

HEAD_BYTES = 64 * 1024
CHUNK = 1024 * 1024
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.-]{0,250}$")


class StorageError(Exception):
    pass


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    method: str
    headers: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True)
class ObjectDigest:
    size: int
    sha256: str
    head: bytes  # the first bytes of the file, for type detection


class Storage(Protocol):
    def presign_upload(self, key: str, *, content_type: str, size: int) -> PresignedUpload: ...

    def presign_download(self, key: str, *, filename: str, content_type: str) -> str: ...

    async def size(self, key: str) -> int | None:
        """Size in bytes, or None if there is no such object."""
        ...

    async def digest(self, key: str) -> ObjectDigest: ...

    async def put_bytes(self, key: str, data: bytes, *, content_type: str) -> None: ...

    async def get_bytes(self, key: str) -> bytes:
        """The whole object. Used by the worker for files it must rewrite (e.g. to remove metadata)."""
        ...

    async def delete(self, key: str) -> None: ...


def check_key(key: str) -> str:
    if not _KEY.match(key) or ".." in key:
        raise StorageError(f"Invalid storage key: {key!r}")
    return key


def content_disposition(filename: str) -> str:
    """``attachment`` header that keeps non-ASCII names (RFC 6266) with an ASCII fallback."""
    fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", filename) or "file"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


# --------------------------------------------------------------------------- local disk


def _temporary_file_beside(target: Path) -> tuple[int, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    return tempfile.mkstemp(dir=target.parent, prefix=".upload-")


class LocalStorage:
    def __init__(self, root: Path, *, secret: bytes, upload_ttl: int, download_ttl: int) -> None:
        self.root = root
        self.secret = secret
        self.upload_ttl = upload_ttl
        self.download_ttl = download_ttl

    def path(self, key: str) -> Path:
        return self.root / check_key(key)

    # Signed tokens: base64(payload).base64(HMAC-SHA256(payload)).

    def sign(self, payload: dict[str, Any]) -> str:
        body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
        mac = base64.urlsafe_b64encode(hmac.new(self.secret, body, hashlib.sha256).digest()).rstrip(b"=")
        return f"{body.decode()}.{mac.decode()}"

    def verify(self, token: str, operation: str) -> dict[str, Any]:
        try:
            body, mac = token.split(".", 1)
            expected = base64.urlsafe_b64encode(
                hmac.new(self.secret, body.encode(), hashlib.sha256).digest()
            ).rstrip(b"=")
            if not hmac.compare_digest(expected, mac.encode()):
                raise StorageError("Bad signature")
            payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except (ValueError, TypeError) as exc:
            raise StorageError("Malformed link") from exc
        if payload.get("op") != operation:
            raise StorageError("Wrong kind of link")
        if payload.get("exp", 0) < time.time():
            raise StorageError("The link has expired")
        return payload

    def presign_upload(self, key: str, *, content_type: str, size: int) -> PresignedUpload:
        expires = datetime.now(UTC) + timedelta(seconds=self.upload_ttl)
        token = self.sign(
            {
                "op": "put",
                "k": check_key(key),
                "ct": content_type,
                "sz": size,
                "exp": int(expires.timestamp()),
            }
        )
        return PresignedUpload(
            url=f"/api/v1/storage/{token}",
            method="PUT",
            headers={"Content-Type": content_type},
            expires_at=expires,
        )

    def presign_download(self, key: str, *, filename: str, content_type: str) -> str:
        exp = int(time.time()) + self.download_ttl
        token = self.sign({"op": "get", "k": check_key(key), "fn": filename, "ct": content_type, "exp": exp})
        return f"/api/v1/storage/{token}"

    async def write_stream(self, key: str, chunks: AsyncIterator[bytes], *, expected_size: int) -> None:
        """Store an upload, refusing it unless it has exactly the size that was signed."""
        target = self.path(key)
        fd, temp_name = await asyncio.to_thread(_temporary_file_beside, target)
        written = 0
        try:
            with os.fdopen(fd, "wb") as handle:
                async for chunk in chunks:
                    written += len(chunk)
                    if written > expected_size:
                        raise StorageError("The file is larger than declared")
                    await asyncio.to_thread(handle.write, chunk)
            if written != expected_size:
                raise StorageError("The file size does not match what was declared")
            await asyncio.to_thread(os.replace, temp_name, target)
        except BaseException:
            # Not awaited: this must also run when the request is cancelled, and removing one file is quick.
            Path(temp_name).unlink(missing_ok=True)  # noqa: ASYNC240
            raise

    async def size(self, key: str) -> int | None:
        try:
            return (await asyncio.to_thread(self.path(key).stat)).st_size
        except FileNotFoundError:
            return None

    async def digest(self, key: str) -> ObjectDigest:
        def run() -> ObjectDigest:
            sha = hashlib.sha256()
            head = b""
            size = 0
            with self.path(key).open("rb") as handle:
                while chunk := handle.read(CHUNK):
                    if len(head) < HEAD_BYTES:
                        head += chunk[: HEAD_BYTES - len(head)]
                    sha.update(chunk)
                    size += len(chunk)
            return ObjectDigest(size=size, sha256=sha.hexdigest(), head=head)

        return await asyncio.to_thread(run)

    async def get_bytes(self, key: str) -> bytes:
        return await asyncio.to_thread(self.path(key).read_bytes)

    async def put_bytes(self, key: str, data: bytes, *, content_type: str) -> None:
        def write() -> None:
            target = self.path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        await asyncio.to_thread(write)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.path(key).unlink, missing_ok=True)


# --------------------------------------------------------------------------- S3


class S3Storage:
    """boto3 is synchronous; network calls run in a thread. Presigning is local computation."""

    def __init__(self, client: S3Client, bucket: str, *, upload_ttl: int, download_ttl: int) -> None:
        self.client = client
        self.bucket = bucket
        self.upload_ttl = upload_ttl
        self.download_ttl = download_ttl

    @classmethod
    def from_settings(cls, settings: Settings) -> S3Storage:
        import boto3
        from botocore.config import Config

        secret = settings.s3_secret_access_key.get_secret_value() if settings.s3_secret_access_key else None
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=secret,
            config=Config(signature_version="s3v4", s3={"addressing_style": settings.s3_addressing_style}),
        )
        return cls(
            client,
            settings.s3_bucket,
            upload_ttl=settings.upload_url_ttl_seconds,
            download_ttl=settings.download_url_ttl_seconds,
        )

    def presign_upload(self, key: str, *, content_type: str, size: int) -> PresignedUpload:
        # Content-Type and Content-Length are part of the signature: the browser must send exactly these.
        url = self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": check_key(key),
                "ContentType": content_type,
                "ContentLength": size,
            },
            ExpiresIn=self.upload_ttl,
        )
        expires = datetime.now(UTC) + timedelta(seconds=self.upload_ttl)
        return PresignedUpload(
            url=url, method="PUT", headers={"Content-Type": content_type}, expires_at=expires
        )

    def presign_download(self, key: str, *, filename: str, content_type: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": check_key(key),
                "ResponseContentDisposition": content_disposition(filename),
                "ResponseContentType": content_type,
            },
            ExpiresIn=self.download_ttl,
        )

    async def size(self, key: str) -> int | None:
        from botocore.exceptions import ClientError

        try:
            response = await asyncio.to_thread(
                self.client.head_object, Bucket=self.bucket, Key=check_key(key)
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return int(response["ContentLength"])

    async def digest(self, key: str) -> ObjectDigest:
        def run() -> ObjectDigest:
            body = self.client.get_object(Bucket=self.bucket, Key=check_key(key))["Body"]
            sha = hashlib.sha256()
            head = b""
            size = 0
            for chunk in body.iter_chunks(CHUNK):
                if len(head) < HEAD_BYTES:
                    head += chunk[: HEAD_BYTES - len(head)]
                sha.update(chunk)
                size += len(chunk)
            return ObjectDigest(size=size, sha256=sha.hexdigest(), head=head)

        return await asyncio.to_thread(run)

    async def get_bytes(self, key: str) -> bytes:
        def run() -> bytes:
            data: bytes = self.client.get_object(Bucket=self.bucket, Key=check_key(key))["Body"].read()
            return data

        return await asyncio.to_thread(run)

    async def put_bytes(self, key: str, data: bytes, *, content_type: str) -> None:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=check_key(key),
            Body=data,
            ContentType=content_type,
        )

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=check_key(key))


def create_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        return S3Storage.from_settings(settings)
    return LocalStorage(
        Path(settings.storage_local_path).resolve(),
        secret=settings.secret_key.get_secret_value().encode(),
        upload_ttl=settings.upload_url_ttl_seconds,
        download_ttl=settings.download_url_ttl_seconds,
    )
