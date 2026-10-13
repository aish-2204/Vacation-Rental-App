from datetime import datetime
from typing import Literal
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.models.enums import Role


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(json_schema_extra={"writeOnly": True})

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        try:
            # Syntactic validation only; no DNS calls. .test supports seeded demos.
            result = validate_email(
                value.strip().lower(),
                check_deliverability=False,
                test_environment=True,
                allow_smtputf8=False,
            )
        except EmailNotValidError:
            raise ValueError("Enter a valid email address") from None
        return result.ascii_email.lower()

    @field_validator("password")
    @classmethod
    def supported_password(cls, value: SecretStr) -> SecretStr:
        if not 1 <= len(value.get_secret_value().encode("utf-8")) <= 72:
            raise ValueError("Password must contain 1 to 72 UTF-8 bytes")
        return value


class RegisterRequest(Credentials):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(pattern=r"^\+?[0-9][0-9 ()-]{6,30}[0-9]$")
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Demo Customer",
                    "email": "customer@example.test",
                    "password": "DemoOnly!2026",
                    "phone": "+15550100123",
                }
            ]
        },
        extra="forbid",
    )

    @field_validator("name", "phone")
    @classmethod
    def trim_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field cannot be blank")
        return value.strip()

    @field_validator("password")
    @classmethod
    def strong_enough_password(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 8:
            raise ValueError("Password must contain 8 to 72 UTF-8 bytes")
        return value


class LoginRequest(Credentials):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email": "customer1@example.test",
                    "password": "DemoOnly!2026",
                }
            ]
        },
        extra="forbid",
    )


class UserResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "11111111-1111-4111-8111-111111111111",
                    "name": "Demo Customer",
                    "email": "customer1@example.test",
                    "phone": "+15550100123",
                    "role": "CUSTOMER",
                    "created_at": "2026-11-15T12:00:00Z",
                }
            ]
        },
    )
    id: UUID
    name: str
    email: str
    phone: str
    role: Role
    created_at: datetime


class LoginResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "access_token": "<access_token_from_login>",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "expires_at": "2026-11-15T13:00:00Z",
                    "user": UserResponse.model_config["json_schema_extra"]["examples"][0],
                }
            ]
        }
    )
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    expires_at: datetime
    user: UserResponse
