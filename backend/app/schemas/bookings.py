from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models.enums import ReservationState
from app.schemas.listings import LocalDate
from app.schemas.search import StayQuery


class BookingCreate(StayQuery):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "listing_id": "11111111-1111-4111-8111-111111111111",
                    "check_in": "2030-01-10",
                    "duration_nights": 2,
                    "guests": 2,
                }
            ]
        },
    )
    listing_id: UUID
    check_in: LocalDate = Field(..., description="Listing-local YYYY-MM-DD")
    guests: int = Field(default=1, ge=1, le=2147483647)


class BookingHistoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=50)


class BookingResponse(BaseModel):
    id: UUID
    listing_id: UUID
    check_in: date
    check_out: date
    nights: int
    guests: int
    check_in_time: time
    check_out_time: time
    arrival_at: datetime
    departure_at: datetime
    nightly_price_snapshot: Decimal
    currency: str
    total_cost: Decimal
    listing_name_snapshot: str
    listing_address_snapshot: str
    listing_zip_snapshot: str
    listing_timezone_snapshot: str
    reservation_state: ReservationState
    status: Literal["CONFIRMED", "CANCELLED", "COMPLETED"]
    can_cancel: bool
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("check_in_time", "check_out_time")
    def serialize_time(self, value):
        return value.strftime("%H:%M")
