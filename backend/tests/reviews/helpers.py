from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models import Booking
from app.models.enums import ReservationState
from seed.demo import demo_id

REVIEWS = "/api/v1/reviews"


def auth(actor="customer1"):
    index = {"admin": 0, "host1": 1, "host2": 2, "customer1": 3, "customer2": 4, "customer3": 5}[
        actor
    ]
    token, _ = create_access_token(demo_id(f"user/{index}"), get_settings())
    return {"Authorization": f"Bearer {token}"}


def page_path(index=0):
    return f"/api/v1/listings/{demo_id(f'listing/{index}')}/reviews"


def payload(identifier, **values):
    return {"booking_id": str(identifier), "rating": 5, "comment": "A comfortable stay.", **values}


async def completed_booking(db, clock, *, offset=-300, customer=3, listing=0):
    """Create unreviewed past inventory only inside the disposable test schema."""
    template = await db.get(Booking, demo_id("booking/0"))
    values = {column.name: getattr(template, column.name) for column in Booking.__table__.columns}
    start = clock[0].date() + timedelta(days=offset)
    timezone = ZoneInfo(template.listing_timezone_snapshot)
    values.update(
        id=uuid4(),
        listing_id=demo_id(f"listing/{listing}"),
        customer_id=demo_id(f"user/{customer}"),
        check_in=start,
        check_out=start + timedelta(days=1),
        arrival_at=datetime.combine(start, time(15), timezone),
        departure_at=datetime.combine(start + timedelta(days=1), time(11), timezone),
        total_cost=template.nightly_price_snapshot,
        created_at=datetime.combine(start - timedelta(days=5), time(12), timezone),
        updated_at=datetime.combine(start - timedelta(days=5), time(12), timezone),
        reservation_state=ReservationState.CONFIRMED,
        cancelled_at=None,
    )
    booking = Booking(**values)
    db.add(booking)
    await db.commit()
    return booking
