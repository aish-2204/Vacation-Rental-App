from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.security import create_access_token
from seed.demo import demo_id


def auth(role="host1"):
    index = {"admin": 0, "host1": 1, "host2": 2, "customer": 3}[role]
    token, _ = create_access_token(demo_id(f"user/{index}"), get_settings())
    return {"Authorization": f"Bearer {token}"}


def path(index=0):
    return f"/api/v1/host/listings/{demo_id(f'listing/{index}')}"


def admin_path(identifier):
    return f"/api/v1/admin/listings/{identifier}"


def hours():
    return [
        {"weekday": day, "closed": False, "opening_time": "09:00", "closing_time": "18:00"}
        for day in range(7)
    ]


def rules():
    return [
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


def payload(*, complete=True):
    data = {
        "name": "New Demo Home",
        "description": "A fictional entire home.",
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
    if complete:
        data.update(
            hours=hours(),
            booking_rules=rules(),
            media=[{"url": "https://example.test/photo.jpg", "caption": "Demo photo"}],
            amenity_ids=[str(demo_id("amenity/Wi-Fi"))],
        )
    return data


def block(offset=700):
    start = datetime.now(UTC).date() + timedelta(days=offset)
    return {
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=3)).isoformat(),
        "reason": "Maintenance",
    }


async def create(api, *, complete=True):
    response = await api.post(
        "/api/v1/host/listings", json=payload(complete=complete), headers=auth()
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]
