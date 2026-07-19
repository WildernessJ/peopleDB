"""Tests for the detail-page avatar sizing hook (issue #16, relocated by the
display-settings feature): the `#detail-avatar` sizing hook must appear on the
detail page, while the `avatar()` macro's output for existing call sites
(card/list view, no size hook) stays byte-for-byte unchanged.

The S/M/L control itself now lives in the shared settings popover
(`_topbar.html`, `#settings-panel`, in-flow since issue #26) rather than inline
on the detail page -- see tests/test_display_settings.py for its markup. It still writes the same
`peopledb-avatar-size` localStorage key the old inline toggle used.

Uses an in-process TestClient with a session created directly against
SessionStore and data seeded directly into ContactStore -- no live CardDAV
server needed. Mirrors tests/test_card_view.py."""

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings

CARD_FULL = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:full-1\r\n"
    "FN:Fully Loaded\r\nN:Loaded;Fully;;;\r\n"
    "ORG:Acme Corp\r\n"
    "TEL:+1 555 111 2222\r\n"
    "EMAIL:fully@example.com\r\n"
    "END:VCARD\r\n"
)

CARD_BARE = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:bare-1\r\n"
    "FN:Bare Bones\r\nN:Bones;Bare;;;\r\n"
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
    store.upsert("tester", "/addressbook/", "/addressbook/full-1.vcf", "etag-1", CARD_FULL)
    store.upsert("tester", "/addressbook/", "/addressbook/bare-1.vcf", "etag-2", CARD_BARE)
    sid = app.state.sessions.create("tester", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


# -- detail page: sizing hook (control lives in the settings popover) --------


def test_detail_page_has_settings_popover_detail_avatar_control(client):
    resp = client.get("/contacts/bare-1")
    assert resp.status_code == 200
    # The old inline #avatar-size-toggle is gone; the control now lives in
    # the shared settings popover, keyed to the same storage key.
    assert 'id="avatar-size-toggle"' not in resp.text
    assert 'data-size-storage-key="peopledb-avatar-size"' in resp.text
    assert 'aria-label="Detail avatar size"' in resp.text


def test_detail_page_avatar_has_sizing_hook(client):
    resp = client.get("/contacts/bare-1")
    assert resp.status_code == 200
    assert 'id="detail-avatar"' in resp.text


def test_detail_page_toggle_buttons_are_accessible(client):
    resp = client.get("/contacts/bare-1")
    assert resp.status_code == 200
    # Each choice button has an aria-label; the group itself is labelled too.
    assert 'aria-label="Small"' in resp.text
    assert 'aria-label="Medium"' in resp.text
    assert 'aria-label="Large"' in resp.text


# -- macro regression: other call sites are unaffected ------------------------


def test_card_view_avatar_has_no_detail_hook(client):
    client.cookies.set("peopledb_view", "card")
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'class="contact-cards"' in resp.text
    assert 'id="detail-avatar"' not in resp.text


def test_list_view_avatar_has_no_detail_hook(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'class="contacts"' in resp.text
    assert 'id="detail-avatar"' not in resp.text
