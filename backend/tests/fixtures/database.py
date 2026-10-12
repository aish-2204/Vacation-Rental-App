import os
from pathlib import Path
from uuid import uuid4

import pytest_asyncio
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from seed.demo import seed_demo

BACKEND = Path(__file__).resolve().parents[2]


def migration_config(connection, schema: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.attributes["connection"] = connection
    config.attributes["version_table_schema"] = schema
    return config


@pytest_asyncio.fixture
async def database_engine():
    # A new schema is migrated from zero for EVERY test. The root conftest
    # validates the local _test URL before this module can be imported.
    schema = f"test_{uuid4().hex}"
    url = os.environ["TEST_DATABASE_URL"]
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": f"{schema},public", "timezone": "UTC"}},
    )
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: command.upgrade(migration_config(sync, schema), "head")
            )
        yield engine, schema
    finally:
        await engine.dispose()
        # Only this fixture's generated UUID schema is removed. No public tables,
        # database, container, or volume are reset or deleted.
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest_asyncio.fixture
async def db(database_engine):
    engine, _ = database_engine
    async with AsyncSession(engine, expire_on_commit=False) as session:
        async with session.begin():
            await seed_demo(session)
        yield session
