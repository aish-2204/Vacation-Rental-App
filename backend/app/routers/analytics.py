from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.clock import get_clock
from app.core.dependencies import SessionDep, require_admin, require_host
from app.models import User
from app.schemas.analytics import AnalyticsQuery, AnalyticsResponse
from app.schemas.common import ErrorResponse, Success
from app.services.analytics import analytics
from app.services.scopes import AdminScope, HostScope

Host = Annotated[User, Depends(require_host)]
Admin = Annotated[User, Depends(require_admin)]
Clock = Annotated[Callable[[], datetime], Depends(get_clock)]
router = APIRouter(
    tags=["analytics"],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 422, 500)},
)


@router.get(
    "/host/analytics",
    response_model=Success[AnalyticsResponse],
    summary="Get your Host listing and booking analytics",
    description=(
        "Host scope comes from the bearer token. Window is rolling [start, end) in UTC. "
        "Booking value uses noncancelled saved totals, not paid revenue."
    ),
)
async def host_analytics(
    query: Annotated[AnalyticsQuery, Query()], session: SessionDep, host: Host, clock: Clock
):
    return Success(data=await analytics(session, query, clock, HostScope(host.id)))


@router.get(
    "/admin/analytics",
    response_model=Success[AnalyticsResponse],
    summary="Get system-wide Admin listing and booking analytics",
    description=(
        "Includes all listing states and retained booking history. ZIP filters current listing "
        "ZIP for inventory and saved booking ZIP for booking metrics."
    ),
)
async def admin_analytics(
    query: Annotated[AnalyticsQuery, Query()], session: SessionDep, admin: Admin, clock: Clock
):
    return Success(data=await analytics(session, query, clock, AdminScope()))
