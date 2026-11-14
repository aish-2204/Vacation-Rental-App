"""Azure Blob Storage adapter (PLACEHOLDER: not yet run against a real account).

Enable with STORAGE_PROVIDER=azure plus AZURE_STORAGE_ACCOUNT_NAME,
AZURE_STORAGE_ACCOUNT_KEY and AZURE_STORAGE_CONTAINER, and install the SDK:
`pip install -e 'backend[azure]'`. The browser uploads straight to Blob Storage
with a write-only SAS for one blob, so the storage account needs a CORS rule
allowing the UI origin, PUT, and the `x-ms-blob-type`/`content-type` headers.

Production hardening: prefer a managed identity + user delegation SAS over an
account key (swap `_sas` below; nothing else changes).
"""

from datetime import datetime

from app.storage.base import ObjectStorage, StoredObject, UploadTicket


class AzureBlobStorage(ObjectStorage):
    def __init__(
        self, account_name: str, account_key: str, container: str, public_base_url: str
    ) -> None:
        try:
            from azure.storage.blob.aio import BlobServiceClient  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "STORAGE_PROVIDER=azure needs the Azure SDK: pip install -e 'backend[azure]'"
            ) from exc
        super().__init__(public_base_url)
        self.account_name, self.container = account_name, container
        self._account_key = account_key
        self.account_url = f"https://{account_name}.blob.core.windows.net"

    def _sas(self, key: str, expires_at: datetime) -> str:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        return generate_blob_sas(
            account_name=self.account_name,
            container_name=self.container,
            blob_name=key,
            account_key=self._account_key,
            permission=BlobSasPermissions(create=True, write=True),
            expiry=expires_at,
        )

    def create_upload(self, key, content_type, max_bytes, expires_at) -> UploadTicket:
        blob_url = f"{self.account_url}/{self.container}/{key}"
        return UploadTicket(
            upload_url=f"{blob_url}?{self._sas(key, expires_at)}",
            public_url=self.public_url(key),
            expires_at=expires_at,
            max_bytes=max_bytes,
            # SAS cannot cap size; the API re-checks size/type with inspect().
            headers={"x-ms-blob-type": "BlockBlob", "Content-Type": content_type},
        )

    def _client(self):
        from azure.storage.blob.aio import BlobServiceClient

        return BlobServiceClient(self.account_url, credential=self._account_key)

    async def inspect(self, key: str) -> StoredObject | None:
        from azure.core.exceptions import ResourceNotFoundError

        async with self._client() as service:
            blob = service.get_blob_client(self.container, key)
            try:
                properties = await blob.get_blob_properties()
            except ResourceNotFoundError:
                return None
        return StoredObject(
            size_bytes=properties.size,
            content_type=properties.content_settings.content_type or "application/octet-stream",
        )

    async def delete(self, key: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        async with self._client() as service:
            try:
                await service.get_blob_client(self.container, key).delete_blob()
            except ResourceNotFoundError:
                return
