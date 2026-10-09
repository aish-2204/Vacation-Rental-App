"""Shared nightly/date/time validation for search, quotes, and future bookings."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AvailabilityBlock, Booking, Listing, ListingBookingRule
from app.models.enums import ListingStatus, ReservationState


class StayError(ValueError):
    def __init__(self, code: str, field: str, message: str):
        self.code, self.field = code, field
        super().__init__(message)


@dataclass(frozen=True)
class StayRequest:
    check_in: date
    check_out: date
    guests: int = 1
    check_in_time: time | None = None
    check_out_time: time | None = None

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


@dataclass(frozen=True)
class ResolvedStay:
    check_in: date
    check_out: date
    nights: int
    guests: int
    check_in_time: time
    check_out_time: time
    arrival_at: datetime
    departure_at: datetime
    nightly_price: Decimal
    total_cost: Decimal
    currency: str


def resolve_dates(check_in: date, check_out: date | None, duration: int | None) -> date:
    if check_out is None and duration is None:
        raise StayError("INVALID_STAY", "check_out", "Supply check_out or duration_nights")
    if duration is not None and not 1 <= duration <= 14:
        raise StayError("INVALID_STAY", "duration_nights", "Stays must be 1 to 14 nights")
    try:
        derived = check_in + timedelta(days=duration) if duration is not None else check_out
    except OverflowError:
        raise StayError(
            "INVALID_STAY", "check_out", "Stay dates exceed the supported range"
        ) from None
    if check_out is not None and derived != check_out:
        raise StayError("INVALID_STAY", "duration_nights", "Duration must agree with check_out")
    if not 1 <= (derived - check_in).days <= 14:
        raise StayError("INVALID_STAY", "check_out", "Stays must be 1 to 14 nights")
    return derived


def validate_global_arrival(request: StayRequest | None, now: datetime) -> None:
    # UTC-12 is the last current local date on Earth. A date before it is
    # impossible everywhere. Same-day arrival is checked in each listing zone.
    if request and request.check_in < (now.astimezone(UTC) - timedelta(hours=12)).date():
        raise StayError("ARRIVAL_IN_PAST", "check_in", "Check-in date is in the past")


def local_to_utc(day: date, wall_time: time, timezone: ZoneInfo, field: str) -> datetime:
    naive = datetime.combine(day, wall_time)
    candidates = set()
    for fold in (0, 1):
        try:
            candidate = naive.replace(tzinfo=timezone, fold=fold).astimezone(UTC)
            if candidate.astimezone(timezone).replace(tzinfo=None) == naive:
                candidates.add(candidate)
        except (OverflowError, ValueError):
            raise StayError(
                "INVALID_STAY", field, "Local time exceeds the supported date range"
            ) from None
    if not candidates:
        raise StayError(
            "NONEXISTENT_LOCAL_TIME",
            field,
            "Time does not exist on this date in the listing timezone",
        )
    if len(candidates) != 1:
        raise StayError(
            "AMBIGUOUS_LOCAL_TIME", field, "Time is ambiguous on this date in the listing timezone"
        )
    return candidates.pop()


def resolve_listing_stay(
    listing: Listing, request: StayRequest, rules: list[ListingBookingRule], now: datetime
) -> ResolvedStay:
    """Resolve and validate a stay; never infer availability from time-of-day overlap.

    Phase 6 must call this after locking/reloading the listing and recheck nightly
    inventory in that same transaction. This helper does not acquire a lock.
    """
    if listing.status != ListingStatus.APPROVED:
        raise StayError("LISTING_UNAVAILABLE", "listing_id", "Listing is not approved")
    resolve_dates(request.check_in, request.check_out, None)
    if request.guests < 1 or request.guests > listing.max_guests:
        raise StayError("GUEST_LIMIT", "guests", "Guest count exceeds the listing capacity")
    try:
        timezone = ZoneInfo(listing.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise StayError("INVALID_TIMEZONE", "timezone", "Listing timezone is not valid") from None
    by_day = {rule.weekday: rule for rule in rules}
    accepted = []
    for direction, day, supplied, field in (
        ("arrival", request.check_in, request.check_in_time, "check_in_time"),
        ("departure", request.check_out, request.check_out_time, "check_out_time"),
    ):
        rule = by_day.get(day.weekday())
        if rule is None or not getattr(rule, f"{direction}_allowed"):
            raise StayError(
                "WINDOW_UNAVAILABLE", field, "This weekday does not allow the requested operation"
            )
        default = getattr(rule, f"{direction}_default")
        start, end = getattr(rule, f"{direction}_start"), getattr(rule, f"{direction}_end")
        wall_time = supplied if supplied is not None else default
        if wall_time is None or start is None or end is None or not start <= wall_time <= end:
            raise StayError(
                "OUTSIDE_BOOKING_WINDOW", field, "Time is outside the listing booking window"
            )
        accepted.append((wall_time, local_to_utc(day, wall_time, timezone, field)))
    (arrival_time, arrival_at), (departure_time, departure_at) = accepted
    if arrival_at <= now:
        raise StayError("ARRIVAL_IN_PAST", "check_in_time", "Arrival must be in the future")
    if departure_at <= arrival_at:
        raise StayError("INVALID_STAY", "check_out_time", "Departure must be after arrival")
    total = (listing.nightly_price * request.nights).quantize(Decimal("0.01"))
    if total > Decimal("99999999.99"):
        raise StayError(
            "TOTAL_OUT_OF_RANGE", "total_cost", "Stay price exceeds the supported total"
        )
    return ResolvedStay(
        request.check_in,
        request.check_out,
        request.nights,
        request.guests,
        arrival_time,
        departure_time,
        arrival_at,
        departure_at,
        listing.nightly_price,
        total,
        listing.currency,
    )


async def occupied_listing_ids(
    session: AsyncSession, listing_ids: list[UUID], request: StayRequest
) -> set[UUID]:
    """Half-open nightly inventory shared by search and future booking validation."""
    bookings = await session.scalars(
        select(Booking.listing_id).where(
            Booking.listing_id.in_(listing_ids),
            Booking.reservation_state == ReservationState.CONFIRMED,
            Booking.check_in < request.check_out,
            Booking.check_out > request.check_in,
        )
    )
    blocks = await session.scalars(
        select(AvailabilityBlock.listing_id).where(
            AvailabilityBlock.listing_id.in_(listing_ids),
            AvailabilityBlock.start_date < request.check_out,
            AvailabilityBlock.end_date > request.check_in,
        )
    )
    return set(bookings.all()) | set(blocks.all())
