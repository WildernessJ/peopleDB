"""Live tests for group management (Apple KIND=group member-list vCards)."""

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


CARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{uid}\r\n"
    "FN:{fn}\r\nN:{family};{given};;;\r\nEND:VCARD\r\n"
)


def make(dav, book, uid, given, family):
    return dav.create(
        book.url, uid,
        CARD.format(uid=uid, fn=f"{given} {family}", given=given, family=family),
    )


def test_group_lifecycle(client, dav, book):
    make(dav, book, "gm-1", "Greta", "Member")
    make(dav, book, "gm-2", "Gustav", "Member")
    client.get("/refresh")  # pick up server-side creations

    # Create group -> exists on the server as a KIND=group card.
    resp = client.post("/groups", data={"name": "Hiking Crew"})
    assert resp.status_code == 303
    group_uid = resp.headers["location"].rsplit("/", 1)[-1]
    raw, _ = dav.get(f"{book.url.rstrip('/')}/{group_uid}.vcf")
    assert "X-ADDRESSBOOKSERVER-KIND:group" in raw
    assert "FN:Hiking Crew" in raw

    # Add members -> written through.
    for uid in ("gm-1", "gm-2"):
        resp = client.post(f"/groups/{group_uid}/members", data={"member_uid": uid})
        assert resp.status_code == 303
    raw, _ = dav.get(f"{book.url.rstrip('/')}/{group_uid}.vcf")
    assert "urn:uuid:gm-1" in raw and "urn:uuid:gm-2" in raw

    # Filter the contact list by group.
    resp = client.get("/", params={"group": group_uid})
    assert "Greta Member" in resp.text and "Gustav Member" in resp.text

    # Remove a member.
    resp = client.post(f"/groups/{group_uid}/members/gm-2/remove")
    assert resp.status_code == 303
    raw, _ = dav.get(f"{book.url.rstrip('/')}/{group_uid}.vcf")
    assert "urn:uuid:gm-1" in raw and "urn:uuid:gm-2" not in raw

    # Rename.
    resp = client.post(f"/groups/{group_uid}", data={"name": "Trail Crew"})
    assert resp.status_code == 303
    raw, _ = dav.get(f"{book.url.rstrip('/')}/{group_uid}.vcf")
    assert "FN:Trail Crew" in raw

    # Delete.
    resp = client.post(f"/groups/{group_uid}/delete")
    assert resp.status_code == 303
    raw, _ = dav.get(f"{book.url.rstrip('/')}/{group_uid}.vcf", missing_ok=True)
    assert raw is None
