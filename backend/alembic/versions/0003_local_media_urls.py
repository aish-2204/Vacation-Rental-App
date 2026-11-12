"""Allow loopback local-storage media URLs (development/test uploads)."""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_local_media_urls"
down_revision: str | Sequence[str] | None = "0002_listing_removal_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HTTPS_ONLY = r"^https://[^/[:space:]]+(/[^[:space:]]*)?$"
# Loopback HTTP cannot be served publicly, so production still effectively stores HTTPS only;
# the API additionally rejects non-HTTPS URLs outside APP_ENV=development/test.
HTTPS_OR_LOCAL_MEDIA = r"^(https://[^/[:space:]]+(/[^[:space:]]*)?|http://(127\.0\.0\.1|localhost)(:[0-9]+)?/media/[^[:space:]]+)$"


def _replace(pattern: str) -> None:
    op.drop_constraint(op.f("ck_listing_media_https_url"), "listing_media", type_="check")
    op.create_check_constraint(
        op.f("ck_listing_media_https_url"), "listing_media", f"url ~ '{pattern}'"
    )


def upgrade() -> None:
    _replace(HTTPS_OR_LOCAL_MEDIA)


def downgrade() -> None:
    # Fails (and rolls back) while local HTTP media rows exist; remove them deliberately first.
    _replace(HTTPS_ONLY)
