from datetime import time
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Booking, Listing, ListingBookingRule
from app.models.enums import ReservationState
from app.schemas.bookings import BookingCreate
from app.services import bookings
from seed.demo import demo_id
from tests.bookings.helpers import BOOKINGS, auth, create, payload


@pytest.mark.parametrize("operation", ["create", "cancel"])
async def test_failed_commit_rolls_back_entire_operation(
    api, db, database_engine, clock, monkeypatch, operation
):
    engine, _ = database_engine
    saved = await create(api, clock) if operation == "cancel" else None
    count = await db.scalar(select(func.count()).select_from(Booking))
    async with AsyncSession(engine, expire_on_commit=False) as session:

        async def fail_commit():
            raise RuntimeError("Injected failure before commit")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="Injected failure"):
            if operation == "create":
                await bookings.create_booking(
                    session,
                    demo_id("user/3"),
                    BookingCreate.model_validate(payload(clock)),
                    lambda: clock[0],
                )
            else:
                await bookings.cancel_booking(
                    session, demo_id("user/3"), UUID(saved["id"]), lambda: clock[0]
                )
        assert not session.in_transaction()
    assert await db.scalar(select(func.count()).select_from(Booking)) == count
    if saved:
        row = await db.get(Booking, UUID(saved["id"]), populate_existing=True)
        assert row.reservation_state == ReservationState.CONFIRMED and row.cancelled_at is None
        assert (
            await api.patch(f"{BOOKINGS}/{saved['id']}/cancel", headers=auth())
        ).status_code == 200
    else:
        await create(api, clock)


async def test_total_range_and_closed_weekday_fail_without_insert(api, db, clock):
    await db.execute(
        update(Listing)
        .where(Listing.id == demo_id("listing/0"))
        .values(nightly_price=Decimal("99999999.99"))
    )
    await db.commit()
    response = await api.post(BOOKINGS, headers=auth(), json=payload(clock))
    assert response.status_code == 422 and response.json()["error"]["code"] == "TOTAL_OUT_OF_RANGE"
    await db.execute(
        update(Listing)
        .where(Listing.id == demo_id("listing/0"))
        .values(nightly_price=Decimal("99.99"))
    )
    await db.execute(
        update(ListingBookingRule)
        .where(ListingBookingRule.listing_id == demo_id("listing/0"))
        .values(arrival_allowed=False, arrival_start=None, arrival_end=None, arrival_default=None)
    )
    await db.commit()
    response = await api.post(BOOKINGS, headers=auth(), json=payload(clock))
    assert response.status_code == 422 and response.json()["error"]["code"] == "WINDOW_UNAVAILABLE"
    assert await db.scalar(select(func.count()).select_from(Booking)) == 18
    # The same shared validator accepts restored rules without a poisoned session.
    await db.execute(
        update(ListingBookingRule)
        .where(ListingBookingRule.listing_id == demo_id("listing/0"))
        .values(
            arrival_allowed=True,
            arrival_start=time(15),
            arrival_end=time(22),
            arrival_default=time(15),
        )
    )
    await db.commit()
    await create(api, clock)
