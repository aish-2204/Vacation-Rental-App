from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.dependencies import SessionDep, StorageDep, require_host
from app.models import Amenity, User
from app.models.enums import ListingStatus
from app.schemas.common import ErrorResponse, Paginated, Success
from app.schemas.listings import (
    AmenityResponse,
    BlockInput,
    BlockResponse,
    DeletedResponse,
    HoursReplace,
    ListingCreate,
    ListingDetail,
    ListingPatch,
    ListingSummary,
    MediaInput,
    MediaPatch,
    MediaResponse,
    MediaUploadRequest,
    MediaUploadResponse,
    ReasonInput,
    RulesReplace,
)
from app.services import listings, media
from app.services.moderation import RemoveListingCommand
from app.services.scopes import HostScope

HostUser = Annotated[User, Depends(require_host)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=50)]
router = APIRouter(
    prefix="/host",
    tags=["host listings"],
    responses={code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 422, 500)},
)


@router.get(
    "/amenities",
    response_model=Success[list[AmenityResponse]],
    summary="Get reference amenities for Host forms",
)
async def amenities(session: SessionDep, host: HostUser):
    rows = (await session.scalars(select(Amenity).order_by(Amenity.name, Amenity.id))).all()
    return Success(data=[AmenityResponse.model_validate(row) for row in rows])


@router.post(
    "/listings",
    status_code=201,
    response_model=Success[ListingDetail],
    summary="Create a pending listing",
)
async def create(request: ListingCreate, session: SessionDep, host: HostUser):
    return Success(data=await listings.create_listing(session, host.id, request))


@router.get("/listings", response_model=Paginated[ListingSummary], summary="List your own listings")
async def list_own(
    session: SessionDep,
    host: HostUser,
    page: Page = 1,
    page_size: PageSize = 10,
    status: ListingStatus | None = None,
):
    return await listings.listing_page(session, page, page_size, HostScope(host.id), status=status)


@router.get(
    "/listings/{listing_id}",
    response_model=Success[ListingDetail],
    summary="View your listing, including removed history",
)
async def detail(listing_id: UUID, session: SessionDep, host: HostUser):
    listing = await listings.get_listing(session, listing_id, host_id=host.id)
    return Success(data=await listings.listing_detail(session, listing))


@router.patch(
    "/listings/{listing_id}",
    response_model=Success[ListingDetail],
    summary="Update your listing; material changes require reapproval",
)
async def patch(listing_id: UUID, request: ListingPatch, session: SessionDep, host: HostUser):
    return Success(data=await listings.patch_listing(session, host.id, listing_id, request))


@router.delete(
    "/listings/{listing_id}",
    response_model=Success[ListingDetail],
    summary="Soft-remove your listing with an audited reason",
)
async def remove(listing_id: UUID, request: ReasonInput, session: SessionDep, host: HostUser):
    return Success(
        data=await RemoveListingCommand(
            host.id, listing_id, request.reason, HostScope(host.id)
        ).execute(session)
    )


