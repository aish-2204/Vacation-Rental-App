"""Host listing media: presigned uploads to object storage plus media records.

Flow: `create_media_upload` issues a one-object upload ticket → the browser
uploads the file directly to storage → `add_media` verifies the stored object
(exists, belongs to this listing, real type/size within limits) and saves its
URL. External HTTPS URLs (e.g. seed placeholders) remain accepted as before.
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import APIError
from app.models import ListingMedia
from app.models.enums import MediaType
from app.schemas.listings import (
    MEDIA_CONTENT_TYPES,
    MediaInput,
    MediaPatch,
    MediaResponse,
    MediaUploadRequest,
    MediaUploadResponse,
)
from app.services import listings
from app.storage import ObjectStorage

logger = logging.getLogger(__name__)
MAX_MEDIA_PER_LISTING = 30


def max_bytes_for(media_type: MediaType) -> int:
    settings = get_settings()
    if media_type == MediaType.VIDEO:
        return settings.media_max_video_bytes
    return settings.media_max_image_bytes


def invalid_upload(message: str, field: str = "url", code: str = "INVALID_MEDIA_UPLOAD"):
    return APIError(422, code, message, details=[{"field": field, "message": message}])


async def media_count(session: AsyncSession, listing_id: UUID) -> int:
    return await session.scalar(
        select(func.count()).select_from(ListingMedia).where(ListingMedia.listing_id == listing_id)
    )


async def verify_stored_media(
    storage: ObjectStorage, listing_id: UUID, url: str, media_type: MediaType
) -> None:
    """Check an uploaded object before saving it. External URLs are not checked."""
    key = storage.key_for_url(url)
    if key is None:
        return
    if not key.startswith(f"listings/{listing_id}/"):
        raise invalid_upload("This uploaded file belongs to a different listing")
    stored = await storage.inspect(key)
    if stored is None:
        raise invalid_upload("Uploaded file not found; upload it before saving the media")
    allowed = MEDIA_CONTENT_TYPES.get(stored.content_type.split(";")[0].strip().lower())
    if allowed is None or allowed[1] != media_type:
        raise invalid_upload(f"Uploaded file is not a supported {media_type.value.lower()}")
    if stored.size_bytes > max_bytes_for(media_type):
        await storage.delete(key)
        raise invalid_upload("Uploaded file is larger than allowed", code="FILE_TOO_LARGE")


async def delete_unused_object(session: AsyncSession, storage: ObjectStorage, url: str) -> None:
    """Best-effort cleanup after commit; never fails the request."""
    key = storage.key_for_url(url)
    if key is None:
        return
    still_used = await session.scalar(select(ListingMedia.id).where(ListingMedia.url == url))
    if still_used is not None:
        return
    try:
        await storage.delete(key)
    except Exception:  # noqa: BLE001 - storage outage must not undo a committed delete
        logger.warning("Could not delete stored media object %s", key)


async def add_media(
    session, storage: ObjectStorage, host_id, listing_id, request: MediaInput
) -> MediaResponse:
    if storage.key_for_url(request.url) is not None:
        # Ownership first (404 reveals nothing about storage), then verify the object
        # BEFORE taking the listing lock: no network I/O while holding the lock.
        await listings.get_listing(session, listing_id, host_id=host_id)
        await verify_stored_media(storage, listing_id, request.url, request.media_type)
    listing = await listings.lock_listing(session, listing_id, host_id=host_id)
    listings.ensure_mutable(listing)
    if await media_count(session, listing.id) >= MAX_MEDIA_PER_LISTING:
        raise listings.conflict(f"A listing supports at most {MAX_MEDIA_PER_LISTING} media URLs")
    media = ListingMedia(listing_id=listing.id, **request.model_dump())
    session.add(media)
    listings.host_edit(listing, material=True)
    await listings.finish(session, listing)
    return MediaResponse.model_validate(media)


async def patch_media(
    session, storage: ObjectStorage, host_id, listing_id, media_id, request: MediaPatch
) -> MediaResponse:
    listing = await listings.lock_listing(session, listing_id, host_id=host_id)
    listings.ensure_mutable(listing)
    media = await listings.nested_row(session, ListingMedia, listing.id, media_id)
    values = request.model_dump(exclude_unset=True)
    old_url = media.url
    if "url" in values or "media_type" in values:
        await verify_stored_media(
            storage,
            listing.id,
            values.get("url", media.url),
            values.get("media_type", media.media_type),
        )
    changed = False
    for field, value in values.items():
        if getattr(media, field) != value:
            setattr(media, field, value)
            changed = True
    listings.host_edit(listing, material=True, changed=changed)
    await listings.finish(session, listing)
    if media.url != old_url:
        await delete_unused_object(session, storage, old_url)
    return MediaResponse.model_validate(media)


async def delete_media(session, storage: ObjectStorage, host_id, listing_id, media_id):
    listing = await listings.lock_listing(session, listing_id, host_id=host_id)
    listings.ensure_mutable(listing)
    media = await listings.nested_row(session, ListingMedia, listing.id, media_id)
    url = media.url
    await session.delete(media)
    listings.host_edit(listing, material=True)
    await listings.finish(session, listing)
    await delete_unused_object(session, storage, url)
