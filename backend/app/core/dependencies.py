from typing import Annotated

import jwt
from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import APIError
from app.core.security import decode_access_token
from app.database.session import get_session
from app.models import User
from app.models.enums import Role
from app.storage import ObjectStorage, get_storage

bearer = HTTPBearer(scheme_name="BearerAuth", auto_error=False)
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
) -> User:
    error = APIError(
        401,
        "UNAUTHENTICATED",
        "A valid bearer token is required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise error
    try:
        user_id = decode_access_token(credentials.credentials, settings)
    except jwt.InvalidTokenError:
        raise error from None
    user = await session.get(User, user_id)
    if user is None:
        raise error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise APIError(403, "FORBIDDEN", "Your role cannot perform this operation")
        return user

    return dependency


require_customer = require_roles(Role.CUSTOMER)
require_host = require_roles(Role.HOST)
require_admin = require_roles(Role.ADMIN)


def require_owned[OwnedResource](
    resource: OwnedResource | None, user: User, *, owner_field: str
) -> OwnedResource:
    """Hide missing and foreign owned resources using the same 404 response."""
    if resource is None or getattr(resource, owner_field) != user.id:
        raise APIError(404, "NOT_FOUND", "Resource not found")
    return resource
