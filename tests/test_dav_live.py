"""Live tests for the CardDAV client seam, against a throwaway local Radicale."""

import pytest

from peopledb.dav import ConflictError, DavClient, InvalidSyncToken
from peopledb.store import ContactStore
from peopledb.sync import sync_user

pytestmark = pytest.mark.live

CARD_TEMPLATE = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:{uid}\r\n"
    "FN:{fn}\r\n"
    "N:{family};{given};;;\r\n"
    "END:VCARD\r\n"
)


@pytest.fixture
def client(dav_server):
    return DavClient(
        dav_server["base_url"], dav_server["username"], dav_server["password"]
    )


def make_card(uid, given="Test", family="Person"):
    return CARD_TEMPLATE.format(uid=uid, fn=f"{given} {family}", given=given, family=family)


def test_validate_credentials(client, dav_server):
    assert client.validate_credentials() is True


def test_discover_addressbooks(client):
    books = client.addressbooks()
    assert any(b.name == "Test Contacts" for b in books)


def test_create_fetch_update_delete_cycle(client):
    (book,) = [b for b in client.addressbooks() if b.name == "Test Contacts"]

    href, etag = client.create(book.url, "cycle-1", make_card("cycle-1", given="Ada"))
    assert href.endswith(".vcf") and etag

    raw, fetched_etag = client.get(href)
    assert "FN:Ada Person" in raw
    assert fetched_etag == etag

    new_etag = client.put(href, make_card("cycle-1", given="Grace"), etag)
    assert new_etag and new_etag != etag

    # Stale etag must raise, not overwrite (spec: 412 conflicts surface).
    with pytest.raises(ConflictError):
        client.put(href, make_card("cycle-1", given="Stale"), etag)

    client.delete(href)
    raw2, _ = client.get(href, missing_ok=True)
    assert raw2 is None


def test_sync_reports_changes_and_deletions(client):
    (book,) = [b for b in client.addressbooks() if b.name == "Test Contacts"]

    initial = client.sync(book.url, token=None)
    assert initial.token

    href, _ = client.create(book.url, "sync-1", make_card("sync-1"))
    delta = client.sync(book.url, token=initial.token)
    assert href in [c.href for c in delta.changed]
    assert "UID:sync-1" in next(c.raw for c in delta.changed if c.href == href)
    assert all(c.etag for c in delta.changed)

    client.delete(href)
    delta2 = client.sync(book.url, token=delta.token)
    assert href in delta2.deleted


def test_garbled_sync_token_raises_invalid_sync_token(client):
    (book,) = [b for b in client.addressbooks() if b.name == "Test Contacts"]
    client.sync(book.url, token=None)  # establish the collection's sync state

    with pytest.raises(InvalidSyncToken):
        client.sync(book.url, token="http://example.test/ns/sync/garbage-not-a-real-token")


def test_sync_user_recovers_from_invalid_sync_token_via_full_resync(client, tmp_path):
    (book,) = [b for b in client.addressbooks() if b.name == "Test Contacts"]
    client.create(book.url, "resync-1", make_card("resync-1", given="Kept"))

    store = ContactStore(tmp_path / "cache.db")
    sync_user(client, store, "testuser")
    assert any(c.contact.uid == "resync-1" for c in store.list_contacts("testuser"))

    good_token = store.get_sync_token("testuser", book.url)
    assert good_token

    # Corrupt the stored token so the next sync-collection REPORT is rejected.
    store.set_sync_token("testuser", book.url, good_token + "-corrupted")

    with pytest.raises(InvalidSyncToken):
        client.sync(book.url, token=store.get_sync_token("testuser", book.url))

    # sync_user must catch that and fall back to a full resync, not blow up.
    sync_user(client, store, "testuser")

    contacts = store.list_contacts("testuser")
    assert any(c.contact.uid == "resync-1" for c in contacts)
    new_token = store.get_sync_token("testuser", book.url)
    assert new_token and new_token != good_token + "-corrupted"
