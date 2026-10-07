from functools import lru_cache
from secrets import token_urlsafe

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
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
