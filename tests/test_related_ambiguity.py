"""Tests for issue #2: contact_detail resolving X-ABRELATEDNAMES to a uid via a
formatted_name -> uid dict silently clobbers when two contacts share a display
name, so a relationship link can point at the wrong person.

Fix: resolve name -> uid only when exactly one contact matches; render plain
text (no link) when 0 or >1 contacts share that name.

Uses an in-process TestClient with a session created directly against
SessionStore and data seeded directly into ContactStore -- no live CardDAV
server needed, following the tests/test_photos.py fixture pattern."""

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings

CARD_CHRIS_1 = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:chris-1\r\n"
    "FN:Chris Smith\r\nN:Smith;Chris;;;\r\nEND:VCARD\r\n"
)

CARD_CHRIS_2 = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:chris-2\r\n"
    "FN:Chris Smith\r\nN:Smith;Chris;;;\r\nEND:VCARD\r\n"
)

CARD_RELATED_TO_CHRIS = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:related-1\r\n"
    "FN:Related Person\r\nN:Person;Related;;;\r\n"
    "X-ABRELATEDNAMES:Chris Smith\r\nEND:VCARD\r\n"
)

CARD_UNIQUE_NAME = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:unique-1\r\n"
    "FN:Unique Person\r\nN:Person;Unique;;;\r\nEND:VCARD\r\n"
)

CARD_RELATED_TO_UNIQUE = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:related-2\r\n"
    "FN:Related Person Two\r\nN:Two;Related;;;\r\n"
    "X-ABRELATEDNAMES:Unique Person\r\nEND:VCARD\r\n"
)

CARD_RELATED_TO_NOBODY = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:related-3\r\n"
    "FN:Related Person Three\r\nN:Three;Related;;;\r\n"
    "X-ABRELATEDNAMES:Nobody Here\r\nEND:VCARD\r\n"
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
    store.upsert("tester", "/addressbook/", "/addressbook/chris-1.vcf", "etag-1", CARD_CHRIS_1)
    store.upsert("tester", "/addressbook/", "/addressbook/chris-2.vcf", "etag-2", CARD_CHRIS_2)
    store.upsert(
        "tester",
        "/addressbook/",
        "/addressbook/related-1.vcf",
        "etag-3",
        CARD_RELATED_TO_CHRIS,
    )
    store.upsert(
        "tester", "/addressbook/", "/addressbook/unique-1.vcf", "etag-4", CARD_UNIQUE_NAME
    )
    store.upsert(
        "tester",
        "/addressbook/",
        "/addressbook/related-2.vcf",
        "etag-5",
        CARD_RELATED_TO_UNIQUE,
    )
    store.upsert(
        "tester",
        "/addressbook/",
        "/addressbook/related-3.vcf",
        "etag-6",
        CARD_RELATED_TO_NOBODY,
    )
    sid = app.state.sessions.create("tester", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


def test_ambiguous_related_name_does_not_link(client):
    """Two contacts share the display name "Chris Smith"; a third contact's
    related-name reference to "Chris Smith" is ambiguous and must render as
    plain text, never as a link to one of the two arbitrarily."""
    resp = client.get("/contacts/related-1")
    assert resp.status_code == 200
    assert 'href="/contacts/chris-1"' not in resp.text
    assert 'href="/contacts/chris-2"' not in resp.text
    assert "Chris Smith" in resp.text


def test_unambiguous_related_name_still_links(client):
    resp = client.get("/contacts/related-2")
    assert resp.status_code == 200
    assert 'href="/contacts/unique-1"' in resp.text


def test_related_name_matching_no_contact_renders_plain(client):
    resp = client.get("/contacts/related-3")
    assert resp.status_code == 200
    assert "Nobody Here" in resp.text
    # The unmatched related name must not be wrapped in a link to any contact.
    assert '<a href="/contacts/' not in resp.text.split("Nobody Here")[0][-200:]
    assert not resp.text.split("Nobody Here", 1)[1].lstrip().startswith("</a>")
