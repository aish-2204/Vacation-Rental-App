"""Command pattern for listing moderation and removal.

Each Admin/Host action on a listing's lifecycle is a command object. `execute`
is shared: lock the listing first (like every other writer), let the command
apply its change through the listing's State, record its audit rows, then
flush, refresh and commit. The `AdminAction` table is the log of executed
moderation commands.
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminAction, Listing, ListingRemoval
from app.models.enums import AdminActionType
from app.schemas.common import Paginated
from app.schemas.listings import AuditResponse, ListingDetail
from app.services import listings
from app.services.listing_state import state_of
from app.services.pagination import PageQuery
from app.services.scopes import AccessScope, AdminScope


class ListingCommand(ABC):
    def __init__(self, actor_id: UUID, listing_id: UUID, reason: str | None = None) -> None:
        self.actor_id, self.listing_id, self.reason = actor_id, listing_id, reason

    @property
    def scope(self) -> AccessScope:
        return AdminScope()

    async def execute(self, session: AsyncSession) -> ListingDetail:
        # Resolve through the module so lock instrumentation in tests still applies.
        listing = await listings.lock_listing(session, self.listing_id, host_id=self.scope.owner_id)
        if await self.already_done(listing):
            return await listings.listing_detail(session, listing)
        now = datetime.now(UTC)
        await self.apply(session, listing, now)
        listing.updated_at = now
        session.add_all(self.audit_rows(listing, now))
        return await listings.finish(session, listing)

    async def already_done(self, listing: Listing) -> bool:
        return False

    @abstractmethod
    async def apply(self, session: AsyncSession, listing: Listing, now: datetime) -> None:
        """Change the listing; raise APIError when the transition is not allowed."""

    @abstractmethod
    def audit_rows(self, listing: Listing, now: datetime) -> list:
        """Rows recording this command."""


class ApproveListingCommand(ListingCommand):
    action = AdminActionType.APPROVED

    async def apply(self, session, listing, now):
        next_status = state_of(listing).approve()
        await listings.ensure_complete(session, listing)
        listing.status = next_status

    def audit_rows(self, listing, now):
        return [AdminAction(admin_id=self.actor_id, listing_id=listing.id, action=self.action)]


class RejectListingCommand(ListingCommand):
    action = AdminActionType.REJECTED

    async def apply(self, session, listing, now):
        listing.status = state_of(listing).reject()

    def audit_rows(self, listing, now):
        return [
            AdminAction(
                admin_id=self.actor_id,
                listing_id=listing.id,
                action=self.action,
                reason=self.reason,
            )
        ]


class RemoveListingCommand(ListingCommand):
    """Soft removal by a Host (own listing) or an Admin (any listing, audited)."""

    def __init__(self, actor_id: UUID, listing_id: UUID, reason: str, scope: AccessScope) -> None:
        super().__init__(actor_id, listing_id, reason)
        self._scope = scope

    @property
    def scope(self) -> AccessScope:
        return self._scope

    async def already_done(self, listing):
        # Repeated removal returns the saved result without new audit rows.
        return state_of(listing).is_removed

    async def apply(self, session, listing, now):
        listing.status = state_of(listing).remove()
        listing.removed_at = now

    def audit_rows(self, listing, now):
        rows = [
            ListingRemoval(
                listing_id=listing.id, actor_id=self.actor_id, reason=self.reason, created_at=now
            )
        ]
        if self.scope.records_admin_action:
            rows.append(
                AdminAction(
                    admin_id=self.actor_id,
                    listing_id=listing.id,
                    action=AdminActionType.REMOVED,
                    reason=self.reason,
                    created_at=now,
                )
            )
        return rows


class AuditPage(PageQuery[AdminAction, AuditResponse]):
    def __init__(self, listing_id: UUID | None = None) -> None:
        self.listing_id = listing_id

    def statement(self) -> Select:
        filters = [AdminAction.listing_id == self.listing_id] if self.listing_id else []
        return select(AdminAction).where(*filters)

    def order_by(self):
        return (AdminAction.created_at.desc(), AdminAction.id)

    def to_item(self, row: AdminAction) -> AuditResponse:
        return AuditResponse.model_validate(row)


async def audit_page(session, page, page_size, listing_id=None) -> Paginated[AuditResponse]:
    return await AuditPage(listing_id).fetch(session, page, page_size)
