"""Local-disk adapter: a stand-in for cloud storage in development and tests.

It mimics a presigned URL: `create_upload` returns a URL on this API carrying a
signed, expiring token that allows exactly one PUT of one object. Files are
written under `root` and served read-only at `<api>/media/<key>`.
Not meant for multi-VM production: each VM would have its own disk.
"""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import jwt

from app.storage.base import ObjectStorage, StoredObject, UploadTicket

UPLOAD_TOKEN_TYPE = "media_upload"
UPLOAD_AUDIENCE = "vacation-rental-media-upload"
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


class LocalDiskStorage(ObjectStorage):
    def __init__(
        self, root: Path, public_base_url: str, upload_base_url: str, signing_key: str
    ) -> None:
        super().__init__(public_base_url)
        self.root = root.resolve()
        self.upload_base_url = upload_base_url.rstrip("/")
        self._signing_key = signing_key

    def path_for(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Object key escapes the storage root")
        return path

    def create_upload(self, key, content_type, max_bytes, expires_at) -> UploadTicket:
        token = jwt.encode(
            {
                "type": UPLOAD_TOKEN_TYPE,
                "aud": UPLOAD_AUDIENCE,
                "key": key,
                "content_type": content_type,
                "max_bytes": max_bytes,
                "exp": expires_at,
            },
            self._signing_key,
            algorithm="HS256",
        )
        return UploadTicket(
            upload_url=f"{self.upload_base_url}/{token}",
            public_url=self.public_url(key),
            expires_at=expires_at,
            max_bytes=max_bytes,
            headers={"Content-Type": content_type},
        )

    def read_upload_token(self, token: str) -> dict:
        """Raises jwt.InvalidTokenError when invalid or expired."""
        claims = jwt.decode(
            token,
            self._signing_key,
            algorithms=["HS256"],
            audience=UPLOAD_AUDIENCE,
            options={"require": ["exp", "aud", "key", "content_type", "max_bytes"]},
        )
        if claims.get("type") != UPLOAD_TOKEN_TYPE:
            raise jwt.InvalidTokenError("Not an upload token")
        return claims

    async def write(self, key: str, chunks, max_bytes: int) -> int:
        """Stream chunks to disk atomically. Returns size, or -1 if over max_bytes."""
        target = self.path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.{uuid4().hex}.part")
        size = 0
        try:
            with temp.open("wb") as handle:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > max_bytes:
                        return -1
                    handle.write(chunk)
            os.replace(temp, target)
            return size
        finally:
            temp.unlink(missing_ok=True)

    async def inspect(self, key: str) -> StoredObject | None:
        try:
            path = self.path_for(key)
            size = (await asyncio.to_thread(path.stat)).st_size
        except (ValueError, FileNotFoundError):
            return None
        content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        return StoredObject(size_bytes=size, content_type=content_type)

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self.path_for(key).unlink, missing_ok=True)
        except ValueError:
            return
