import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_serializer,
    model_validator,
)

from app.core.config import get_settings
from app.models.enums import AdminActionType, ListingStatus, MediaType
from app.schemas.auth import Credentials


def timezone_name(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Use a valid IANA timezone") from None
    return value


def contact_email(value: str) -> str:
    return Credentials.normalize_email(value) if value else ""


def local_media_url(value: str) -> bool:
    """Development/test only: local storage serves uploads over plain HTTP."""
    settings = get_settings()
    return settings.app_env in {"development", "test"} and value.startswith(
        f"{settings.media_public_base_url}/"
    )


def https_url(value: str) -> str:
    parsed = HttpUrl(value)
    if (
        (parsed.scheme != "https" and not local_media_url(value))
        or parsed.username
        or parsed.password
        or any(c.isspace() for c in value)
    ):
        raise ValueError("Use an HTTPS URL without credentials or whitespace")
    return str(parsed)


def local_time(value):
    if isinstance(value, str) and not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError("Use listing-local HH:MM time")
    if isinstance(value, time) and (value.tzinfo or value.second or value.microsecond):
        raise ValueError("Use listing-local HH:MM time")
    return value


def date_only(value):
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    if type(value) is date:
        return value
    raise ValueError("Use YYYY-MM-DD dates")


def unique_ids(values: list[UUID]) -> list[UUID]:
    if len(values) != len(set(values)):
        raise ValueError("Duplicate amenity IDs are not allowed")
    return values


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
City = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
State = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z]{2}$"),
    BeforeValidator(lambda value: value.strip().upper() if isinstance(value, str) else value),
]
ZIP = Annotated[str, StringConstraints(pattern=r"^[0-9]{5}(-[0-9]{4})?$")]
Timezone = Annotated[str, Field(max_length=64), AfterValidator(timezone_name)]
Money = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
Latitude = Annotated[Decimal, Field(ge=-90, le=90, max_digits=9, decimal_places=6)]
Longitude = Annotated[Decimal, Field(ge=-180, le=180, max_digits=9, decimal_places=6)]
Phone = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, max_length=32, pattern=r"^(?:\+?[0-9][0-9 ()-]{6,30}[0-9])?$"
    ),
]
Email = Annotated[str, Field(max_length=254), AfterValidator(contact_email)]
WallTime = Annotated[time, BeforeValidator(local_time)]
LocalDate = Annotated[date, BeforeValidator(date_only)]
AmenityIDs = Annotated[list[UUID], Field(max_length=50), AfterValidator(unique_ids)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
HTTPS = Annotated[str, Field(max_length=2048), AfterValidator(https_url)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HoursInput(InputModel):
    weekday: int = Field(ge=0, le=6)
    closed: bool = False
    opening_time: WallTime | None = None
    closing_time: WallTime | None = None

    @field_serializer("opening_time", "closing_time", when_used="json")
    def serialize_time(self, value):
        return value.strftime("%H:%M") if value is not None else None

    @model_validator(mode="after")
    def valid_window(self):
        if self.closed:
            if self.opening_time is not None or self.closing_time is not None:
                raise ValueError("Closed contact hours must omit opening/closing times")
        elif (
            self.opening_time is None
            or self.closing_time is None
            or (self.opening_time >= self.closing_time)
        ):
            raise ValueError("Open contact hours require opening_time before closing_time")
        return self


class BookingRuleInput(InputModel):
    weekday: int = Field(ge=0, le=6)
    arrival_allowed: bool
    arrival_start: WallTime | None = None
    arrival_end: WallTime | None = None
    arrival_default: WallTime | None = None
    departure_allowed: bool
    departure_start: WallTime | None = None
    departure_end: WallTime | None = None
    departure_default: WallTime | None = None

    @field_serializer(
        "arrival_start",
        "arrival_end",
        "arrival_default",
        "departure_start",
        "departure_end",
        "departure_default",
        when_used="json",
    )
    def serialize_time(self, value):
        return value.strftime("%H:%M") if value is not None else None

    @model_validator(mode="after")
    def valid_windows(self):
        for direction in ("arrival", "departure"):
            allowed = getattr(self, f"{direction}_allowed")
            start, end, default = (
                getattr(self, f"{direction}_{suffix}") for suffix in ("start", "end", "default")
            )
            if allowed:
                if start is None or end is None or default is None or not start <= default <= end:
                    raise ValueError(f"{direction} requires start <= default <= end")
            elif any(value is not None for value in (start, end, default)):
                raise ValueError(f"Disabled {direction} must omit its times")
        return self


def full_week(items):
    if {item.weekday for item in items} != set(range(7)) or len(items) != 7:
        raise ValueError("Supply exactly one entry for every weekday, Monday=0 through Sunday=6")
    return items


WeekHours = Annotated[
    list[HoursInput], Field(min_length=7, max_length=7), AfterValidator(full_week)
]
WeekRules = Annotated[
    list[BookingRuleInput], Field(min_length=7, max_length=7), AfterValidator(full_week)
]


class HoursReplace(InputModel):
    hours: WeekHours
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "hours": [
                        {
                            "weekday": day,
                            "closed": False,
                            "opening_time": "09:00",
                            "closing_time": "18:00",
                        }
                        for day in range(7)
                    ]
                }
            ]
        },
    )


class RulesReplace(InputModel):
    booking_rules: WeekRules
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "booking_rules": [
                        {
                            "weekday": day,
                            "arrival_allowed": True,
                            "arrival_start": "15:00",
                            "arrival_end": "22:00",
                            "arrival_default": "15:00",
                            "departure_allowed": True,
                            "departure_start": "07:00",
                            "departure_end": "11:00",
                            "departure_default": "11:00",
                        }
                        for day in range(7)
                    ]
                }
            ]
        },
    )


class MediaInput(InputModel):
    url: HTTPS
    media_type: MediaType = MediaType.IMAGE
    caption: str | None = Field(default=None, max_length=200)
    sort_order: int = Field(default=0, ge=0, le=2147483647)
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "url": "https://placehold.co/800x600",
                    "media_type": "IMAGE",
                    "caption": "Demo photo",
                    "sort_order": 0,
                }
            ]
        },
    )


class NonemptyPatch(InputModel):
    @model_validator(mode="after")
    def nonempty_and_no_nulls(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one field to update")
        for field in self.model_fields_set - {"address_line2", "caption"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class MediaPatch(NonemptyPatch):
    url: HTTPS | None = None
    media_type: MediaType | None = None
    caption: str | None = Field(default=None, max_length=200)
    sort_order: int | None = Field(default=None, ge=0, le=2147483647)


class ListingCreate(InputModel):
    name: Name
    description: str = Field(default="", max_length=5000)
    address_line1: Address
    address_line2: str | None = Field(default=None, max_length=200)
    city: City
    state: State
    zip_code: ZIP
    latitude: Latitude
    longitude: Longitude
    timezone: Timezone
    contact_name: str = Field(default="", max_length=120)
    contact_email: Email = ""
    contact_phone: Phone = ""
    nightly_price: Money
    currency: Literal["USD"] = "USD"
    max_guests: int = Field(ge=1, le=2147483647)
    amenity_ids: AmenityIDs = Field(default_factory=list)
    media: list[MediaInput] = Field(default_factory=list, max_length=30)
    hours: WeekHours | None = None
    booking_rules: WeekRules | None = None

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "Sunny San Jose Home",
                    "description": "A fictional entire-home demo rental.",
                    "address_line1": "100 Example Lane",
                    "city": "San Jose",
                    "state": "CA",
                    "zip_code": "95112",
                    "latitude": "37.338200",
                    "longitude": "-121.886300",
                    "timezone": "America/Los_Angeles",
                    "nightly_price": "150.00",
                    "max_guests": 4,
                    "contact_name": "Demo Host",
                    "contact_email": "host1@example.test",
                    "contact_phone": "+15550100123",
                }
            ]
        },
    )


class ListingPatch(NonemptyPatch):
    name: Name | None = None
    description: str | None = Field(default=None, max_length=5000)
    address_line1: Address | None = None
    address_line2: str | None = Field(default=None, max_length=200)
    city: City | None = None
    state: State | None = None
    zip_code: ZIP | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    timezone: Timezone | None = None
    contact_name: str | None = Field(default=None, max_length=120)
    contact_email: Email | None = None
    contact_phone: Phone | None = None
    nightly_price: Money | None = None
    currency: Literal["USD"] | None = None
    max_guests: int | None = Field(default=None, ge=1, le=2147483647)
    amenity_ids: AmenityIDs | None = None


class BlockInput(InputModel):
    start_date: LocalDate
    end_date: LocalDate
    reason: Reason
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "start_date": "2030-01-10",
                    "end_date": "2030-01-13",
                    "reason": "Maintenance",
                }
            ]
        },
    )

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class ReasonInput(InputModel):
    reason: Reason
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "reason": "Listing information needs correction",
                }
            ]
        },
    )


class ORMResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AmenityResponse(ORMResponse):
    id: UUID
    name: str


MEDIA_CONTENT_TYPES: dict[str, tuple[str, MediaType]] = {
    "image/jpeg": (".jpg", MediaType.IMAGE),
    "image/png": (".png", MediaType.IMAGE),
    "image/webp": (".webp", MediaType.IMAGE),
    "video/mp4": (".mp4", MediaType.VIDEO),
    "video/webm": (".webm", MediaType.VIDEO),
}
UploadContentType = Literal["image/jpeg", "image/png", "image/webp", "video/mp4", "video/webm"]


class MediaUploadRequest(InputModel):
    content_type: UploadContentType = Field(description="MIME type of the file to upload")
    size_bytes: int = Field(gt=0, le=2**40, description="Exact file size in bytes")
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"content_type": "image/jpeg", "size_bytes": 482133}]},
    )


class MediaUploadResponse(BaseModel):
    upload_url: str = Field(description="Send the file bytes here; expires at expires_at")
    method: str = Field(description="HTTP method for the upload request")
    headers: dict[str, str] = Field(description="Headers the upload request must include")
    public_url: str = Field(description="Use as `url` when adding the media after uploading")
    media_type: MediaType
    max_bytes: int
    expires_at: datetime


class MediaResponse(ORMResponse):
    id: UUID
    url: str
    media_type: MediaType
    caption: str | None
    sort_order: int


class HoursResponse(HoursInput):
    model_config = ConfigDict(from_attributes=True)


class RuleResponse(BookingRuleInput):
    model_config = ConfigDict(from_attributes=True)


class BlockResponse(ORMResponse):
    id: UUID
    listing_id: UUID
    start_date: date
    end_date: date
    reason: str
    created_at: datetime


class RemovalResponse(ORMResponse):
    actor_id: UUID
    reason: str
    created_at: datetime


class ListingSummary(ORMResponse):
    id: UUID
    host_id: UUID
    name: str
    city: str
    state: str
    zip_code: str
    nightly_price: Decimal
    currency: str
    max_guests: int
    status: ListingStatus
    created_at: datetime
    updated_at: datetime
    removed_at: datetime | None
    cost_rating: str


class ListingDetail(ListingSummary):
    description: str
    address_line1: str
    address_line2: str | None
    latitude: float
    longitude: float
    timezone: str
    contact_name: str
    contact_email: str
    contact_phone: str
    amenities: list[AmenityResponse]
    media: list[MediaResponse]
    hours: list[HoursResponse]
    booking_rules: list[RuleResponse]
    removal: RemovalResponse | None


class AuditResponse(ORMResponse):
    id: UUID
    admin_id: UUID
    listing_id: UUID
    action: AdminActionType
    reason: str | None
    created_at: datetime


class DeletedResponse(BaseModel):
    id: UUID
    deleted: Literal[True] = True
