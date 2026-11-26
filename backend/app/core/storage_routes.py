"""Upload and download endpoints for the local storage backend (development, tests, small installs).

They mirror S3 presigned URLs: the signed token in the path is the only permission needed, so they
do not use the session cookie and are not exposed when the S3 backend is configured.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse

from app.core.errors import BadRequest, NotFound
from app.core.storage import LocalStorage, StorageError

router = APIRouter(prefix="/api/v1/storage", tags=["storage"], include_in_schema=False)


def _local(request: Request) -> LocalStorage:
    storage = request.app.state.storage
    if not isinstance(storage, LocalStorage):
        raise NotFound()
    return storage


@router.put("/{token}", status_code=204)
async def upload(token: str, request: Request) -> Response:
    storage = _local(request)
    try:
        grant = storage.verify(token, "put")
    except StorageError as exc:
        raise BadRequest(f"This upload link cannot be used: {exc}.", code="invalid_upload_link") from exc
    if request.headers.get("content-type", "").split(";")[0].strip() != grant["ct"]:
        raise BadRequest(
            "The Content-Type header does not match the upload link.", code="content_type_mismatch"
        )
    try:
        await storage.write_stream(grant["k"], request.stream(), expected_size=int(grant["sz"]))
    except StorageError as exc:
        raise BadRequest(str(exc) + ".", code="size_mismatch") from exc
    return Response(status_code=204)


@router.get("/{token}")
async def download(token: str, request: Request) -> FileResponse:
    storage = _local(request)
    try:
        grant = storage.verify(token, "get")
    except StorageError as exc:
        raise NotFound(f"This download link cannot be used: {exc}.") from exc
    path = storage.path(grant["k"])
    if not path.is_file():
        raise NotFound("File not found.")
    return FileResponse(
        path, media_type=grant["ct"], filename=grant["fn"], content_disposition_type="attachment"
    )
