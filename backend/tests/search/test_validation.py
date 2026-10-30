from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.models.enums import ListingStatus
from app.schemas.search import AvailabilityQuery, SearchQuery, StayQuery
from app.services.availability import (
    StayError,
    StayRequest,
    local_to_utc,
    resolve_dates,
    resolve_listing_stay,
    validate_global_arrival,
)
from app.services.search import haversine_km


@pytest.mark.parametrize(
    "values",
    [
        {"check_in": "2030-01-01"},
        {"check_out": "2030-01-02"},
        {"duration_nights": 2},
        {"check_in_time": "15:00"},
        {"check_in": "2030-01-01", "duration_nights": 0},
        {"check_in": "2030-01-01", "duration_nights": 15},
        {"check_in": "2030-01-01", "check_out": "2030-01-01"},
        {"check_in": "2030-01-01", "check_out": "2030-01-16"},
        {"check_in": "2030-01-01", "check_out": "2030-01-03", "duration_nights": 3},
        {"check_in": "2030-02-30", "duration_nights": 1},
        {"check_in": "2030-01-01T00:00:00Z", "duration_nights": 1},
        {"check_in": "2030-01-01", "duration_nights": 1, "check_in_time": "15:00:00"},
        {"check_in": "2030-01-01", "duration_nights": 1, "check_out_time": "25:00"},
        {"check_in": "9999-12-31", "duration_nights": 1},
        {"available_only": True},
        {"latitude": 37},
        {"latitude": 37, "longitude": -121},
        {"latitude": 91, "longitude": -121, "radius_km": 10},
        {"latitude": 37, "longitude": -181, "radius_km": 10},
        {"latitude": 37, "longitude": -121, "radius_km": 0},
        {"latitude": 37, "longitude": -121, "radius_km": 501},
        {"latitude": "nan", "longitude": -121, "radius_km": 10},
        {"sort": "distance_asc"},
        {"sort": "injected"},
        {"min_price": "200.00", "max_price": "100.00"},
        {"min_price": "-0.01"},
        {"max_price": "1.001"},
        {"min_price": "NaN"},
        {"amenities": [str(uuid4())] * 51},
        {"amenities": ["not-a-uuid"]},
        {"guests": 0},
        {"page": 0},
        {"page_size": 51},
        {"city": " "},
        {"city": "San\u0000Jose"},
        {"zip_code": 2108},
        {"unknown": "value"},
    ],
)
def test_invalid_global_query_inputs(values):
    with pytest.raises(ValidationError):
        SearchQuery.model_validate(values)


@pytest.mark.parametrize("nights", [1, 14])
def test_valid_dates_defaults_and_consistent_duration(nights):
    start = date(2030, 1, 1)
    query = SearchQuery(
        check_in=start, check_out=start + timedelta(days=nights), duration_nights=nights
    )
    assert query.available_only is True
    assert query.stay_request().nights == nights
    assert query.stay_request().guests == 1
    assert resolve_dates(start, None, nights) == start + timedelta(days=nights)
    browse = SearchQuery()
    assert browse.available_only is False and browse.stay_request() is None
    assert StayQuery(guests=2).stay_request() is None
    with pytest.raises(ValidationError):
        AvailabilityQuery()


def test_duplicate_amenities_and_global_past_arrival():
    identifier = uuid4()
    with pytest.raises(ValidationError):
        SearchQuery(amenities=[identifier, identifier])
    with pytest.raises(StayError, match="past"):
        validate_global_arrival(
            StayRequest(date(2020, 1, 1), date(2020, 1, 2)), datetime(2026, 11, 15, tzinfo=UTC)
        )


def test_dst_ambiguous_and_nonexistent_times_are_rejected():
    timezone = ZoneInfo("America/Los_Angeles")
    with pytest.raises(StayError) as gap:
        local_to_utc(date(2027, 3, 14), time(2, 30), timezone, "check_in_time")
    assert gap.value.code == "NONEXISTENT_LOCAL_TIME"
    with pytest.raises(StayError) as fold:
        local_to_utc(date(2027, 11, 7), time(1, 30), timezone, "check_in_time")
    assert fold.value.code == "AMBIGUOUS_LOCAL_TIME"
    assert local_to_utc(date(2027, 11, 7), time(15), timezone, "check_in_time") == (
        datetime(2027, 11, 7, 23, tzinfo=UTC)
    )
    with pytest.raises(StayError, match="supported date range"):
        local_to_utc(date(9999, 12, 31), time(23, 59), ZoneInfo("Etc/GMT+12"), "check_out_time")


def listing_and_rules():
    listing = SimpleNamespace(
        status=ListingStatus.APPROVED,
        max_guests=4,
        timezone="America/Los_Angeles",
        nightly_price=Decimal("99.99"),
        currency="USD",
    )
    rules = [
        SimpleNamespace(
            weekday=day,
            arrival_allowed=True,
            arrival_start=time(15),
            arrival_end=time(22),
            arrival_default=time(15),
            departure_allowed=True,
            departure_start=time(7),
            departure_end=time(11),
            departure_default=time(11),
        )
        for day in range(7)
    ]
    return listing, rules


@pytest.mark.parametrize("start,hours", [(date(2027, 3, 13), 19), (date(2027, 11, 6), 21)])
def test_dst_day_length_does_not_change_nightly_price(start, hours):
    listing, rules = listing_and_rules()
    result = resolve_listing_stay(
        listing,
        StayRequest(start, start + timedelta(days=1)),
        rules,
        datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert result.nights == 1 and result.total_cost == Decimal("99.99")
    assert result.departure_at - result.arrival_at == timedelta(hours=hours)
    assert result.arrival_at.utcoffset() == timedelta(0)


def test_listing_stay_validation_includes_state_capacity_windows_past_and_total():
    listing, rules = listing_and_rules()
    request = StayRequest(date(2030, 1, 1), date(2030, 1, 2))
    now = datetime(2029, 1, 1, tzinfo=UTC)
    listing.status = ListingStatus.REMOVED
    with pytest.raises(StayError) as removed:
        resolve_listing_stay(listing, request, rules, now)
    assert removed.value.code == "LISTING_UNAVAILABLE"
    listing.status = ListingStatus.APPROVED
    with pytest.raises(StayError) as capacity:
        resolve_listing_stay(
            listing, StayRequest(request.check_in, request.check_out, guests=5), rules, now
        )
    assert capacity.value.code == "GUEST_LIMIT"
    with pytest.raises(StayError) as window:
        resolve_listing_stay(
            listing,
            StayRequest(request.check_in, request.check_out, check_in_time=time(14)),
            rules,
            now,
        )
    assert window.value.code == "OUTSIDE_BOOKING_WINDOW"
    with pytest.raises(StayError) as past:
        resolve_listing_stay(listing, request, rules, datetime(2030, 1, 2, tzinfo=UTC))
    assert past.value.code == "ARRIVAL_IN_PAST"
    listing.nightly_price = Decimal("99999999.99")
    with pytest.raises(StayError) as total:
        resolve_listing_stay(listing, StayRequest(date(2030, 1, 1), date(2030, 1, 3)), rules, now)
    assert total.value.code == "TOTAL_OUT_OF_RANGE"


def test_haversine_is_stable_at_same_point_and_dateline():
    assert haversine_km(37.3382, -121.8863, 37.3382, -121.8863) == 0
    assert haversine_km(0, 179, 0, -179) == pytest.approx(222.39016, rel=1e-6)
    assert 30 < haversine_km(37.3382, -121.8863, 36.9741, -122.0308) < 60
