from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.clock import get_clock
from app.core.dependencies import SessionDep, require_customer
from app.models import User
from app.schemas.bookings import BookingCreate, BookingHistoryQuery, BookingResponse
from app.schemas.common import ErrorResponse, Paginated, Success
from app.services import bookings

Customer = Annotated[User, Depends(require_customer)]
Clock = Annotated[bookings.Clock, Depends(get_clock)]
router = APIRouter(
    prefix="/bookings",
    tags=["customer bookings"],
    responses={code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 422, 500)},
)


@router.post(
    "",
    status_code=201,
    response_model=Success[BookingResponse],
    summary="Reserve available nights at the current server price",
    description="Revalidates listing, local stay rules and inventory in one locked transaction.",
)
async def create(request: BookingCreate, session: SessionDep, customer: Customer, clock: Clock):
    return Success(data=await bookings.create_booking(session, customer.id, request, clock))


# Static path must precede the UUID detail path.
@router.get("/my", response_model=Paginated[BookingResponse], summary="List your booking history")
async def history(
    query: Annotated[BookingHistoryQuery, Query()],
    session: SessionDep,
    customer: Customer,
    clock: Clock,
):
    return await bookings.booking_history(session, customer.id, query.page, query.page_size, clock)


@router.get(
    "/{booking_id}", response_model=Success[BookingResponse], summary="View your saved confirmation"
)
async def detail(booking_id: UUID, session: SessionDep, customer: Customer, clock: Clock):
    return Success(data=await bookings.booking_detail(session, customer.id, booking_id, clock))


@router.patch(
    "/{booking_id}/cancel",
    response_model=Success[BookingResponse],
    summary="Cancel your booking before arrival; repeated cancellation is idempotent",
)
async def cancel(booking_id: UUID, session: SessionDep, customer: Customer, clock: Clock):
    return Success(data=await bookings.cancel_booking(session, customer.id, booking_id, clock))
