from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models import Booking, Listing, ListingBookingRule
from app.models.enums import ReservationState
from app.schemas.bookings import BookingCreate, BookingResponse
from app.schemas.common import Paginated
from app.services import listings
from app.services.availability import (
    ResolvedStay,
    StayError,
    StayRequest,
    occupied_listing_ids,
    resolve_listing_stay,
)
from app.services.listing_state import state_of
from app.services.pagination import PageQuery

Clock = Callable[[], datetime]


def confirmation(booking: Booking, now: datetime) -> BookingResponse:
    """Use accepted snapshots, including after listing edits/removal."""
    cancelled = booking.reservation_state == ReservationState.CANCELLED
    timezone = ZoneInfo(booking.listing_timezone_snapshot)
    return BookingResponse.model_validate(
        {
            **{field: getattr(booking, field) for field in Booking.__table__.columns.keys()},
            "nights": (booking.check_out - booking.check_in).days,
            "check_in_time": booking.arrival_at.astimezone(timezone).time(),
            "check_out_time": booking.departure_at.astimezone(timezone).time(),
            "status": "CANCELLED"
            if cancelled
            else "COMPLETED"
            if booking.departure_at <= now
            else "CONFIRMED",
            "can_cancel": not cancelled and now < booking.arrival_at,
        }
    )


async def owned_booking(session: AsyncSession, customer_id: UUID, booking_id: UUID, *, lock=False):
    statement = select(Booking).where(Booking.id == booking_id, Booking.customer_id == customer_id)
    if lock:
        statement = statement.with_for_update()
    booking = await session.scalar(statement.execution_options(populate_existing=True))
    if booking is None:
        raise APIError(404, "NOT_FOUND", "Booking not found")
    return booking


# ---------------------------------------------------------------------------
# Chain of Responsibility: each check validates one booking rule and passes
# the shared context to the next. Order matters: the listing lock comes first
# (every writer locks the listing before anything else), local stay rules
# (422) are reported before overlapping nights (409).
# ---------------------------------------------------------------------------


@dataclass
class BookingContext:
    session: AsyncSession
    request: BookingCreate
    clock: Clock
    stay_request: StayRequest = field(init=False)
    listing: Listing | None = None
    stay: ResolvedStay | None = None
    now: datetime | None = None

    def __post_init__(self) -> None:
        self.stay_request = self.request.stay_request()


class BookingCheck(ABC):
    def __init__(self) -> None:
        self._next: BookingCheck | None = None

    def then(self, check: "BookingCheck") -> "BookingCheck":
        self._next = check
        return check

    async def handle(self, context: BookingContext) -> None:
        await self.check(context)
        if self._next is not None:
            await self._next.handle(context)

    @abstractmethod
    async def check(self, context: BookingContext) -> None:
        """Raise APIError to stop the chain."""


class ListingIsBookable(BookingCheck):
    async def check(self, context):
        context.listing = await listings.lock_listing(context.session, context.request.listing_id)
        if not state_of(context.listing).accepts_bookings:
            raise APIError(409, "LISTING_UNAVAILABLE", "Listing is not available for booking")


class StayFollowsListingRules(BookingCheck):
    """Dates, local arrival/departure windows, capacity, 1–14 nights, DST."""

    async def check(self, context):
        rules = list(
            (
                await context.session.scalars(
                    select(ListingBookingRule).where(
                        ListingBookingRule.listing_id == context.listing.id
                    )
                )
            ).all()
        )
        # Read the clock only after the listing lock is held.
        context.now = context.clock()
        try:
            context.stay = resolve_listing_stay(
                context.listing, context.stay_request, rules, context.now
            )
        except StayError as exc:
            raise APIError(
                422, exc.code, str(exc), details=[{"field": exc.field, "message": str(exc)}]
            ) from None


class NightsAreFree(BookingCheck):
    async def check(self, context):
        occupied = await occupied_listing_ids(
            context.session, [context.listing.id], context.stay_request
        )
        if context.listing.id in occupied:
            raise APIError(409, "DATES_UNAVAILABLE", "Requested nights are not available")


def booking_checks() -> BookingCheck:
    first = ListingIsBookable()
    first.then(StayFollowsListingRules()).then(NightsAreFree())
    return first


def new_booking(customer_id: UUID, listing: Listing, stay: ResolvedStay, now: datetime) -> Booking:
    """Factory: snapshot the listing so confirmations survive later edits/removal."""
    address = ", ".join(
        part
        for part in (
            listing.address_line1,
            listing.address_line2,
            listing.city,
            listing.state,
            listing.zip_code,
        )
        if part
    )
    return Booking(
        listing_id=listing.id,
        customer_id=customer_id,
        check_in=stay.check_in,
        check_out=stay.check_out,
        arrival_at=stay.arrival_at,
        departure_at=stay.departure_at,
        guests=stay.guests,
        nightly_price_snapshot=stay.nightly_price,
        total_cost=stay.total_cost,
        currency=stay.currency,
        listing_name_snapshot=listing.name,
        listing_address_snapshot=address,
        listing_zip_snapshot=listing.zip_code,
        listing_timezone_snapshot=listing.timezone,
        reservation_state=ReservationState.CONFIRMED,
        cancelled_at=None,
        created_at=now,
        updated_at=now,
    )


async def create_booking(
    session: AsyncSession, customer_id: UUID, request: BookingCreate, clock: Clock
) -> BookingResponse:
    # Auth already began this request's transaction. Keep the listing lock through
    # all validation, snapshot insertion and commit, just like other writers.
    try:
        context = BookingContext(session, request, clock)
        await booking_checks().handle(context)
        booking = new_booking(customer_id, context.listing, context.stay, context.now)
        session.add(booking)
        await session.flush()
        result = confirmation(booking, context.now)
        await session.commit()
        return result
    except IntegrityError as exc:
        await session.rollback()
        # PostgreSQL exclusion is a second defense against writers that bypass
        # the service. Inspect structured driver metadata, never SQL/error text.
        cause = getattr(exc.orig, "__cause__", None)
        if getattr(cause, "constraint_name", None) == "ex_bookings_no_confirmed_overlap":
            raise APIError(409, "DATES_UNAVAILABLE", "Requested nights are not available") from None
        raise
    except Exception:
        await session.rollback()
        raise


