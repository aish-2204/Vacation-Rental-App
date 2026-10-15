import os

import pytest

from app.core.config import Settings, get_settings
from app.database.safety import validate_test_database_url

pytest_plugins = ["tests.fixtures.database"]

DEVELOPMENT_DATABASE_URL = Settings().database_url
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError("TEST_DATABASE_URL must be explicitly set for backend tests")
validate_test_database_url(TEST_DATABASE_URL, DEVELOPMENT_DATABASE_URL)
# Set this BEFORE importing the application or engine; no test route can inherit
# the development database, even if a dependency override is accidentally omitted.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_ENV"] = "test"
get_settings.cache_clear()


@pytest.fixture
def development_database_url() -> str:
    return DEVELOPMENT_DATABASE_URL
