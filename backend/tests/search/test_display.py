from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import update

from app.models import Booking, Listing, Review
from app.models.enums import ReservationState
from app.services.search import haversine_km
from seed.demo import demo_id
from tests.search.helpers import SEARCH, listing_path


async def test_cost_rating_review_counts_and_no_review_null(api):
    response = await api.get(SEARCH)
    data = {row["id"]: row for row in response.json()["data"]}
    for index, rating in [(0, "$"), (1, "$$"), (2, "$$"), (3, "$$$"), (4, "$$$"), (5, "$$$$")]:
        assert data[str(demo_id(f"listing/{index}"))]["cost_rating"] == rating
    assert data[str(demo_id("listing/0"))]["average_rating"] == 3.0
    assert data[str(demo_id("listing/0"))]["review_count"] == 1
    assert data[str(demo_id("listing/2"))]["average_rating"] is None
    assert data[str(demo_id("listing/2"))]["review_count"] == 0


async def test_future_and_cancelled_stay_reviews_never_inflate_public_ratings(api, db, clock):
    for index in (8, 9, 2):
        db.add(
            Review(
                id=uuid4(),
                booking_id=demo_id(f"booking/{index}"),
                rating=5,
                comment="Invalid eligibility fixture",
                created_at=clock[0],
            )
        )
    await db.commit()
    expected = [(0, 3.0, 1), (1, 4.0, 1), (2, None, 0)]
    for index, average, count in expected:
        response = await api.get(listing_path(index))
        assert response.status_code == 200
        assert response.json()["data"]["average_rating"] == average
        assert response.json()["data"]["review_count"] == count


async def test_bookings_today_uses_listing_local_day_and_excludes_cancelled(api, db, clock):
    clock[0] = datetime(2026, 11, 16, 2, tzinfo=UTC)
    await db.execute(update(Booking).values(created_at=clock[0] - timedelta(days=200)))
    await db.execute(
        update(Listing).where(Listing.id == demo_id("listing/2")).values(timezone="Asia/Tokyo")
    )
    template = await db.get(Booking, demo_id("booking/8"))
    for listing_index, start in [
        (0, datetime(2026, 11, 15, 8, tzinfo=UTC)),  # Nov 15 in Los Angeles.
        (2, datetime(2026, 11, 15, 15, tzinfo=UTC)),  # Nov 16 in Tokyo.
    ]:
        end = start + timedelta(days=1)
        times = [
            start - timedelta(microseconds=1),
            start,
            start + timedelta(hours=1),
            end - timedelta(microseconds=1),
            end,
            start + timedelta(hours=2),
        ]
        for index, created in enumerate(times):
            values = {
                column.name: getattr(template, column.name) for column in Booking.__table__.columns
            }
            first = template.check_in + timedelta(days=700 + index * 10)
            cancelled = index == 5
            values.update(
                id=uuid4(),
                listing_id=demo_id(f"listing/{listing_index}"),
                check_in=first,
                check_out=first + timedelta(days=2),
                arrival_at=template.arrival_at + timedelta(days=700 + index * 10),
                departure_at=template.arrival_at + timedelta(days=702 + index * 10),
                total_cost=template.nightly_price_snapshot * 2,
                created_at=created,
                updated_at=created,
                reservation_state=ReservationState.CANCELLED
                if cancelled
                else ReservationState.CONFIRMED,
                cancelled_at=created + timedelta(minutes=1) if cancelled else None,
            )
            db.add(Booking(**values))
    await db.commit()
    for index in (0, 2):
        response = await api.get(listing_path(index))
        assert response.status_code == 200
        assert response.json()["data"]["bookings_today"] == 3


async def test_totals_are_counted_after_availability_filter(api, db):
    booking = await db.get(Booking, demo_id("booking/8"))
    params = {
        "check_in": booking.check_in.isoformat(),
        "check_out": booking.check_out.isoformat(),
        "page_size": 2,
    }
    default = await api.get(SEARCH, params=params)
    marked = await api.get(SEARCH, params={**params, "available_only": "false"})
    assert default.json()["pagination"]["total_items"] == 7
    assert default.json()["pagination"]["total_pages"] == 4
    assert marked.json()["pagination"]["total_items"] == 8


async def test_radius_filter_uses_unrounded_distance(api):
    radius = haversine_km(37.3382, -121.8863, 37.7749, -122.4194)
    params = {
        "latitude": 37.3382,
        "longitude": -121.8863,
        "radius_km": radius,
        "sort": "distance_asc",
    }
    included = await api.get(SEARCH, params=params)
    assert str(demo_id("listing/2")) in {item["id"] for item in included.json()["data"]}
    outside = await api.get(SEARCH, params={**params, "radius_km": radius - 0.0001})
    assert str(demo_id("listing/2")) not in {item["id"] for item in outside.json()["data"]}
