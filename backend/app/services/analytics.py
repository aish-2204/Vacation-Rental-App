from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Date, String, cast, func, literal, null, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Booking, Listing
from app.models.enums import ListingStatus, ReservationState
from app.schemas.analytics import (
    AnalyticsQuery,
    AnalyticsResponse,
    BookingsByZip,
    DailyBookings,
    RentalsByZip,
)
from app.services.scopes import AccessScope

ZERO = Decimal("0.00")


@dataclass
class BookingMetrics:
    """Value object for one group of booking counts (total, per ZIP, per day)."""

    bookings_created: int = 0
    cancelled_bookings: int = 0
    net_bookings: int = 0
    booking_value_usd: Decimal = ZERO

    def add(self, row) -> None:
        self.bookings_created += row["bookings_created"]
        self.cancelled_bookings += row["cancelled_bookings"]
        self.net_bookings += row["bookings_created"] - row["cancelled_bookings"]
        self.booking_value_usd += row["booking_value_usd"].quantize(Decimal("0.01"))

    def as_dict(self) -> dict:
        return asdict(self)


async def analytics(
    session: AsyncSession,
    query: AnalyticsQuery,
    clock: Callable[[], datetime],
    scope: AccessScope,
) -> AnalyticsResponse:
    end = clock().astimezone(UTC)
    start = end - timedelta(days=query.period_days)
    listing_filters = scope.listing_filters()
    booking_filters = scope.listing_filters()
    if query.zip_code is not None:
        listing_filters.append(Listing.zip_code == query.zip_code)
        booking_filters.append(Booking.listing_zip_snapshot == query.zip_code)
    booking_filters.extend((Booking.created_at >= start, Booking.created_at < end))

    # Both grouped populations use ONE SQL statement/snapshot. Totals and all
    # chart breakdowns derive from these rows, even during concurrent writes.
    current_listings = (
        select(
            literal("listing").label("kind"),
            Listing.zip_code.label("zip_code"),
            cast(Listing.status, String).label("listing_status"),
            cast(null(), Date).label("booking_date"),
            func.count(Listing.id).label("total_listings"),
            func.count(Listing.id)
            .filter(Listing.created_at >= start, Listing.created_at < end)
            .label("new_listings_in_period"),
            literal(0).label("bookings_created"),
            literal(0).label("cancelled_bookings"),
            literal(ZERO).label("booking_value_usd"),
        )
        .where(*listing_filters)
        .group_by(Listing.zip_code, Listing.status)
    )
    utc_date = func.timezone("UTC", Booking.created_at).cast(Date)
    historical_bookings = (
        select(
            literal("booking"),
            Booking.listing_zip_snapshot,
            cast(null(), String),
            utc_date,
            literal(0),
            literal(0),
            func.count(Booking.id),
            func.count(Booking.id).filter(Booking.reservation_state == ReservationState.CANCELLED),
            func.coalesce(
                func.sum(Booking.total_cost).filter(
                    Booking.reservation_state == ReservationState.CONFIRMED
                ),
                ZERO,
            ),
        )
        .join(Listing, Booking.listing_id == Listing.id)
        .where(*booking_filters)
        .group_by(utc_date, Booking.listing_zip_snapshot)
    )
    rows = (await session.execute(union_all(current_listings, historical_bookings))).mappings()
    totals = BookingMetrics()
    status_counts = dict.fromkeys(ListingStatus, 0)
    rentals = defaultdict(int)
    by_zip = defaultdict(BookingMetrics)
    by_day = defaultdict(BookingMetrics)
    new_listings = 0
    for row in rows:
        if row["kind"] == "listing":
            rentals[row["zip_code"]] += row["total_listings"]
            status_counts[ListingStatus(row["listing_status"])] += row["total_listings"]
            new_listings += row["new_listings_in_period"]
        else:
            totals.add(row)
            by_zip[row["zip_code"]].add(row)
            by_day[row["booking_date"]].add(row)

    daily = []
    day = start.date()
    # UTC calendar dates intersecting the rolling window: partial first/last
    # days are clipped, so non-midnight windows normally touch period_days+1 dates.
    while (midnight := datetime.combine(day, time.min, UTC)) < end:
        following = midnight + timedelta(days=1)
        daily.append(
            DailyBookings(
                date=day,
                window_start=max(start, midnight),
                window_end=min(end, following),
                **by_day[day].as_dict(),
            )
        )
        day = following.date()
    return AnalyticsResponse(
        **totals.as_dict(),
        scope=scope.label,
        period_days=query.period_days,
        zip_code=query.zip_code,
        window_start=start,
        window_end=end,
        total_listings=sum(rentals.values()),
        listing_status_counts=status_counts,
        new_listings_in_period=new_listings,
        rentals_by_zip=[
            RentalsByZip(zip_code=zip_code, total_listings=rentals[zip_code])
            for zip_code in sorted(rentals)
        ],
        bookings_by_zip=[
            BookingsByZip(zip_code=zip_code, **by_zip[zip_code].as_dict())
            for zip_code in sorted(by_zip)
        ],
        daily_bookings=daily,
    )
