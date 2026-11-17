import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Review
from app.schemas.reviews import ReviewCreate
from app.services import listings, reviews
from seed.demo import demo_id
from tests.reviews.helpers import REVIEWS, auth, completed_booking, payload


async def queued_requests(engine, monkeypatch, actions, before_release=None):
    """Queue real request sessions behind one held PostgreSQL listing lock."""
    original = listings.lock_listing
    pids, tasks = [], []
    async with AsyncSession(engine, expire_on_commit=False) as holder:
        await original(holder, demo_id("listing/0"))

        async def instrumented(session, *args, **kwargs):
            pids.append(await session.scalar(text("SELECT pg_backend_pid()")))
            return await original(session, *args, **kwargs)

        monkeypatch.setattr(listings, "lock_listing", instrumented)

        async def observe_waiters():
            async with AsyncSession(engine) as observer:
                while True:
                    if len(pids) == len(actions):
                        blocked = [
                            await observer.scalar(
                                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                                {"pid": pid},
                            )
                            for pid in pids
                        ]
                        if all(blocked):
                            return
                    await asyncio.sleep(0.01)

        try:
            tasks = [asyncio.create_task(action()) for action in actions]
            await asyncio.wait_for(observe_waiters(), timeout=8)
            assert len(set(pids)) == len(actions)
            assert not any(task.done() for task in tasks)
            if before_release:
                before_release()
            await holder.commit()
            return await asyncio.wait_for(asyncio.gather(*tasks), timeout=8)
        finally:
            await holder.rollback()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def test_concurrent_duplicate_reviews_have_one_insert_and_one_conflict(
    api, db, database_engine, clock, monkeypatch
):
    engine, _ = database_engine
    booking = await completed_booking(db, clock)
    responses = await queued_requests(
        engine,
        monkeypatch,
        [
            lambda: api.post(REVIEWS, headers=auth(), json=payload(booking.id, rating=1)),
            lambda: api.post(REVIEWS, headers=auth(), json=payload(booking.id, rating=5)),
        ],
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    loser = next(response for response in responses if response.status_code == 409)
    assert loser.json()["error"]["code"] == "REVIEW_ALREADY_EXISTS"
    stored = (await db.scalars(select(Review).where(Review.booking_id == booking.id))).all()
    winner = next(response.json()["data"] for response in responses if response.status_code == 201)
    assert len(stored) == 1 and str(stored[0].id) == winner["id"]
    assert stored[0].rating == winner["rating"]
    detail = (await api.get(f"/api/v1/listings/{booking.listing_id}")).json()["data"]
    assert detail["review_count"] == 2 and detail["average_rating"] == (3 + winner["rating"]) / 2


async def test_different_completed_stays_can_both_be_reviewed_concurrently(
    api, db, database_engine, clock, monkeypatch
):
    engine, _ = database_engine
    first = await completed_booking(db, clock, offset=-300)
    second = await completed_booking(db, clock, offset=-310)
    responses = await queued_requests(
        engine,
        monkeypatch,
        [
            lambda: api.post(REVIEWS, headers=auth(), json=payload(first.id)),
            lambda: api.post(REVIEWS, headers=auth(), json=payload(second.id)),
        ],
    )
    assert [response.status_code for response in responses] == [201, 201]
    assert (
        await db.scalar(
            select(func.count())
            .select_from(Review)
            .where(Review.booking_id.in_([first.id, second.id]))
        )
        == 2
    )


async def test_checkout_eligibility_is_read_after_waiting_for_lock(
    api, db, database_engine, clock, monkeypatch
):
    engine, _ = database_engine
    booking = await completed_booking(db, clock)
    departure = booking.departure_at
    clock[0] = departure - timedelta(microseconds=1)

    def reach_checkout():
        clock[0] = departure

    responses = await queued_requests(
        engine,
        monkeypatch,
        [lambda: api.post(REVIEWS, headers=auth(), json=payload(booking.id))],
        before_release=reach_checkout,
    )
    assert responses[0].status_code == 201


async def test_commit_failure_rolls_back_review_and_allows_retry(
    api, db, database_engine, clock, monkeypatch
):
    engine, _ = database_engine
    booking = await completed_booking(db, clock)
    request = ReviewCreate.model_validate(payload(booking.id))
    async with AsyncSession(engine, expire_on_commit=False) as session:

        async def fail_commit():
            raise RuntimeError("Injected review commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="Injected review commit failure"):
            await reviews.create_review(session, demo_id("user/3"), request, lambda: clock[0])
        assert not session.in_transaction()
    assert (
        await db.scalar(
            select(func.count()).select_from(Review).where(Review.booking_id == booking.id)
        )
        == 0
    )
    assert (await api.post(REVIEWS, headers=auth(), json=payload(booking.id))).status_code == 201
