from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, update

from app.models import Booking, Listing, ListingBookingRule
from app.models.enums import ReservationState
from seed.demo import demo_id
from tests.bookings.helpers import BOOKINGS, auth, create, payload


@pytest.mark.parametrize("nights", [1, 14])
async def test_search_to_booking_persists_server_price_and_complete_snapshots(
    api, db, clock, nights
):
    request = payload(clock, nights=nights, check_in_time="16:00", check_out_time="10:00")
    stay_query = {key: value for key, value in request.items() if key != "listing_id"}
    detail = await api.get(f"/api/v1/listings/{request['listing_id']}", params=stay_query)
    quote = detail.json()["data"]["quote"]
    response = await api.post(BOOKINGS, headers=auth(), json=request)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["total_cost"] == quote["total_cost"] == f"{Decimal('99.99') * nights:.2f}"
    assert data["arrival_at"] == quote["arrival_at"]
    assert data["departure_at"] == quote["departure_at"]
    assert data["status"] == data["reservation_state"] == "CONFIRMED" and data["can_cancel"]
    assert data["check_in_time"] == "16:00" and data["check_out_time"] == "10:00"
    assert data["listing_zip_snapshot"] == "95112"
    assert data["listing_timezone_snapshot"] == "America/Los_Angeles"
    listing = await db.get(Listing, demo_id("listing/0"))
    assert all(part in data["listing_address_snapshot"] for part in (listing.city, listing.state))
    stored = await db.get(Booking, UUID(data["id"]))
    assert stored.customer_id == demo_id("user/3")
    assert stored.nightly_price_snapshot == Decimal("99.99")
    assert stored.total_cost == Decimal(data["total_cost"])
    assert stored.created_at == stored.updated_at == clock[0]
    assert stored.cancelled_at is None and stored.arrival_at.tzinfo
    assert "customer_id" not in data and "host_id" not in data and "password" not in response.text


async def test_overlap_half_open_dates_and_changed_times_cannot_bypass_inventory(api, clock):
    first = await create(api, clock)
    for changes in ({}, {"check_in_time": "22:00", "check_out_time": "07:00"}):
        response = await api.post(
            BOOKINGS, headers=auth("customer2"), json=payload(clock, **changes)
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DATES_UNAVAILABLE"
    adjacent = payload(clock, offset=302, nights=1)
    assert (await api.post(BOOKINGS, headers=auth(), json=adjacent)).status_code == 201
    previous = payload(clock, offset=299, nights=1)
    assert (await api.post(BOOKINGS, headers=auth(), json=previous)).status_code == 201
    assert first["check_out"] == adjacent["check_in"]


async def test_blocks_and_cancelled_seed_inventory(api, db, clock):
    blocked = await api.post(BOOKINGS, headers=auth(), json=payload(clock, offset=60))
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "DATES_UNAVAILABLE"
    cancelled = await db.get(Booking, demo_id("booking/9"))
    request = {
        "listing_id": str(cancelled.listing_id),
        "check_in": cancelled.check_in.isoformat(),
        "check_out": cancelled.check_out.isoformat(),
    }
    assert (await api.post(BOOKINGS, headers=auth(), json=request)).status_code == 201


async def test_cancel_is_idempotent_releases_inventory_and_preserves_confirmation(api, db, clock):
    first = await create(api, clock)
    endpoint = f"{BOOKINGS}/{first['id']}/cancel"
    response = await api.patch(endpoint, headers=auth())
    assert response.status_code == 200
    cancelled = response.json()["data"]
    assert cancelled["status"] == cancelled["reservation_state"] == "CANCELLED"
    assert (
        cancelled["cancelled_at"]
        == cancelled["updated_at"]
        == clock[0].isoformat().replace("+00:00", "Z")
    )
    assert cancelled["total_cost"] == first["total_cost"] and not cancelled["can_cancel"]
    clock[0] += timedelta(minutes=1)
    again = await api.patch(endpoint, headers=auth())
    assert again.json()["data"] == cancelled
    second = await api.post(BOOKINGS, headers=auth("customer2"), json=payload(clock))
    assert second.status_code == 201 and second.json()["data"]["id"] != first["id"]
    # Idempotency also holds after the original arrival has passed.
    clock[0] = datetime.fromisoformat(first["departure_at"])
    assert (await api.patch(endpoint, headers=auth())).json()["data"] == cancelled
    stored = await db.get(Booking, UUID(first["id"]))
    assert stored.reservation_state == ReservationState.CANCELLED


@pytest.mark.parametrize("offset_microseconds,expected", [(-1, 200), (0, 409), (1, 409)])
async def test_cancellation_closes_exactly_at_accepted_utc_arrival(
    api, clock, offset_microseconds, expected
):
    booking = await create(api, clock)
    clock[0] = datetime.fromisoformat(booking["arrival_at"]) + timedelta(
        microseconds=offset_microseconds
    )
    response = await api.patch(f"{BOOKINGS}/{booking['id']}/cancel", headers=auth())
    assert response.status_code == expected
    if expected == 409:
        assert response.json()["error"]["code"] == "CANCELLATION_CLOSED"
        detail = (await api.get(f"{BOOKINGS}/{booking['id']}", headers=auth())).json()["data"]
        assert detail["reservation_state"] == "CONFIRMED" and detail["cancelled_at"] is None


async def test_completion_is_derived_at_checkout_without_mutating_reservation_state(api, db, clock):
    booking = await create(api, clock)
    endpoint = f"{BOOKINGS}/{booking['id']}"
    checkout = datetime.fromisoformat(booking["departure_at"])
    for now, status in [
        (checkout - timedelta(microseconds=1), "CONFIRMED"),
        (checkout, "COMPLETED"),
    ]:
        clock[0] = now
        data = (await api.get(endpoint, headers=auth())).json()["data"]
        assert data["status"] == status and data["reservation_state"] == "CONFIRMED"
        assert not data["can_cancel"]
        history = (await api.get(BOOKINGS + "/my", headers=auth())).json()["data"]
        assert next(item for item in history if item["id"] == booking["id"])["status"] == status
    stored = await db.get(Booking, UUID(booking["id"]))
    assert stored.reservation_state == ReservationState.CONFIRMED
    assert (
        stored.updated_at.isoformat() == datetime.fromisoformat(booking["updated_at"]).isoformat()
    )


async def test_history_is_owned_paginated_stable_and_empty_safe(api, db):
    expected = set(
        (await db.scalars(select(Booking.id).where(Booking.customer_id == demo_id("user/3")))).all()
    )
    seen = []
    for page in range(1, (len(expected) + 1) // 2 + 1):
        response = await api.get(
            BOOKINGS + "/my", headers=auth(), params={"page": page, "page_size": 2}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["pagination"]["total_items"] == len(expected)
        assert body["pagination"]["total_pages"] == (len(expected) + 1) // 2
        seen += [UUID(row["id"]) for row in body["data"]]
    assert set(seen) == expected and len(seen) == len(expected)
    for empty_page in (99, 10**30):
        result = await api.get(BOOKINGS + "/my", headers=auth(), params={"page": empty_page})
        assert result.status_code == 200 and result.json()["data"] == []
        assert result.json()["pagination"]["total_items"] == len(expected)
    # All history ordered by created_at DESC, then id ASC, including tied times.
    await db.execute(update(Booking).values(created_at=datetime(2020, 1, 1, tzinfo=UTC)))
    await db.commit()
    tied = await api.get(BOOKINGS + "/my", headers=auth(), params={"page_size": 50})
    assert [row["id"] for row in tied.json()["data"]] == sorted(map(str, expected))


@pytest.mark.parametrize("actor,expected", [(None, 401), ("host1", 403), ("admin", 403)])
async def test_all_booking_operations_require_customer(api, clock, actor, expected):
    headers = auth(actor) if actor else {}
    for method, path, body in [
        ("POST", BOOKINGS, payload(clock)),
        ("GET", BOOKINGS + "/my", None),
        ("GET", f"{BOOKINGS}/{demo_id('booking/0')}", None),
        ("PATCH", f"{BOOKINGS}/{demo_id('booking/0')}/cancel", None),
    ]:
        response = await api.request(method, path, json=body, headers=headers)
        assert response.status_code == expected
        assert response.json()["request_id"] == response.headers["X-Request-ID"]


async def test_foreign_and_missing_booking_access_are_indistinguishable(api, clock):
    booking = await create(api, clock)
    for method, suffix in [("GET", ""), ("PATCH", "/cancel")]:
        foreign = await api.request(
            method, f"{BOOKINGS}/{booking['id']}{suffix}", headers=auth("customer2")
        )
        missing = await api.request(
            method, f"{BOOKINGS}/{uuid4()}{suffix}", headers=auth("customer2")
        )
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json()["error"] == missing.json()["error"]


async def test_snapshot_history_survives_price_changes_and_listing_removal(api, clock):
    first = await create(api, clock)
    host_path = f"/api/v1/host/listings/{first['listing_id']}"
    assert (
        await api.patch(host_path, headers=auth("host1"), json={"nightly_price": "250.00"})
    ).status_code == 200
    second = await create(api, clock, offset=310)
    assert second["nightly_price_snapshot"] == "250.00" and second["total_cost"] == "500.00"
    assert (
        await api.patch(host_path, headers=auth("host1"), json={"name": "Renamed Home"})
    ).status_code == 200
    assert (
        await api.request(
            "DELETE", host_path, headers=auth("host1"), json={"reason": "Retire property"}
        )
    ).status_code == 200
    for saved in (first, second):
        assert (await api.get(f"{BOOKINGS}/{saved['id']}", headers=auth())).json()["data"] == saved
    assert (await api.get(f"/api/v1/listings/{first['listing_id']}")).status_code == 404
    assert (
        await api.post(BOOKINGS, headers=auth(), json=payload(clock, offset=320))
    ).status_code == 409
    # Removal does not prevent the owner from cancelling their future stay.
    assert (await api.patch(f"{BOOKINGS}/{first['id']}/cancel", headers=auth())).status_code == 200


async def test_booking_uses_current_price_instead_of_older_search_quote(api, clock):
    query = payload(clock)
    query.pop("listing_id")
    quote = (await api.get(f"/api/v1/listings/{demo_id('listing/0')}", params=query)).json()[
        "data"
    ]["quote"]
    assert quote["total_cost"] == "199.98"
    await api.patch(
        f"/api/v1/host/listings/{demo_id('listing/0')}",
        headers=auth("host1"),
        json={"nightly_price": "123.45"},
    )
    booking = await create(api, clock)
    assert booking["total_cost"] == "246.90" and booking["nightly_price_snapshot"] == "123.45"


@pytest.mark.parametrize("start,hours", [("2027-03-13", 19), ("2027-11-06", 21)])
async def test_dst_changes_elapsed_hours_not_nightly_price(api, clock, start, hours):
    clock[0] = datetime(2027, 1, 1, tzinfo=UTC)
    booking = await create(api, clock, check_in=start, nights=1)
    assert booking["total_cost"] == "99.99" and booking["nights"] == 1
    assert datetime.fromisoformat(booking["departure_at"]) - datetime.fromisoformat(
        booking["arrival_at"]
    ) == timedelta(hours=hours)


@pytest.mark.parametrize(
    "start,wall,code",
    [
        ("2027-03-14", "02:30", "NONEXISTENT_LOCAL_TIME"),
        ("2027-11-07", "01:30", "AMBIGUOUS_LOCAL_TIME"),
    ],
)
async def test_booking_rejects_dst_gaps_and_folds(api, db, clock, start, wall, code):
    clock[0] = datetime(2027, 1, 1, tzinfo=UTC)
    await db.execute(
        update(ListingBookingRule)
        .where(ListingBookingRule.listing_id == demo_id("listing/0"))
        .values(arrival_start=datetime.strptime("00:00", "%H:%M").time())
    )
    await db.commit()
    response = await api.post(
        BOOKINGS, headers=auth(), json=payload(clock, check_in=start, check_in_time=wall)
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == code


async def test_same_local_day_arrival_is_allowed_even_when_utc_date_is_tomorrow(api, clock):
    clock[0] = datetime(2027, 1, 2, 1, tzinfo=UTC)  # Jan 1 17:00 in Los Angeles.
    booking = await create(api, clock, check_in="2027-01-01", check_in_time="18:00", nights=1)
    accepted = datetime.fromisoformat(booking["arrival_at"])
    assert accepted == datetime(2027, 1, 2, 2, tzinfo=UTC)
    assert (
        accepted.astimezone(ZoneInfo(booking["listing_timezone_snapshot"])).date().isoformat()
        == "2027-01-01"
    )


async def test_database_exclusion_is_translated_and_session_failure_does_not_leak(
    api, db, clock, monkeypatch
):
    from app.services import bookings

    await create(api, clock)

    async def bypass_service_check(*args):
        return set()

    monkeypatch.setattr(bookings, "occupied_listing_ids", bypass_service_check)
    response = await api.post(BOOKINGS, headers=auth(), json=payload(clock))
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "DATES_UNAVAILABLE"
    assert await db.scalar(select(func.count()).select_from(Booking)) == 19
    assert (
        await api.post(BOOKINGS, headers=auth(), json=payload(clock, offset=310))
    ).status_code == 201
