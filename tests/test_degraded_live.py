"""Degraded-mode tests: server killed mid-session -> cached reads with a
staleness banner, writes fail loudly and never queue."""

import pytest
from fastapi.testclient import TestClient

from peopledb.app import create_app
from peopledb.config import Settings
from peopledb.dav import DavClient

pytestmark = pytest.mark.live

CARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:off-1\r\n"
    "FN:Offline Test\r\nN:Test;Offline;;;\r\n"
    "EMAIL;TYPE=WORK:offline@example.net\r\nEND:VCARD\r\n"
)


def test_server_down_serves_cache_readonly_and_fails_writes(make_dav_server, tmp_path):
    server = make_dav_server()
    dav = DavClient(server["base_url"], server["username"], server["password"])
    (book,) = [b for b in dav.addressbooks() if b.name == "Test Contacts"]
    dav.create(book.url, "off-1", CARD)

    settings = Settings(
        dav_url=server["base_url"], secret_key="", db_path=str(tmp_path / "cache.db"), secure_cookies=False
    )
    client = TestClient(create_app(settings), follow_redirects=False)
    assert client.post(
        "/login", data={"username": "testuser", "password": "anything"}
    ).status_code == 303
    assert "Offline Test" in client.get("/").text

    server["process"].terminate()
    server["process"].wait(timeout=5)

    # A refresh attempt notices the outage; reads still serve the cache.
    assert client.get("/refresh").status_code == 303
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Offline Test" in resp.text  # cached data still browsable
    assert "unreachable" in resp.text.lower()  # staleness banner

    # Detail and search still work from cache.
    assert client.get("/contacts/off-1").status_code == 200
    assert "Offline Test" in client.get("/search", params={"q": "offline"}).text

    # Writes fail loudly and are never queued.
    resp = client.post(
        "/contacts/off-1",
        data={
            "given": "Changed", "family": "Test", "org": "", "note": "", "bday": "",
            "email_label": [], "email_value": [],
            "phone_label": [], "phone_value": [],
            "url_label": [], "url_value": [],
            "related_label": [], "related_value": [],
        },
    )
    assert resp.status_code == 503
    assert "not saved" in resp.text.lower()
    # Cache unchanged: the edit did not silently apply anywhere.
    assert "Offline Test" in client.get("/contacts/off-1").text
