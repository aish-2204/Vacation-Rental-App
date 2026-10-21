import os

import pytest

from app.core.config import get_settings
from app.database.safety import validate_seed_target, validate_test_database_url


def test_development_and_test_database_urls_are_distinct(development_database_url) -> None:
    settings = get_settings()
    test_url = os.environ["TEST_DATABASE_URL"]
    assert development_database_url != test_url
    assert settings.database_url == test_url
    validate_test_database_url(test_url, development_database_url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@127.0.0.1:55432/vacation_rental_dev",
        "postgresql+asyncpg://u:p@db.example.com/vacation_rental_test",
        "postgresql+asyncpg://u:p@127.0.0.1/production",
        "sqlite+aiosqlite:///vacation_rental_test",
    ],
)
def test_unsafe_test_targets_are_rejected(url, development_database_url) -> None:
    with pytest.raises(ValueError):
        validate_test_database_url(url, development_database_url)


@pytest.mark.parametrize(
    "url,env",
    [
        ("postgresql+asyncpg://u:p@127.0.0.1/vacation_rental_test", "development"),
        ("postgresql+asyncpg://u:p@127.0.0.1/vacation_rental_dev", "production"),
        ("postgresql+asyncpg://u:p@db.example.com/vacation_rental_dev", "development"),
    ],
)
def test_seed_rejects_nonlocal_or_nondevelopment_targets(url, env) -> None:
    with pytest.raises(ValueError):
        validate_seed_target(url, env)
