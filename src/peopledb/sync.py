"""Sync service: refresh the local cache from the CardDAV server using
sync-collection tokens. Only changed cards travel; the server stays canonical."""

from __future__ import annotations

from peopledb.dav import DavClient, InvalidSyncToken
from peopledb.store import ContactStore


def sync_user(dav: DavClient, store: ContactStore, user: str) -> None:
    for book in dav.addressbooks():
        token = store.get_sync_token(user, book.url)
        try:
            result = dav.sync(book.url, token)
        except InvalidSyncToken:
            # Server forgot our token; discard it and do a full resync.
            result = dav.sync(book.url, None)
        for change in result.changed:
            store.upsert(user, book.url, change.href, change.etag, change.raw)
        for href in result.deleted:
            store.delete(user, href)
        store.set_sync_token(user, book.url, result.token)
