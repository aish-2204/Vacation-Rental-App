from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models import Booking, ListingBookingRule, ListingHours, ListingMedia, User
from app.models.enums import Role
from seed.demo import demo_id
from tests.analytics.helpers import ADMIN, HOST, add_booking, add_listing, auth, curated_data


def metrics(data):
    return {
        key: data[key]
        for key in ("bookings_created", "cancelled_bookings", "net_bookings", "booking_value_usd")
    }


def reconcile(data):
    assert sum(data["listing_status_counts"].values()) == data["total_listings"]
    assert sum(row["total_listings"] for row in data["rentals_by_zip"]) == data["total_listings"]
    for name in ("bookings_by_zip", "daily_bookings"):
        rows = data[name]
        for key in ("bookings_created", "cancelled_bookings", "net_bookings"):
            assert sum(row[key] for row in rows) == data[key]
        assert sum((Decimal(row["booking_value_usd"]) for row in rows), Decimal("0.00")) == Decimal(
            data["booking_value_usd"]
        )
        assert all(
            row["bookings_created"] - row["cancelled_bookings"] == row["net_bookings"]
            for row in rows
        )
    assert data["bookings_created"] - data["cancelled_bookings"] == data["net_bookings"]
    assert [row["zip_code"] for row in data["rentals_by_zip"]] == sorted(
        row["zip_code"] for row in data["rentals_by_zip"]
    )
    assert [row["zip_code"] for row in data["bookings_by_zip"]] == sorted(
        row["zip_code"] for row in data["bookings_by_zip"]
    )


async def test_hand_calculated_host_totals_statuses_and_removed_history(api, db, clock):
    hosts, _, bookings = await curated_data(db, clock)
    first = await api.get(HOST, headers=auth(user_id=hosts[0].id))
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["scope"] == "HOST" and data["period_days"] == 30 and data["zip_code"] is None
    assert data["total_listings"] == 2 and data["new_listings_in_period"] == 1
    assert data["listing_status_counts"] == {
        "APPROVED": 1,
        "PENDING": 0,
        "REJECTED": 0,
        "REMOVED": 1,
    }
    assert metrics(data) == {
        "bookings_created": 3,
        "cancelled_bookings": 1,
        "net_bookings": 2,
        "booking_value_usd": "400.40",
    }
    assert data["rentals_by_zip"] == [
        {"zip_code": "00001", "total_listings": 1},
        {"zip_code": "00002", "total_listings": 1},
    ]
    assert data["bookings_by_zip"] == [{"zip_code": "00001", **metrics(data)}]
    assert bookings[2].departure_at < clock[0]  # Completed retained reservation still contributes.
    reconcile(data)
    second = (await api.get(HOST, headers=auth(user_id=hosts[1].id))).json()["data"]
    assert second["total_listings"] == 2 and second["new_listings_in_period"] == 1
    assert second["listing_status_counts"] == {
        "APPROVED": 0,
        "PENDING": 1,
        "REJECTED": 1,
        "REMOVED": 0,
    }
    assert metrics(second) == {
        "bookings_created": 1,
        "cancelled_bookings": 0,
        "net_bookings": 1,
        "booking_value_usd": "400.40",
    }
    reconcile(second)


@pytest.mark.parametrize("period", [30, 60, 90])
async def test_admin_zip_counts_use_current_listings_and_saved_booking_zip(api, db, clock, period):
    await curated_data(db, clock)
    data = (
        await api.get(
            ADMIN, headers=auth("admin"), params={"period_days": period, "zip_code": "00001"}
        )
    ).json()["data"]
    assert data["scope"] == "ADMIN" and data["period_days"] == period
    assert data["total_listings"] == 2 and data["new_listings_in_period"] == 2
    assert metrics(data) == {
        "bookings_created": 4,
        "cancelled_bookings": 1,
        "net_bookings": 3,
        "booking_value_usd": "800.80",
    }
    assert data["listing_status_counts"] == {
        "APPROVED": 1,
        "PENDING": 1,
        "REJECTED": 0,
        "REMOVED": 0,
    }
    assert data["rentals_by_zip"] == [{"zip_code": "00001", "total_listings": 2}]
    assert data["bookings_by_zip"] == [{"zip_code": "00001", **metrics(data)}]
    reconcile(data)
    moved = (
        await api.get(
            ADMIN, headers=auth("admin"), params={"period_days": period, "zip_code": "00002"}
        )
    ).json()["data"]
    assert moved["total_listings"] == 1 and moved["listing_status_counts"]["REMOVED"] == 1
    assert metrics(moved) == {
        "bookings_created": 0,
        "cancelled_bookings": 0,
        "net_bookings": 0,
        "booking_value_usd": "0.00",
    }
    assert moved["bookings_by_zip"] == []
    reconcile(moved)


@pytest.mark.parametrize(
    "period,created,value,new", [(30, 1, "400.40", 1), (60, 2, "900.90", 2), (90, 2, "900.90", 2)]
)
async def test_period_selection_changes_only_period_metrics(
    api, db, clock, period, created, value, new
):
    hosts, _, _ = await curated_data(db, clock)
    data = (
        await api.get(HOST, headers=auth(user_id=hosts[1].id), params={"period_days": period})
    ).json()["data"]
    assert data["total_listings"] == 2 and data["new_listings_in_period"] == new
    assert (
        data["bookings_created"] == data["net_bookings"] == created
        and data["booking_value_usd"] == value
    )
    reconcile(data)


@pytest.mark.parametrize("period", [30, 60, 90])
async def test_start_inclusive_end_exclusive_for_listings_and_bookings(api, db, clock, period):
    clock[0] = datetime(2026, 11, 16, 12, 30, tzinfo=UTC)
    end = clock[0]
    start = end - timedelta(days=period)
    times = [
        start - timedelta(microseconds=1),
        start,
        start + timedelta(microseconds=1),
        end - timedelta(microseconds=1),
        end,
        end + timedelta(microseconds=1),
    ]
    for index, created in enumerate(times):
        listing = await add_listing(db, created)
        await add_booking(
            db,
            clock,
            listing,
            created,
            price=["99.99", "10.01", "20.02", "30.03", "99.99", "99.99"][index],
            cancelled=index == 2,
        )
    await db.commit()
    response = await api.get(
        ADMIN, headers=auth("admin"), params={"period_days": period, "zip_code": "99999"}
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total_listings"] == 6 and data["new_listings_in_period"] == 3
    assert metrics(data) == {
        "bookings_created": 3,
        "cancelled_bookings": 1,
        "net_bookings": 2,
        "booking_value_usd": "40.04",
    }
    assert datetime.fromisoformat(data["window_start"]) == start
    assert datetime.fromisoformat(data["window_end"]) == end
    assert data["timezone"] == "UTC" and data["currency"] == "USD"
    assert len(data["daily_bookings"]) == period + 1
    reconcile(data)


@pytest.mark.parametrize("period", [30, 60, 90])
@pytest.mark.parametrize("hour", [0, 12])
async def test_daily_calendar_buckets_are_zero_filled_clipped_and_contiguous(
    api, clock, period, hour
):
    clock[0] = datetime(2026, 11, 16, hour, tzinfo=UTC)
    data = (
        await api.get(HOST, headers=auth(), params={"period_days": period, "zip_code": "00000"})
    ).json()["data"]
    assert data["total_listings"] == data["bookings_created"] == 0
    assert data["listing_status_counts"] == {
        "APPROVED": 0,
        "PENDING": 0,
        "REJECTED": 0,
        "REMOVED": 0,
    }
    assert data["rentals_by_zip"] == data["bookings_by_zip"] == []
    days = data["daily_bookings"]
    assert len(days) == period + (hour != 0)
    assert days[0]["window_start"] == data["window_start"]
    assert days[-1]["window_end"] == data["window_end"]
    for index, bucket in enumerate(days):
        assert (
            bucket["bookings_created"]
            == bucket["cancelled_bookings"]
            == bucket["net_bookings"]
            == 0
        )
        assert bucket["booking_value_usd"] == "0.00"
        assert datetime.fromisoformat(bucket["window_start"]) < datetime.fromisoformat(
            bucket["window_end"]
        )
        if index:
            assert bucket["window_start"] == days[index - 1]["window_end"]
    reconcile(data)


