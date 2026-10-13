from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import bcrypt
import jwt

from app.core.config import Settings

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "vacation-rental-api"
JWT_AUDIENCE = "vacation-rental-web"
# Used for unknown accounts to perform the same expensive bcrypt operation.
DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"unusable-dummy-password", bcrypt.gensalt(rounds=12)).decode()


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if not 8 <= len(encoded) <= 72:
        raise ValueError("Password must contain 8 to 72 UTF-8 bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    encoded = password.encode("utf-8")
    if not 1 <= len(encoded) <= 72:
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode())
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: UUID, settings: Settings, *, now: datetime | None = None
) -> tuple[str, datetime]:
    issued_at = (now or datetime.now(UTC)).replace(microsecond=0)
    expires_at = issued_at + timedelta(minutes=settings.jwt_expire_minutes)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "iat": issued_at,
            "exp": expires_at,
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
            "type": "access",
            "jti": str(uuid4()),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    return token, expires_at


def decode_access_token(token: str, settings: Settings) -> UUID:
    if len(token) > 8192:
        raise jwt.InvalidTokenError("Invalid access token")
    payload = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[JWT_ALGORITHM],
        issuer=JWT_ISSUER,
        audience=JWT_AUDIENCE,
        options={"require": ["sub", "iat", "exp", "iss", "aud", "type", "jti"]},
    )
    if payload["type"] != "access":
        raise jwt.InvalidTokenError("Invalid token type")
    try:
        return UUID(payload["sub"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise jwt.InvalidTokenError("Invalid token subject") from exc
