from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.database.session import get_session
from app.main import app

client = TestClient(app)


def test_health_is_process_only_and_returns_json() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"success": True, "data": {"status": "healthy"}}
    assert response.headers["x-request-id"]


def test_unknown_route_uses_error_envelope() -> None:
    response = client.get("/does-not-exist", headers={"X-Request-ID": "test-request"})
    assert response.status_code == 404
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["request_id"] == "test-request"


def test_ready_is_503_before_database_migrations() -> None:
    session = AsyncMock()
    session.scalar.return_value = None

    async def missing_schema():
        yield session

    app.dependency_overrides[get_session] = missing_schema
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_session)
    assert response.status_code == 503
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "HTTP_ERROR"


def test_database_outage_keeps_health_healthy() -> None:
    session = AsyncMock()
    session.execute.side_effect = ConnectionError("Database offline")

    async def offline_database():
        yield session

    app.dependency_overrides[get_session] = offline_database
    try:
        assert client.get("/ready").status_code == 503
        assert client.get("/health").status_code == 200
    finally:
        app.dependency_overrides.pop(get_session)


def test_documentation_endpoints_are_available() -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert "/health" in openapi.json()["paths"]
    assert "/ready" in openapi.json()["paths"]
