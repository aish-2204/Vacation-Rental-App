from sqlalchemy.engine import URL, make_url

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def validate_local_url(raw_url: str) -> URL:
    url = make_url(raw_url)
    if url.drivername != "postgresql+asyncpg" or url.host not in LOCAL_HOSTS:
        raise ValueError("This command requires a local PostgreSQL asyncpg URL")
    if not url.database:
        raise ValueError("A database name is required")
    return url


def validate_test_database_url(raw_url: str, development_url: str) -> URL:
    url = validate_local_url(raw_url)
    development = make_url(development_url)
    if not url.database.endswith("_test") or url.database == development.database:
        raise ValueError("TEST_DATABASE_URL must name a separate local database ending in _test")
    return url


def validate_seed_target(raw_url: str, app_env: str) -> URL:
    url = validate_local_url(raw_url)
    if app_env != "development" or url.database != "vacation_rental_dev":
        raise ValueError("Demo seed is restricted to development/vacation_rental_dev on localhost")
    return url
