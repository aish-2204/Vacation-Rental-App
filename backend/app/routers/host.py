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


@router.put(
    "/listings/{listing_id}/hours",
    response_model=Success[ListingDetail],
    summary="Replace all seven weekdays of display contact hours",
)
async def hours(listing_id: UUID, request: HoursReplace, session: SessionDep, host: HostUser):
    return Success(data=await listings.replace_hours(session, host.id, listing_id, request))


@router.put(
    "/listings/{listing_id}/booking-rules",
    response_model=Success[ListingDetail],
    summary="Replace seven weekdays of arrival/departure rules",
)
async def rules(listing_id: UUID, request: RulesReplace, session: SessionDep, host: HostUser):
    return Success(data=await listings.replace_rules(session, host.id, listing_id, request))


@router.get(
    "/listings/{listing_id}/blocks",
    response_model=Paginated[BlockResponse],
    summary="List your listing's date blocks",
)
async def blocks(
    listing_id: UUID, session: SessionDep, host: HostUser, page: Page = 1, page_size: PageSize = 10
):
    return await listings.blocks_page(session, host.id, listing_id, page, page_size)


@router.post(
    "/listings/{listing_id}/blocks",
    status_code=201,
    response_model=Success[BlockResponse],
    summary="Block a half-open unreserved nightly date range",
)
async def add_block(listing_id: UUID, request: BlockInput, session: SessionDep, host: HostUser):
    return Success(data=await listings.add_block(session, host.id, listing_id, request))


@router.delete(
    "/listings/{listing_id}/blocks/{block_id}",
    response_model=Success[DeletedResponse],
    summary="Delete one of your listing's date blocks",
)
async def delete_block(listing_id: UUID, block_id: UUID, session: SessionDep, host: HostUser):
    await listings.delete_block(session, host.id, listing_id, block_id)
    return Success(data=DeletedResponse(id=block_id))


@router.post(
    "/listings/{listing_id}/media/upload-url",
    status_code=201,
    response_model=Success[MediaUploadResponse],
    summary="Get a short-lived upload URL for one photo or video",
    description=(
        "Step 1 of an upload: send the returned `headers` with the file bytes to `upload_url` "
        "using `method`, then add the media with `url` = `public_url`. Nothing is saved until "
        "then. JPEG/PNG/WebP images and MP4/WebM videos; size limits apply."
    ),
)
async def media_upload_url(
    listing_id: UUID,
    request: MediaUploadRequest,
    session: SessionDep,
    host: HostUser,
    storage: StorageDep,
):
    return Success(
        data=await media.create_media_upload(session, storage, host.id, listing_id, request)
    )


@router.post(
    "/listings/{listing_id}/media",
    status_code=201,
    response_model=Success[MediaResponse],
    summary="Add an uploaded file or an external HTTPS media URL",
)
async def add_media(
    listing_id: UUID, request: MediaInput, session: SessionDep, host: HostUser, storage: StorageDep
):
    return Success(data=await media.add_media(session, storage, host.id, listing_id, request))


@router.patch(
    "/listings/{listing_id}/media/{media_id}",
    response_model=Success[MediaResponse],
    summary="Replace or reorder an owned media URL",
)
async def patch_media(
    listing_id: UUID,
    media_id: UUID,
    request: MediaPatch,
    session: SessionDep,
    host: HostUser,
    storage: StorageDep,
):
    return Success(
        data=await media.patch_media(session, storage, host.id, listing_id, media_id, request)
    )


@router.delete(
    "/listings/{listing_id}/media/{media_id}",
    response_model=Success[DeletedResponse],
    summary="Remove an owned media URL",
)
async def delete_media(
    listing_id: UUID, media_id: UUID, session: SessionDep, host: HostUser, storage: StorageDep
):
    await media.delete_media(session, storage, host.id, listing_id, media_id)
    return Success(data=DeletedResponse(id=media_id))
