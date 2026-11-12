"""Upload receiver for STORAGE_PROVIDER=local only.

Plays the role a cloud bucket plays for presigned URLs: the signed token in
the path authorizes one PUT of one object, with a fixed content type and a
maximum size. With a cloud provider the browser uploads to the cloud instead,
and this route answers 404.
"""

import jwt
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.dependencies import StorageDep
from app.core.errors import APIError
from app.schemas.common import ErrorResponse, Success
from app.storage.local import LocalDiskStorage

router = APIRouter(
    prefix="/uploads",
    tags=["media uploads (local storage)"],
    responses={code: {"model": ErrorResponse} for code in (403, 404, 413, 415, 422)},
)


class UploadResult(BaseModel):
    public_url: str
    size_bytes: int


@router.put(
    "/{token}",
    status_code=201,
    response_model=Success[UploadResult],
    summary="Receive one file for a local-storage upload URL",
)
async def receive_upload(token: str, request: Request, storage: StorageDep):
    if not isinstance(storage, LocalDiskStorage):
        raise APIError(404, "NOT_FOUND", "Not found")
    try:
        claims = storage.read_upload_token(token)
    except jwt.InvalidTokenError:
        raise APIError(403, "UPLOAD_URL_INVALID", "Upload URL is invalid or expired") from None
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != claims["content_type"]:
        raise APIError(
            415, "UNSUPPORTED_MEDIA_TYPE", f"Content-Type must be {claims['content_type']}"
        )
    max_bytes = claims["max_bytes"]
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise APIError(413, "FILE_TOO_LARGE", f"File must be at most {max_bytes} bytes")
    size = await storage.write(claims["key"], request.stream(), max_bytes)
    if size < 0:
        raise APIError(413, "FILE_TOO_LARGE", f"File must be at most {max_bytes} bytes")
    if size == 0:
        await storage.delete(claims["key"])
        raise APIError(422, "EMPTY_UPLOAD", "The uploaded file is empty")
    return Success(data=UploadResult(public_url=storage.public_url(claims["key"]), size_bytes=size))
