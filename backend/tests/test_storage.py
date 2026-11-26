from __future__ import annotations

import hashlib
import socket
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from moto.server import ThreadedMotoServer

from app.core.storage import LocalStorage, S3Storage, StorageError, check_key, content_disposition

PDF = b"%PDF-1.7\n" + b"x" * 5000


async def _chunks(data: bytes, size: int = 1000) -> AsyncIterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


@pytest.fixture
def local(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path, secret=b"test-secret", upload_ttl=60, download_ttl=60)


async def test_local_upload_and_digest(local: LocalStorage):
    ticket = local.presign_upload("submissions/1/a.pdf", content_type="application/pdf", size=len(PDF))
    grant = local.verify(ticket.url.rsplit("/", 1)[1], "put")
    assert grant["k"] == "submissions/1/a.pdf" and grant["sz"] == len(PDF)

    await local.write_stream("submissions/1/a.pdf", _chunks(PDF), expected_size=len(PDF))
    assert await local.size("submissions/1/a.pdf") == len(PDF)
    digest = await local.digest("submissions/1/a.pdf")
    assert digest.sha256 == hashlib.sha256(PDF).hexdigest()
    assert digest.head.startswith(b"%PDF-")
    await local.delete("submissions/1/a.pdf")
    assert await local.size("submissions/1/a.pdf") is None


@pytest.mark.parametrize("declared", [len(PDF) - 1, len(PDF) + 1])
async def test_local_rejects_wrong_size(local: LocalStorage, declared: int):
    with pytest.raises(StorageError):
        await local.write_stream("a/b.pdf", _chunks(PDF), expected_size=declared)
    assert await local.size("a/b.pdf") is None
    assert not any(local.root.rglob(".upload-*"))  # no temporary files left behind


def test_local_tokens_cannot_be_forged_or_reused_after_expiry(local: LocalStorage):
    url = local.presign_download("a/b.pdf", filename="b.pdf", content_type="application/pdf")
    token = url.rsplit("/", 1)[1]
    assert local.verify(token, "get")["k"] == "a/b.pdf"
    with pytest.raises(StorageError):
        local.verify(token, "put")  # a download link is not an upload link
    body, mac = token.split(".")
    with pytest.raises(StorageError):
        local.verify(body[:-2] + "AA." + mac, "get")
    other = LocalStorage(local.root, secret=b"another-secret", upload_ttl=60, download_ttl=60)
    with pytest.raises(StorageError):
        other.verify(token, "get")
    expired = local.sign({"op": "get", "k": "a/b.pdf", "fn": "b.pdf", "ct": "x", "exp": int(time.time()) - 1})
    with pytest.raises(StorageError):
        local.verify(expired, "get")


@pytest.mark.parametrize("key", ["../etc/passwd", "/abs/path", "a/../../b", "", "a b"])
def test_storage_keys_are_restricted(key: str):
    with pytest.raises(StorageError):
        check_key(key)


def test_content_disposition_keeps_unicode_names():
    header = content_disposition('Статья "final".pdf')
    assert header.startswith('attachment; filename="')
    assert "filename*=UTF-8''%D0%A1%D1%82%D0%B0%D1%82%D1%8C%D1%8F" in header
    assert '"final"' not in header.split(";")[1]


# --------------------------------------------------------------------------- S3 (moto emulates the protocol)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@pytest.fixture(scope="module")
def moto_endpoint() -> Iterator[str]:
    port = _free_port()
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    yield f"http://127.0.0.1:{port}"
    server.stop()


@pytest.fixture
def s3(moto_endpoint: str, monkeypatch: pytest.MonkeyPatch) -> S3Storage:
    import boto3
    from botocore.config import Config

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    client = boto3.client(
        "s3",
        endpoint_url=moto_endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    client.create_bucket(Bucket="jps-test")
    return S3Storage(client, "jps-test", upload_ttl=60, download_ttl=60)


async def test_s3_presigned_upload_and_download(s3: S3Storage):
    key = "submissions/7/article.pdf"
    ticket = s3.presign_upload(key, content_type="application/pdf", size=len(PDF))
    assert ticket.method == "PUT" and ticket.headers == {"Content-Type": "application/pdf"}
    assert "X-Amz-Signature=" in ticket.url and "content-length" in ticket.url.lower()

    async with httpx.AsyncClient(trust_env=False) as http:
        uploaded = await http.put(ticket.url, content=PDF, headers=ticket.headers)
        assert uploaded.status_code == 200, uploaded.text

        assert await s3.size(key) == len(PDF)
        digest = await s3.digest(key)
        assert digest.sha256 == hashlib.sha256(PDF).hexdigest()
        assert digest.size == len(PDF)

        url = s3.presign_download(key, filename="Статья.pdf", content_type="application/pdf")
        downloaded = await http.get(url)
        assert downloaded.status_code == 200
        assert downloaded.content == PDF
        assert "UTF-8''%D0%A1" in downloaded.headers["content-disposition"]

    await s3.delete(key)
    assert await s3.size(key) is None
    assert await s3.size("never/existed.pdf") is None
