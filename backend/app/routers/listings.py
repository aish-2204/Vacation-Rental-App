from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.clock import utc_now
from app.core.dependencies import SessionDep
from app.models import Amenity
from app.schemas.common import ErrorResponse, Paginated, Success
from app.schemas.listings import AmenityResponse
from app.schemas.search import (
    AvailabilityQuery,
    AvailabilityResponse,
    PublicListingCard,
    PublicListingDetail,
    SearchQuery,
    StayQuery,
)
from app.services import search

Now = Annotated[datetime, Depends(utc_now)]
router = APIRouter(
    tags=["public listings"], responses={code: {"model": ErrorResponse} for code in (404, 422, 500)}
)


@router.get(
    "/amenities",
    response_model=Success[list[AmenityResponse]],
    summary="Get public reference amenities",
)
async def amenities(session: SessionDep):
    rows = (await session.scalars(select(Amenity).order_by(Amenity.name, Amenity.id))).all()
    return Success(data=[AmenityResponse.model_validate(row) for row in rows])


# Keep this static path before the UUID route.
@router.get(
    "/listings/search",
    response_model=Paginated[PublicListingCard],
    summary="Search approved rentals and indicative nightly quotes",
    description=(
        "All supplied filters combine with AND. Without dates, quote/availability are null. "
        "With dates, available_only defaults to true."
    ),
)
async def find(query: Annotated[SearchQuery, Query()], session: SessionDep, now: Now):
    return await search.search(session, query, now)


@router.get(
    "/listings/{listing_id}",
    response_model=Success[PublicListingDetail],
    summary="Get an approved listing, optionally with a stay quote",
)
async def detail(
    listing_id: UUID, query: Annotated[StayQuery, Query()], session: SessionDep, now: Now
):
    return Success(data=await search.detail(session, listing_id, query, now))


@router.get(
    "/listings/{listing_id}/availability",
    response_model=Success[AvailabilityResponse],
    summary="Check nightly availability and quote for a valid stay",
    description="Quotes do not reserve inventory. Booking must recheck under the listing lock.",
)
async def availability(
    listing_id: UUID, query: Annotated[AvailabilityQuery, Query()], session: SessionDep, now: Now
):
    return Success(data=await search.availability(session, listing_id, query, now))
