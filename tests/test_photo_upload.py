"""Route-level tests for photo upload/editing (issue #11): validation-error
paths that short-circuit before any DAV call, so they run against a seeded
in-process store with no live CardDAV server (same pattern as test_photos.py).
Success paths (upload actually lands on the server, folded correctly; remove
actually clears PHOTO) need a real DAV round trip and live in
test_web_live.py."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from peopledb.app import create_app
from peopledb.config import Settings
from peopledb.photos import MAX_UPLOAD_BYTES

CARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:upl-1\r\n"
    "FN:Upload Person\r\nN:Person;Upload;;;\r\nEND:VCARD\r\n"
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
    store.upsert("tester", "/addressbook/", "/addressbook/upl-1.vcf", "etag-1", CARD)
    sid = app.state.sessions.create("tester", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


def _base_edit_fields(given="Upload"):
    return {
        "given": given, "family": "Person", "org": "", "note": "", "bday": "",
        "email_label": [], "email_value": [],
        "phone_label": [], "phone_value": [],
        "url_label": [], "url_value": [],
        "related_label": [], "related_value": [],
        "etag": "etag-1",
    }


def _base_create_fields(given="Nina"):
    return {
        "given": given, "family": "Novak", "org": "", "note": "", "bday": "",
        "email_label": [], "email_value": [],
        "phone_label": [], "phone_value": [],
        "url_label": [], "url_value": [],
        "related_label": [], "related_value": [],
    }


def test_update_contact_rejects_oversize_photo_and_preserves_other_edits(app, client):
    oversize = b"x" * (MAX_UPLOAD_BYTES + 1)
    resp = client.post(
        "/contacts/upl-1",
        data=_base_edit_fields(given="Changed"),
        files={"photo": ("big.jpg", oversize, "image/jpeg")},
    )
    assert resp.status_code == 400
    assert "too large" in resp.text.lower()
    # the user's other (valid) edit is not silently discarded from the re-rendered form
    assert 'value="Changed"' in resp.text
    # nothing was written -- store still has the original card, untouched
    rec = app.state.store.get_by_uid("tester", "upl-1")
    assert rec.etag == "etag-1"


def test_update_contact_rejects_corrupt_photo(app, client):
    resp = client.post(
        "/contacts/upl-1",
        data=_base_edit_fields(given="Changed"),
        files={"photo": ("bad.jpg", b"not-an-image", "image/jpeg")},
    )
    assert resp.status_code == 400
    assert "corrupt" in resp.text.lower() or "recognizable" in resp.text.lower()
    assert 'value="Changed"' in resp.text


def test_update_contact_rejects_non_image_upload(app, client):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(buf, format="BMP")
    resp = client.post(
        "/contacts/upl-1",
        data=_base_edit_fields(given="Changed"),
        files={"photo": ("pic.bmp", buf.getvalue(), "image/bmp")},
    )
    assert resp.status_code == 400
    assert 'value="Changed"' in resp.text


def test_update_contact_form_error_does_not_500_on_no_op_reload(app, client):
    # No file at all -- must behave exactly like the existing (photo-less) edit path.
    resp = client.post("/contacts/upl-1", data=_base_edit_fields(given="Renamed"))
    # unreachable DAV server -> the write itself fails loudly (503), but that's
    # the existing global handler's job, not a photo-processing 500.
    assert resp.status_code == 503


def test_create_contact_rejects_oversize_photo_and_preserves_entered_fields(app, client):
    oversize = b"x" * (MAX_UPLOAD_BYTES + 1)
    resp = client.post(
        "/contacts",
        data=_base_create_fields(given="Nina"),
        files={"photo": ("big.jpg", oversize, "image/jpeg")},
    )
    assert resp.status_code == 400
    assert "too large" in resp.text.lower()
    assert 'value="Nina"' in resp.text
    # nothing was created
    assert app.state.store.get_by_uid("tester", "upl-1") is not None  # unrelated existing contact
    assert all(c.contact.formatted_name != "Nina Novak" for c in app.state.store.list_contacts("tester"))


def test_create_contact_rejects_corrupt_photo(app, client):
    resp = client.post(
        "/contacts",
        data=_base_create_fields(given="Nina"),
        files={"photo": ("bad.jpg", b"not-an-image", "image/jpeg")},
    )
    assert resp.status_code == 400
    assert 'value="Nina"' in resp.text


def test_edit_form_shows_remove_checkbox_only_when_contact_has_photo(app, client):
    import base64

    photo_b64 = base64.b64encode(b"fake-jpeg").decode()
    card_with_photo = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:upl-photo\r\nFN:Has Photo\r\nN:Photo;Has;;;\r\n"
        f"PHOTO;ENCODING=b;TYPE=JPEG:{photo_b64}\r\nEND:VCARD\r\n"
    )
    app.state.store.upsert(
        "tester", "/addressbook/", "/addressbook/upl-photo.vcf", "etag-p", card_with_photo
    )
    resp = client.get("/contacts/upl-photo/edit")
    assert resp.status_code == 200
    assert 'name="photo_remove"' in resp.text

    resp_none = client.get("/contacts/upl-1/edit")
    assert resp_none.status_code == 200
    assert 'name="photo_remove"' not in resp_none.text


def test_new_contact_form_has_no_remove_checkbox(client):
    resp = client.get("/contacts/new")
    assert resp.status_code == 200
    assert 'name="photo_remove"' not in resp.text
    assert 'enctype="multipart/form-data"' in resp.text


def test_update_contact_rejects_oversize_content_length_before_parsing_form(app, client):
    # A fake Content-Length far past the cap must be turned away without ever
    # calling request.form() on the (much smaller) actual body -- proven by
    # the store staying untouched, same as the post-hoc oversize-photo test.
    huge = MAX_UPLOAD_BYTES + 50 * 1024 * 1024
    resp = client.post(
        "/contacts/upl-1",
        data=_base_edit_fields(given="Changed"),
        headers={"content-length": str(huge)},
    )
    assert resp.status_code == 413
    assert "too large" in resp.text.lower()
    rec = app.state.store.get_by_uid("tester", "upl-1")
    assert rec.etag == "etag-1"


def test_create_contact_rejects_oversize_content_length_before_parsing_form(app, client):
    huge = MAX_UPLOAD_BYTES + 50 * 1024 * 1024
    resp = client.post(
        "/contacts",
        data=_base_create_fields(given="Nina"),
        headers={"content-length": str(huge)},
    )
    assert resp.status_code == 413
    assert "too large" in resp.text.lower()
    assert all(c.contact.formatted_name != "Nina Novak" for c in app.state.store.list_contacts("tester"))


def test_update_contact_normal_content_length_is_not_rejected_by_guard(app, client):
    # A small, honest Content-Length must sail past the guard -- only the
    # unreachable DAV server (503) should stop this request, not the guard.
    resp = client.post("/contacts/upl-1", data=_base_edit_fields(given="Renamed"))
    assert resp.status_code == 503
