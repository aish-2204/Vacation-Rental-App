import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.security import JWT_ALGORITHM, create_access_token, verify_password
from app.main import create_app
from app.models import User
from app.models.enums import Role
from seed.demo import DEMO_PASSWORD, demo_id

PREFIX = "/api/v1/auth"
SIGNUP = {
    "name": "New Customer",
    "email": "new@example.test",
    "password": "MyDemoPass!2026",
    "phone": "+15550100123",
}


async def log_in(api, email="customer1@example.test", password=DEMO_PASSWORD):
    response = await api.post(f"{PREFIX}/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["data"]


@pytest.mark.parametrize("kind,role", [("customer", Role.CUSTOMER), ("host", Role.HOST)])
async def test_signup_normalizes_hashes_and_returns_safe_user(api, db, kind, role):
    response = await api.post(
        f"{PREFIX}/register/{kind}",
        json={
            **SIGNUP,
            "email": "  NEW@EXAMPLE.TEST  ",
            "name": " New User ",
        },
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["role"] == role and data["email"] == "new@example.test"
    assert data["name"] == "New User"
    assert set(data) == {"id", "name", "email", "phone", "role", "created_at"}
    user = await db.scalar(select(User).where(User.email == data["email"]))
    assert user is not None and verify_password(SIGNUP["password"], user.password_hash)
    assert SIGNUP["password"] not in response.text and user.password_hash not in response.text
    login = await log_in(api, " NEW@EXAMPLE.TEST ", SIGNUP["password"])
    assert login["user"]["id"] == data["id"]


async def test_duplicate_signup_is_case_insensitive_and_atomic(api, db):
    first, second = await asyncio.gather(
        api.post(f"{PREFIX}/register/customer", json=SIGNUP),
        api.post(f"{PREFIX}/register/host", json={**SIGNUP, "email": " NEW@EXAMPLE.TEST "}),
    )
    assert sorted([first.status_code, second.status_code]) == [201, 409]
    error = first if first.status_code == 409 else second
    assert error.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"
    assert len((await db.scalars(select(User).where(User.email == SIGNUP["email"]))).all()) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"name": " "},
        {"email": "bad-email"},
        {"phone": "x"},
        {"password": "short"},
        {"password": "é" * 37},
        {"password": "a" * 73},
        {"role": "ADMIN"},
        {"role": "HOST"},
        {"password_hash": "injected"},
        {"name": 123},
    ],
)
async def test_invalid_registration_and_role_injection(api, change):
    response = await api.post(f"{PREFIX}/register/customer", json={**SIGNUP, **change})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert SIGNUP["password"] not in response.text


async def test_maximum_bcrypt_bytes_work_without_truncation(api):
    password = "é" * 36
    response = await api.post(f"{PREFIX}/register/customer", json={**SIGNUP, "password": password})
    assert response.status_code == 201
    assert (await log_in(api, SIGNUP["email"], password))["token_type"] == "bearer"
    response = await api.post(
        f"{PREFIX}/login", json={"email": SIGNUP["email"], "password": password + "a"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "email,role",
    [
        ("customer1@example.test", "CUSTOMER"),
        ("host1@example.test", "HOST"),
        ("admin@example.test", "ADMIN"),
    ],
)
async def test_all_roles_can_log_in_and_get_me(api, email, role):
    data = await log_in(api, email)
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == get_settings().jwt_expire_minutes * 60
    assert datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")) > datetime.now(UTC)
    assert data["user"]["role"] == role
    response = await api.get(
        f"{PREFIX}/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert response.status_code == 200
    assert response.json()["data"] == data["user"]
    assert response.headers["Cache-Control"] == "no-store"
    assert "password_hash" not in response.text


async def test_unknown_account_and_wrong_password_are_indistinguishable(api):
    responses = [
        await api.post(f"{PREFIX}/login", json={"email": email, "password": "wrong password"})
        for email in ("missing@example.test", "customer1@example.test")
    ]
    for response in responses:
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
    assert responses[0].json()["error"] == responses[1].json()["error"]


@pytest.mark.parametrize("header", [None, "Basic abc", "Bearer invalid", "Bearer"])
async def test_missing_or_invalid_bearer_is_401(api, header):
    response = await api.get(f"{PREFIX}/me", headers={"Authorization": header} if header else {})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "kind",
    [
        "expired",
        "tampered",
        "none",
        "wrong-key",
        "wrong-algorithm",
        "unknown-user",
        "missing-expiry",
    ],
)
async def test_forged_expired_and_incomplete_tokens_are_rejected(api, kind):
    settings = get_settings()
    now = datetime.now(UTC) - timedelta(days=2) if kind == "expired" else datetime.now(UTC)
    token, _ = create_access_token(
        uuid4() if kind == "unknown-user" else demo_id("user/3"), settings, now=now
    )
    if kind == "tampered":
        parts = token.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        token = ".".join(parts)
    elif kind in {"none", "wrong-key", "wrong-algorithm", "missing-expiry"}:
        claims = jwt.decode(token, options={"verify_signature": False})
        algorithm = (
            "none" if kind == "none" else ("HS384" if kind == "wrong-algorithm" else JWT_ALGORITHM)
        )
        key = (
            None
            if kind == "none"
            else (
                "wrong-key-for-test-" * 4
                if kind == "wrong-key"
                else settings.jwt_secret_key.get_secret_value()
            )
        )
        if kind == "missing-expiry":
            del claims["exp"]
        token = jwt.encode(claims, key, algorithm=algorithm)
    response = await api.get(f"{PREFIX}/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert token not in response.text


async def test_roles_come_from_database_not_old_token(api, db):
    data = await log_in(api)
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    assert (await api.get("/test/customer", headers=headers)).status_code == 200
    assert (await api.get("/test/host", headers=headers)).status_code == 403
    await db.execute(update(User).where(User.id == demo_id("user/3")).values(role=Role.HOST))
    await db.commit()
    assert (await api.get("/test/customer", headers=headers)).status_code == 403
    assert (await api.get("/test/host", headers=headers)).status_code == 200


@pytest.mark.parametrize(
    "email,allowed",
    [
        ("customer1@example.test", "customer"),
        ("host1@example.test", "host"),
        ("admin@example.test", "admin"),
    ],
)
async def test_role_gates_allow_only_their_role(api, email, allowed):
    data = await log_in(api, email)
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    for role in ("customer", "host", "admin"):
        response = await api.get(f"/test/{role}", headers=headers)
        assert response.status_code == (200 if role == allowed else 403)
        if role != allowed:
            assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_deleted_user_token_stops_working(api, db):
    response = await api.post(f"{PREFIX}/register/customer", json=SIGNUP)
    user_id = response.json()["data"]["id"]
    data = await log_in(api, SIGNUP["email"], SIGNUP["password"])
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
    response = await api.get(
        f"{PREFIX}/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert response.status_code == 401


async def test_no_public_admin_signup(api):
    assert (await api.post(f"{PREFIX}/register/admin", json=SIGNUP)).status_code == 404
    assert (
        await api.post(f"{PREFIX}/register/host", json={**SIGNUP, "role": "ADMIN"})
    ).status_code == 422


async def test_login_throttle_cannot_be_bypassed_by_forwarded_headers(api):
    for _ in range(get_settings().login_max_attempts):
        response = await api.post(
            f"{PREFIX}/login", json={"email": "missing@example.test", "password": "wrong password"}
        )
        assert response.status_code == 401
    response = await api.post(
        f"{PREFIX}/login",
        json={"email": "admin@example.test", "password": DEMO_PASSWORD},
        headers={"X-Forwarded-For": "192.0.2.20", "Forwarded": "for=192.0.2.20"},
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert 1 <= int(response.headers["Retry-After"]) <= get_settings().login_window_seconds


async def test_json_only_errors_and_no_sensitive_response_or_logs(api, caplog, db):
    malformed = await api.post(
        f"{PREFIX}/login", content='{"password":', headers={"Content-Type": "application/json"}
    )
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "INVALID_JSON"
    form = await api.post(
        f"{PREFIX}/login", data={"email": "admin@example.test", "password": DEMO_PASSWORD}
    )
    assert form.status_code == 422
    login = await api.post(
        f"{PREFIX}/login", json={"email": "admin@example.test", "password": DEMO_PASSWORD}
    )
    assert login.status_code == 200
    assert login.headers["Cache-Control"] == "no-store"
    token = login.json()["data"]["access_token"]
    admin = await db.get(User, demo_id("user/0"))
    for secret in (DEMO_PASSWORD, admin.password_hash, token):
        assert secret not in caplog.text
    assert admin.password_hash not in login.text
    assert DEMO_PASSWORD not in login.text
    assert "password_hash" not in json.dumps(login.json())


async def test_openapi_documents_real_auth_contract(api):
    schema = (await api.get("/openapi.json")).json()
    assert schema["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"
    login = schema["paths"][f"{PREFIX}/login"]["post"]
    assert set(login["requestBody"]["content"]) == {"application/json"}
    assert {"200", "400", "401", "422", "429", "500"} <= login["responses"].keys()
    assert schema["paths"][f"{PREFIX}/me"]["get"]["security"] == [{"BearerAuth": []}]
    assert not any(path.startswith("/test/") for path in schema["paths"])
    assert "HTTPValidationError" not in schema["components"]["schemas"]


async def test_unexpected_errors_cannot_log_or_return_credentials(caplog):
    application = create_app()
    sensitive = "private-password-and-token-must-not-be-logged"

    @application.get("/test/failure", include_in_schema=False)
    async def failing_route():
        raise RuntimeError(sensitive)

    async with AsyncClient(
        transport=ASGITransport(application, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get("/test/failure", headers={"X-Request-ID": "failure-check"})
    assert response.status_code == 500
    assert response.json()["request_id"] == response.headers["X-Request-ID"] == "failure-check"
    assert sensitive not in response.text and sensitive not in caplog.text
    assert "RuntimeError" in caplog.text
