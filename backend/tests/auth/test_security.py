import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.dependencies import require_owned
from app.core.errors import APIError
from app.core.security import (
    JWT_ALGORITHM,
    JWT_AUDIENCE,
    JWT_ISSUER,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.core.throttle import LoginRateLimiter
from app.schemas.auth import LoginRequest, LoginResponse, RegisterRequest, UserResponse
from app.schemas.common import ErrorResponse, Success


def test_password_hashing_and_byte_boundaries():
    password = "é" * 36  # Exactly 72 UTF-8 bytes.
    hashed = hash_password(password)
    assert hashed.startswith("$2b$") and password not in hashed
    assert verify_password(password, hashed)
    assert not verify_password("wrong password", hashed)
    assert not verify_password(password + "a", hashed)
    assert not verify_password("password", "malformed-hash")
    with pytest.raises(ValueError):
        hash_password(password + "a")


def test_token_roundtrip_and_expiry():
    settings = get_settings()
    user_id = uuid4()
    token, expires_at = create_access_token(user_id, settings)
    assert decode_access_token(token, settings) == user_id
    claims = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[JWT_ALGORITHM],
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
    )
    assert claims["exp"] - claims["iat"] == settings.jwt_expire_minutes * 60
    assert expires_at.timestamp() == claims["exp"]
    expired, _ = create_access_token(user_id, settings, now=datetime.now(UTC) - timedelta(days=2))
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired, settings)


@pytest.mark.parametrize(
    "change",
    [
        {"type": "refresh"},
        {"aud": "wrong-client"},
        {"iss": "wrong-issuer"},
        {"sub": "not-a-uuid"},
        {"iat": datetime.now(UTC) + timedelta(days=2)},
    ],
)
def test_invalid_signed_claims_are_rejected(change):
    settings = get_settings()
    payload = {
        "sub": str(uuid4()),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "type": "access",
        "jti": str(uuid4()),
        **change,
    }
    token = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=JWT_ALGORITHM)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, settings)


@pytest.mark.parametrize("claim", ["exp", "iat", "sub", "iss", "aud", "type", "jti"])
def test_required_token_claims_cannot_be_omitted(claim):
    settings = get_settings()
    token, _ = create_access_token(uuid4(), settings)
    payload = jwt.decode(token, options={"verify_signature": False})
    del payload[claim]
    invalid = jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=JWT_ALGORITHM
    )
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_access_token(invalid, settings)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"app_env": "production"},
        {"app_env": "staging"},
        {"jwt_secret_key": "short"},
        {"jwt_secret_key": "replace-with-a-local-only-secret"},
        {"jwt_expire_minutes": 0},
        {"login_max_attempts": 0},
    ],
)
def test_unsafe_auth_settings_fail(kwargs):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


def test_local_keys_are_ephemeral_and_configured_key_is_redacted():
    first = Settings(_env_file=None, app_env="development", jwt_secret_key=None)
    second = Settings(_env_file=None, app_env="development", jwt_secret_key=None)
    assert first.jwt_secret_key != second.jwt_secret_key
    configured = Settings(_env_file=None, app_env="production", jwt_secret_key="a" * 48)
    assert "a" * 48 not in repr(configured)


def test_login_throttle_expires_without_sleep_and_is_bounded():
    now = [100.0]
    limiter = LoginRateLimiter(2, 60, clock=lambda: now[0])
    limiter.check("127.0.0.1")
    limiter.check("127.0.0.1")
    with pytest.raises(APIError) as error:
        limiter.check("127.0.0.1")
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "60"
    now[0] += 60
    limiter.check("127.0.0.1")
    assert len(limiter._attempts["127.0.0.1"]) == 1


def test_owner_helper_hides_missing_or_foreign_resources():
    user = SimpleNamespace(id=uuid4())
    owned = SimpleNamespace(host_id=user.id)
    assert require_owned(owned, user, owner_field="host_id") is owned
    for resource in (None, SimpleNamespace(host_id=uuid4())):
        with pytest.raises(APIError) as error:
            require_owned(resource, user, owner_field="host_id")
        assert error.value.status_code == 404


def test_frontend_mock_examples_match_auth_models():
    fixture_path = Path(__file__).resolve().parents[3] / "docs" / "fixtures" / "auth.json"
    examples = json.loads(fixture_path.read_text())
    RegisterRequest.model_validate(examples["register_customer_request"])
    RegisterRequest.model_validate(examples["register_host_request"])
    LoginRequest.model_validate(examples["login_request"])
    Success[UserResponse].model_validate(examples["register_success"])
    Success[UserResponse].model_validate(examples["me_success"])
    Success[LoginResponse].model_validate(examples["login_success"])
    for key in (
        "invalid_credentials",
        "unauthenticated",
        "forbidden",
        "duplicate_email",
        "validation_error",
        "rate_limited",
    ):
        ErrorResponse.model_validate(examples[key])
