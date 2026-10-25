import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from app.database.base import Base
from app.database.schema import REQUIRED_TABLES, SCHEMA_REVISION, schema_is_current
from app.database.session import get_session
from app.main import app
from app.models import (
    AdminAction,
    AvailabilityBlock,
    Booking,
    Listing,
    ListingBookingRule,
    ListingMedia,
    Review,
    User,
)
from app.models.enums import ListingStatus, ReservationState, Role
from seed.demo import DEMO_PASSWORD, demo_id, seed_demo
from tests.fixtures.database import migration_config


def row_copy(instance, **changes):
    return {
        **{column.name: getattr(instance, column.name) for column in instance.__table__.columns},
        "id": uuid4(),
        **changes,
    }


async def test_migrations_from_zero_and_schema_roundtrip(database_engine):
    engine, schema = database_engine
    async with engine.begin() as connection:
        tables = set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
        assert set(REQUIRED_TABLES) | {"alembic_version"} == tables
        assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            SCHEMA_REVISION
        )
        await connection.run_sync(
            lambda sync: command.downgrade(migration_config(sync, schema), "base")
        )
        assert set(await connection.run_sync(lambda sync: inspect(sync).get_table_names())) == {
            "alembic_version"
        }
        await connection.run_sync(
            lambda sync: command.upgrade(migration_config(sync, schema), "head")
        )
    async with AsyncSession(engine) as session:
        assert await schema_is_current(session)


@pytest.mark.parametrize(
    "model,label,changes",
    [
        (Listing, "listing/0", {"nightly_price": Decimal("-1.00")}),
        (Listing, "listing/0", {"max_guests": 0}),
        (Listing, "listing/0", {"latitude": Decimal("91")}),
        (Listing, "listing/0", {"longitude": Decimal("-181")}),
        (Listing, "listing/0", {"host_id": UUID(int=0)}),
        (User, "user/1", {"email": "MixedCase@example.test"}),
        (Booking, "booking/8", {"customer_id": UUID(int=0)}),
        (Booking, "booking/8", {"guests": 0}),
        (Booking, "booking/8", {"total_cost": Decimal("0.01")}),
        (Booking, "booking/8", {"reservation_state": ReservationState.CANCELLED}),
        (Review, "review/0", {"rating": 0}),
        (Review, "review/0", {"rating": 6}),
        (AvailabilityBlock, "block/0", {"end_date": date(2000, 1, 1)}),
        (ListingBookingRule, "rules/0/0", {"arrival_start": None}),
        (ListingMedia, "media/0", {"url": "http://example.test/photo.jpg"}),
        (AdminAction, "action/10", {"reason": " "}),
    ],
)
async def test_constraints_reject_invalid_data_and_rollback(db, model, label, changes):
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(update(model).where(model.id == demo_id(label)).values(**changes))
    assert await db.scalar(text("SELECT 1")) == 1


@pytest.mark.parametrize("nights", [0, 15])
async def test_invalid_night_counts_are_rejected(db, nights):
    booking = await db.get(Booking, demo_id("booking/8"))
    with pytest.raises(IntegrityError, match="nightly_duration"):
        async with db.begin_nested():
            await db.execute(
                update(Booking)
                .where(Booking.id == booking.id)
                .values(
                    check_out=booking.check_in + timedelta(days=nights),
                    total_cost=booking.nightly_price_snapshot * nights,
                )
            )
    assert await db.scalar(text("SELECT 1")) == 1


@pytest.mark.parametrize("model,label", [(User, "user/1"), (Review, "review/0")])
async def test_duplicate_email_and_review_are_rejected(db, model, label):
    original = await db.get(model, demo_id(label))
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(model(**row_copy(original)))
            await db.flush()


@pytest.mark.parametrize("nights", [1, 14])
async def test_boundary_night_counts_are_accepted(db, nights):
    original = await db.get(Booking, demo_id("booking/8"))
    check_in = original.check_out + timedelta(days=300)
    db.add(
        Booking(
            **row_copy(
                original,
                check_in=check_in,
                check_out=check_in + timedelta(days=nights),
                arrival_at=original.arrival_at + timedelta(days=300),
                departure_at=original.arrival_at + timedelta(days=300 + nights),
                total_cost=original.nightly_price_snapshot * nights,
            )
        )
    )
    await db.flush()


async def test_overlap_back_to_back_and_cancelled_inventory(db):
    original = await db.get(Booking, demo_id("booking/8"))
    with pytest.raises(IntegrityError, match="ex_bookings_no_confirmed_overlap"):
        async with db.begin_nested():
            db.add(Booking(**row_copy(original)))
            await db.flush()
    db.add(
        Booking(
            **row_copy(
                original,
                reservation_state=ReservationState.CANCELLED,
                cancelled_at=datetime.now(UTC),
            )
        )
    )
    db.add(
        Booking(
            **row_copy(
                original,
                check_in=original.check_out,
                check_out=original.check_out + timedelta(days=2),
                arrival_at=original.departure_at + timedelta(hours=4),
                departure_at=original.departure_at + timedelta(days=2),
                total_cost=original.nightly_price_snapshot * 2,
            )
        )
    )
    await db.flush()


async def test_exclusion_constraint_with_two_real_transactions(db, database_engine):
    engine, _ = database_engine
    original = await db.get(Booking, demo_id("booking/8"))
    values = row_copy(
        original,
        check_in=original.check_in + timedelta(days=400),
        check_out=original.check_out + timedelta(days=400),
        arrival_at=original.arrival_at + timedelta(days=400),
        departure_at=original.departure_at + timedelta(days=400),
    )
    await db.rollback()
    waiter_pids = []

    async def attempt():
        async with AsyncSession(engine) as session:
            try:
                async with session.begin():
                    waiter_pids.append(await session.scalar(text("SELECT pg_backend_pid()")))
                    session.add(Booking(**{**values, "id": uuid4()}))
                return "inserted"
            except IntegrityError as exc:
                assert "ex_bookings_no_confirmed_overlap" in str(exc)
                return "conflict"

    # Two unsynchronized raw GiST inserts can deadlock while discovering each
    # other. Keep one inserted row uncommitted, observe the other transaction's
    # real constraint wait, then commit. No application row lock is used here;
    # Phase 6 separately tests truly simultaneous API writes with listing locks.
    async with AsyncSession(engine) as first:
        first.add(Booking(**{**values, "id": uuid4()}))
        await first.flush()
        first_pid = await first.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(attempt())

        async def observe_constraint_wait():
            async with AsyncSession(engine) as observer:
                while True:
                    if waiter_pids and await observer.scalar(
                        text("SELECT :holder = ANY(pg_blocking_pids(:waiter))"),
                        {"holder": first_pid, "waiter": waiter_pids[0]},
                    ):
                        return
                    await asyncio.sleep(0.01)

        try:
            await asyncio.wait_for(observe_constraint_wait(), timeout=8)
            assert waiter_pids[0] != first_pid and not task.done()
            await first.commit()
            assert await asyncio.wait_for(task, timeout=8) == "conflict"
        finally:
            await first.rollback()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert (
        len(
            (
                await db.scalars(
                    select(Booking.id).where(
                        Booking.listing_id == values["listing_id"],
                        Booking.check_in == values["check_in"],
                        Booking.reservation_state == ReservationState.CONFIRMED,
                    )
                )
            ).all()
        )
        == 1
    )


async def test_seed_is_idempotent_preserves_edits_and_covers_fixtures(db):
    listing = await db.get(Listing, demo_id("listing/0"))
    listing.name = "Host edited the demo name"
    await db.commit()
    counts = await seed_demo(db, as_of=datetime.now(UTC) + timedelta(days=7))
    assert all(count == 0 for count in counts.values())
    await db.commit()
    await db.refresh(listing)
    assert listing.name == "Host edited the demo name"
    users = (await db.scalars(select(User))).all()
    assert [user.role for user in users].count(Role.ADMIN) == 1
    assert [user.role for user in users].count(Role.HOST) == 2
    assert [user.role for user in users].count(Role.CUSTOMER) == 3
    assert bcrypt.checkpw(DEMO_PASSWORD.encode(), users[0].password_hash.encode())
    listings = (await db.scalars(select(Listing))).all()
    assert len(listings) == 12
    assert len({item.zip_code for item in listings}) == 4
    assert {item.status for item in listings} == set(ListingStatus)
    bookings = (await db.scalars(select(Booking))).all()
    anchor = (await db.get(User, demo_id("user/0"))).created_at + timedelta(days=200)
    creation_times = {item.created_at for item in bookings}
    for days in (30, 60, 90):
        for offset in (-1, 0, 1):
            assert anchor - timedelta(days=days) + timedelta(microseconds=offset) in creation_times
    assert anchor in creation_times
    assert all(item.created_at < item.arrival_at for item in bookings)
    for review in (await db.scalars(select(Review))).all():
        booking = await db.get(Booking, review.booking_id)
        assert booking.reservation_state == ReservationState.CONFIRMED
        assert booking.departure_at < review.created_at < anchor


async def test_postgres_types_snapshots_indexes_and_history(db):
    booking = await db.get(Booking, demo_id("booking/3"))
    listing = await db.get(Listing, booking.listing_id)
    assert isinstance(booking.id, UUID)
    assert isinstance(booking.total_cost, Decimal)
    assert (
        booking.total_cost
        == booking.nightly_price_snapshot * (booking.check_out - booking.check_in).days
    )
    assert isinstance(booking.check_in, date) and not isinstance(booking.check_in, datetime)
    assert booking.created_at.utcoffset() == timedelta(0)
    assert booking.arrival_at.utcoffset() == timedelta(0)
    assert booking.listing_zip_snapshot == "02108"
    saved = booking.total_cost, booking.listing_zip_snapshot, booking.listing_name_snapshot
    listing.nightly_price = Decimal("499.99")
    listing.zip_code = "99999"
    listing.status = ListingStatus.REMOVED
    listing.removed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(booking)
    assert (
        booking.total_cost,
        booking.listing_zip_snapshot,
        booking.listing_name_snapshot,
    ) == saved
    index_names = set(
        (
            await db.scalars(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
            )
        ).all()
    )
    assert {
        "ix_listings_approved_location",
        "ix_listings_approved_zip",
        "ix_bookings_customer_created",
        "ix_bookings_created_zip",
        "ex_bookings_no_confirmed_overlap",
        "uq_reviews_booking_id",
    } <= index_names
    assert set(Base.metadata.tables) == set(REQUIRED_TABLES)


async def test_ready_requires_current_revision_and_tables(database_engine):
    engine, _ = database_engine

    async def isolated_session():
        async with AsyncSession(engine) as session:
            yield session

    app.dependency_overrides[get_session] = isolated_session
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            assert (await client.get("/ready")).status_code == 200
            async with engine.begin() as connection:
                await connection.execute(text("UPDATE alembic_version SET version_num = 'old'"))
            assert (await client.get("/ready")).status_code == 503
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE alembic_version SET version_num = :head"),
                    {"head": SCHEMA_REVISION},
                )
                await connection.execute(text("ALTER TABLE users RENAME TO users_missing"))
            assert (await client.get("/ready")).status_code == 503
            assert (await client.get("/health")).status_code == 200
    finally:
        app.dependency_overrides.pop(get_session)
