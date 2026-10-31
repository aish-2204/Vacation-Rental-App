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


async def test_admin_is_sum_of_all_host_scopes(api, db, clock):
    await curated_data(db, clock)
    hosts = (await db.scalars(select(User.id).where(User.role == Role.HOST))).all()
    parts = [
        (await api.get(HOST, headers=auth(user_id=identifier))).json()["data"]
        for identifier in hosts
    ]
    admin = (await api.get(ADMIN, headers=auth("admin"))).json()["data"]
    for key in (
        "total_listings",
        "new_listings_in_period",
        "bookings_created",
        "cancelled_bookings",
        "net_bookings",
    ):
        assert admin[key] == sum(part[key] for part in parts)
    assert Decimal(admin["booking_value_usd"]) == sum(
        Decimal(part["booking_value_usd"]) for part in parts
    )
    for status in admin["listing_status_counts"]:
        assert admin["listing_status_counts"][status] == sum(
            part["listing_status_counts"][status] for part in parts
        )
    reconcile(admin)


async def test_seed_window_fixtures_match_independent_python_counts(api, db, clock):
    # No new fixture population: exercise the original exact 30/60/90-day seed edges.
    bookings = (await db.scalars(select(Booking))).all()
    for period in (30, 60, 90):
        start = clock[0] - timedelta(days=period)
        selected = [booking for booking in bookings if start <= booking.created_at < clock[0]]
        cancelled = [booking for booking in selected if booking.reservation_state == "CANCELLED"]
        data = (await api.get(ADMIN, headers=auth("admin"), params={"period_days": period})).json()[
            "data"
        ]
        assert data["bookings_created"] == len(selected) and data["cancelled_bookings"] == len(
            cancelled
        )
        assert Decimal(data["booking_value_usd"]) == sum(
            (booking.total_cost for booking in selected if booking not in cancelled),
            Decimal("0.00"),
        )
        reconcile(data)


async def test_utc_grouping_ignores_database_and_listing_timezones(
    api, db, clock, database_timezone
):
    clock[0] = datetime(2027, 3, 15, 12, tzinfo=UTC).astimezone(ZoneInfo("America/Los_Angeles"))
    database_timezone[0] = "Pacific/Honolulu"
    listing = await add_listing(db, clock[0] - timedelta(days=40))
    for index, created in enumerate(
        [datetime(2027, 3, 14, 23, 59, 59, tzinfo=UTC), datetime(2027, 3, 15, 0, 0, tzinfo=UTC)]
    ):
        await add_booking(db, clock, listing, created, price="11.11", offset=500 + index * 4)
    await db.commit()
    data = (await api.get(ADMIN, headers=auth("admin"), params={"zip_code": "99999"})).json()[
        "data"
    ]
    assert datetime.fromisoformat(data["window_end"]) == datetime(2027, 3, 15, 12, tzinfo=UTC)
    assert datetime.fromisoformat(data["window_end"]) - datetime.fromisoformat(
        data["window_start"]
    ) == timedelta(days=30)
    active = [row for row in data["daily_bookings"] if row["bookings_created"]]
    assert [row["date"] for row in active] == ["2027-03-14", "2027-03-15"]
    assert [row["booking_value_usd"] for row in active] == ["11.11", "11.11"]
    reconcile(data)


async def test_price_edits_preserve_booking_value_and_cancelled_older_creations_stay_out(
    api, db, clock
):
    hosts, listings, bookings = await curated_data(db, clock)
    # Aggregation fixtures need no children, but an actual edit to an APPROVED
    # listing rightly revalidates approval completeness. Copy valid form rows
    # into this disposable fixture before exercising the Host edit API.
    for model in (ListingHours, ListingBookingRule, ListingMedia):
        originals = (
            await db.scalars(select(model).where(model.listing_id == demo_id("listing/0")))
        ).all()
        for original in originals:
            values = {
                column.name: getattr(original, column.name) for column in model.__table__.columns
            }
            values.update(id=uuid4(), listing_id=listings[0].id)
            db.add(model(**values))
    await db.commit()
    path = f"/api/v1/host/listings/{listings[0].id}"
    changed = await api.patch(
        path, headers=auth(user_id=hosts[0].id), json={"nightly_price": "999.99"}
    )
    assert changed.status_code == 200, changed.text
    older = await add_booking(
        db, clock, listings[0], clock[0] - timedelta(days=100), cancelled=True, offset=900
    )
    older.cancelled_at = clock[0] - timedelta(hours=1)
    await db.commit()
    data = (await api.get(HOST, headers=auth(user_id=hosts[0].id))).json()["data"]
    assert (
        data["booking_value_usd"] == "400.40"
        and data["bookings_created"] == 3
        and data["cancelled_bookings"] == 1
    )
    assert bookings[0].total_cost == Decimal("100.10")
    reconcile(data)


async def test_empty_host_and_large_money_totals_are_valid(api, db, clock):
    hosts, _, _ = await curated_data(db, clock)
    # Aggregate money is not limited to one booking's NUMERIC(10,2) range.
    listing = await add_listing(
        db, clock[0] - timedelta(days=1), host_id=hosts[0].id, zip_code="00004"
    )
    for index in range(2):
        await add_booking(
            db,
            clock,
            listing,
            clock[0] - timedelta(hours=1),
            price="99999999.99",
            offset=900 + index * 4,
        )
    await db.commit()
    data = (
        await api.get(HOST, headers=auth(user_id=hosts[0].id), params={"zip_code": "00004"})
    ).json()["data"]
    assert data["booking_value_usd"] == "199999999.98" and data["net_bookings"] == 2
    template = await db.get(User, hosts[0].id)
    identifier = uuid4()
    db.add(
        User(
            id=identifier,
            name="Empty Host",
            email=f"{identifier}@example.test",
            password_hash=template.password_hash,
            phone="+15550100100",
            role=Role.HOST,
            created_at=clock[0],
            updated_at=clock[0],
        )
    )
    await db.commit()
    empty = (await api.get(HOST, headers=auth(user_id=identifier))).json()["data"]
    assert empty["total_listings"] == empty["new_listings_in_period"] == 0
    assert (
        empty["booking_value_usd"] == "0.00"
        and empty["rentals_by_zip"] == empty["bookings_by_zip"] == []
    )
    reconcile(empty)


async def test_known_other_host_scope_injection_is_denied_and_reads_are_private(api, db, clock):
    hosts, _, _ = await curated_data(db, clock)
    denied = await api.get(
        HOST, headers=auth(user_id=hosts[0].id), params={"host_id": str(hosts[1].id)}
    )
    assert denied.status_code == 422
    data = (await api.get(HOST, headers=auth(user_id=hosts[0].id))).json()["data"]
    assert data["total_listings"] == 2 and data["booking_value_usd"] == "400.40"
    assert set(data) == {
        "scope",
        "period_days",
        "zip_code",
        "window_start",
        "window_end",
        "timezone",
        "currency",
        "total_listings",
        "listing_status_counts",
        "new_listings_in_period",
        "rentals_by_zip",
        "bookings_created",
        "cancelled_bookings",
        "net_bookings",
        "booking_value_usd",
        "bookings_by_zip",
        "daily_bookings",
    }
    for forbidden in ("customer_id", "booking_id", "email", "password_hash", "revenue", "host_id"):
        assert forbidden not in str(data)
    reconcile(data)


async def test_zip_plus_four_filters_both_populations_and_all_cancelled_values_are_zero(
    api, db, clock
):
    hosts, _, _ = await curated_data(db, clock)
    listing = await add_listing(
        db, clock[0] - timedelta(days=1), host_id=hosts[0].id, zip_code="02108-1234"
    )
    for index in range(2):
        await add_booking(
            db,
            clock,
            listing,
            clock[0] - timedelta(hours=1),
            cancelled=True,
            offset=950 + index * 4,
        )
    await db.commit()
    data = (
        await api.get(HOST, headers=auth(user_id=hosts[0].id), params={"zip_code": "02108-1234"})
    ).json()["data"]
    assert data["total_listings"] == data["new_listings_in_period"] == 1
    assert metrics(data) == {
        "bookings_created": 2,
        "cancelled_bookings": 2,
        "net_bookings": 0,
        "booking_value_usd": "0.00",
    }
    assert data["rentals_by_zip"] == [{"zip_code": "02108-1234", "total_listings": 1}]
    reconcile(data)
