"""Object storage: provider-neutral interface + adapters, chosen by a Factory.

Add a provider (S3, GCS, ...): write an `ObjectStorage` subclass, register a
builder in `PROVIDERS`, and add the name to `Settings.storage_provider`.
"""

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from app.core.config import Settings, get_settings
from app.storage.base import ObjectStorage, StoredObject, UploadTicket

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _local(settings: Settings) -> ObjectStorage:
    from app.storage.local import LocalDiskStorage

    root = Path(settings.storage_local_root)
    return LocalDiskStorage(
        root=root if root.is_absolute() else BACKEND_ROOT / root,
        public_base_url=settings.media_public_base_url,
        upload_base_url=f"{settings.api_public_base_url.rstrip('/')}/api/v1/uploads",
        signing_key=settings.jwt_secret_key.get_secret_value(),
    )


def _azure(settings: Settings) -> ObjectStorage:
    from app.storage.azure_blob import AzureBlobStorage

    if not settings.azure_storage_account_name or not settings.azure_storage_account_key:
        raise RuntimeError(
            "STORAGE_PROVIDER=azure requires AZURE_STORAGE_ACCOUNT_NAME and "
            "AZURE_STORAGE_ACCOUNT_KEY"
        )
    return AzureBlobStorage(
        account_name=settings.azure_storage_account_name,
        account_key=settings.azure_storage_account_key.get_secret_value(),
        container=settings.azure_storage_container,
        public_base_url=settings.media_public_base_url,
    )


PROVIDERS: dict[str, Callable[[Settings], ObjectStorage]] = {
    "local": _local,
    "azure": _azure,
}


def build_storage(settings: Settings) -> ObjectStorage:
    return PROVIDERS[settings.storage_provider](settings)


@lru_cache
def get_storage() -> ObjectStorage:
    """FastAPI dependency; tests override it with their own instance."""
    return build_storage(get_settings())


__all__ = ["ObjectStorage", "StoredObject", "UploadTicket", "build_storage", "get_storage"]
