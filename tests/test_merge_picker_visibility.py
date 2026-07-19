"""Tests for issue #30: the "Merge with…" picker on the contact detail page
must NOT render on a group's own detail page (group merges are rejected
downstream, so the control is a dead end there), but must still render on an
ordinary contact's detail page.

Uses an in-process TestClient with data seeded directly into ContactStore --
no live CardDAV server needed."""

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings

CONTACT_CARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:person-1\r\n"
    "FN:Jane Person\r\nN:Person;Jane;;;\r\n"
    "END:VCARD\r\n"
)

GROUP_CARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:group-family\r\n"
    "FN:Family\r\nN:Family;;;;\r\n"
    "X-ADDRESSBOOKSERVER-KIND:group\r\n"
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
    store.upsert("tester", "/addressbook/", "/addressbook/person-1.vcf", "etag-1", CONTACT_CARD)
    store.upsert("tester", "/addressbook/", "/addressbook/group-family.vcf", "etag-2", GROUP_CARD)
    sid = app.state.sessions.create("tester", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


def test_contact_detail_shows_merge_picker(client):
    resp = client.get("/contacts/person-1")
    assert resp.status_code == 200
    assert 'class="merge-picker"' in resp.text
    assert "Merge with" in resp.text


def test_group_detail_hides_merge_picker(client):
    resp = client.get("/contacts/group-family")
    assert resp.status_code == 200
    assert 'class="merge-picker"' not in resp.text
    assert "Merge with" not in resp.text
