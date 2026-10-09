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


