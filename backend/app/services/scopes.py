"""Strategy for who an operation acts on behalf of.

Replaces `host_id=None` flag arguments: callers pass `HostScope(host.id)` or
`AdminScope()`, and each strategy decides how listings are filtered, which
owner a listing lock must match, and whether an Admin audit row is recorded.
"""

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from app.models import Listing


class AccessScope(ABC):
    label: str

    @property
    @abstractmethod
    def owner_id(self) -> UUID | None:
        """Listing owner a lock/lookup must match, or None for any listing."""

    @abstractmethod
    def listing_filters(self) -> list[Any]:
        """SQL conditions restricting listings to this scope."""

    @property
    @abstractmethod
    def records_admin_action(self) -> bool:
        """Whether removals in this scope are added to the Admin audit log."""


class HostScope(AccessScope):
    label = "HOST"

    def __init__(self, host_id: UUID) -> None:
        self.host_id = host_id

    @property
    def owner_id(self) -> UUID:
        return self.host_id

    def listing_filters(self) -> list[Any]:
        return [Listing.host_id == self.host_id]

    @property
    def records_admin_action(self) -> bool:
        return False


class AdminScope(AccessScope):
    label = "ADMIN"

    @property
    def owner_id(self) -> None:
        return None

    def listing_filters(self) -> list[Any]:
        return []

    @property
    def records_admin_action(self) -> bool:
        return True
