from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Comment = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=2000,
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+$",
    ),
]


class ReviewCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "booking_id": "11111111-1111-4111-8111-111111111111",
                    "rating": 5,
                    "comment": "A comfortable stay and a convenient location.",
                }
            ]
        },
    )
    booking_id: UUID
    rating: int = Field(strict=True, ge=1, le=5)
    comment: Comment


class ReviewPageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=50)


class PublicReview(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    rating: int
    comment: str
    created_at: datetime


class CreatedReview(PublicReview):
    booking_id: UUID
    listing_id: UUID
