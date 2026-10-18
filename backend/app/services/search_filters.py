"""Specification pattern for public search filters.

Each optional search criterion is a small specification: it says whether the
query uses it (`applies`) and which SQL conditions it adds (`clauses`). Adding
a new filter means adding one class to `SPECIFICATIONS`, not editing search().
"""

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy import func, select

from app.models import Listing, ListingAmenity
from app.schemas.search import SearchQuery


class SearchSpecification(ABC):
    def applies(self, query: SearchQuery) -> bool:
        return True

    @abstractmethod
    def clauses(self, query: SearchQuery) -> list[Any]:
        """SQL conditions for this criterion (combined with AND)."""


class FieldSpecification(SearchSpecification):
    """Criterion driven by one optional query field."""

    field: str

    def applies(self, query):
        return getattr(query, self.field) is not None

    def clauses(self, query):
        return [self.clause(getattr(query, self.field))]

    @abstractmethod
    def clause(self, value) -> Any: ...


class CityIs(FieldSpecification):
    field = "city"

    def clause(self, value):
        return func.lower(Listing.city) == value.lower()


class StateIs(FieldSpecification):
    field = "state"

    def clause(self, value):
        return Listing.state == value


class ZipCodeIs(FieldSpecification):
    field = "zip_code"

    def clause(self, value):
        return Listing.zip_code == value


class FitsGuests(FieldSpecification):
    field = "guests"

    def clause(self, value):
        return Listing.max_guests >= value


class PriceAtLeast(FieldSpecification):
    field = "min_price"

    def clause(self, value):
        return Listing.nightly_price >= value


class PriceAtMost(FieldSpecification):
    field = "max_price"

    def clause(self, value):
        return Listing.nightly_price <= value


class HasAllAmenities(SearchSpecification):
    def applies(self, query):
        return bool(query.amenities)

    def clauses(self, query):
        return [
            Listing.id.in_(
                select(ListingAmenity.listing_id).where(ListingAmenity.amenity_id == amenity_id)
            )
            for amenity_id in query.amenities
        ]


SPECIFICATIONS: tuple[SearchSpecification, ...] = (
    CityIs(),
    StateIs(),
    ZipCodeIs(),
    FitsGuests(),
    PriceAtLeast(),
    PriceAtMost(),
    HasAllAmenities(),
)


def search_filters(query: SearchQuery) -> list[Any]:
    return [
        clause
        for specification in SPECIFICATIONS
        if specification.applies(query)
        for clause in specification.clauses(query)
    ]
