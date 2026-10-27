from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models import Booking, Listing, User
from app.models.enums import ListingStatus, ReservationState, Role
from seed.demo import demo_id

HOST = "/api/v1/host/analytics"
ADMIN = "/api/v1/admin/analytics"


def auth(actor="host1", *, user_id=None):
    if user_id is None:
        index = {"admin": 0, "host1": 1, "host2": 2, "customer": 3}[actor]
        user_id = demo_id(f"user/{index}")
    token, _ = create_access_token(user_id, get_settings())
    return {"Authorization": f"Bearer {token}"}


async def add_listing(
    db, created_at, *, host_id=None, zip_code="99999", status=ListingStatus.APPROVED
):
    template = await db.get(Listing, demo_id("listing/0"))
    values = {column.name: getattr(template, column.name) for column in Listing.__table__.columns}
    values.update(
        id=uuid4(),
        host_id=host_id or demo_id("user/1"),
        zip_code=zip_code,
        status=status,
        created_at=created_at,
        updated_at=created_at,
        removed_at=created_at if status == ListingStatus.REMOVED else None,
    )
    listing = Listing(**values)
    db.add(listing)
    await db.flush()
    return listing


async def add_booking(
    db,
    clock,
    listing,
    created_at,
    *,
    price="10.01",
    zip_code=None,
    cancelled=False,
    offset=500,
    completed=False,
):
    template = await db.get(Booking, demo_id("booking/8"))
    values = {column.name: getattr(template, column.name) for column in Booking.__table__.columns}
    day = clock[0].astimezone(UTC).date() + timedelta(days=offset if not completed else -2)
    timezone = ZoneInfo(listing.timezone)
    values.update(
        id=uuid4(),
        listing_id=listing.id,
        check_in=day,
        check_out=day + timedelta(days=1),
        arrival_at=datetime.combine(day, time(15), timezone),
        departure_at=datetime.combine(day + timedelta(days=1), time(11), timezone),
        nightly_price_snapshot=Decimal(price),
        total_cost=Decimal(price),
        currency="USD",
        listing_name_snapshot=listing.name,
        listing_zip_snapshot=zip_code or listing.zip_code,
        listing_timezone_snapshot=listing.timezone,
        reservation_state=ReservationState.CANCELLED if cancelled else ReservationState.CONFIRMED,
        cancelled_at=created_at + timedelta(hours=1) if cancelled else None,
        created_at=created_at,
        updated_at=created_at,
    )
    booking = Booking(**values)
    db.add(booking)
    await db.flush()
    return booking


async def curated_data(db, clock):
    clock[0] = datetime(2026, 11, 16, 12, 30, tzinfo=UTC)
    template = await db.get(User, demo_id("user/1"))
    hosts = []
    for _ in range(2):
        identifier = uuid4()
        host = User(
            id=identifier,
            name="Analytics fixture host",
            email=f"{identifier}@example.test",
            password_hash=template.password_hash,
            phone="+15550100100",
            role=Role.HOST,
            created_at=clock[0] - timedelta(days=200),
            updated_at=clock[0],
        )
        db.add(host)
        hosts.append(host)
    await db.flush()
    a = await add_listing(db, clock[0] - timedelta(days=10), host_id=hosts[0].id, zip_code="00001")
    b = await add_listing(
        db,
        clock[0] - timedelta(days=100),
        host_id=hosts[0].id,
        zip_code="00002",
        status=ListingStatus.REMOVED,
    )
    c = await add_listing(
        db,
        clock[0] - timedelta(days=5),
        host_id=hosts[1].id,
        zip_code="00001",
        status=ListingStatus.PENDING,
    )
    d = await add_listing(
        db,
        clock[0] - timedelta(days=31),
        host_id=hosts[1].id,
        zip_code="00003",
        status=ListingStatus.REJECTED,
    )
    bookings = []
    for index, (listing, days, price, zip_code, cancelled, completed) in enumerate(
        [
            (a, 1, "100.10", "00001", False, False),
            (a, 2, "200.20", "00001", True, False),
            (b, 3, "300.30", "00001", False, True),
            (c, 4, "400.40", "00001", False, False),
            (d, 40, "500.50", "00003", False, False),
            (a, 100, "600.60", "00001", False, False),
            (a, 0, "700.70", "00001", False, False),
        ]
    ):
        bookings.append(
            await add_booking(
                db,
                clock,
                listing,
                clock[0] - timedelta(days=days),
                price=price,
                zip_code=zip_code,
                cancelled=cancelled,
                offset=500 + index * 4,
                completed=completed,
            )
        )
    await db.commit()
    return hosts, (a, b, c, d), bookings
