from collections.abc import Callable
from datetime import UTC, datetime


def utc_now() -> datetime:
    """Request clock, overridable in boundary/DST tests."""
    return datetime.now(UTC)


def get_clock() -> Callable[[], datetime]:
    """Defer time-sensitive decisions until after inventory locks are acquired."""
    return utc_now
