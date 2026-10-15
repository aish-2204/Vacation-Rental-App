"""Provider-neutral object storage interface (Adapter target).

The rest of the app only talks to `ObjectStorage`. Each provider (local disk,
Azure Blob, S3, GCS, ...) is an adapter that implements these few methods, so
switching providers is a configuration change plus, at most, one new class.

Upload flow: the API issues a short-lived, single-object upload ticket (a
presigned URL / SAS); the browser sends the bytes straight to `upload_url`;
the API later checks the stored object with `inspect` before saving its URL.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class UploadTicket:
    upload_url: str
    public_url: str
    expires_at: datetime
    max_bytes: int
    method: str = "PUT"
    # Headers the client MUST send with the upload request.
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredObject:
    size_bytes: int
    content_type: str


class ObjectStorage(ABC):
    def __init__(self, public_base_url: str) -> None:
        self.public_base_url = public_base_url.rstrip("/")

    def public_url(self, key: str) -> str:
        return f"{self.public_base_url}/{key}"

    def key_for_url(self, url: str) -> str | None:
        """The object key if `url` points into this storage, else None."""
        prefix = f"{self.public_base_url}/"
        if not url.startswith(prefix):
            return None
        key = url[len(prefix) :]
        if not key or ".." in key.split("/") or "?" in key or "#" in key:
            return None
        return key

    @abstractmethod
    def create_upload(
        self, key: str, content_type: str, max_bytes: int, expires_at: datetime
    ) -> UploadTicket:
        """Presign a write of exactly one object `key`."""

    @abstractmethod
    async def inspect(self, key: str) -> StoredObject | None:
        """Size/type of a stored object, or None if it does not exist."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete an object; deleting a missing object is not an error."""
