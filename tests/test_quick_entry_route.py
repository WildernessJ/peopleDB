"""Tests for the quick-entry pre-fill route (GET /contacts/new?q=...).

Uses an in-process TestClient with a session created directly against
SessionStore -- no live CardDAV server needed. Mirrors
tests/test_detail_avatar_size.py."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings
from peopledb.dav import DavError


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
    sid = app.state.sessions.create("tester", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


def test_quick_entry_prefills_form(client):
    resp = client.get("/contacts/new", params={"q": "Jane Doe jane@x.com"})
    assert resp.status_code == 200
    assert 'value="Jane"' in resp.text
    assert 'value="Doe"' in resp.text
    assert 'value="jane@x.com"' in resp.text


def test_no_query_renders_blank_form(client):
    resp = client.get("/contacts/new")
    assert resp.status_code == 200
    assert 'value="Jane"' not in resp.text
    assert 'name="given" value=""' in resp.text


def test_split_domestic_phones_prefill_two_form_fields(client):
    # Issue #23 end-to-end at the route: a two-domestic-phone quick-add must
    # render TWO pre-filled phone value inputs, not one merged field. Renders
    # the real form template, so this covers the parser split -> form pre-fill
    # path the browser exercises.
    resp = client.get("/contacts/new", params={"q": "Jane 555-123-4567 555-987-6543"})
    assert resp.status_code == 200
    assert 'class="value" name="phone_value" value="555-123-4567"' in resp.text
    assert 'class="value" name="phone_value" value="555-987-6543"' in resp.text


# -- issue #24: #group sigil + create-form group checkboxes ------------------

GROUP_CARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:group-family\r\n"
    "FN:Family\r\nN:Family;;;;\r\n"
    "X-ADDRESSBOOKSERVER-KIND:group\r\n"
    "END:VCARD\r\n"
)


@pytest.fixture
def client_with_group(app):
    store = app.state.store
    store.upsert("tester", "/addressbook/", "/addressbook/group-family.vcf", "etag-1", GROUP_CARD)
    sid = app.state.sessions.create("tester", "pw")
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


def test_blank_form_lists_all_groups_unchecked(client_with_group):
    resp = client_with_group.get("/contacts/new")
    assert resp.status_code == 200
    assert 'name="group_uid" value="group-family"' in resp.text
    assert 'name="group_uid" value="group-family" checked' not in resp.text
    assert "Family" in resp.text


def test_group_sigil_prechecks_matching_group(client_with_group):
    resp = client_with_group.get("/contacts/new", params={"q": "Jane Doe #family"})
    assert resp.status_code == 200
    assert 'name="group_uid" value="group-family" checked' in resp.text


def test_unknown_group_sigil_shows_not_assigned_note(client_with_group):
    resp = client_with_group.get("/contacts/new", params={"q": "Jane Doe #nope"})
    assert resp.status_code == 200
    assert 'checked' not in resp.text.split("Groups")[1].split("</fieldset>")[0]
    assert "nope" in resp.text
    assert "not assigned" in resp.text


class _CreateOkGroupPutFailsDav:
    """DavClient stand-in: the contact `create` (and refetch) succeed, but the
    group-card `put` fails with a server-side DavError. Exercises the
    post-create group-assignment failure path (#24 audit) without a live
    server -- the contact must still be created and the failure surfaced via
    group_warn, never propagated as a 'not saved' error."""

    def __init__(self, book_url="/addressbook/"):
        self._book = SimpleNamespace(name="Test", url=book_url)

    def addressbooks(self):
        return [self._book]

    def create(self, book_url, uid, raw):
        return f"{book_url}{uid}.vcf", "etag-new"

    def get(self, href):  # refetch after create -> fall back to sent raw
        raise DavError("no refetch in test")

    def put(self, href, raw, etag):  # the group PUT: transient server failure
        raise DavError("PUT -> 500")


@pytest.fixture
def client_group_put_fails(app):
    store = app.state.store
    store.upsert("tester", "/addressbook/", "/addressbook/group-family.vcf", "etag-1", GROUP_CARD)
    sid = app.state.sessions.create("tester", "pw")
    app.state.dav_clients[("tester", "pw")] = _CreateOkGroupPutFailsDav()
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("peopledb_session", sid)
    return c


def test_group_put_failure_still_creates_contact_and_surfaces_warning(client_group_put_fails):
    # Regression (#24 audit, MAJOR): a non-409 failure on the group PUT (500,
    # 403, transport drop) must NOT propagate to the app-level handler and
    # render "not saved" -- the contact is already created, so that would mask
    # the create and invite a duplicate on retry. Instead: contact created,
    # 303 redirect, failure surfaced via group_warn.
    resp = client_group_put_fails.post(
        "/contacts",
        data={
            "given": "Greta", "family": "Member", "org": "", "bday": "", "note": "",
            "group_uid": "group-family",
        },
    )
    assert resp.status_code == 303
    assert "group_warn" in resp.headers["location"]
    contact_uid = resp.headers["location"].split("/contacts/")[1].split("?")[0]
    assert client_group_put_fails.app.state.store.get_by_uid("tester", contact_uid) is not None
