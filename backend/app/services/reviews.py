from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models import Booking, Listing, Review
from app.models.enums import ListingStatus, ReservationState
from app.schemas.reviews import CreatedReview, PublicReview, ReviewCreate
from app.services import bookings, listings
from app.services.pagination import PageQuery

Clock = Callable[[], datetime]


def eligible_reviews(now: datetime):
    """Keep public review pages and listing rating aggregates on one policy."""
    return (
        Booking.reservation_state == ReservationState.CONFIRMED,
        Booking.departure_at <= now,
        Review.created_at <= now,
    )


async def create_review(
    session: AsyncSession, customer_id: UUID, request: ReviewCreate, clock: Clock
) -> CreatedReview:
    try:
        # Read ownership without acquiring a booking lock ahead of its listing.
        listing_id = await session.scalar(
            select(Booking.listing_id).where(
                Booking.id == request.booking_id, Booking.customer_id == customer_id
            )
        )
        if listing_id is None:
            raise APIError(404, "NOT_FOUND", "Booking not found")
        # Removal does not erase a past guest's ability to leave feedback. Public
        # pages still require approval; no current-listing state is changed here.
        await listings.lock_listing(session, listing_id)
        booking = await bookings.owned_booking(session, customer_id, request.booking_id, lock=True)
        now = clock()
        if booking.reservation_state != ReservationState.CONFIRMED or booking.departure_at > now:
            raise APIError(
                409, "REVIEW_NOT_ALLOWED", "Only noncancelled checked-out stays can be reviewed"
            )
        review = await session.scalar(
            insert(Review)
            .values(
                booking_id=booking.id,
                rating=request.rating,
                comment=request.comment,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=[Review.booking_id])
            .returning(Review)
        )
        if review is None:
            raise APIError(409, "REVIEW_ALREADY_EXISTS", "This booking already has a review")
        result = CreatedReview(
            **PublicReview.model_validate(review).model_dump(),
            booking_id=booking.id,
            listing_id=listing_id,
        )
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise


class ReviewPage(PageQuery[Review, PublicReview]):
    def __init__(self, listing_id: UUID, now: datetime) -> None:
        self.listing_id, self.now = listing_id, now

    def statement(self) -> Select:
        return (
            select(Review)
            .join(Booking, Review.booking_id == Booking.id)
            .where(Booking.listing_id == self.listing_id, *eligible_reviews(self.now))
        )

    def order_by(self):
        return (Review.created_at.desc(), Review.id)

    def to_item(self, row: Review) -> PublicReview:
        return PublicReview.model_validate(row)


async def public_reviews(session, listing_id, page, page_size, clock: Clock):
    approved = await session.scalar(
        select(Listing.id).where(Listing.id == listing_id, Listing.status == ListingStatus.APPROVED)
    )
    if approved is None:
        raise APIError(404, "NOT_FOUND", "Listing not found")
    return await ReviewPage(listing_id, clock()).fetch(session, page, page_size)
