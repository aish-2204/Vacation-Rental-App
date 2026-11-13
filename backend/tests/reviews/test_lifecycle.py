from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update

from app.models import Booking, Listing, Review
from app.models.enums import ListingStatus, ReservationState
from seed.demo import demo_id
from tests.reviews.helpers import REVIEWS, auth, completed_booking, page_path, payload


async def test_review_owned_seeded_past_stay_updates_public_page_search_and_detail(api, db, clock):
    # The seed already reviews every eligible past stay; remove only this fixture
    # schema's example review to exercise reviewing the original seeded booking.
    await db.execute(delete(Review).where(Review.booking_id == demo_id("booking/0")))
    await db.commit()
    before = (await api.get(f"/api/v1/listings/{demo_id('listing/0')}")).json()["data"]
    assert before["average_rating"] is None and before["review_count"] == 0
    request = payload(demo_id("booking/0"), comment="  Comfortable stay.\nThank you!  ", rating=4)
    response = await api.post(REVIEWS, headers=auth(), json=request)
    assert response.status_code == 201, response.text
    created = response.json()["data"]
    assert created["booking_id"] == str(demo_id("booking/0"))
    assert created["listing_id"] == str(demo_id("listing/0"))
    assert created["comment"] == "Comfortable stay.\nThank you!" and created["rating"] == 4
    assert datetime.fromisoformat(created["created_at"]) == clock[0]
    stored = await db.get(Review, UUID(created["id"]))
    assert stored.booking_id == demo_id("booking/0") and stored.rating == 4
    public = await api.get(page_path())
    assert public.status_code == 200
    assert public.json()["data"] == [
        {key: value for key, value in created.items() if key not in ("booking_id", "listing_id")}
    ]
    detail = (await api.get(f"/api/v1/listings/{demo_id('listing/0')}")).json()["data"]
    search = (await api.get("/api/v1/listings/search")).json()["data"]
    card = next(row for row in search if row["id"] == created["listing_id"])
    for data in (detail, card):
        assert data["average_rating"] == 4 and data["review_count"] == 1
    booking = await db.get(Booking, demo_id("booking/0"))
    assert booking.reservation_state == ReservationState.CONFIRMED
    assert booking.updated_at < clock[0]  # Review does not rewrite the reservation.


@pytest.mark.parametrize("actor,expected", [(None, 401), ("host1", 403), ("admin", 403)])
async def test_create_requires_customer_and_get_remains_public(api, actor, expected):
    response = await api.post(
        REVIEWS, headers=auth(actor) if actor else {}, json=payload(demo_id("booking/0"))
    )
    assert response.status_code == expected
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert (await api.get(page_path())).status_code == 200


async def test_foreign_and_missing_booking_errors_are_indistinguishable(api):
    foreign = await api.post(REVIEWS, headers=auth("customer2"), json=payload(demo_id("booking/0")))
    missing = await api.post(REVIEWS, headers=auth("customer2"), json=payload(uuid4()))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"] == missing.json()["error"]


@pytest.mark.parametrize("state", ["future", "ongoing", "cancelled"])
async def test_future_ongoing_and_cancelled_stays_are_ineligible(api, db, clock, state):
    booking = await completed_booking(db, clock)
    if state == "cancelled":
        booking.reservation_state = ReservationState.CANCELLED
        booking.cancelled_at = clock[0] - timedelta(days=400)
    elif state == "future":
        clock[0] = booking.arrival_at - timedelta(microseconds=1)
    else:
        clock[0] = booking.arrival_at + timedelta(hours=1)
    await db.commit()
    response = await api.post(REVIEWS, headers=auth(), json=payload(booking.id))
    assert response.status_code == 409 and response.json()["error"]["code"] == "REVIEW_NOT_ALLOWED"
    assert (
        await db.scalar(
            select(func.count()).select_from(Review).where(Review.booking_id == booking.id)
        )
        == 0
    )


async def test_review_eligibility_opens_exactly_at_utc_checkout(api, db, clock):
    booking = await completed_booking(db, clock)
    clock[0] = booking.departure_at - timedelta(microseconds=1)
    assert (await api.post(REVIEWS, headers=auth(), json=payload(booking.id))).status_code == 409
    clock[0] = booking.departure_at
    assert (await api.post(REVIEWS, headers=auth(), json=payload(booking.id))).status_code == 201
    public = (await api.get(page_path())).json()
    # Existing seed reviews are in the future relative to this frozen clock.
    assert public["pagination"]["total_items"] == 1
    assert public["data"][0]["rating"] == 5


async def test_duplicate_is_conflict_and_never_overwrites_original(api, db, clock):
    booking = await completed_booking(db, clock)
    first = await api.post(REVIEWS, headers=auth(), json=payload(booking.id, rating=1))
    assert first.status_code == 201
    clock[0] += timedelta(minutes=1)
    duplicate = await api.post(
        REVIEWS, headers=auth(), json=payload(booking.id, rating=5, comment="Replace old review")
    )
    assert (
        duplicate.status_code == 409
        and duplicate.json()["error"]["code"] == "REVIEW_ALREADY_EXISTS"
    )
    reviews = (await api.get(page_path())).json()["data"]
    saved = next(row for row in reviews if row["id"] == first.json()["data"]["id"])
    assert saved["rating"] == 1 and saved["comment"] == "A comfortable stay."
    assert saved["created_at"] == first.json()["data"]["created_at"]
    assert (
        await db.scalar(
            select(func.count()).select_from(Review).where(Review.booking_id == booking.id)
        )
        == 1
    )


async def test_each_completed_stay_can_be_reviewed_and_aggregate_is_computed(api, db, clock):
    # Seed listing 0 has one eligible rating of 3. These add 5 and 2 => 3.33.
    for offset, rating in [(-300, 5), (-310, 2)]:
        booking = await completed_booking(db, clock, offset=offset)
        assert (
            await api.post(REVIEWS, headers=auth(), json=payload(booking.id, rating=rating))
        ).status_code == 201
    detail = (await api.get(f"/api/v1/listings/{demo_id('listing/0')}")).json()["data"]
    assert detail["review_count"] == 3 and detail["average_rating"] == 3.33
    assert (await api.get(page_path())).json()["pagination"]["total_items"] == 3
    empty = (await api.get(f"/api/v1/listings/{demo_id('listing/2')}")).json()["data"]
    assert empty["review_count"] == 0 and empty["average_rating"] is None


@pytest.mark.parametrize("index", [8, 9, 10, 11])
async def test_nonpublic_listing_reviews_are_hidden(api, index):
    hidden = await api.get(page_path(index))
    missing = await api.get(f"/api/v1/listings/{uuid4()}/reviews")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json()["error"] == missing.json()["error"]


async def test_removal_preserves_reviews_and_past_guest_right_without_public_exposure(
    api, db, clock
):
    booking = await completed_booking(db, clock)
    assert (
        await api.request(
            "DELETE",
            f"/api/v1/host/listings/{booking.listing_id}",
            headers=auth("host1"),
            json={"reason": "Retire home"},
        )
    ).status_code == 200
    response = await api.post(REVIEWS, headers=auth(), json=payload(booking.id))
    assert response.status_code == 201
    assert (await api.get(page_path())).status_code == 404
    assert (
        await db.scalar(
            select(func.count()).select_from(Review).where(Review.booking_id == booking.id)
        )
        == 1
    )
    assert (await api.get(f"/api/v1/bookings/{booking.id}", headers=auth())).json()["data"][
        "status"
    ] == "COMPLETED"


async def test_public_pages_and_rating_aggregates_share_eligibility(api, db, clock):
    # Legacy/corrupt examples must not make public review totals diverge from cards.
    for index in (8, 9, 2):
        db.add(
            Review(
                booking_id=demo_id(f"booking/{index}"),
                rating=5,
                comment="Ineligible stay",
                created_at=clock[0],
            )
        )
    future_submission = await completed_booking(db, clock, offset=-300)
    db.add(
        Review(
            booking_id=future_submission.id,
            rating=1,
            comment="Future submission",
            created_at=clock[0] + timedelta(days=1),
        )
    )
    await db.commit()
    for index, expected in [(0, 1), (1, 1), (2, 0)]:
        page = (await api.get(page_path(index))).json()
        detail = (await api.get(f"/api/v1/listings/{demo_id(f'listing/{index}')}")).json()["data"]
        assert page["pagination"]["total_items"] == detail["review_count"] == expected
        assert all(
            row["comment"] not in ("Ineligible stay", "Future submission") for row in page["data"]
        )


async def test_public_review_shape_excludes_customer_profile_and_booking_information(api):
    page = (await api.get(page_path())).json()
    assert page["data"]
    for row in page["data"]:
        assert set(row) == {"id", "rating", "comment", "created_at"}
    text = str(page)
    for forbidden in (
        "customer_id",
        "booking_id",
        "email",
        "phone",
        "password_hash",
        "reservation_state",
        "host_id",
    ):
        assert forbidden not in text


async def test_pagination_is_stable_with_ties_and_large_empty_pages(api, db, clock):
    for offset in (-300, -310, -320):
        booking = await completed_booking(db, clock, offset=offset)
        assert (
            await api.post(REVIEWS, headers=auth(), json=payload(booking.id))
        ).status_code == 201
    await db.execute(update(Review).values(created_at=clock[0]))
    await db.commit()
    expected = sorted(
        (
            await db.scalars(
                select(Review.id).join(Booking).where(Booking.listing_id == demo_id("listing/0"))
            )
        ).all()
    )
    seen = []
    for number in (1, 2):
        response = await api.get(page_path(), params={"page": number, "page_size": 2})
        assert response.status_code == 200
        assert response.json()["pagination"] == {
            "page": number,
            "page_size": 2,
            "total_items": 4,
            "total_pages": 2,
        }
        seen.extend(UUID(row["id"]) for row in response.json()["data"])
    assert seen == expected
    for number in (99, 10**30):
        response = await api.get(page_path(), params={"page": number})
        assert response.status_code == 200 and response.json()["data"] == []
        assert response.json()["pagination"]["total_items"] == 4
    empty = (await api.get(page_path(2))).json()
    assert (
        empty["data"] == []
        and empty["pagination"]["total_items"] == empty["pagination"]["total_pages"] == 0
    )


async def test_public_order_is_newest_first(api, db, clock):
    for offset in (-300, -310):
        booking = await completed_booking(db, clock, offset=offset)
        assert (
            await api.post(REVIEWS, headers=auth(), json=payload(booking.id))
        ).status_code == 201
        clock[0] += timedelta(minutes=1)
    rows = (await api.get(page_path())).json()["data"]
    assert [row["created_at"] for row in rows] == sorted(
        (row["created_at"] for row in rows), reverse=True
    )


async def test_utc_checkout_is_authoritative_across_listing_timezone(api, db, clock):
    booking = await completed_booking(db, clock)
    # UTC is the next date while Los Angeles is still on the checkout date.
    booking.departure_at = datetime.combine(
        booking.check_out, datetime.strptime("23:00", "%H:%M").time(), tzinfo=UTC
    )
    await db.commit()
    clock[0] = booking.departure_at - timedelta(microseconds=1)
    assert (await api.post(REVIEWS, headers=auth(), json=payload(booking.id))).status_code == 409
    clock[0] = booking.departure_at
    assert (await api.post(REVIEWS, headers=auth(), json=payload(booking.id))).status_code == 201
    listing = await db.get(Listing, booking.listing_id)
    assert listing.status == ListingStatus.APPROVED
