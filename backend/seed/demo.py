"""Idempotent demo dataset. Only the CLI is permitted to target development."""

import asyncio
import json
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

import bcrypt
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.database.safety import validate_seed_target
from app.database.schema import schema_is_current
from app.models import (
    AdminAction,
    Amenity,
    AvailabilityBlock,
    Booking,
    Listing,
    ListingAmenity,
    ListingBookingRule,
    ListingHours,
    ListingMedia,
    ListingRemoval,
    Review,
    User,
)
from app.models.enums import AdminActionType, ListingStatus, MediaType, ReservationState, Role

DEMO_PASSWORD = "DemoOnly!2026"
DEMO_EMAILS = (
    "admin@example.test",
    "host1@example.test",
    "host2@example.test",
    "customer1@example.test",
    "customer2@example.test",
    "customer3@example.test",
)
LOCATIONS = (
    ("San Jose", "CA", "95112", "37.338200", "-121.886300", "America/Los_Angeles"),
    ("Santa Cruz", "CA", "95060", "36.974100", "-122.030800", "America/Los_Angeles"),
    ("San Francisco", "CA", "94103", "37.774900", "-122.419400", "America/Los_Angeles"),
    ("Boston", "MA", "02108", "42.360100", "-71.058900", "America/New_York"),
)


def demo_id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"vacation-rental-demo/v1/{label}")


async def insert_missing(session: AsyncSession, model: type, rows: list[dict]) -> int:
    if not rows:
        return 0
    # Primary-key conflicts only: conflicting user-owned unique fields must fail
    # the transaction rather than hiding a partial seed or overwriting their data.
    keys = list(model.__table__.primary_key.columns)
    result = await session.execute(
        insert(model).values(rows).on_conflict_do_nothing(index_elements=keys).returning(*keys)
    )
    return len(result.all())


async def seed_demo(session: AsyncSession, *, as_of: datetime | None = None) -> dict[str, int]:
    """Insert missing deterministic rows inside the caller's transaction.

    Existing rows are never updated or deleted. Relative dates are anchored to
    the initial Admin's creation time so later reruns can repair missing rows
    without moving bookings or changing historical analytics boundaries.
    """
    existing_anchor = await session.scalar(
        select(User.created_at).where(User.id == demo_id("user/0"))
    )
    anchor = (
        (existing_anchor + timedelta(days=200)) if existing_anchor else (as_of or datetime.now(UTC))
    )
    anchor = anchor.astimezone(UTC)
    counts: dict[str, int] = {}
    password_hash = bcrypt.hashpw(DEMO_PASSWORD.encode(), bcrypt.gensalt(rounds=12)).decode()
    roles = [Role.ADMIN, Role.HOST, Role.HOST, Role.CUSTOMER, Role.CUSTOMER, Role.CUSTOMER]
    users = [
        dict(
            id=demo_id(f"user/{i}"),
            name=f"Demo {role.title()} {i}",
            email=email,
            phone=f"+15550100{i:03}",
            role=role,
            password_hash=password_hash,
            created_at=anchor - timedelta(days=200),
            updated_at=anchor - timedelta(days=200),
        )
        for i, (email, role) in enumerate(zip(DEMO_EMAILS, roles, strict=True))
    ]
    counts["users"] = await insert_missing(session, User, users)
    amenities = [
        {"id": demo_id(f"amenity/{name}"), "name": name}
        for name in ("Wi-Fi", "Kitchen", "Parking", "Pool", "Pet friendly", "Workspace")
    ]
    counts["amenities"] = await insert_missing(session, Amenity, amenities)
    listings = []
    prices = ["99.99", "100.00", "199.99", "200.00", "299.99", "300.00"]
    statuses = [ListingStatus.APPROVED] * 8 + [
        ListingStatus.PENDING,
        ListingStatus.PENDING,
        ListingStatus.REJECTED,
        ListingStatus.REMOVED,
    ]
    for i in range(12):
        city, state, zip_code, lat, lng, timezone = LOCATIONS[i % len(LOCATIONS)]
        listings.append(
            dict(
                id=demo_id(f"listing/{i}"),
                host_id=demo_id(f"user/{1 + i % 2}"),
                name=f"Demo {city} Home {i + 1}",
                description="Fictional entire-home course demo rental.",
                address_line1=f"{100 + i} Example Lane",
                address_line2=None,
                city=city,
                state=state,
                zip_code=zip_code,
                latitude=Decimal(lat),
                longitude=Decimal(lng),
                timezone=timezone,
                contact_name="Demo Host",
                contact_email=DEMO_EMAILS[1 + i % 2],
                contact_phone="+15550100100",
                nightly_price=Decimal(prices[i % len(prices)]),
                currency="USD",
                max_guests=2 + i % 5,
                status=statuses[i],
                removed_at=anchor - timedelta(days=1)
                if statuses[i] == ListingStatus.REMOVED
                else None,
                created_at=anchor - timedelta(days=180 - i * 2),
                updated_at=anchor,
            )
        )
    counts["listings"] = await insert_missing(session, Listing, listings)
    hours, rules, media, links, blocks, actions = [], [], [], [], [], []
    for i, listing in enumerate(listings):
        listing_id = listing["id"]
        for weekday in range(7):
            hours.append(
                dict(
                    id=demo_id(f"hours/{i}/{weekday}"),
                    listing_id=listing_id,
                    weekday=weekday,
                    closed=weekday == 6,
                    opening_time=None if weekday == 6 else time(9),
                    closing_time=None if weekday == 6 else time(18),
                )
            )
            rules.append(
                dict(
                    id=demo_id(f"rules/{i}/{weekday}"),
                    listing_id=listing_id,
                    weekday=weekday,
                    arrival_allowed=True,
                    arrival_start=time(15),
                    arrival_end=time(22),
                    arrival_default=time(15),
                    departure_allowed=True,
                    departure_start=time(7),
                    departure_end=time(11),
                    departure_default=time(11),
                )
            )
        media.append(
            dict(
                id=demo_id(f"media/{i}"),
                listing_id=listing_id,
                url=f"https://placehold.co/800x600?text=Demo+Home+{i + 1}",
                media_type=MediaType.IMAGE,
                caption="Placeholder photo for fictional demo home",
                sort_order=0,
            )
        )
        links.extend(
            {"listing_id": listing_id, "amenity_id": amenity["id"]}
            for amenity in amenities[: 2 + i % 5]
        )
        blocks.append(
            dict(
                id=demo_id(f"block/{i}"),
                listing_id=listing_id,
                start_date=anchor.date() + timedelta(days=60),
                end_date=anchor.date() + timedelta(days=63),
                reason="Demo maintenance",
                created_at=anchor,
            )
        )
        if listing["status"] != ListingStatus.PENDING:
            action = AdminActionType(listing["status"].value)
            actions.append(
                dict(
                    id=demo_id(f"action/{i}"),
                    listing_id=listing_id,
                    admin_id=demo_id("user/0"),
                    action=action,
                    reason="Demo moderation decision",
                    created_at=listing["updated_at"],
                )
            )
    for model, rows in (
        (ListingHours, hours),
        (ListingBookingRule, rules),
        (ListingMedia, media),
        (ListingAmenity, links),
        (AvailabilityBlock, blocks),
        (AdminAction, actions),
    ):
        counts[model.__tablename__] = await insert_missing(session, model, rows)
    counts["listing_removals"] = await insert_missing(
        session,
        ListingRemoval,
        [
            dict(
                id=demo_id("removal/11"),
                listing_id=demo_id("listing/11"),
                actor_id=demo_id("user/0"),
                reason="Demo moderation decision",
                created_at=listings[11]["removed_at"],
            )
        ],
    )
    bookings, reviews = [], []
    # Exact boundary, one microsecond inside, and one microsecond outside each window.
    created_times = [anchor]
    for days in (30, 60, 90):
        boundary = anchor - timedelta(days=days)
        created_times.extend(
            [boundary - timedelta(microseconds=1), boundary, boundary + timedelta(microseconds=1)]
        )
    for i in range(12):
        listing = listings[i % 8]
        past = i < 8
        offset = -(110 - i * 4) if past else 10 + (i - 8) * 5
        check_in = anchor.date() + timedelta(days=offset)
        check_out = check_in + timedelta(days=2 + i % 3)
        timezone = ZoneInfo(listing["timezone"])
        arrival = datetime.combine(check_in, time(15), timezone).astimezone(UTC)
        departure = datetime.combine(check_out, time(11), timezone).astimezone(UTC)
        cancelled = i in (2, 9)
        # Historical creations must precede the stay; future creations exercise
        # the 30/60/90 boundaries and a booking created today.
        created = arrival - timedelta(days=5) if past else created_times[i - 8]
        bookings.append(
            dict(
                id=demo_id(f"booking/{i}"),
                listing_id=listing["id"],
                customer_id=demo_id(f"user/{3 + i % 3}"),
                check_in=check_in,
                check_out=check_out,
                arrival_at=arrival,
                departure_at=departure,
                guests=2,
                nightly_price_snapshot=listing["nightly_price"],
                currency="USD",
                total_cost=listing["nightly_price"] * (check_out - check_in).days,
                listing_name_snapshot=listing["name"],
                listing_address_snapshot=f"{listing['address_line1']}, {listing['city']}",
                listing_zip_snapshot=listing["zip_code"],
                listing_timezone_snapshot=listing["timezone"],
                reservation_state=ReservationState.CANCELLED
                if cancelled
                else ReservationState.CONFIRMED,
                cancelled_at=created + timedelta(hours=1) if cancelled else None,
                created_at=created,
                updated_at=created,
            )
        )
        if past and not cancelled:
            reviews.append(
                dict(
                    id=demo_id(f"review/{i}"),
                    booking_id=demo_id(f"booking/{i}"),
                    rating=3 + i % 3,
                    comment="Fictional review of a completed demo stay.",
                    created_at=departure + timedelta(days=1),
                )
            )
    counts["bookings"] = await insert_missing(session, Booking, bookings)
    counts["reviews"] = await insert_missing(session, Review, reviews)
    return counts


async def main() -> None:
    settings = get_settings()
    target = validate_seed_target(settings.database_url, settings.app_env)
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine) as session, session.begin():
            if await session.scalar(text("SELECT current_database()")) != target.database:
                raise RuntimeError("Connected database does not match the seed target")
            if not await schema_is_current(session):
                raise RuntimeError("Run make migrate before make seed")
            counts = await seed_demo(session)
        print(json.dumps({"inserted": counts}, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
