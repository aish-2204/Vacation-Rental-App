from datetime import timedelta

from app.core.config import get_settings
from app.core.security import create_access_token
from seed.demo import demo_id

BOOKINGS = "/api/v1/bookings"


def auth(actor="customer1"):
    index = {"admin": 0, "host1": 1, "host2": 2, "customer1": 3, "customer2": 4, "customer3": 5}[
        actor
    ]
    token, _ = create_access_token(demo_id(f"user/{index}"), get_settings())
    return {"Authorization": f"Bearer {token}"}


def payload(clock, *, offset=300, nights=2, listing=0, **extra):
    return {
        "listing_id": str(demo_id(f"listing/{listing}")),
        "check_in": (clock[0].date() + timedelta(days=offset)).isoformat(),
        "duration_nights": nights,
        "guests": 2,
        **extra,
    }


async def create(api, clock, **values):
    response = await api.post(BOOKINGS, headers=auth(), json=payload(clock, **values))
    assert response.status_code == 201, response.text
    return response.json()["data"]
