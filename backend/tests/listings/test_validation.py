from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, func, select

from app.models import AdminAction
from app.schemas.listings import (
    BlockInput,
    BookingRuleInput,
    HoursReplace,
    ListingCreate,
    ListingPatch,
    MediaInput,
    MediaPatch,
    ReasonInput,
    RulesReplace,
)
from app.services.listings import cost_rating
from seed.demo import demo_id
from tests.listings.helpers import admin_path, auth, create, hours, path, payload, rules


@pytest.mark.parametrize(
    "change",
    [
        {"name": " "},
        {"nightly_price": "0.00"},
        {"nightly_price": "1.001"},
        {"nightly_price": "NaN"},
        {"max_guests": 0},
        {"latitude": 91},
        {"longitude": -181},
        {"latitude": "37.1234567"},
        {"timezone": "Not/A_Timezone"},
        {"zip_code": 2108},
        {"zip_code": "21"},
        {"currency": "EUR"},
        {"host_id": str(uuid4())},
        {"status": "APPROVED"},
        {"contact_email": "invalid"},
        {"contact_phone": "invalid"},
        {"amenity_ids": [str(demo_id("amenity/Wi-Fi"))] * 2},
    ],
)
def test_invalid_listing_inputs_are_rejected(change):
    with pytest.raises(ValidationError):
        ListingCreate.model_validate({**payload(), **change})


def test_state_and_money_normalize_without_losing_zip_or_time_format():
    listing = ListingCreate.model_validate({**payload(), "state": " ca ", "zip_code": "02108"})
    assert listing.state == "CA" and listing.zip_code == "02108"
    assert listing.nightly_price == Decimal("150.00")
    encoded = listing.model_dump(mode="json")
    assert encoded["booking_rules"][0]["arrival_start"] == "15:00"
    # Native persistence still receives datetime.time, not a serialized string.
    assert listing.model_dump()["booking_rules"][0]["arrival_start"].hour == 15


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/a.jpg",
        "https://user:secret@example.test/a.jpg",
        "https://example.test/a b.jpg",
        "javascript:alert(1)",
    ],
)
def test_only_https_urls_without_credentials_are_accepted(url):
    with pytest.raises(ValidationError):
        MediaInput(url=url)


@pytest.mark.parametrize(
    "model,data",
    [
        (ListingPatch, {}),
        (ListingPatch, {"nightly_price": None}),
        (ListingPatch, {"status": "APPROVED"}),
        (MediaPatch, {}),
        (MediaPatch, {"url": None}),
        (HoursReplace, {"hours": hours()[:6]}),
        (HoursReplace, {"hours": [hours()[0]] * 7}),
        (RulesReplace, {"booking_rules": rules()[:6]}),
        (RulesReplace, {"booking_rules": [rules()[0]] * 7}),
        (BookingRuleInput, {**rules()[0], "arrival_start": "15:00:00"}),
        (BookingRuleInput, {**rules()[0], "arrival_default": "23:00"}),
        (BookingRuleInput, {**rules()[0], "departure_end": "06:00"}),
        (BookingRuleInput, {**rules()[0], "arrival_allowed": False}),
        (BlockInput, {"start_date": "2030-01-02", "end_date": "2030-01-01", "reason": "Invalid"}),
        (
            BlockInput,
            {"start_date": "2030-01-01T00:00:00Z", "end_date": "2030-01-03", "reason": "Invalid"},
        ),
        (ReasonInput, {"reason": " "}),
    ],
)
def test_patch_windows_dates_and_reasons_validate(model, data):
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize(
    "price,rating",
    [
        ("99.99", "$"),
        ("100.00", "$$"),
        ("199.99", "$$"),
        ("200.00", "$$$"),
        ("299.99", "$$$"),
        ("300.00", "$$$$"),
    ],
)
def test_cost_rating_boundaries(price, rating):
    assert cost_rating(Decimal(price)) == rating


async def test_invalid_amenities_and_approved_contact_edits_roll_back(api):
    original = (await api.get(path(), headers=auth())).json()["data"]
    for change in (
        {"name": "Must roll back", "amenity_ids": [str(uuid4())]},
        {"contact_name": " "},
        {"contact_email": ""},
        {"contact_phone": ""},
    ):
        response = await api.patch(path(), headers=auth(), json=change)
        assert response.status_code == 422
        current = (await api.get(path(), headers=auth())).json()["data"]
        assert current == original


async def test_material_capacity_amenity_and_location_edits_need_reapproval(api):
    for change in (
        {"max_guests": 7},
        {"amenity_ids": []},
        {"latitude": "38.123456"},
        {"description": "Material description edit"},
    ):
        response = await api.patch(path(4), headers=auth(), json=change)
        assert response.status_code == 200 and response.json()["data"]["status"] == "PENDING"
        approved = await api.patch(
            admin_path(demo_id("listing/4")) + "/approve", headers=auth("admin")
        )
        assert approved.status_code == 200


async def test_removing_last_photo_requires_reapproval_and_failed_approval_has_no_audit(api, db):
    before = await db.scalar(select(func.count()).select_from(AdminAction))
    response = await api.delete(path(4) + f"/media/{demo_id('media/4')}", headers=auth())
    assert response.status_code == 200
    approval = await api.patch(admin_path(demo_id("listing/4")) + "/approve", headers=auth("admin"))
    assert approval.status_code == 422
    assert (await api.get(path(4), headers=auth())).json()["data"]["status"] == "PENDING"
    assert await db.scalar(select(func.count()).select_from(AdminAction)) == before


async def test_reason_required_and_state_transitions_are_explicit(api):
    for endpoint in (path(), admin_path(demo_id("listing/0"))):
        for body in (None, {"reason": " "}):
            response = await api.request(
                "DELETE",
                endpoint,
                headers=auth("admin" if "/admin/" in endpoint else "host1"),
                json=body,
            )
            assert response.status_code == 422
    assert (
        await api.patch(admin_path(demo_id("listing/0")) + "/approve", headers=auth("admin"))
    ).status_code == 409
    assert (
        await api.patch(
            admin_path(demo_id("listing/10")) + "/reject",
            headers=auth("admin"),
            json={"reason": "Already rejected"},
        )
    ).status_code == 409
    for reason in (None, {"reason": " "}):
        assert (
            await api.patch(
                admin_path(demo_id("listing/8")) + "/reject", headers=auth("admin"), json=reason
            )
        ).status_code == 422


async def test_database_audit_failure_rolls_back_the_moderation_transition(api, db):
    listing = await create(api)

    def reject_audit(mapper, connection, target):
        raise RuntimeError("Simulated audit storage failure")

    event.listen(AdminAction, "before_insert", reject_audit)
    try:
        with pytest.raises(RuntimeError, match="Simulated audit"):
            await api.patch(admin_path(listing["id"]) + "/approve", headers=auth("admin"))
    finally:
        event.remove(AdminAction, "before_insert", reject_audit)
    current = await api.get(admin_path(listing["id"]), headers=auth("admin"))
    assert current.json()["data"]["status"] == "PENDING"
    assert (
        await db.scalar(
            select(func.count())
            .select_from(AdminAction)
            .where(AdminAction.listing_id == listing["id"])
        )
        == 0
    )


async def test_openapi_host_admin_security_and_json_contract(api):
    schema = (await api.get("/openapi.json")).json()
    operations = [
        operation
        for path_name, methods in schema["paths"].items()
        if path_name.startswith(("/api/v1/host/", "/api/v1/admin/"))
        for method, operation in methods.items()
        if method in {"get", "post", "patch", "put", "delete"}
        # Keep this Phase 4 contract focused on management/moderation. Analytics
        # uses these prefixes too and has its own role/error/OpenAPI coverage.
        and set(operation.get("tags", [])) & {"host listings", "admin moderation"}
    ]
    assert len(operations) == 22  # includes POST media/upload-url
    for operation in operations:
        assert operation["security"] == [{"BearerAuth": []}]
        assert {"401", "403", "404", "409", "422"} <= operation["responses"].keys()
    removal = schema["paths"]["/api/v1/host/listings/{listing_id}"]["delete"]
    assert set(removal["requestBody"]["content"]) == {"application/json"}
