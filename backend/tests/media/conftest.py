import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.session import get_session
from app.main import create_app
from app.storage import get_storage
from app.storage.local import LocalDiskStorage


@pytest.fixture
def storage(tmp_path):
    settings = get_settings()
    return LocalDiskStorage(
        root=tmp_path / "media",
        public_base_url=settings.media_public_base_url,
        upload_base_url="http://test/api/v1/uploads",
        signing_key=settings.jwt_secret_key.get_secret_value(),
    )


@pytest_asyncio.fixture
async def api(db, database_engine, storage):
    engine, _ = database_engine
    application = create_app()

    async def isolated_session():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    application.dependency_overrides[get_session] = isolated_session
    application.dependency_overrides[get_storage] = lambda: storage
    async with AsyncClient(transport=ASGITransport(application), base_url="http://test") as client:
        yield client
