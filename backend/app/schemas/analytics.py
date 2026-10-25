from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.models.enums import ListingStatus
from app.schemas.listings import ZIP


def period_input(value):
    # Query parameters arrive as text; preserve an integer enum in OpenAPI.
    return int(value) if isinstance(value, str) and value in {"30", "60", "90"} else value


PeriodDays = Annotated[Literal[30, 60, 90], BeforeValidator(period_input)]


class AnalyticsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_days: PeriodDays = Field(
        default=30, description="Rolling UTC window: 30, 60, or 90 days"
    )
    zip_code: ZIP | None = Field(
        default=None, description="Exact ZIP text; current listings versus saved booking ZIP"
    )


class BookingMetrics(BaseModel):
    bookings_created: int = Field(ge=0)
    cancelled_bookings: int = Field(ge=0)
    net_bookings: int = Field(ge=0)
    booking_value_usd: Decimal = Field(
        ge=0, description="Noncancelled total_cost snapshots; booking value, not paid revenue"
    )


class RentalsByZip(BaseModel):
    zip_code: str
    total_listings: int


class BookingsByZip(BookingMetrics):
    zip_code: str


class DailyBookings(BookingMetrics):
    date: date
    window_start: datetime
    window_end: datetime


class AnalyticsResponse(BookingMetrics):
    scope: Literal["HOST", "ADMIN"]
    period_days: Literal[30, 60, 90]
    zip_code: str | None
    window_start: datetime
    window_end: datetime
    timezone: Literal["UTC"] = "UTC"
    currency: Literal["USD"] = "USD"
    total_listings: int
    listing_status_counts: dict[ListingStatus, int]
    new_listings_in_period: int
    rentals_by_zip: list[RentalsByZip]
    bookings_by_zip: list[BookingsByZip]
    daily_bookings: list[DailyBookings]
