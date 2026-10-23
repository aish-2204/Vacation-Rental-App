from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models import (
    Amenity,
    AvailabilityBlock,
    Booking,
    Listing,
    ListingAmenity,
    ListingBookingRule,
    ListingHours,
    ListingMedia,
    ListingRemoval,
)
from app.models.enums import ListingStatus, MediaType, ReservationState
from app.schemas.common import Paginated
from app.schemas.listings import (
    BlockInput,
    BlockResponse,
    BookingRuleInput,
    HoursInput,
    ListingCreate,
    ListingDetail,
    ListingPatch,
    ListingSummary,
)
from app.services.listing_state import state_of
from app.services.pagination import PageQuery
from app.services.scopes import AccessScope

LOCATION_FIELDS = {
    "address_line1",
    "address_line2",
    "city",
    "state",
    "zip_code",
    "latitude",
    "longitude",
    "timezone",
}
MATERIAL_FIELDS = LOCATION_FIELDS | {"name", "description", "max_guests", "amenity_ids"}


def conflict(message: str, code="LISTING_CONFLICT") -> APIError:
    return APIError(409, code, message)


async def get_listing(
    session: AsyncSession, listing_id: UUID, *, host_id: UUID | None = None, lock: bool = False
) -> Listing:
    statement = select(Listing).where(Listing.id == listing_id)
    if host_id is not None:
        statement = statement.where(Listing.host_id == host_id)
    if lock:
        # All inventory/content writers must acquire this row FIRST. Refresh
        # cached state after waiting for another writer, including moderation.
        statement = statement.with_for_update().execution_options(populate_existing=True)
    listing = await session.scalar(statement)
    if listing is None:
        raise APIError(404, "NOT_FOUND", "Listing not found")
    return listing


async def lock_listing(session: AsyncSession, listing_id: UUID, *, host_id: UUID | None = None):
    return await get_listing(session, listing_id, host_id=host_id, lock=True)


def ensure_mutable(listing: Listing) -> None:
    state_of(listing).ensure_mutable()


def host_edit(listing: Listing, *, material=False, changed=True) -> None:
    if changed:
        listing.status = state_of(listing).after_host_edit(material=material)
        listing.updated_at = datetime.now(UTC)


def cost_rating(price: Decimal) -> str:
    return "$" if price < 100 else "$$" if price < 200 else "$$$" if price < 300 else "$$$$"


def listing_values(listing: Listing) -> dict:
    return {
        **{column.name: getattr(listing, column.name) for column in Listing.__table__.columns},
        "cost_rating": cost_rating(listing.nightly_price),
    }


async def listing_detail(session: AsyncSession, listing: Listing) -> ListingDetail:
    amenities = (
        await session.scalars(
            select(Amenity)
            .join(ListingAmenity)
            .where(ListingAmenity.listing_id == listing.id)
            .order_by(Amenity.name, Amenity.id)
        )
    ).all()
    media = (
        await session.scalars(
            select(ListingMedia)
            .where(ListingMedia.listing_id == listing.id)
            .order_by(ListingMedia.sort_order, ListingMedia.id)
        )
    ).all()
    hours = (
        await session.scalars(
            select(ListingHours)
            .where(ListingHours.listing_id == listing.id)
            .order_by(ListingHours.weekday)
        )
    ).all()
    rules = (
        await session.scalars(
            select(ListingBookingRule)
            .where(ListingBookingRule.listing_id == listing.id)
            .order_by(ListingBookingRule.weekday)
        )
    ).all()
    removal = await session.scalar(
        select(ListingRemoval).where(ListingRemoval.listing_id == listing.id)
    )
    return ListingDetail.model_validate(
        {
            **listing_values(listing),
            "amenities": amenities,
            "media": media,
            "hours": hours,
            "booking_rules": rules,
            "removal": removal,
        }
    )


async def finish(session: AsyncSession, listing: Listing) -> ListingDetail:
    await session.flush()
    await session.refresh(listing)
    result = await listing_detail(session, listing)
    await session.commit()
    return result


class ListingPage(PageQuery[Listing, ListingSummary]):
    def __init__(self, scope: AccessScope, status: ListingStatus | None = None) -> None:
        self.scope, self.status = scope, status

    def statement(self) -> Select:
        filters = self.scope.listing_filters()
        if self.status is not None:
            filters.append(Listing.status == self.status)
        return select(Listing).where(*filters)

    def order_by(self):
        return (Listing.created_at.desc(), Listing.id)

    def to_item(self, row: Listing) -> ListingSummary:
        return ListingSummary.model_validate(listing_values(row))


async def listing_page(
    session: AsyncSession,
    page: int,
    page_size: int,
    scope: AccessScope,
    *,
    status: ListingStatus | None = None,
) -> Paginated[ListingSummary]:
    return await ListingPage(scope, status).fetch(session, page, page_size)


async def validate_amenities(session: AsyncSession, ids: list[UUID]) -> None:
    found = set((await session.scalars(select(Amenity.id).where(Amenity.id.in_(ids)))).all())
    if found != set(ids):
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "Unknown amenity IDs",
            details=[{"field": "amenity_ids", "message": "Use IDs from reference amenities"}],
        )


async def set_amenities(session: AsyncSession, listing_id: UUID, ids: list[UUID]) -> bool:
    await validate_amenities(session, ids)
    current = set(
        (
            await session.scalars(
                select(ListingAmenity.amenity_id).where(ListingAmenity.listing_id == listing_id)
            )
        ).all()
    )
    if current == set(ids):
        return False
    await session.execute(delete(ListingAmenity).where(ListingAmenity.listing_id == listing_id))
    session.add_all(
        ListingAmenity(listing_id=listing_id, amenity_id=identifier) for identifier in ids
    )
    return True


async def set_week(session: AsyncSession, listing_id: UUID, model: type, inputs: list) -> bool:
    current = {
        row.weekday: row
        for row in (
            await session.scalars(select(model).where(model.listing_id == listing_id))
        ).all()
    }
    changed = False
    for value in inputs:
        values = value.model_dump()
        row = current.get(value.weekday)
        if row is None:
            session.add(model(listing_id=listing_id, **values))
            changed = True
        else:
            for field, new_value in values.items():
                if getattr(row, field) != new_value:
                    setattr(row, field, new_value)
                    changed = True
    return changed


async def create_listing(
    session: AsyncSession, host_id: UUID, request: ListingCreate
) -> ListingDetail:
    values = request.model_dump(exclude={"amenity_ids", "hours", "booking_rules", "media"})
    listing = Listing(host_id=host_id, status=ListingStatus.PENDING, **values)
    session.add(listing)
    await session.flush()
    await set_amenities(session, listing.id, request.amenity_ids)
    if request.hours is not None:
        await set_week(session, listing.id, ListingHours, request.hours)
    if request.booking_rules is not None:
        await set_week(session, listing.id, ListingBookingRule, request.booking_rules)
    session.add_all(
        ListingMedia(listing_id=listing.id, **item.model_dump()) for item in request.media
    )
    return await finish(session, listing)


async def replace_hours(session, host_id, listing_id, request) -> ListingDetail:
    listing = await lock_listing(session, listing_id, host_id=host_id)
    ensure_mutable(listing)
    changed = await set_week(session, listing.id, ListingHours, request.hours)
    host_edit(listing, changed=changed)
    return await finish(session, listing)


async def replace_rules(session, host_id, listing_id, request) -> ListingDetail:
    listing = await lock_listing(session, listing_id, host_id=host_id)
    ensure_mutable(listing)
    rules = {rule.weekday: rule for rule in request.booking_rules}
    timezone = ZoneInfo(listing.timezone)
    for stay in await active_future_stays(session, listing.id):
        for direction, accepted in (("arrival", stay.arrival_at), ("departure", stay.departure_at)):
            local = accepted.astimezone(timezone)
            rule = rules[local.weekday()]
            if not getattr(rule, f"{direction}_allowed") or not (
                getattr(rule, f"{direction}_start")
                <= local.time()
                <= getattr(rule, f"{direction}_end")
            ):
                raise conflict(
                    "Booking rules cannot invalidate a future/ongoing stay's accepted times"
                )
    changed = await set_week(session, listing.id, ListingBookingRule, request.booking_rules)
    host_edit(listing, changed=changed)
    if listing.status == ListingStatus.APPROVED:
        await ensure_complete(session, listing)
    return await finish(session, listing)


async def nested_row(session, model, listing_id: UUID, identifier: UUID):
    row = await session.scalar(
        select(model).where(model.id == identifier, model.listing_id == listing_id)
    )
    if row is None:
        raise APIError(404, "NOT_FOUND", "Resource not found")
    return row


class BlockPage(PageQuery[AvailabilityBlock, BlockResponse]):
    def __init__(self, listing_id: UUID) -> None:
        self.listing_id = listing_id

    def statement(self) -> Select:
        return select(AvailabilityBlock).where(AvailabilityBlock.listing_id == self.listing_id)

    def order_by(self):
        return (AvailabilityBlock.start_date, AvailabilityBlock.id)

    def to_item(self, row: AvailabilityBlock) -> BlockResponse:
        return BlockResponse.model_validate(row)


async def blocks_page(session, host_id, listing_id, page, page_size) -> Paginated[BlockResponse]:
    await get_listing(session, listing_id, host_id=host_id)
    return await BlockPage(listing_id).fetch(session, page, page_size)


async def add_block(session, host_id, listing_id, request: BlockInput) -> BlockResponse:
    listing = await lock_listing(session, listing_id, host_id=host_id)
    ensure_mutable(listing)
    reserved = await session.scalar(
        select(Booking.id)
        .where(
            Booking.listing_id == listing.id,
            Booking.reservation_state == ReservationState.CONFIRMED,
            Booking.check_in < request.end_date,
            Booking.check_out > request.start_date,
        )
        .limit(1)
    )
    blocked = await session.scalar(
        select(AvailabilityBlock.id)
        .where(
            AvailabilityBlock.listing_id == listing.id,
            AvailabilityBlock.start_date < request.end_date,
            AvailabilityBlock.end_date > request.start_date,
        )
        .limit(1)
    )
    if reserved or blocked:
        raise conflict(
            "Dates overlap a noncancelled reservation or an existing block", "DATES_UNAVAILABLE"
        )
    block = AvailabilityBlock(listing_id=listing.id, **request.model_dump())
    session.add(block)
    host_edit(listing)
    await finish(session, listing)
    return BlockResponse.model_validate(block)


async def delete_block(session, host_id, listing_id, block_id):
    listing = await lock_listing(session, listing_id, host_id=host_id)
    ensure_mutable(listing)
    block = await nested_row(session, AvailabilityBlock, listing.id, block_id)
    await session.delete(block)
    host_edit(listing)
    await finish(session, listing)
