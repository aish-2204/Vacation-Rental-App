import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_admin, require_customer, require_host
from app.database.session import get_session
from app.main import create_app
from app.schemas.auth import UserResponse


@pytest_asyncio.fixture
async def api(db, database_engine):
    engine, _ = database_engine
    application = create_app()

    async def isolated_session():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    application.dependency_overrides[get_session] = isolated_session
    # Role gates are tested without adding future product endpoints to production.
    for role, dependency in (
        ("customer", require_customer),
        ("host", require_host),
        ("admin", require_admin),
    ):

        async def protected(user=Depends(dependency)):
            return {"success": True, "data": UserResponse.model_validate(user)}

        application.add_api_route(
            f"/test/{role}", protected, methods=["GET"], include_in_schema=False
        )
    async with AsyncClient(
        transport=ASGITransport(application), base_url="http://test", follow_redirects=True
    ) as client:
        yield client
