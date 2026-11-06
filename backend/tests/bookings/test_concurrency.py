import asyncio
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Booking, Listing
from app.models.enums import ListingStatus, ReservationState
from app.services import listings
from seed.demo import demo_id
from tests.bookings.helpers import BOOKINGS, auth, create, payload


async def wait_for_database_lock(engine, pids):
    """Observe an actual PostgreSQL lock wait, not an assumed scheduling delay."""
    async with AsyncSession(engine) as observer:
        while True:
            if pids and await observer.scalar(
                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pids[-1]}
            ):
                return
            await asyncio.sleep(0.01)


async def ordered_race(engine, monkeypatch, first, second):
    """Pause one real request after its listing lock, then queue another writer."""
    original = listings.lock_listing
    locked, release = asyncio.Event(), asyncio.Event()
    pids = []
    tasks = []

    async def instrumented(session, *args, **kwargs):
        pid = await session.scalar(text("SELECT pg_backend_pid()"))
        pids.append(pid)
        position = len(pids)
        result = await original(session, *args, **kwargs)
        if position == 1:
            locked.set()
            await release.wait()
        return result

    monkeypatch.setattr(listings, "lock_listing", instrumented)
    try:
        tasks.append(asyncio.create_task(first()))
        await asyncio.wait_for(locked.wait(), timeout=8)
        tasks.append(asyncio.create_task(second()))

        async def observe_second():
            while len(pids) < 2:
                await asyncio.sleep(0.01)
            await wait_for_database_lock(engine, [pids[1]])

        await asyncio.wait_for(observe_second(), timeout=8)
        assert len(set(pids[:2])) == 2, "Race must use separate PostgreSQL connections"
        assert not any(task.done() for task in tasks)
        release.set()
        return await asyncio.wait_for(asyncio.gather(*tasks), timeout=8)
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def active_count(db, request):
    return await db.scalar(
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.listing_id == UUID(request["listing_id"]),
            Booking.check_in == datetime.fromisoformat(request["check_in"]).date(),
            Booking.reservation_state == ReservationState.CONFIRMED,
        )
    )


async def test_simultaneous_bookings_have_exactly_one_winner(
    api, db, database_engine, clock, monkeypatch
):
    engine, _ = database_engine
    request = payload(clock)
    responses = await ordered_race(
        engine,
        monkeypatch,
        lambda: api.post(BOOKINGS, headers=auth(), json=request),
        lambda: api.post(BOOKINGS, headers=auth("customer2"), json=request),
    )
    assert [response.status_code for response in responses] == [201, 409]
    assert responses[1].json()["error"]["code"] == "DATES_UNAVAILABLE"
    assert await active_count(db, request) == 1


@pytest.mark.parametrize("first", ["booking", "block"])
async def test_booking_and_host_block_serialize_in_both_orders(
    api, db, database_engine, clock, monkeypatch, first
):
    engine, _ = database_engine
    request = payload(clock)
    start = datetime.fromisoformat(request["check_in"]).date()
    block = {
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=2)).isoformat(),
        "reason": "Maintenance",
    }
    actions = {
        "booking": lambda: api.post(BOOKINGS, headers=auth(), json=request),
        "block": lambda: api.post(
            f"/api/v1/host/listings/{request['listing_id']}/blocks",
            headers=auth("host1"),
            json=block,
        ),
    }
    second = "block" if first == "booking" else "booking"
    responses = await ordered_race(engine, monkeypatch, actions[first], actions[second])
    assert [response.status_code for response in responses] == [201, 409]
    assert await active_count(db, request) == (1 if first == "booking" else 0)


@pytest.mark.parametrize("first", ["booking", "removal"])
@pytest.mark.parametrize("actor", ["host1", "admin"])
async def test_booking_and_removal_preserve_only_preceding_bookings(
    api, db, database_engine, clock, monkeypatch, first, actor
):
    engine, _ = database_engine
    request = payload(clock)
    prefix = "host" if actor == "host1" else "admin"
    actions = {
        "booking": lambda: api.post(BOOKINGS, headers=auth(), json=request),
        "removal": lambda: api.request(
            "DELETE",
            f"/api/v1/{prefix}/listings/{request['listing_id']}",
            headers=auth(actor),
            json={"reason": "Retire listing"},
        ),
    }
    second = "removal" if first == "booking" else "booking"
    responses = await ordered_race(engine, monkeypatch, actions[first], actions[second])
    assert [response.status_code for response in responses] == (
        [201, 200] if first == "booking" else [200, 409]
    )
    assert await active_count(db, request) == (1 if first == "booking" else 0)
    listing = await db.get(Listing, demo_id("listing/0"), populate_existing=True)
    assert listing.status == ListingStatus.REMOVED
    if first == "booking":
        saved = responses[0].json()["data"]
        assert (await api.get(f"{BOOKINGS}/{saved['id']}", headers=auth())).json()["data"] == saved


@pytest.mark.parametrize(
    "change,expected", [({"nightly_price": "250.00"}, 201), ({"name": "Needs reapproval"}, 409)]
)
async def test_waiting_booking_rechecks_committed_price_and_approval(
    api, database_engine, clock, monkeypatch, change, expected
):
    engine, _ = database_engine
    request = payload(clock)
    responses = await ordered_race(
        engine,
        monkeypatch,
        lambda: api.patch(
            f"/api/v1/host/listings/{request['listing_id']}", headers=auth("host1"), json=change
        ),
        lambda: api.post(BOOKINGS, headers=auth(), json=request),
    )
    assert responses[0].status_code == 200 and responses[1].status_code == expected
    if expected == 201:
        assert responses[1].json()["data"]["total_cost"] == "500.00"
    else:
        assert responses[1].json()["error"]["code"] == "LISTING_UNAVAILABLE"


@pytest.mark.parametrize("first", ["cancel", "booking"])
async def test_cancellation_and_rebooking_follow_lock_order(
    api, db, database_engine, clock, monkeypatch, first
):
    engine, _ = database_engine
    saved = await create(api, clock)
    request = payload(clock)
    actions = {
        "cancel": lambda: api.patch(f"{BOOKINGS}/{saved['id']}/cancel", headers=auth()),
        "booking": lambda: api.post(BOOKINGS, headers=auth("customer2"), json=request),
    }
    second = "booking" if first == "cancel" else "cancel"
    responses = await ordered_race(engine, monkeypatch, actions[first], actions[second])
    assert [response.status_code for response in responses] == (
        [200, 201] if first == "cancel" else [409, 200]
    )
    assert await active_count(db, request) == (1 if first == "cancel" else 0)
    if first == "booking":
        assert (
            await api.post(BOOKINGS, headers=auth("customer2"), json=request)
        ).status_code == 201


async def test_simultaneous_cancellations_return_identical_saved_state(
    api, database_engine, clock, monkeypatch
):
    engine, _ = database_engine
    saved = await create(api, clock)
    endpoint = f"{BOOKINGS}/{saved['id']}/cancel"
    responses = await ordered_race(
        engine,
        monkeypatch,
        lambda: api.patch(endpoint, headers=auth()),
        lambda: api.patch(endpoint, headers=auth()),
    )
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json()["data"] == responses[1].json()["data"]


async def test_waiting_booking_rechecks_new_booking_windows(
    api, database_engine, clock, monkeypatch
):
    engine, _ = database_engine
    request = payload(clock, listing=4, check_in_time="15:00")
    path = f"/api/v1/host/listings/{request['listing_id']}"
    detail = (await api.get(path, headers=auth("host1"))).json()["data"]
    rules = detail["booking_rules"]
    for rule in rules:
        rule.update(arrival_start="16:00", arrival_default="16:00")
    responses = await ordered_race(
        engine,
        monkeypatch,
        lambda: api.put(
            path + "/booking-rules", headers=auth("host1"), json={"booking_rules": rules}
        ),
        lambda: api.post(BOOKINGS, headers=auth(), json=request),
    )
    assert [response.status_code for response in responses] == [200, 422]
    assert responses[1].json()["error"]["code"] == "OUTSIDE_BOOKING_WINDOW"


@pytest.mark.parametrize(
    "operation,expected,code",
    [("create", 422, "ARRIVAL_IN_PAST"), ("cancel", 409, "CANCELLATION_CLOSED")],
)
async def test_time_is_rechecked_after_waiting_for_listing_lock(
    api, database_engine, clock, monkeypatch, operation, expected, code
):
    engine, _ = database_engine
    request = payload(clock)
    if operation == "cancel":
        saved = await create(api, clock)
        arrival = datetime.fromisoformat(saved["arrival_at"])

        def action():
            return api.patch(f"{BOOKINGS}/{saved['id']}/cancel", headers=auth())
    else:
        local_day = datetime.fromisoformat(request["check_in"]).date()
        arrival = datetime.combine(
            local_day, datetime.strptime("15:00", "%H:%M").time(), ZoneInfo("America/Los_Angeles")
        )

        def action():
            return api.post(BOOKINGS, headers=auth(), json=request)

    original = listings.lock_listing
    pids = []
    task = None
    async with AsyncSession(engine, expire_on_commit=False) as holder:
        await original(holder, demo_id("listing/0"))

        async def instrumented(session, *args, **kwargs):
            pids.append(await session.scalar(text("SELECT pg_backend_pid()")))
            return await original(session, *args, **kwargs)

        monkeypatch.setattr(listings, "lock_listing", instrumented)
        try:
            task = asyncio.create_task(action())
            await asyncio.wait_for(wait_for_database_lock(engine, pids), timeout=8)
            clock[0] = arrival
            await holder.commit()
            response = await asyncio.wait_for(task, timeout=8)
            assert response.status_code == expected
            assert response.json()["error"]["code"] == code
        finally:
            await holder.rollback()
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
