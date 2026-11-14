from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import get_settings
from app.storage.local import LocalDiskStorage
from seed.demo import demo_id
from tests.listings.helpers import auth, path

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2048
LISTING = demo_id("listing/0")


async def ticket(api, content_type="image/jpeg", size=len(JPEG), index=0, role="host1"):
    return await api.post(
        f"{path(index)}/media/upload-url",
        headers=auth(role),
        json={"content_type": content_type, "size_bytes": size},
    )


async def upload(api, data, content_type="image/jpeg", body=JPEG):
    url = data["upload_url"].removeprefix("http://test")
    return await api.put(
        url, content=body, headers={**data["headers"], "Content-Type": content_type}
    )


async def uploaded(api, **kwargs):
    response = await ticket(api, **kwargs)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert (await upload(api, data)).status_code == 201
    return data


async def test_presigned_upload_then_add_and_delete_media(api, storage):
    response = await ticket(api)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["method"] == "PUT"
    assert data["media_type"] == "IMAGE"
    assert data["headers"] == {"Content-Type": "image/jpeg"}
    assert data["public_url"].startswith(
        f"{get_settings().media_public_base_url}/listings/{LISTING}/"
    )
    assert data["public_url"].endswith(".jpg")

    put = await upload(api, data)
    assert put.status_code == 201, put.text
    assert put.json()["data"] == {"public_url": data["public_url"], "size_bytes": len(JPEG)}
    key = storage.key_for_url(data["public_url"])
    assert storage.path_for(key).read_bytes() == JPEG

    added = await api.post(
        f"{path()}/media", headers=auth(), json={"url": data["public_url"], "caption": "Uploaded"}
    )
    assert added.status_code == 201, added.text
    media_id = added.json()["data"]["id"]
    listing = (await api.get(path(), headers=auth())).json()["data"]
    assert data["public_url"] in [item["url"] for item in listing["media"]]

    deleted = await api.delete(f"{path()}/media/{media_id}", headers=auth())
    assert deleted.status_code == 200, deleted.text
    assert not storage.path_for(key).exists()


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"content_type": "image/gif", "size_bytes": 10}, 422, "VALIDATION_ERROR"),
        ({"content_type": "image/jpeg", "size_bytes": 0}, 422, "VALIDATION_ERROR"),
        ({"content_type": "image/jpeg", "size_bytes": 10 * 1024 * 1024 + 1}, 422, "FILE_TOO_LARGE"),
        ({"content_type": "video/mp4", "size_bytes": 200 * 1024 * 1024 + 1}, 422, "FILE_TOO_LARGE"),
    ],
)
async def test_upload_url_validates_type_and_size(api, body, status, code):
    response = await api.post(f"{path()}/media/upload-url", headers=auth(), json=body)
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize(("role", "status"), [("host2", 404), ("customer", 403), ("admin", 403)])
async def test_upload_url_requires_listing_owner(api, role, status):
    assert (await ticket(api, role=role)).status_code == status


async def test_upload_receiver_enforces_token_type_and_size(api, storage):
    data = (await ticket(api)).json()["data"]
    wrong_type = await upload(api, data, content_type="image/png")
    assert wrong_type.status_code == 415
    too_big = await upload(api, data, body=JPEG + b"x")
    assert too_big.status_code == 413
    empty = await upload(api, data, body=b"")
    assert empty.status_code == 422
    assert not storage.path_for(storage.key_for_url(data["public_url"])).exists()

    forged = LocalDiskStorage(
        storage.root, storage.public_base_url, "http://test/api/v1/uploads", "x" * 48
    ).create_upload(
        f"listings/{LISTING}/forged.jpg",
        "image/jpeg",
        100,
        datetime.now(UTC) + timedelta(minutes=5),
    )
    for url in (forged.upload_url, "http://test/api/v1/uploads/not-a-token"):
        response = await api.put(
            url.removeprefix("http://test"), content=JPEG, headers=data["headers"]
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "UPLOAD_URL_INVALID"

    expired = storage.create_upload(
        f"listings/{LISTING}/expired.jpg",
        "image/jpeg",
        100,
        datetime.now(UTC) - timedelta(seconds=1),
    )
    response = await api.put(
        expired.upload_url.removeprefix("http://test"), content=b"x", headers=expired.headers
    )
    assert response.status_code == 403


async def test_upload_token_is_not_an_access_token(api):
    data = (await ticket(api)).json()["data"]
    token = data["upload_url"].rsplit("/", 1)[1]
    response = await api.get(path(), headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_add_media_rejects_missing_or_foreign_uploads(api, storage):
    data = (await ticket(api)).json()["data"]
    missing = await api.post(f"{path()}/media", headers=auth(), json={"url": data["public_url"]})
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "INVALID_MEDIA_UPLOAD"

    other = await uploaded(api)
    foreign = other["public_url"].replace(str(LISTING), str(demo_id("listing/1")))
    response = await api.post(f"{path()}/media", headers=auth(), json={"url": foreign})
    assert response.status_code == 422


async def test_add_media_checks_uploaded_type(api):
    data = await uploaded(api)
    response = await api.post(
        f"{path()}/media",
        headers=auth(),
        json={"url": data["public_url"], "media_type": "VIDEO"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_MEDIA_UPLOAD"


async def test_other_host_cannot_attach_upload(api):
    data = await uploaded(api)
    response = await api.post(
        f"{path()}/media", headers=auth("host2"), json={"url": data["public_url"]}
    )
    assert response.status_code == 404


async def test_replacing_media_url_deletes_unused_upload(api, storage):
    first = await uploaded(api)
    second = await uploaded(api)
    media_id = (
        await api.post(f"{path()}/media", headers=auth(), json={"url": first["public_url"]})
    ).json()["data"]["id"]
    patched = await api.patch(
        f"{path()}/media/{media_id}", headers=auth(), json={"url": second["public_url"]}
    )
    assert patched.status_code == 200, patched.text
    assert not storage.path_for(storage.key_for_url(first["public_url"])).exists()
    assert storage.path_for(storage.key_for_url(second["public_url"])).exists()


async def test_external_https_urls_still_work_and_http_elsewhere_is_rejected(api):
    ok = await api.post(
        f"{path()}/media", headers=auth(), json={"url": "https://example.test/new.jpg"}
    )
    assert ok.status_code == 201, ok.text
    bad = await api.post(
        f"{path()}/media", headers=auth(), json={"url": "http://example.test/new.jpg"}
    )
    assert bad.status_code == 422
