from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.models import Booking, Listing, ListingBookingRule, ListingHours
from seed.demo import demo_id
from tests.search.helpers import SEARCH, ids, listing_path, stay


async def test_public_browse_has_required_fields_no_quote_or_private_data(api):
    response = await api.get(SEARCH)
    assert ids(response) == {str(demo_id(f"listing/{i}")) for i in range(8)}
    assert response.json()["pagination"]["total_items"] == 8
    for card in response.json()["data"]:
        assert card["available"] is None and card["quote"] is None and card["total_cost"] is None
        assert isinstance(card["nightly_price"], str)
        assert isinstance(card["latitude"], (int, float))
        assert card["media"] and card["amenities"]
        assert {
            "cost_rating",
            "average_rating",
            "review_count",
            "bookings_today",
            "max_guests",
            "timezone",
            "city",
            "state",
            "zip_code",
        } <= card.keys()
    text = response.text
    for field in (
        "customer_id",
        "password_hash",
        "reservation_state",
        "removal",
        "admin_id",
        "host_id",
    ):
        assert f'"{field}"' not in text
    reference = await api.get("/api/v1/amenities")
    assert reference.status_code == 200 and len(reference.json()["data"]) == 6


@pytest.mark.parametrize("index", [8, 9, 10, 11])
async def test_unapproved_and_removed_details_are_hidden(api, clock, index):
    for suffix, params in [("", {}), ("/availability", stay(clock))]:
        response = await api.get(listing_path(index) + suffix, params=params)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_each_filter_and_combined_and_semantics(api, clock):
    cases = [
        ({"city": " san JOSE "}, {0, 4}),
        ({"state": "ma"}, {3, 7}),
        ({"zip_code": "02108"}, {3, 7}),
        ({"min_price": "300.00"}, {5}),
        ({"max_price": "99.99"}, {0, 6}),
        ({"guests": 6}, {4}),
        ({"amenities": str(demo_id("amenity/Pool"))}, {2, 3, 4, 7}),
    ]
    for params, expected in cases:
        assert ids(await api.get(SEARCH, params=params)) == {
            str(demo_id(f"listing/{i}")) for i in expected
        }
    parameters = {
        **stay(clock),
        "city": "San Jose",
        "state": "CA",
        "zip_code": "95112",
        "guests": 4,
        "min_price": "200.00",
        "check_in_time": "15:00",
        "check_out_time": "11:00",
    }
    assert ids(await api.get(SEARCH, params=parameters)) == {str(demo_id("listing/4"))}
    parameters["state"] = "MA"
    assert ids(await api.get(SEARCH, params=parameters)) == set()
    multiple = [
        ("amenities", str(demo_id("amenity/Pool"))),
        ("amenities", str(demo_id("amenity/Pet friendly"))),
    ]
    assert ids(await api.get(SEARCH, params=multiple)) == {
        str(demo_id("listing/3")),
        str(demo_id("listing/4")),
    }
    assert ids(await api.get(SEARCH, params={"amenities": str(uuid4())})) == set()


async def test_quote_defaults_details_and_availability_share_one_result(api, clock):
    params = stay(clock, nights=14, guests=2)
    response = await api.get(SEARCH, params=params)
    assert response.status_code == 200
    card = next(item for item in response.json()["data"] if item["id"] == str(demo_id("listing/0")))
    assert card["available"] is True
    assert card["total_cost"] == "1399.86"
    assert card["quote"]["nights"] == 14
    assert card["quote"]["check_in_time"] == "15:00" and card["quote"]["check_out_time"] == "11:00"
    detail = await api.get(listing_path(), params=params)
    availability = await api.get(listing_path() + "/availability", params=params)
    assert detail.status_code == availability.status_code == 200
    assert card["quote"] == detail.json()["data"]["quote"] == availability.json()["data"]["quote"]
    assert len(detail.json()["data"]["hours"]) == len(detail.json()["data"]["booking_rules"]) == 7
    assert detail.json()["data"]["description"]
    assert "customer_id" not in detail.text and "host_id" not in detail.text
    # Explicit dates + duration must agree and one-night stays also work.
    params = stay(clock, nights=1)
    params["check_out"] = (
        datetime.fromisoformat(params["check_in"]).date() + timedelta(days=1)
    ).isoformat()
    assert (await api.get(listing_path() + "/availability", params=params)).status_code == 200


async def test_inventory_conflicts_quotes_and_half_open_dates(api, db, clock):
    booking = await db.get(Booking, demo_id("booking/8"))
    params = {"check_in": booking.check_in.isoformat(), "check_out": booking.check_out.isoformat()}
    assert str(demo_id("listing/0")) not in ids(await api.get(SEARCH, params=params))
    marked = await api.get(SEARCH, params={**params, "available_only": "false"})
    occupied = next(
        item for item in marked.json()["data"] if item["id"] == str(demo_id("listing/0"))
    )
    assert occupied["available"] is False and occupied["quote"] is not None
    assert occupied["unavailable_reason"] == "DATES_UNAVAILABLE"
    assert (await api.get(listing_path() + "/availability", params=params)).json()["data"][
        "available"
    ] is False
    # Time changes never permit reuse of an occupied night.
    params["check_in_time"] = "21:00"
    assert (await api.get(listing_path() + "/availability", params=params)).json()["data"][
        "available"
    ] is False
    adjacent = {"check_in": booking.check_out.isoformat(), "duration_nights": 1}
    assert (await api.get(listing_path() + "/availability", params=adjacent)).json()["data"][
        "available"
    ] is True
    blocked = stay(clock, offset=60, nights=2)
    assert str(demo_id("listing/0")) not in ids(await api.get(SEARCH, params=blocked))
    assert (await api.get(listing_path() + "/availability", params=blocked)).json()["data"][
        "available"
    ] is False
    cancelled = await db.get(Booking, demo_id("booking/9"))
    assert (
        await api.get(
            listing_path(1) + "/availability",
            params={
                "check_in": cancelled.check_in.isoformat(),
                "check_out": cancelled.check_out.isoformat(),
            },
        )
    ).json()["data"]["available"] is True


async def test_window_guest_and_contact_hour_rules(api, db, clock):
    params = stay(clock, check_in_time="14:00")
    assert ids(await api.get(SEARCH, params=params)) == set()
    assert ids(await api.get(SEARCH, params={**params, "available_only": "false"})) == set()
    response = await api.get(listing_path() + "/availability", params=params)
    assert (
        response.status_code == 422 and response.json()["error"]["code"] == "OUTSIDE_BOOKING_WINDOW"
    )
    assert (
        await api.get(listing_path() + "/availability", params=stay(clock, guests=3))
    ).status_code == 422
    await db.execute(
        update(ListingHours)
        .where(ListingHours.listing_id == demo_id("listing/0"))
        .values(closed=True, opening_time=None, closing_time=None)
    )
    await db.commit()
    detail = await api.get(listing_path(), params=stay(clock))
    assert detail.status_code == 200 and detail.json()["data"]["available"] is True
    assert all(row["closed"] for row in detail.json()["data"]["hours"])


async def test_radius_search_and_stable_sorting(api):
    params = {"latitude": 37.3382, "longitude": -121.8863, "radius_km": 10, "sort": "distance_asc"}
    result = await api.get(SEARCH, params=params)
    assert ids(result) == {str(demo_id("listing/0")), str(demo_id("listing/4"))}
    assert all(item["distance_km"] == 0 for item in result.json()["data"])
    ids_sorted = [item["id"] for item in result.json()["data"]]
    assert ids_sorted == sorted(ids_sorted)
    for sort, reverse in [("price_asc", False), ("price_desc", True)]:
        result = await api.get(SEARCH, params={"sort": sort})
        prices = [Decimal(item["nightly_price"]) for item in result.json()["data"]]
        assert prices == sorted(prices, reverse=reverse)
    result = await api.get(SEARCH, params={"sort": "rating_desc"})
    ratings = [item["average_rating"] for item in result.json()["data"]]
    nonnull = [rating for rating in ratings if rating is not None]
    assert nonnull == sorted(nonnull, reverse=True)
    assert ratings[-1] is None
    result = await api.get(SEARCH, params={"latitude": 0, "longitude": 0, "radius_km": 1})
    assert ids(result) == set()


async def test_pagination_defaults_empty_pages_and_counts(api):
    collected = []
    for page in range(1, 5):
        result = await api.get(SEARCH, params={"page": page, "page_size": 2})
        assert result.status_code == 200
        assert result.json()["pagination"] == {
            "page": page,
            "page_size": 2,
            "total_items": 8,
            "total_pages": 4,
        }
        collected += [item["id"] for item in result.json()["data"]]
    assert len(set(collected)) == 8
    empty = await api.get(SEARCH, params={"page": 5, "page_size": 2})
    assert empty.json()["data"] == [] and empty.json()["pagination"]["total_items"] == 8
    no_matches = await api.get(SEARCH, params={"city": "No Such City"})
    assert no_matches.json()["pagination"]["total_pages"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"available_only": "true"},
        {"check_in": "2020-01-01", "duration_nights": 1},
        {"check_in": "2030-01-01", "duration_nights": 15},
        {"check_in": "2030-01-01", "duration_nights": 1, "check_in_time": "15:00:00"},
        {"latitude": 37},
        {"page_size": 51},
        {"amenities": "Wi-Fi"},
        {"unexpected": "value"},
    ],
)
async def test_global_http_validation_uses_json_error_envelope(api, params):
    response = await api.get(SEARCH, params=params)
    assert response.status_code == 422
    assert response.json()["success"] is False
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert response.json()["error"]["details"]


async def test_same_day_arrival_is_checked_in_listing_timezone(api, clock):
    clock[0] = datetime(2030, 1, 2, 1, tzinfo=UTC)  # Jan 1, 17:00 in Los Angeles.
    params = {"check_in": "2030-01-01", "duration_nights": 1, "check_in_time": "18:00"}
    response = await api.get(listing_path() + "/availability", params=params)
    assert response.status_code == 200 and response.json()["data"]["available"] is True
    params["check_in_time"] = "16:00"
    response = await api.get(listing_path() + "/availability", params=params)
    assert response.status_code == 422 and response.json()["error"]["code"] == "ARRIVAL_IN_PAST"


async def test_dst_failure_excludes_only_affected_listing_from_search(api, db, clock):
    clock[0] = datetime(2027, 1, 1, tzinfo=UTC)
    await db.execute(
        update(Listing).where(Listing.id == demo_id("listing/4")).values(timezone="UTC")
    )
    await db.execute(
        update(ListingBookingRule)
        .where(ListingBookingRule.listing_id.in_([demo_id("listing/0"), demo_id("listing/4")]))
        .values(arrival_start=time(0), arrival_end=time(4), arrival_default=time(1, 30))
    )
    await db.commit()
    params = {
        "check_in": "2027-11-07",
        "duration_nights": 1,
        "check_in_time": "01:30",
        "zip_code": "95112",
    }
    assert ids(await api.get(SEARCH, params=params)) == {str(demo_id("listing/4"))}
    params.pop("zip_code")
    response = await api.get(listing_path() + "/availability", params=params)
    assert (
        response.status_code == 422 and response.json()["error"]["code"] == "AMBIGUOUS_LOCAL_TIME"
    )


async def test_public_openapi_documents_all_filters_and_no_auth_requirement(api):
    schema = (await api.get("/openapi.json")).json()
    for path in (
        "/api/v1/amenities",
        SEARCH,
        "/api/v1/listings/{listing_id}",
        "/api/v1/listings/{listing_id}/availability",
    ):
        operation = schema["paths"][path]["get"]
        assert not operation.get("security")
        assert "422" in operation["responses"]
    params = {item["name"] for item in schema["paths"][SEARCH]["get"]["parameters"]}
    assert {
        "check_in",
        "check_out",
        "duration_nights",
        "check_in_time",
        "check_out_time",
        "guests",
        "city",
        "state",
        "zip_code",
        "latitude",
        "longitude",
        "radius_km",
        "amenities",
        "min_price",
        "max_price",
        "available_only",
        "sort",
        "page",
        "page_size",
    } == params
