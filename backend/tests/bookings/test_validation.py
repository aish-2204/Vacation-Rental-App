from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.main import create_app
from app.schemas.bookings import BookingCreate
from tests.bookings.helpers import BOOKINGS, auth, payload


@pytest.mark.parametrize(
    "changes",
    [
        {"duration_nights": 0},
        {"duration_nights": 15},
        {"duration_nights": None},
        {"check_in": None},
        {"check_in": "2030-02-30"},
        {"check_in": "2030-01-10T00:00:00Z"},
        {"check_in_time": "15:00:00"},
        {"check_out_time": "25:00"},
        {"check_out": "2030-01-13"},
        {"check_out": "2030-01-10"},
        {"listing_id": "not-uuid"},
        {"guests": 0},
        {"guests": None},
        {"total_cost": "0.01"},
        {"nightly_price_snapshot": "0.01"},
        {"customer_id": str(uuid4())},
        {"reservation_state": "CONFIRMED"},
        {"status": "COMPLETED"},
        {"currency": "EUR"},
        {"unknown": "value"},
    ],
)
def test_invalid_or_client_controlled_fields_are_rejected(changes):
    with pytest.raises(ValidationError):
        BookingCreate.model_validate(
            {"listing_id": str(uuid4()), "check_in": "2030-01-10", "duration_nights": 2, **changes}
        )


@pytest.mark.parametrize("index", [8, 9, 10, 11])
async def test_unapproved_and_removed_listings_cannot_be_booked(api, clock, index):
    response = await api.post(BOOKINGS, headers=auth(), json=payload(clock, listing=index))
    assert response.status_code == 409 and response.json()["error"]["code"] == "LISTING_UNAVAILABLE"


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"guests": 3}, "GUEST_LIMIT"),
        ({"check_in_time": "14:00"}, "OUTSIDE_BOOKING_WINDOW"),
        ({"check_out_time": "12:00"}, "OUTSIDE_BOOKING_WINDOW"),
        ({"check_in": "2020-01-01"}, "ARRIVAL_IN_PAST"),
        ({"duration_nights": 15}, "VALIDATION_ERROR"),
        ({"total_cost": "1.00"}, "VALIDATION_ERROR"),
    ],
)
async def test_http_validation_has_consistent_errors_and_no_writes(
    api, db, clock, changes, expected
):
    from sqlalchemy import func, select

    from app.models import Booking

    response = await api.post(BOOKINGS, headers=auth(), json=payload(clock, **changes))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == expected
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert "password" not in response.text
    assert await db.scalar(select(func.count()).select_from(Booking)) == 18


async def test_missing_listing_and_malformed_requests(api, clock):
    assert (
        await api.post(BOOKINGS, headers=auth(), json=payload(clock, listing_id=str(uuid4())))
    ).status_code == 404
    response = await api.post(
        BOOKINGS, headers={**auth(), "Content-Type": "application/json"}, content='{"listing_id":'
    )
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_JSON"
    for endpoint in (BOOKINGS + "/not-uuid", BOOKINGS + "/not-uuid/cancel"):
        method = "PATCH" if endpoint.endswith("cancel") else "GET"
        assert (await api.request(method, endpoint, headers=auth())).status_code == 422
    for query in ({"page": 0}, {"page_size": 51}, {"customer_id": str(uuid4())}):
        assert (await api.get(BOOKINGS + "/my", headers=auth(), params=query)).status_code == 422


def test_openapi_has_four_customer_routes_and_safe_confirmation_schema():
    schema = create_app().openapi()
    for method, path, status in [
        ("post", BOOKINGS, "201"),
        ("get", BOOKINGS + "/my", "200"),
        ("get", BOOKINGS + "/{booking_id}", "200"),
        ("patch", BOOKINGS + "/{booking_id}/cancel", "200"),
    ]:
        operation = schema["paths"][path][method]
        assert operation["security"] == [{"BearerAuth": []}]
        assert status in operation["responses"]
        assert {"401", "403", "404", "409", "422"} <= operation["responses"].keys()
    fields = schema["components"]["schemas"]["BookingResponse"]["properties"]
    assert {
        "status",
        "reservation_state",
        "can_cancel",
        "total_cost",
        "listing_zip_snapshot",
    } <= fields.keys()
    assert not {"customer_id", "password_hash", "host_id"} & fields.keys()
