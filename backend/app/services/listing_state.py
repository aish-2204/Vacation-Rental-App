"""State pattern for the listing lifecycle.

Each `ListingStatus` has one state object that knows which transitions it
allows. Services ask the current state (`state_of(listing)`) instead of
spreading `if listing.status == ...` checks across functions.

    PENDING  --approve-->  APPROVED      (Admin; listing must be complete)
    PENDING  --reject--->  REJECTED      (Admin)
    REJECTED --host edit-> PENDING
    APPROVED --material host edit--> PENDING (re-approval required)
    any      --remove--->  REMOVED       (terminal; repeated removal is a no-op)
"""

from abc import ABC
from typing import ClassVar

from app.core.errors import APIError
from app.models import Listing
from app.models.enums import ListingStatus


def _removed_error() -> APIError:
    return APIError(409, "LISTING_REMOVED", "Removed listings cannot be changed")


def _not_pending_error() -> APIError:
    return APIError(
        409, "INVALID_LISTING_STATE", "Only pending listings can be approved or rejected"
    )


class ListingState(ABC):
    status: ClassVar[ListingStatus]
    accepts_bookings: ClassVar[bool] = False
    is_removed: ClassVar[bool] = False

    def ensure_mutable(self) -> None:
        """Raise if Hosts/Admins may no longer change the listing."""

    def after_host_edit(self, *, material: bool) -> ListingStatus:
        """Status after a Host changes the listing."""
        return self.status

    def approve(self) -> ListingStatus:
        raise _not_pending_error()

    def reject(self) -> ListingStatus:
        raise _not_pending_error()

    def remove(self) -> ListingStatus:
        return ListingStatus.REMOVED


class PendingState(ListingState):
    status = ListingStatus.PENDING

    def approve(self) -> ListingStatus:
        return ListingStatus.APPROVED

    def reject(self) -> ListingStatus:
        return ListingStatus.REJECTED


class ApprovedState(ListingState):
    status = ListingStatus.APPROVED
    accepts_bookings = True

    def after_host_edit(self, *, material: bool) -> ListingStatus:
        return ListingStatus.PENDING if material else self.status


class RejectedState(ListingState):
    status = ListingStatus.REJECTED

    def after_host_edit(self, *, material: bool) -> ListingStatus:
        return ListingStatus.PENDING


class RemovedState(ListingState):
    status = ListingStatus.REMOVED
    is_removed = True

    def ensure_mutable(self) -> None:
        raise _removed_error()

    def approve(self) -> ListingStatus:
        raise _removed_error()

    def reject(self) -> ListingStatus:
        raise _removed_error()


_STATES: dict[ListingStatus, ListingState] = {
    state.status: state
    for state in (PendingState(), ApprovedState(), RejectedState(), RemovedState())
}


def state_of(listing: Listing) -> ListingState:
    return _STATES[ListingStatus(listing.status)]
