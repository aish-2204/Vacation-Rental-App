from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.clock import get_clock
from app.core.dependencies import SessionDep, require_customer
from app.models import User
from app.schemas.common import ErrorResponse, Paginated, Success
from app.schemas.reviews import CreatedReview, PublicReview, ReviewCreate, ReviewPageQuery
from app.services import reviews

Customer = Annotated[User, Depends(require_customer)]
Clock = Annotated[reviews.Clock, Depends(get_clock)]
router = APIRouter(tags=["reviews"])


@router.post(
    "/reviews",
    status_code=201,
    response_model=Success[CreatedReview],
    responses={code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 422, 500)},
    summary="Review your noncancelled checked-out stay once",
    description=(
        "Customer only. Rating must be an integer 1–5; comment is plain text, 1–2000 characters."
    ),
)
async def create(request: ReviewCreate, session: SessionDep, customer: Customer, clock: Clock):
    return Success(data=await reviews.create_review(session, customer.id, request, clock))


@router.get(
    "/listings/{listing_id}/reviews",
    response_model=Paginated[PublicReview],
    responses={code: {"model": ErrorResponse} for code in (404, 422, 500)},
    summary="Read eligible reviews for an approved listing",
    description="Public, newest first. Booking IDs and customer profile data are excluded.",
)
async def list_public(
    listing_id: UUID,
    query: Annotated[ReviewPageQuery, Query()],
    session: SessionDep,
    clock: Clock,
):
    return await reviews.public_reviews(session, listing_id, query.page, query.page_size, clock)
