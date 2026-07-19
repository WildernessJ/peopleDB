"""Template-level checks for photo preview + crop on the contact form
(issues #14, #17): the avatar-spot preview and crop-surface markup hooks
render on both the create and edit forms, and the crop UI wires up to the
existing photo file input without adding new server-facing fields.

Uses an in-process TestClient with a session created directly against
SessionStore -- no live CardDAV server needed, since these are GET routes
that never call out to DAV."""

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings

CARD_WITH_PHOTO = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:photo-1\r\n"
    "FN:Photo Person\r\nN:Photo;Iris;;;\r\n"
    "PHOTO;ENCODING=b;TYPE=JPEG:dG90YWxseS1hLWpwZWc=\r\nEND:VCARD\r\n"
)

CARD_NO_PHOTO = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:noph-1\r\n"
    "FN:No Photo\r\nN:Photo;No;;;\r\nEND:VCARD\r\n"
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
    sid = app.state.sessions.create("tester", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


def test_new_contact_form_has_preview_and_crop_hooks(client):
    resp = client.get("/contacts/new")
    assert resp.status_code == 200
    body = resp.text
    assert 'id="photo-input"' in body
    assert 'id="photo-preview-wrap"' in body
    assert 'id="photo-crop-canvas"' in body
    assert 'id="photo-crop-stage"' in body


def test_edit_form_without_photo_has_preview_and_crop_hooks(client):
    resp = client.get("/contacts/noph-1/edit")
    assert resp.status_code == 200
    body = resp.text
    assert 'id="photo-input"' in body
    assert 'id="photo-preview-wrap"' in body
    assert 'id="photo-crop-canvas"' in body


def test_edit_form_with_existing_photo_still_renders_current_avatar(client):
    resp = client.get("/contacts/photo-1/edit")
    assert resp.status_code == 200
    body = resp.text
    # The existing avatar image (server photo route) must still render --
    # the crop UI only takes over once a *new* file is chosen client-side.
    assert 'src="/contacts/photo-1/photo"' in body
    assert 'id="photo-crop-canvas"' in body
    assert 'id="photo-remove"' in body


def test_no_server_side_photo_fields_added(client):
    # Progressive enhancement: no new server-dependent form field names beyond
    # the existing "photo" file input and "photo_remove" checkbox.
    resp = client.get("/contacts/photo-1/edit")
    body = resp.text
    assert 'name="photo"' in body
    assert 'name="photo_remove"' in body
    # crop export re-uses the same "photo" input rather than adding a sibling
    # hidden field for crop coordinates (out of scope per spec).
    assert "name=\"crop" not in body
