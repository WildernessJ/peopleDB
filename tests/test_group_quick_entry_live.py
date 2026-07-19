"""Live test for issue #24: `POST /contacts` with a checked `group_uid`
writes the new contact's UID into that group's member list.

The create route does a real `dav.create` (and, for group assignment, a real
etag-conditional `dav.put` on the group card), so this needs an actual CardDAV
server -- mirrors tests/test_groups_live.py."""

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings
from peopledb.dav import DavClient

pytestmark = pytest.mark.live


@pytest.fixture
def dav(dav_server):
    return DavClient(dav_server["base_url"], dav_server["username"], dav_server["password"])


@pytest.fixture
def book(dav):
    (book,) = [b for b in dav.addressbooks() if b.name == "Test Contacts"]
    return book


@pytest.fixture
def client(dav_server, tmp_path):
    settings = Settings(
        dav_url=dav_server["base_url"], secret_key="", db_path=str(tmp_path / "cache.db"), secure_cookies=False
    )
    client = TestClient(create_app(settings), follow_redirects=False)
    resp = client.post("/login", data={"username": "testuser", "password": "anything"})
    assert resp.status_code == 303
    return client


def test_create_contact_with_checked_group_adds_membership(client, dav, book):
    # Create the group on the server first, then pick it up into the cache.
    resp = client.post("/groups", data={"name": "Hiking Crew"})
    assert resp.status_code == 303
    group_uid = resp.headers["location"].rsplit("/", 1)[-1]

    resp = client.post(
        "/contacts",
        data={
            "given": "Greta", "family": "Member", "org": "", "bday": "", "note": "",
            "group_uid": group_uid,
        },
    )
    assert resp.status_code == 303
    contact_uid = resp.headers["location"].rsplit("/", 1)[-1]
    assert "group_warn" not in resp.headers["location"]

    store = client.app.state.store
    rec = store.get_by_uid("testuser", group_uid)
    assert contact_uid in rec.contact.member_uids

    # And it really landed on the server, not just the local cache.
    raw, _ = dav.get(f"{book.url.rstrip('/')}/{group_uid}.vcf")
    assert f"urn:uuid:{contact_uid}" in raw


def test_create_contact_with_unknown_group_uid_still_creates_contact(client):
    # Regression (#24 review): a group_uid that resolves to nothing -- the group
    # was deleted between the form GET and this POST, or the value is stale /
    # tampered -- must NOT 404 the request after the contact is already created.
    # The contact is created and the unresolved group is surfaced via group_warn.
    resp = client.post(
        "/contacts",
        data={
            "given": "Nadia", "family": "NoGroup", "org": "", "bday": "", "note": "",
            "group_uid": "does-not-exist",
        },
    )
    assert resp.status_code == 303
    assert "group_warn" in resp.headers["location"]
    contact_uid = resp.headers["location"].split("/contacts/")[1].split("?")[0]
    store = client.app.state.store
    assert store.get_by_uid("testuser", contact_uid) is not None


def test_create_contact_with_non_group_uid_is_not_rewritten_as_group(client):
    # Regression (#24 review): a group_uid pointing at a normal contact must
    # never be set_group()'d -- that would rewrite the victim contact INTO a
    # group card. The assignment is refused (surfaced via group_warn) and the
    # referenced contact is left untouched.
    resp = client.post(
        "/contacts",
        data={"given": "Victim", "family": "Contact", "org": "", "bday": "", "note": ""},
    )
    assert resp.status_code == 303
    victim_uid = resp.headers["location"].rsplit("/", 1)[-1]

    resp = client.post(
        "/contacts",
        data={
            "given": "Trudy", "family": "Tamper", "org": "", "bday": "", "note": "",
            "group_uid": victim_uid,
        },
    )
    assert resp.status_code == 303
    assert "group_warn" in resp.headers["location"]

    store = client.app.state.store
    victim = store.get_by_uid("testuser", victim_uid)
    assert victim is not None
    assert not victim.contact.is_group  # unchanged, not rewritten into a group
