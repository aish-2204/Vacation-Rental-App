from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.main import create_app
from app.schemas.analytics import AnalyticsQuery
from tests.analytics.helpers import ADMIN, HOST, auth


@pytest.mark.parametrize(
    "values",
    [
        {"period_days": 0},
        {"period_days": 29},
        {"period_days": 31},
        {"period_days": 120},
        {"period_days": "banana"},
        {"period_days": "30.5"},
        {"period_days": ""},
        {"period_days": None},
        {"zip_code": ""},
        {"zip_code": "2108"},
        {"zip_code": "0210X"},
        {"zip_code": "02108-123"},
        {"zip_code": " 02108"},
        {"zip_code": 2108},
        {"host_id": str(uuid4())},
        {"customer_id": str(uuid4())},
        {"as_of": "2020-01-01T00:00:00Z"},
        {"status": "APPROVED"},
        {"unknown": True},
    ],
)
def test_invalid_period_zip_and_scope_injection(values):
    with pytest.raises(ValidationError):
        AnalyticsQuery.model_validate(values)


@pytest.mark.parametrize("period", [30, 60, 90])
def test_allowed_period_query_text_and_leading_zero_zip(period):
    query = AnalyticsQuery.model_validate({"period_days": str(period), "zip_code": "02108"})
    assert query.period_days == period and query.zip_code == "02108"
    assert AnalyticsQuery(zip_code="02108-1234").zip_code == "02108-1234"
    assert AnalyticsQuery().period_days == 30 and AnalyticsQuery().zip_code is None


@pytest.mark.parametrize(
    "path,actor,expected",
    [
        (HOST, None, 401),
        (ADMIN, None, 401),
        (HOST, "customer", 403),
        (ADMIN, "customer", 403),
        (HOST, "admin", 403),
        (ADMIN, "host1", 403),
        (ADMIN, "host2", 403),
    ],
)
async def test_role_matrix(api, path, actor, expected):
    response = await api.get(path, headers=auth(actor) if actor else {})
    assert response.status_code == expected
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    if expected == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("path,actor", [(HOST, "host1"), (ADMIN, "admin")])
async def test_http_validation_errors_and_host_scope_cannot_be_overridden(api, path, actor):
    for query in (
        {"period_days": 31},
        {"zip_code": "0210X"},
        {"host_id": str(uuid4())},
        {"as_of": "2020-01-01T00:00:00Z"},
    ):
        response = await api.get(path, headers=auth(actor), params=query)
        assert (
            response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
        )
        assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_openapi_documents_roles_period_enum_zip_and_booking_value():
    schema = create_app().openapi()
    for path in (HOST, ADMIN):
        operation = schema["paths"][path]["get"]
        assert operation["security"] == [{"BearerAuth": []}]
        assert {"200", "401", "403", "422", "500"} <= operation["responses"].keys()
        parameters = {item["name"]: item for item in operation["parameters"]}
        assert set(parameters) == {"period_days", "zip_code"}
        assert parameters["period_days"]["schema"]["enum"] == [30, 60, 90]
        assert parameters["period_days"]["schema"]["default"] == 30
    fields = schema["components"]["schemas"]["AnalyticsResponse"]["properties"]
    assert {
        "window_start",
        "window_end",
        "timezone",
        "booking_value_usd",
        "daily_bookings",
        "rentals_by_zip",
        "bookings_by_zip",
    } <= fields.keys()
    assert (
        not {"revenue", "customer_id", "host_id", "booking_id", "email", "password_hash"}
        & fields.keys()
    )
