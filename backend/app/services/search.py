from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from uuid import UUID

from sqlalchemy import Date, DateTime, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models import (
    Amenity,
    Booking,
    Listing,
    ListingAmenity,
    ListingBookingRule,
    ListingHours,
    ListingMedia,
)
from app.models.enums import ListingStatus, ReservationState
from app.schemas.common import Paginated
from app.schemas.search import (
    AvailabilityResponse,
    PublicListingCard,
    PublicListingDetail,
    QuoteResponse,
    SearchQuery,
    StayQuery,
)
from app.services.availability import (
    ResolvedStay,
    StayError,
    occupied_listing_ids,
    resolve_listing_stay,
    validate_global_arrival,
)
from app.services.listings import cost_rating
from app.services.pagination import pagination
from app.services.search_filters import search_filters


def invalid_stay(error: StayError) -> APIError:
    return APIError(
        422, error.code, str(error), details=[{"field": error.field, "message": str(error)}]
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * asin(sqrt(max(0.0, min(1.0, a))))


@dataclass
class RelatedData:
    media: dict
    amenities: dict
    hours: dict
    rules: dict
    ratings: dict
    bookings_today: dict


async def load_related(session: AsyncSession, ids: list[UUID], now: datetime) -> RelatedData:
    """Batch collections/aggregates; never join customer profiles into public data."""
    media, hours, rules, amenities = (defaultdict(list) for _ in range(4))
    if not ids:
        return RelatedData(media, amenities, hours, rules, {}, {})
    for model, destination, order in (
        (ListingMedia, media, (ListingMedia.sort_order, ListingMedia.id)),
        (ListingHours, hours, (ListingHours.weekday,)),
        (ListingBookingRule, rules, (ListingBookingRule.weekday,)),
    ):
        rows = await session.scalars(
            select(model).where(model.listing_id.in_(ids)).order_by(*order)
        )
        for row in rows:
            destination[row.listing_id].append(row)
    for listing_id, amenity in await session.execute(
        select(ListingAmenity.listing_id, Amenity)
        .join(Amenity)
        .where(ListingAmenity.listing_id.in_(ids))
        .order_by(Amenity.name, Amenity.id)
    ):
        amenities[listing_id].append(amenity)
    ratings = {}
    local_created_date = func.timezone(Listing.timezone, Booking.created_at).cast(Date)
    local_today = func.timezone(Listing.timezone, literal(now, type_=DateTime(timezone=True))).cast(
        Date
    )
    today = dict(
        (
            await session.execute(
                select(Booking.listing_id, func.count(Booking.id))
                .join(Listing, Booking.listing_id == Listing.id)
                .where(
                    Booking.listing_id.in_(ids),
                    Booking.reservation_state == ReservationState.CONFIRMED,
                    local_created_date == local_today,
                )
                .group_by(Booking.listing_id)
            )
        ).all()
    )
    return RelatedData(media, amenities, hours, rules, ratings, today)


def public_values(
    listing: Listing,
    related: RelatedData,
    stay: ResolvedStay | None,
    available: bool | None,
    distance: float | None = None,
) -> dict:
    average, count = related.ratings.get(listing.id, (None, 0))
    quote = QuoteResponse.from_stay(stay) if stay else None
    return {
        **{
            field: getattr(listing, field)
            for field in PublicListingCard.model_fields
            if field in Listing.__table__.columns
        },
        "cost_rating": cost_rating(listing.nightly_price),
        "media": related.media[listing.id],
        "amenities": related.amenities[listing.id],
        "average_rating": average,
        "review_count": count,
        "bookings_today": related.bookings_today.get(listing.id, 0),
        "available": available,
        "total_cost": stay.total_cost if stay else None,
        "quote": quote,
        "unavailable_reason": "DATES_UNAVAILABLE" if available is False else None,
        "distance_km": round(distance, 3) if distance is not None else None,
    }


async def search(
    session: AsyncSession, query: SearchQuery, now: datetime
) -> Paginated[PublicListingCard]:
    request = query.stay_request()
    try:
        validate_global_arrival(request, now)
    except StayError as exc:
        raise invalid_stay(exc) from None
    filters = [Listing.status == ListingStatus.APPROVED, *search_filters(query)]
    candidates = list((await session.scalars(select(Listing).where(*filters))).all())
    distances = {}
    if query.latitude is not None:
        for listing in candidates:
            distances[listing.id] = haversine_km(
                query.latitude, query.longitude, float(listing.latitude), float(listing.longitude)
            )
        candidates = [listing for listing in candidates if distances[listing.id] <= query.radius_km]
    ids = [listing.id for listing in candidates]
    related = await load_related(session, ids, now)
    occupied = await occupied_listing_ids(session, ids, request) if request and ids else set()
    matches = []
    for listing in candidates:
        stay = None
        available = None
        if request:
            try:
                stay = resolve_listing_stay(listing, request, related.rules[listing.id], now)
            except StayError:
                # A globally valid search can fail one listing's local window,
                # capacity, past arrival, or DST rules without failing other zones.
                continue
            available = listing.id not in occupied
            if query.available_only and not available:
                continue
        matches.append((listing, stay, available))

    def order(item):
        listing = item[0]
        if query.sort == "price_asc":
            key = listing.nightly_price
        elif query.sort == "price_desc":
            key = -listing.nightly_price
        elif query.sort == "rating_desc":
            rating = related.ratings.get(listing.id, (None, 0))[0]
            key = -rating if rating is not None else float("inf")
        elif query.sort == "distance_asc":
            key = distances[listing.id]
        else:
            key = -listing.created_at.timestamp()
        return key, listing.id

    matches.sort(key=order)
    total = len(matches)
    page = matches[(query.page - 1) * query.page_size : query.page * query.page_size]
    return Paginated(
        data=[
            PublicListingCard.model_validate(
                public_values(listing, related, stay, available, distances.get(listing.id))
            )
            for listing, stay, available in page
        ],
        pagination=pagination(query.page, query.page_size, total),
    )


async def one_listing(
    session: AsyncSession, listing_id: UUID, query: StayQuery, now: datetime
) -> tuple[Listing, RelatedData, ResolvedStay | None, bool | None]:
    request = query.stay_request()
    try:
        validate_global_arrival(request, now)
    except StayError as exc:
        raise invalid_stay(exc) from None
    listing = await session.scalar(
        select(Listing).where(Listing.id == listing_id, Listing.status == ListingStatus.APPROVED)
    )
    if listing is None:
        raise APIError(404, "NOT_FOUND", "Listing not found")
    related = await load_related(session, [listing.id], now)
    stay = None
    available = None
    if request:
        try:
            stay = resolve_listing_stay(listing, request, related.rules[listing.id], now)
        except StayError as exc:
            raise invalid_stay(exc) from None
        available = listing.id not in await occupied_listing_ids(session, [listing.id], request)
    elif query.guests is not None and query.guests > listing.max_guests:
        raise APIError(422, "GUEST_LIMIT", "Guest count exceeds the listing capacity")
    return listing, related, stay, available


async def detail(session: AsyncSession, listing_id: UUID, query: StayQuery, now: datetime):
    listing, related, stay, available = await one_listing(session, listing_id, query, now)
    return PublicListingDetail.model_validate(
        {
            **public_values(listing, related, stay, available),
            "address_line2": listing.address_line2,
            "description": listing.description,
            "contact_name": listing.contact_name,
            "contact_email": listing.contact_email,
            "contact_phone": listing.contact_phone,
            "hours": related.hours[listing.id],
            "booking_rules": related.rules[listing.id],
        }
    )


async def availability(session: AsyncSession, listing_id: UUID, query: StayQuery, now: datetime):
    listing, related, stay, available = await one_listing(session, listing_id, query, now)
    if stay is None:
        raise APIError(422, "INVALID_STAY", "Availability requires a valid stay")
    return AvailabilityResponse(
        listing_id=listing.id,
        available=available,
        quote=QuoteResponse.from_stay(stay),
        total_cost=stay.total_cost,
        unavailable_reason="DATES_UNAVAILABLE" if not available else None,
    )
