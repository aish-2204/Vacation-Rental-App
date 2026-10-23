import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.main import create_app


@pytest_asyncio.fixture
async def api(db, database_engine):
    engine, _ = database_engine
    application = create_app()

    async def isolated_session():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    application.dependency_overrides[get_session] = isolated_session
    async with AsyncClient(transport=ASGITransport(application), base_url="http://test") as client:
        yield client
