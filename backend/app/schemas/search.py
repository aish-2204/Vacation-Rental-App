from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    model_validator,
)

from app.schemas.listings import (
    ZIP,
    AmenityResponse,
    HoursResponse,
    LocalDate,
    MediaResponse,
    RuleResponse,
    State,
    WallTime,
)
from app.services.availability import ResolvedStay, StayRequest, resolve_dates


class StayQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_in: LocalDate | None = Field(default=None, description="Listing-local YYYY-MM-DD")
    check_out: LocalDate | None = Field(
        default=None, description="Exclusive checkout date; supply this or duration_nights"
    )
    duration_nights: int | None = Field(
        default=None, ge=1, le=14, description="Local date difference, 1–14 nights"
    )
    check_in_time: WallTime | None = Field(
        default=None, description="Listing-local HH:MM; defaults to weekday arrival rule"
    )
    check_out_time: WallTime | None = Field(
        default=None, description="Listing-local HH:MM; defaults to weekday departure rule"
    )
    guests: int | None = Field(
        default=None, ge=1, le=2147483647, description="Requested guests; defaults to 1 for a stay"
    )

    @model_validator(mode="after")
    def validate_stay(self):
        if self.check_in is None:
            if any(
                value is not None
                for value in (
                    self.check_out,
                    self.duration_nights,
                    self.check_in_time,
                    self.check_out_time,
                )
            ):
                raise ValueError("check_in is required with stay dates, duration, or times")
        else:
            self.check_out = resolve_dates(self.check_in, self.check_out, self.duration_nights)
        return self

    def stay_request(self) -> StayRequest | None:
        if self.check_in is None:
            return None
        return StayRequest(
            self.check_in, self.check_out, self.guests or 1, self.check_in_time, self.check_out_time
        )


class AvailabilityQuery(StayQuery):
    check_in: LocalDate = Field(...)


FilterMoney = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
FilterText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f]+$"
    ),
]


class SearchQuery(StayQuery):
    city: FilterText | None = None
    state: State | None = None
    zip_code: ZIP | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float | None = Field(default=None, gt=0, le=500)
    amenities: list[UUID] = Field(
        default_factory=list,
        max_length=50,
        description="Repeat amenity UUIDs from GET /api/v1/amenities; all must match",
    )
    min_price: FilterMoney | None = None
    max_price: FilterMoney | None = None
    available_only: bool | None = Field(
        default=None,
        description="Default: true with dates, false without dates. Explicit true requires dates.",
    )
    sort: Literal["newest", "price_asc", "price_desc", "rating_desc", "distance_asc"] = "newest"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def validate_filters(self):
        coordinates = self.latitude, self.longitude, self.radius_km
        if any(item is not None for item in coordinates) and not all(
            item is not None for item in coordinates
        ):
            raise ValueError("latitude, longitude, and radius_km must be supplied together")
        if self.sort == "distance_asc" and self.latitude is None:
            raise ValueError("distance_asc requires coordinates and radius_km")
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price must not exceed max_price")
        if len(self.amenities) != len(set(self.amenities)):
            raise ValueError("Duplicate amenity IDs are not allowed")
        if self.available_only is True and self.check_in is None:
            raise ValueError("available_only=true requires a valid stay")
        if self.available_only is None:
            self.available_only = self.check_in is not None
        return self


class QuoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    check_in: date
    check_out: date
    nights: int
    guests: int
    check_in_time: time
    check_out_time: time
    arrival_at: datetime
    departure_at: datetime
    nightly_price: Decimal
    total_cost: Decimal
    currency: str

    @field_serializer("check_in_time", "check_out_time")
    def serialize_time(self, value):
        return value.strftime("%H:%M")

    @classmethod
    def from_stay(cls, stay: ResolvedStay):
        return cls.model_validate(stay)


class AvailabilityResponse(BaseModel):
    listing_id: UUID
    available: bool
    total_cost: Decimal
    quote: QuoteResponse
    unavailable_reason: Literal["DATES_UNAVAILABLE"] | None = None


class PublicListingCard(BaseModel):
    id: UUID
    name: str
    address_line1: str
    city: str
    state: str
    zip_code: str
    latitude: float
    longitude: float
    timezone: str
    max_guests: int
    nightly_price: Decimal
    currency: str
    cost_rating: str
    media: list[MediaResponse]
    amenities: list[AmenityResponse]
    average_rating: float | None
    review_count: int
    bookings_today: int
    available: bool | None
    total_cost: Decimal | None
    quote: QuoteResponse | None
    unavailable_reason: Literal["DATES_UNAVAILABLE"] | None = None
    distance_km: float | None = None


class PublicListingDetail(PublicListingCard):
    address_line2: str | None
    description: str
    contact_name: str
    contact_email: str
    contact_phone: str
    hours: list[HoursResponse]
    booking_rules: list[RuleResponse]
