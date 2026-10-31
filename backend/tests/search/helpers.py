from datetime import timedelta

from seed.demo import demo_id

SEARCH = "/api/v1/listings/search"


def listing_path(index=0):
    return f"/api/v1/listings/{demo_id(f'listing/{index}')}"


def stay(clock, *, offset=300, nights=2, **extra):
    start = clock[0].date() + timedelta(days=offset)
    return {"check_in": start.isoformat(), "duration_nights": nights, **extra}


def ids(response):
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["data"]}
