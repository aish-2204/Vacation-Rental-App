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


