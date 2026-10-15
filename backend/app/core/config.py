from functools import lru_cache
from secrets import token_urlsafe
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Vacation Rental API"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://vacation:vacation@127.0.0.1:55432/vacation_rental_dev"
    test_database_url: str = (
        "postgresql+asyncpg://vacation:vacation@127.0.0.1:55433/vacation_rental_test"
    )
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    jwt_secret_key: SecretStr | None = None
    jwt_expire_minutes: int = Field(default=60, ge=1, le=1440)
    login_max_attempts: int = Field(default=10, ge=1, le=1000)
    login_window_seconds: int = Field(default=60, ge=1, le=3600)

    # Object storage for Host media uploads. "local" works with no cloud account:
    # files are uploaded to this API and served from /media. Switch providers by
    # changing STORAGE_PROVIDER and the matching settings below; see docs/media-storage.md.
    storage_provider: Literal["local", "azure"] = "local"
    # Externally reachable base URL of this API (used to build local upload URLs).
    api_public_base_url: str = "http://127.0.0.1:8000"
    # Public read base for stored objects. Local default: <api_public_base_url>/media.
    # Azure example: https://<account>.blob.core.windows.net/<container> (or a CDN URL).
    storage_public_base_url: str | None = None
    storage_local_root: str = "media-uploads"
    upload_url_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    media_max_image_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    media_max_video_bytes: int = Field(default=200 * 1024 * 1024, ge=1)
    # Azure Blob Storage placeholders (used only when STORAGE_PROVIDER=azure).
    azure_storage_account_name: str | None = None
    azure_storage_account_key: SecretStr | None = None
    azure_storage_container: str = "listing-media"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    @model_validator(mode="after")
    def validate_signing_key(self):
        key = self.jwt_secret_key.get_secret_value() if self.jwt_secret_key else ""
        if not key:
            if self.app_env not in {"development", "test"}:
                raise ValueError("JWT_SECRET_KEY must be configured outside development/test")
            # Only local development may use a temporary process-specific key.
            # A configured key must be shared across workers/VMs in deployment.
            self.jwt_secret_key = SecretStr(token_urlsafe(48))
        elif len(key.encode("utf-8")) < 32 or key == "replace-with-a-local-only-secret":
            raise ValueError("JWT_SECRET_KEY must be a generated secret of at least 32 bytes")
        return self

    @property
    def media_public_base_url(self) -> str:
        if self.storage_public_base_url:
            return self.storage_public_base_url.rstrip("/")
        if self.storage_provider == "azure":
            return (
                f"https://{self.azure_storage_account_name}.blob.core.windows.net/"
                f"{self.azure_storage_container}"
            )
        return f"{self.api_public_base_url.rstrip('/')}/media"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
