"""Tests for issue #32: the bordered field box (`<dl class="card">`) on the
contact detail page must NOT render when there are no fields to show -- a bare
group (no phones/emails/urls/addresses/related/bday/note) otherwise renders an
empty bordered box. A contact (or group) that does have fields must still show
the box.

Uses an in-process TestClient with data seeded directly into ContactStore --
no live CardDAV server needed."""

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings

# Bare group: KIND=group, no contact fields at all.
BARE_GROUP_CARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:group-empty\r\n"
    "FN:Empties\r\nN:Empties;;;;\r\n"
    "X-ADDRESSBOOKSERVER-KIND:group\r\n"
    "END:VCARD\r\n"
)

# Contact carrying a single field (email) -- the box must still render.
CONTACT_WITH_FIELD_CARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:person-1\r\n"
    "FN:Jane Person\r\nN:Person;Jane;;;\r\n"
    "EMAIL;TYPE=INTERNET:jane@example.com\r\n"
    "END:VCARD\r\n"
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
    store.upsert("tester", "/addressbook/", "/addressbook/group-empty.vcf", "etag-1", BARE_GROUP_CARD)
    store.upsert("tester", "/addressbook/", "/addressbook/person-1.vcf", "etag-2", CONTACT_WITH_FIELD_CARD)
    sid = app.state.sessions.create("tester", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


def test_bare_group_omits_field_box(client):
    resp = client.get("/contacts/group-empty")
    assert resp.status_code == 200
    assert 'class="card"' not in resp.text


def test_contact_with_field_shows_field_box(client):
    resp = client.get("/contacts/person-1")
    assert resp.status_code == 200
    assert 'class="card"' in resp.text
    assert "jane@example.com" in resp.text
