from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey
from app.models.enums import AdminActionType, ListingStatus, MediaType, ReservationState, Role


def enum_type(enum_class: type, name: str) -> Enum:
    return Enum(enum_class, name=name, native_enum=False, create_constraint=True)


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(btrim(email)) AND email <> ''", name="normalized_email"),
    )

    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str] = mapped_column(String(32))
    role: Mapped[Role] = mapped_column(enum_type(Role, "user_role"))


class Listing(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "listings"
    __table_args__ = (
        CheckConstraint("nightly_price > 0", name="positive_price"),
        CheckConstraint("currency = 'USD'", name="usd_currency"),
        CheckConstraint("max_guests > 0", name="positive_capacity"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_bounds"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_bounds"),
        CheckConstraint(
            "(status = 'REMOVED') = (removed_at IS NOT NULL)", name="removal_timestamp"
        ),
        Index("ix_listings_host_status", "host_id", "status"),
        Index(
            "ix_listings_approved_location",
            "city",
            "state",
            "zip_code",
            postgresql_where=text("status = 'APPROVED'"),
        ),
        Index("ix_listings_approved_zip", "zip_code", postgresql_where=text("status = 'APPROVED'")),
        Index("ix_listings_created_zip", "created_at", "zip_code"),
    )

    host_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    address_line1: Mapped[str] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2))
    zip_code: Mapped[str] = mapped_column(String(10))
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    timezone: Mapped[str] = mapped_column(String(64))
    contact_name: Mapped[str] = mapped_column(String(120))
    contact_email: Mapped[str] = mapped_column(String(254))
    contact_phone: Mapped[str] = mapped_column(String(32))
    nightly_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    max_guests: Mapped[int] = mapped_column(Integer)
    status: Mapped[ListingStatus] = mapped_column(
        enum_type(ListingStatus, "listing_status"),
        default=ListingStatus.PENDING,
        server_default="PENDING",
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ListingHours(UUIDPrimaryKey, Base):
    __tablename__ = "listing_hours"
    __table_args__ = (
        UniqueConstraint("listing_id", "weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint(
            "(closed AND opening_time IS NULL AND closing_time IS NULL) OR "
            "(NOT closed AND opening_time IS NOT NULL AND closing_time IS NOT NULL "
            "AND opening_time < closing_time)",
            name="contact_window",
        ),
    )

    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    weekday: Mapped[int] = mapped_column(Integer)
    closed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    opening_time: Mapped[time | None] = mapped_column(Time)
    closing_time: Mapped[time | None] = mapped_column(Time)


class ListingBookingRule(UUIDPrimaryKey, Base):
    __tablename__ = "listing_booking_rules"
    __table_args__ = (
        UniqueConstraint("listing_id", "weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint(
            "(NOT arrival_allowed AND arrival_start IS NULL AND arrival_end IS NULL "
            "AND arrival_default IS NULL) OR (arrival_allowed AND arrival_start IS NOT NULL "
            "AND arrival_end IS NOT NULL AND arrival_default IS NOT NULL "
            "AND arrival_start <= arrival_default AND arrival_default <= arrival_end)",
            name="arrival_window",
        ),
        CheckConstraint(
            "(NOT departure_allowed AND departure_start IS NULL AND departure_end IS NULL "
            "AND departure_default IS NULL) OR (departure_allowed AND departure_start IS NOT NULL "
            "AND departure_end IS NOT NULL AND departure_default IS NOT NULL "
            "AND departure_start <= departure_default AND departure_default <= departure_end)",
            name="departure_window",
        ),
    )

    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    weekday: Mapped[int] = mapped_column(Integer)
    arrival_allowed: Mapped[bool] = mapped_column(Boolean)
    arrival_start: Mapped[time | None] = mapped_column(Time)
    arrival_end: Mapped[time | None] = mapped_column(Time)
    arrival_default: Mapped[time | None] = mapped_column(Time)
    departure_allowed: Mapped[bool] = mapped_column(Boolean)
    departure_start: Mapped[time | None] = mapped_column(Time)
    departure_end: Mapped[time | None] = mapped_column(Time)
    departure_default: Mapped[time | None] = mapped_column(Time)


class ListingMedia(UUIDPrimaryKey, Base):
    __tablename__ = "listing_media"
    __table_args__ = (
        # HTTPS everywhere; plain HTTP only for loopback local-storage uploads (dev/test).
        CheckConstraint(
            "url ~ '^(https://[^/[:space:]]+(/[^[:space:]]*)?"
            "|http://(127\\.0\\.0\\.1|localhost)(:[0-9]+)?/media/[^[:space:]]+)$'",
            name="https_url",
        ),
        CheckConstraint("sort_order >= 0", name="nonnegative_order"),
        Index("ix_listing_media_listing_order", "listing_id", "sort_order"),
    )

    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    url: Mapped[str] = mapped_column(Text)
    media_type: Mapped[MediaType] = mapped_column(enum_type(MediaType, "media_type"))
    caption: Mapped[str | None] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Amenity(UUIDPrimaryKey, Base):
    __tablename__ = "amenities"
    name: Mapped[str] = mapped_column(String(80), unique=True)


class ListingAmenity(Base):
    __tablename__ = "listing_amenities"
    listing_id: Mapped[UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="RESTRICT"), primary_key=True
    )
    amenity_id: Mapped[UUID] = mapped_column(
        ForeignKey("amenities.id", ondelete="RESTRICT"), primary_key=True
    )


class AvailabilityBlock(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "availability_blocks"
    __table_args__ = (
        CheckConstraint("end_date > start_date", name="ordered_dates"),
        Index("ix_availability_blocks_listing_dates", "listing_id", "start_date", "end_date"),
    )

    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)


