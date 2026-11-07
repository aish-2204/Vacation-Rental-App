from datetime import timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import get_clock, utc_now
from app.database.session import get_session
from app.main import create_app
from app.models import User
from seed.demo import demo_id


@pytest_asyncio.fixture
async def clock(db):
    return [(await db.get(User, demo_id("user/0"))).created_at + timedelta(days=200)]


@pytest_asyncio.fixture
async def api(db, database_engine, clock):
    engine, _ = database_engine
    application = create_app()

    async def isolated_session():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    application.dependency_overrides[get_session] = isolated_session
    application.dependency_overrides[utc_now] = lambda: clock[0]
    application.dependency_overrides[get_clock] = lambda: lambda: clock[0]
    async with AsyncClient(transport=ASGITransport(application), base_url="http://test") as client:
        yield client
