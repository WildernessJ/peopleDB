"""Tests for contact photo display (issue #9): the /contacts/{uid}/photo route
and the avatar/initials rendering in detail.html and _contacts.html.

Uses an in-process TestClient with a session created directly against
SessionStore and data seeded directly into ContactStore -- no live CardDAV
server needed, since none of these routes ever call out to DAV."""

import base64

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings

JPEG_BYTES = b"totally-a-jpeg"
JPEG_B64 = base64.b64encode(JPEG_BYTES).decode()

CARD_WITH_PHOTO = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-1\r\n"
    "FN:Photo Person\r\nN:Photo;Iris;;;\r\n"
    f"PHOTO;ENCODING=b;TYPE=JPEG:{JPEG_B64}\r\nEND:VCARD\r\n"
)

CARD_NO_PHOTO = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:noph-1\r\n"
    "FN:No Photo\r\nN:Photo;No;;;\r\nEND:VCARD\r\n"
)

CARD_URI_PHOTO = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:uriph-1\r\n"
    "FN:Uri Person\r\nN:Person;Uri;;;\r\n"
    "PHOTO;VALUE=uri:https://example.com/photo.jpg\r\nEND:VCARD\r\n"
)

CARD_BAD_PHOTO = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:badph-1\r\n"
    "FN:Bad Photo\r\nN:Photo;Bad;;;\r\n"
    "PHOTO;ENCODING=b;TYPE=JPEG:not-valid-base64!!!\r\nEND:VCARD\r\n"
)


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        dav_url="http://unused.invalid",
        secret_key="",
        db_path=str(tmp_path / "cache.db"),
        secure_cookies=False,
    )
    return create_app(settings)


@pytest.fixture
def client(app):
    store = app.state.store
    store.upsert("tester", "/addressbook/", "/addressbook/photo-1.vcf", "etag-1", CARD_WITH_PHOTO)
    store.upsert("tester", "/addressbook/", "/addressbook/noph-1.vcf", "etag-2", CARD_NO_PHOTO)
    store.upsert("tester", "/addressbook/", "/addressbook/uriph-1.vcf", "etag-3", CARD_URI_PHOTO)
    store.upsert("tester", "/addressbook/", "/addressbook/badph-1.vcf", "etag-4", CARD_BAD_PHOTO)
    sid = app.state.sessions.create("tester", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


# -- GET /contacts/{uid}/photo -------------------------------------------------


def test_photo_route_returns_bytes_and_media_type(client):
    resp = client.get("/contacts/photo-1/photo")
    assert resp.status_code == 200
    assert resp.content == JPEG_BYTES
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["cache-control"] == "private, max-age=3600"
    assert resp.headers["etag"] == "etag-1"


def test_photo_route_returns_304_on_matching_if_none_match(client):
    resp = client.get("/contacts/photo-1/photo", headers={"If-None-Match": "etag-1"})
    assert resp.status_code == 304
    # RFC 7232: a 304 must repeat ETag/Cache-Control, not omit them.
    assert resp.headers["etag"] == "etag-1"
    assert resp.headers["cache-control"] == "private, max-age=3600"


def test_photo_route_returns_304_on_weak_if_none_match(client):
    resp = client.get("/contacts/photo-1/photo", headers={"If-None-Match": 'W/"etag-1"'})
    assert resp.status_code == 304


def test_photo_route_returns_304_on_multi_value_if_none_match(client):
    resp = client.get(
        "/contacts/photo-1/photo", headers={"If-None-Match": '"other-etag", etag-1'}
    )
    assert resp.status_code == 304


def test_photo_route_404_when_contact_has_no_photo(client):
    resp = client.get("/contacts/noph-1/photo")
    assert resp.status_code == 404


def test_photo_route_404_when_photo_is_uri_only(client):
    resp = client.get("/contacts/uriph-1/photo")
    assert resp.status_code == 404


def test_photo_route_404_when_photo_base64_was_invalid(client):
    resp = client.get("/contacts/badph-1/photo")
    assert resp.status_code == 404


def test_photo_route_404_for_unknown_uid(client):
    resp = client.get("/contacts/no-such-uid/photo")
    assert resp.status_code == 404


def test_photo_route_requires_auth(app):
    app.state.store.upsert(
        "tester", "/addressbook/", "/addressbook/photo-1.vcf", "etag-1", CARD_WITH_PHOTO
    )
    anon = TestClient(app, follow_redirects=False)
    resp = anon.get("/contacts/photo-1/photo")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


# -- template rendering --------------------------------------------------------


def test_detail_page_embeds_photo_img_for_embedded_photo(client):
    resp = client.get("/contacts/photo-1")
    assert resp.status_code == 200
    assert 'src="/contacts/photo-1/photo"' in resp.text
    assert 'alt="Photo Person"' in resp.text


def test_detail_page_embeds_external_uri_for_uri_photo(client):
    resp = client.get("/contacts/uriph-1")
    assert resp.status_code == 200
    assert 'src="https://example.com/photo.jpg"' in resp.text


def test_detail_page_shows_initials_fallback_when_no_photo(client):
    resp = client.get("/contacts/noph-1")
    assert resp.status_code == 200
    assert "NP" in resp.text  # given "No" + family "Photo"


def test_contact_list_shows_avatar_for_photo_and_initials_for_none(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'src="/contacts/photo-1/photo"' in resp.text
    assert "NP" in resp.text
