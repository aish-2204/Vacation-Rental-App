import asyncio
from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminAction, Booking, ListingRemoval, Review
from app.models.enums import ReservationState
from app.services import listings
from app.services.moderation import RemoveListingCommand
from app.services.scopes import HostScope
from seed.demo import demo_id
from tests.listings.helpers import admin_path, auth, block, create, hours, path, payload, rules


async def test_complete_lifecycle_and_material_reapproval(api):
    listing = await create(api)
    identifier = listing["id"]
    owned = f"/api/v1/host/listings/{identifier}"
    moderation = admin_path(identifier)
    assert listing["status"] == "PENDING" and listing["nightly_price"] == "150.00"
    assert listing["cost_rating"] == "$$" and len(listing["hours"]) == 7
    assert listing["hours"][0]["opening_time"] == "09:00"
    assert listing["booking_rules"][0]["arrival_default"] == "15:00"
    assert (await api.patch(moderation + "/approve", headers=auth("admin"))).status_code == 200
    response = await api.patch(
        owned, headers=auth(), json={"nightly_price": "175.00", "contact_name": "Updated contact"}
    )
    assert response.status_code == 200 and response.json()["data"]["status"] == "APPROVED"
    added = await api.post(
        owned + "/media", headers=auth(), json={"url": "https://example.test/second.jpg"}
    )
    assert added.status_code == 201
    assert (await api.get(owned, headers=auth())).json()["data"]["status"] == "PENDING"
    assert (await api.patch(moderation + "/approve", headers=auth("admin"))).status_code == 200
    updated = await api.patch(
        owned + "/media/" + added.json()["data"]["id"],
        headers=auth(),
        json={"url": "https://example.test/replaced.jpg", "sort_order": 4, "caption": None},
    )
    assert updated.status_code == 200 and updated.json()["data"]["sort_order"] == 4
    assert (await api.get(owned, headers=auth())).json()["data"]["status"] == "PENDING"
    deleted = await api.delete(owned + "/media/" + added.json()["data"]["id"], headers=auth())
    assert deleted.status_code == 200 and deleted.json()["data"]["deleted"] is True
    rejected = await api.patch(
        moderation + "/reject", headers=auth("admin"), json={"reason": "Fix description"}
    )
    assert rejected.status_code == 200 and rejected.json()["data"]["status"] == "REJECTED"
    response = await api.patch(owned, headers=auth(), json={"description": "Corrected description"})
    assert response.status_code == 200 and response.json()["data"]["status"] == "PENDING"
    response = await api.patch(moderation + "/approve", headers=auth("admin"))
    assert response.status_code == 200
    # Actual effective changes trigger review, while a no-op patch does not.
    same = await api.patch(owned, headers=auth(), json={"name": listing["name"]})
    assert same.json()["data"]["status"] == "APPROVED"
    changed = await api.patch(owned, headers=auth(), json={"name": "Material rename"})
    assert changed.json()["data"]["status"] == "PENDING"
    audit = await api.get(
        "/api/v1/admin/audit-actions", params={"listing_id": identifier}, headers=auth("admin")
    )
    assert audit.status_code == 200
    assert sorted(item["action"] for item in audit.json()["data"]) == [
        "APPROVED",
        "APPROVED",
        "APPROVED",
        "REJECTED",
    ]


async def test_incomplete_draft_reports_missing_fields_and_can_be_completed(api):
    listing = await create(api, complete=False)
    identifier = listing["id"]
    owned = f"/api/v1/host/listings/{identifier}"
    moderation = admin_path(identifier)
    response = await api.patch(moderation + "/approve", headers=auth("admin"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LISTING_INCOMPLETE"
    fields = {item["field"] for item in response.json()["error"]["details"]}
    assert {"media", "hours", "booking_rules"} <= fields
    audit = await api.get(
        "/api/v1/admin/audit-actions", params={"listing_id": identifier}, headers=auth("admin")
    )
    assert audit.json()["data"] == []
    assert (
        await api.patch(
            moderation + "/reject", headers=auth("admin"), json={"reason": "Add missing fields"}
        )
    ).status_code == 200
    assert (
        await api.put(owned + "/hours", headers=auth(), json={"hours": hours()})
    ).status_code == 200
    assert (
        await api.put(owned + "/booking-rules", headers=auth(), json={"booking_rules": rules()})
    ).status_code == 200
    assert (
        await api.post(
            owned + "/media", headers=auth(), json={"url": "https://example.test/photo.jpg"}
        )
    ).status_code == 201
    assert (await api.patch(moderation + "/approve", headers=auth("admin"))).json()["data"][
        "status"
    ] == "APPROVED"


@pytest.mark.parametrize("actor", ["host1", "customer", None])
async def test_all_admin_operations_require_admin(api, actor):
    headers = auth(actor) if actor else {}
    expected = 403 if actor else 401
    for method, endpoint, body in [
        ("GET", "/api/v1/admin/listings", None),
        ("GET", "/api/v1/admin/listings/pending", None),
        ("GET", admin_path(demo_id("listing/0")), None),
        ("PATCH", admin_path(demo_id("listing/8")) + "/approve", None),
        ("PATCH", admin_path(demo_id("listing/8")) + "/reject", {"reason": "Not allowed"}),
        ("DELETE", admin_path(demo_id("listing/0")), {"reason": "Not allowed"}),
        ("GET", "/api/v1/admin/audit-actions", None),
    ]:
        assert (
            await api.request(method, endpoint, headers=headers, json=body)
        ).status_code == expected


async def test_lists_are_owned_paginated_filtered_and_stable(api):
    seen = []
    for page in (1, 2, 3):
        response = await api.get(
            "/api/v1/host/listings", headers=auth(), params={"page": page, "page_size": 2}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["pagination"]["total_items"] == 6
        assert body["pagination"]["total_pages"] == 3
        assert all(item["host_id"] == str(demo_id("user/1")) for item in body["data"])
        seen += [item["id"] for item in body["data"]]
    assert len(set(seen)) == 6
    pending = await api.get("/api/v1/admin/listings/pending", headers=auth("admin"))
    assert pending.status_code == 200 and pending.json()["pagination"]["total_items"] == 2
    assert all(item["status"] == "PENDING" for item in pending.json()["data"])
    all_rows = await api.get(
        "/api/v1/admin/listings", headers=auth("admin"), params={"page_size": 50}
    )
    assert all_rows.json()["pagination"]["total_items"] == 12
    assert any(item["status"] == "REMOVED" for item in all_rows.json()["data"])
    assert (await api.get("/api/v1/host/listings", headers=auth(), params={"page": 99})).json()[
        "data"
    ] == []
    for params in ({"page": 0}, {"page_size": 51}, {"status": "UNKNOWN"}):
        assert (
            await api.get("/api/v1/admin/listings", headers=auth("admin"), params=params)
        ).status_code == 422
    reference = await api.get("/api/v1/host/amenities", headers=auth())
    assert reference.status_code == 200 and len(reference.json()["data"]) == 6


async def test_blocks_reject_reservations_but_allow_cancelled_and_adjacent_ranges(api, db):
    booking = await db.get(Booking, demo_id("booking/8"))
    request = {
        "start_date": booking.check_in.isoformat(),
        "end_date": booking.check_out.isoformat(),
        "reason": "Maintenance",
    }
    assert (await api.post(path() + "/blocks", headers=auth(), json=request)).status_code == 409
    request["start_date"] = booking.check_out.isoformat()
    request["end_date"] = (booking.check_out + timedelta(days=1)).isoformat()
    response = await api.post(path() + "/blocks", headers=auth(), json=request)
    assert response.status_code == 201
    identifier = response.json()["data"]["id"]
    assert (await api.post(path() + "/blocks", headers=auth(), json=request)).status_code == 409
    assert (await api.get(path() + "/blocks", headers=auth())).json()["pagination"][
        "total_items"
    ] == 2
    assert (await api.delete(path() + f"/blocks/{identifier}", headers=auth())).json()["data"][
        "deleted"
    ]
    cancelled = await db.get(Booking, demo_id("booking/9"))
    request.update(
        start_date=cancelled.check_in.isoformat(), end_date=cancelled.check_out.isoformat()
    )
    assert (
        await api.post(path(1) + "/blocks", headers=auth("host2"), json=request)
    ).status_code == 201


async def test_future_location_capacity_and_windows_are_protected(api, db):
    for change in (
        {"timezone": "America/New_York"},
        {"zip_code": "02108"},
        {"latitude": "38.000000"},
        {"address_line1": "New address"},
        {"max_guests": 1},
    ):
        response = await api.patch(path(), headers=auth(), json=change)
        assert response.status_code == 409, response.text
    proposed = rules()
    booking = await db.get(Booking, demo_id("booking/8"))
    proposed[booking.check_in.weekday()].update(
        arrival_allowed=False, arrival_start=None, arrival_end=None, arrival_default=None
    )
    assert (
        await api.put(path() + "/booking-rules", headers=auth(), json={"booking_rules": proposed})
    ).status_code == 409
    proposed = rules()
    for rule in proposed:
        rule["arrival_default"] = "16:00"
    accepted = await api.put(
        path() + "/booking-rules", headers=auth(), json={"booking_rules": proposed}
    )
    assert accepted.status_code == 200 and accepted.json()["data"]["status"] == "APPROVED"
    assert (
        await api.put(
            path() + "/hours",
            headers=auth(),
            json={"hours": [{"weekday": day, "closed": True} for day in range(7)]},
        )
    ).json()["data"]["status"] == "APPROVED"
    await db.refresh(booking)
    assert booking.arrival_at.astimezone(ZoneInfo("America/Los_Angeles")).hour == 15


@pytest.mark.parametrize("actor", ["host1", "admin"])
async def test_terminal_removal_is_audited_idempotent_and_preserves_history(api, db, actor):
    endpoint = path() if actor == "host1" else admin_path(demo_id("listing/0"))
    booking = await db.get(Booking, demo_id("booking/8"))
    saved = booking.total_cost, booking.check_in, booking.reservation_state
    review_count = await db.scalar(select(func.count()).select_from(Review))
    for reason in ("Initial removal reason", "Repeat must not rewrite history"):
        response = await api.request(
            "DELETE", endpoint, headers=auth(actor), json={"reason": reason}
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "REMOVED" and data["removed_at"]
        assert data["removal"]["reason"] == "Initial removal reason"
        assert data["removal"]["actor_id"] == str(
            demo_id("user/1" if actor == "host1" else "user/0")
        )
    removals = (
        await db.scalars(
            select(ListingRemoval).where(ListingRemoval.listing_id == demo_id("listing/0"))
        )
    ).all()
    assert len(removals) == 1
    await db.refresh(booking)
    assert (booking.total_cost, booking.check_in, booking.reservation_state) == saved
    assert booking.reservation_state == ReservationState.CONFIRMED
    assert await db.scalar(select(func.count()).select_from(Review)) == review_count
    audit_count = await db.scalar(
        select(func.count())
        .select_from(AdminAction)
        .where(AdminAction.listing_id == demo_id("listing/0"), AdminAction.action == "REMOVED")
    )
    assert audit_count == (1 if actor == "admin" else 0)
    assert (
        await api.patch(path(), headers=auth(), json={"name": "Cannot revive"})
    ).status_code == 409
    assert (await api.post(path() + "/blocks", headers=auth(), json=block())).status_code == 409
    assert (
        await api.patch(admin_path(demo_id("listing/0")) + "/approve", headers=auth("admin"))
    ).status_code == 409
    assert (await api.get(path(), headers=auth())).status_code == 200


async def test_existing_booking_snapshots_survive_permitted_listing_edits(api, db):
    booking = await db.get(Booking, demo_id("booking/4"))
    saved = booking.total_cost, booking.listing_name_snapshot, booking.listing_zip_snapshot
    response = await api.patch(
        path(4),
        headers=auth(),
        json={"name": "New name", "nightly_price": "399.99", "zip_code": "99999"},
    )
    assert response.status_code == 200 and response.json()["data"]["status"] == "PENDING"
    await db.refresh(booking)
    assert (
        booking.total_cost,
        booking.listing_name_snapshot,
        booking.listing_zip_snapshot,
    ) == saved


async def test_concurrent_overlapping_blocks_have_one_winner(api):
    responses = await asyncio.gather(
        api.post(path() + "/blocks", headers=auth(), json=block()),
        api.post(path() + "/blocks", headers=auth(), json=block()),
    )
    assert sorted(response.status_code for response in responses) == [201, 409]


async def test_waiting_writer_rechecks_removed_state_after_lock(api, database_engine, monkeypatch):
    engine, _ = database_engine
    original = listings.lock_listing
    waiting = asyncio.Event()
    task = None
    async with AsyncSession(engine, expire_on_commit=False) as holder:
        await original(holder, demo_id("listing/0"), host_id=demo_id("user/1"))

        async def instrumented(session, *args, **kwargs):
            if session is not holder:
                waiting.set()
            return await original(session, *args, **kwargs)

        monkeypatch.setattr(listings, "lock_listing", instrumented)
        try:
            task = asyncio.create_task(
                api.patch(path(), headers=auth(), json={"name": "Queued edit"})
            )
            await asyncio.wait_for(waiting.wait(), timeout=5)
            assert not task.done()
            await RemoveListingCommand(
                demo_id("user/1"),
                demo_id("listing/0"),
                "Removed while another writer waited",
                HostScope(demo_id("user/1")),
            ).execute(holder)
            response = await asyncio.wait_for(task, timeout=5)
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "LISTING_REMOVED"
        finally:
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
