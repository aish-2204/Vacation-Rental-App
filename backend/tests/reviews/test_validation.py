from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.main import create_app
from app.schemas.reviews import ReviewCreate
from seed.demo import demo_id
from tests.reviews.helpers import REVIEWS, auth, completed_booking, page_path, payload


@pytest.mark.parametrize(
    "changes",
    [
        {"booking_id": None},
        {"booking_id": "not-uuid"},
        {"rating": 0},
        {"rating": 6},
        {"rating": 1.5},
        {"rating": 3.0},
        {"rating": "5"},
        {"rating": True},
        {"rating": None},
        {"comment": ""},
        {"comment": " \n\t "},
        {"comment": "x" * 2001},
        {"comment": None},
        {"comment": 42},
        {"comment": "bad\u0000text"},
        {"comment": "bad\u0007text"},
        {"customer_id": str(uuid4())},
        {"listing_id": str(uuid4())},
        {"created_at": "2020-01-01T00:00:00Z"},
        {"id": str(uuid4())},
        {"average_rating": 5},
        {"unknown": True},
    ],
)
def test_invalid_ratings_comments_ids_and_injected_fields(changes):
    with pytest.raises(ValidationError):
        ReviewCreate.model_validate(payload(uuid4(), **changes))


@pytest.mark.parametrize("rating", [1, 5])
def test_rating_and_comment_boundaries(rating):
    request = ReviewCreate.model_validate(
        payload(uuid4(), rating=rating, comment=" " + "é" * 2000 + " ")
    )
    assert request.rating == rating and len(request.comment) == 2000


@pytest.mark.parametrize(
    "changes",
    [
        {"rating": 0},
        {"rating": 6},
        {"rating": True},
        {"comment": " "},
        {"customer_id": str(uuid4())},
        {"comment": "bad\u0000text"},
    ],
)
async def test_http_validation_errors_are_safe_and_do_not_insert(api, db, clock, changes):
    from sqlalchemy import func, select

    from app.models import Review

    booking = await completed_booking(db, clock)
    response = await api.post(REVIEWS, headers=auth(), json=payload(booking.id, **changes))
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert (
        await db.scalar(
            select(func.count()).select_from(Review).where(Review.booking_id == booking.id)
        )
        == 0
    )


async def test_malformed_json_missing_fields_and_page_validation(api):
    response = await api.post(
        REVIEWS, headers={**auth(), "Content-Type": "application/json"}, content='{"rating":'
    )
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_JSON"
    assert (await api.post(REVIEWS, headers=auth(), json={})).status_code == 422
    for query in ({"page": 0}, {"page_size": 0}, {"page_size": 51}, {"customer_id": str(uuid4())}):
        response = await api.get(page_path(), params=query)
        assert response.status_code == 422
        assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert (await api.get("/api/v1/listings/not-uuid/reviews")).status_code == 422


def test_openapi_security_examples_and_public_privacy():
    schema = create_app().openapi()
    creation = schema["paths"][REVIEWS]["post"]
    public = schema["paths"]["/api/v1/listings/{listing_id}/reviews"]["get"]
    assert creation["security"] == [{"BearerAuth": []}]
    assert not public.get("security")
    assert {"201", "401", "403", "404", "409", "422"} <= creation["responses"].keys()
    assert {"200", "404", "422"} <= public["responses"].keys()
    assert set(schema["components"]["schemas"]["PublicReview"]["properties"]) == {
        "id",
        "rating",
        "comment",
        "created_at",
    }
    assert set(schema["components"]["schemas"]["ReviewCreate"]["properties"]) == {
        "booking_id",
        "rating",
        "comment",
    }
    ReviewCreate.model_validate(schema["components"]["schemas"]["ReviewCreate"]["examples"][0])
    assert str(demo_id("user/3")) not in str(schema["components"]["schemas"]["PublicReview"])
