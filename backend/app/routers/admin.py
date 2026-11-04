from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.dependencies import SessionDep, require_admin
from app.models import User
from app.models.enums import ListingStatus
from app.routers.host import Page, PageSize
from app.schemas.common import ErrorResponse, Paginated, Success
from app.schemas.listings import AuditResponse, ListingDetail, ListingSummary, ReasonInput
from app.services import listings, moderation
from app.services.moderation import (
    ApproveListingCommand,
    RejectListingCommand,
    RemoveListingCommand,
)
from app.services.scopes import AdminScope

AdminUser = Annotated[User, Depends(require_admin)]
router = APIRouter(
    prefix="/admin",
    tags=["admin moderation"],
    responses={code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 422, 500)},
)


@router.get(
    "/listings",
    response_model=Paginated[ListingSummary],
    summary="List all listings with an optional status filter",
)
async def list_all(
    session: SessionDep,
    admin: AdminUser,
    page: Page = 1,
    page_size: PageSize = 10,
    status: ListingStatus | None = None,
):
    return await listings.listing_page(session, page, page_size, AdminScope(), status=status)


@router.get(
    "/listings/pending",
    response_model=Paginated[ListingSummary],
    summary="List pending listings for moderation",
)
async def pending(session: SessionDep, admin: AdminUser, page: Page = 1, page_size: PageSize = 10):
    return await listings.listing_page(
        session, page, page_size, AdminScope(), status=ListingStatus.PENDING
    )


@router.get(
    "/listings/{listing_id}",
    response_model=Success[ListingDetail],
    summary="View a listing and all approval fields",
)
async def detail(listing_id: UUID, session: SessionDep, admin: AdminUser):
    listing = await listings.get_listing(session, listing_id)
    return Success(data=await listings.listing_detail(session, listing))


@router.patch(
    "/listings/{listing_id}/approve",
    response_model=Success[ListingDetail],
    summary="Approve a complete pending listing and record an audit action",
)
async def approve(listing_id: UUID, session: SessionDep, admin: AdminUser):
    return Success(data=await ApproveListingCommand(admin.id, listing_id).execute(session))


@router.patch(
    "/listings/{listing_id}/reject",
    response_model=Success[ListingDetail],
    summary="Reject a pending listing with an audited reason",
)
async def reject(listing_id: UUID, request: ReasonInput, session: SessionDep, admin: AdminUser):
    return Success(
        data=await RejectListingCommand(admin.id, listing_id, request.reason).execute(session)
    )


@router.delete(
    "/listings/{listing_id}",
    response_model=Success[ListingDetail],
    summary="Soft-remove a listing with an audited reason",
)
async def remove(listing_id: UUID, request: ReasonInput, session: SessionDep, admin: AdminUser):
    return Success(
        data=await RemoveListingCommand(admin.id, listing_id, request.reason, AdminScope()).execute(
            session
        )
    )


@router.get(
    "/audit-actions",
    response_model=Paginated[AuditResponse],
    summary="List Admin moderation history",
)
async def audit(
    session: SessionDep,
    admin: AdminUser,
    page: Page = 1,
    page_size: PageSize = 10,
    listing_id: UUID | None = None,
):
    return await moderation.audit_page(session, page, page_size, listing_id)
